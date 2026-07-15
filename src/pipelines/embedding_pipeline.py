"""Embedding pipeline for semantic search in HireFlow AI.

Generates embeddings for job descriptions using sentence-transformers,
builds a FAISS index, and provides semantic search capabilities.
"""

import argparse
import json
import logging
from pathlib import Path

import faiss
import numpy as np

from src.config.database import SessionLocal
from src.config.settings import settings
from src.models.job import Job

logger = logging.getLogger(__name__)

# Default path for the FAISS index and metadata
DEFAULT_INDEX_DIR = Path("data/faiss_index")
INDEX_FILENAME = "job_embeddings.index"
METADATA_FILENAME = "job_metadata.json"


class EmbeddingPipeline:
    """Pipeline for embedding jobs and performing semantic search.

    Attributes:
        index_dir: Directory where the FAISS index and metadata are stored.
        model_name: The sentence-transformers model to use (from settings).
    """

    def __init__(self, index_dir: Path | str = DEFAULT_INDEX_DIR):
        self.index_dir = Path(index_dir)
        self.model_name = settings.embedding_model_name
        self._model = None
        self._index: faiss.Index | None = None

        # metadata mapping: dict mapping integer FAISS ID to job details
        # e.g., { 0: {"job_id": "...", "role_title": "...", "company_name": "..."} }
        self._metadata: dict[int, dict] = {}

    def _load_model(self):
        """Lazily load the embedding model."""
        if self._model is None:
            logger.info(f"Loading embedding model: {self.model_name}")
            try:
                from sentence_transformers import SentenceTransformer
            except ImportError as e:
                logger.error("sentence-transformers is not installed.")
                raise RuntimeError("Please install sentence-transformers.") from e

            self._model = SentenceTransformer(self.model_name)
        return self._model

    def embed_text(self, text: str) -> np.ndarray:
        """Embed a single text string."""
        if not text or not text.strip():
            # Return a zero vector or raise ValueError depending on use case.
            # We'll return a zero vector of the correct dimension if model is loaded.
            model = self._load_model()
            dim = model.get_sentence_embedding_dimension()
            return np.zeros((1, dim), dtype=np.float32)

        model = self._load_model()
        embedding = model.encode(text, convert_to_numpy=True)
        if embedding.ndim == 1:
            embedding = embedding.reshape(1, -1)
        # Normalize for cosine similarity (Inner Product) if using L2/cosine
        faiss.normalize_L2(embedding)
        return embedding

    def embed_jobs(self, texts: list[str]) -> np.ndarray:
        """Embed a batch of job descriptions."""
        if not texts:
            return np.array([])

        model = self._load_model()
        embeddings = model.encode(texts, convert_to_numpy=True)
        faiss.normalize_L2(embeddings)
        return embeddings

    def _build_index(self, embeddings: np.ndarray):
        """Initialize and populate the FAISS index."""
        if len(embeddings) == 0:
            logger.warning("No embeddings to build index.")
            return

        dim = embeddings.shape[1]
        # Inner product index acts as cosine similarity since vectors are L2-normalized
        self._index = faiss.IndexFlatIP(dim)
        self._index.add(embeddings)
        logger.info(f"Built FAISS index with {self._index.ntotal} vectors.")

    def _save_index(self):
        """Persist the FAISS index and metadata to disk."""
        if self._index is None:
            logger.warning("No index to save.")
            return

        self.index_dir.mkdir(parents=True, exist_ok=True)

        index_path = self.index_dir / INDEX_FILENAME
        meta_path = self.index_dir / METADATA_FILENAME

        faiss.write_index(self._index, str(index_path))

        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(self._metadata, f, indent=2)

        logger.info(f"Saved FAISS index to {index_path}")
        logger.info(f"Saved metadata to {meta_path}")

    def _load_index(self) -> bool:
        """Load the FAISS index and metadata from disk."""
        index_path = self.index_dir / INDEX_FILENAME
        meta_path = self.index_dir / METADATA_FILENAME

        if not index_path.exists() or not meta_path.exists():
            logger.error("Index or metadata files not found.")
            return False

        try:
            self._index = faiss.read_index(str(index_path))
            with open(meta_path, "r", encoding="utf-8") as f:
                # json keys are always strings, need to convert back to int
                raw_metadata = json.load(f)
                self._metadata = {int(k): v for k, v in raw_metadata.items()}
            logger.info(f"Loaded FAISS index with {self._index.ntotal} vectors.")
            return True
        except Exception as e:
            logger.error(f"Failed to load index: {e}")
            return False

    def search(self, text: str, top_k: int = 5) -> list[dict]:
        """Search the FAISS index for jobs semantically similar to `text`.

        Args:
            text: The profile or search text.
            top_k: Number of results to return.

        Returns:
            List of dicts containing job_id, role_title, company_name, and score.
        """
        if not text or not text.strip():
            logger.warning("Empty search text provided.")
            return []

        if self._index is None:
            # Try to load if not already loaded
            if not self._load_index():
                logger.warning("Cannot search: Index not loaded or built.")
                return []

        # Ensure top_k is bounded by the number of elements in the index
        if self._index.ntotal == 0:
            return []

        k = min(top_k, self._index.ntotal)

        # Embed query and reshape for FAISS (n_queries, dim)
        query_vector = self.embed_text(text).reshape(1, -1)

        scores, indices = self._index.search(query_vector, k)

        results = []
        for i, idx in enumerate(indices[0]):
            if idx == -1:  # FAISS returns -1 if there are fewer results than k
                continue

            score = float(scores[0][i])
            meta = self._metadata.get(idx, {})

            if meta:
                results.append(
                    {
                        "job_id": meta.get("job_id"),
                        "role_title": meta.get("role_title"),
                        "company_name": meta.get("company_name"),
                        "score": score,
                    }
                )

        return results

    def run(self):
        """Fetch all non-spam jobs, embed them, and save the index."""
        db = SessionLocal()
        try:
            # Fetch valid jobs
            jobs = (
                db.query(Job)
                .filter(
                    Job.is_spam.is_(False),
                    Job.jd_text.isnot(None),
                    Job.jd_text != "",
                )
                .all()
            )

            if not jobs:
                logger.warning("No valid, non-spam jobs found in the database.")
                return

            logger.info(f"Found {len(jobs)} jobs to embed.")

            texts = []
            self._metadata = {}

            for job in jobs:
                if not job.jd_text or not job.jd_text.strip():
                    continue

                # We can embed the JD directly, or a combination of title and JD
                content = f"{job.role_title}\n\n{job.jd_text}"

                faiss_id = len(texts)
                texts.append(content)
                self._metadata[faiss_id] = {
                    "job_id": str(job.id),
                    "role_title": job.role_title,
                    "company_name": job.company_name,
                }

            logger.info("Generating embeddings (this may take a while)...")
            embeddings = self.embed_jobs(texts)

            logger.info("Building FAISS index...")
            self._build_index(embeddings)

            logger.info("Saving index to disk...")
            self._save_index()

            logger.info("Embedding pipeline completed successfully.")

        except Exception as e:
            logger.error(f"Embedding pipeline failed: {e}")
            raise
        finally:
            db.close()


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    parser = argparse.ArgumentParser(description="HireFlow Embedding Pipeline")
    parser.add_argument(
        "--embed-jobs",
        action="store_true",
        help="Run the embedding pipeline on all valid jobs in the database.",
    )

    args = parser.parse_args()

    if args.embed_jobs:
        pipeline = EmbeddingPipeline()
        pipeline.run()
    else:
        parser.print_help()
