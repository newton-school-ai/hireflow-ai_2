"""
Embedding Pipeline and FAISS Index for HireFlow AI.

Generates semantic embeddings for job descriptions and user profiles,
manages a FAISS index for high-performance similarity search, and provides
a command-line interface to build and save the index.
"""

import argparse
import json
import logging
import os
import uuid
from typing import Any

import faiss
import numpy as np
from sqlalchemy.orm import Session

from src.config.database import SessionLocal
from src.config.settings import settings

logger = logging.getLogger(__name__)

# Module-level model cache to reuse the singleton model instance
_model_cache: dict[str, Any] = {}


def get_embedding_model(model_name: str) -> Any:
    """Lazily loads and caches the SentenceTransformer model to avoid repeated loading.

    Args:
        model_name: The HuggingFace model name or path.

    Returns:
        SentenceTransformer model instance.
    """
    if model_name not in _model_cache:
        try:
            logger.info(f"Loading embedding model: {model_name}")
            from sentence_transformers import SentenceTransformer

            _model_cache[model_name] = SentenceTransformer(model_name)
        except Exception as e:
            logger.error(
                f"Failed to load sentence-transformers model '{model_name}': {e}"
            )
            raise RuntimeError(f"Embedding model loading failure: {e}") from e
    return _model_cache[model_name]


class EmbeddingPipeline:
    """Handles vector embedding generation and FAISS similarity indexing."""

    def __init__(
        self, model_name: str | None = None, index_dir: str | None = None
    ) -> None:
        """Initializes the EmbeddingPipeline with configuration options.

        Args:
            model_name: Optional custom embedding model name. If not provided,
                        retrieved from settings.
            index_dir: Optional custom path for the FAISS index files. If not
                       provided, retrieved from settings.
        """
        self.model_name = model_name or settings.embedding_model
        self.index_dir = index_dir or settings.faiss_index_dir
        self.index: faiss.IndexFlatIP | None = None
        self.job_metadata: list[dict[str, Any]] = []

    @property
    def model(self) -> Any:
        """Property to access the lazily loaded model instance."""
        return get_embedding_model(self.model_name)

    def embed_text(self, text: str | None) -> np.ndarray | None:
        """Generates a normalized 1D float32 vector embedding for a single text string.

        Args:
            text: The input text to embed.

        Returns:
            A normalized 1D numpy array of shape (dimension,) or None if text is empty/None.
        """
        if text is None:
            logger.warning("Received None input for embedding.")
            return None

        cleaned = text.strip()
        if not cleaned:
            logger.warning("Received empty string for embedding.")
            return None

        try:
            # sentence-transformers' encode supports returning L2-normalized embeddings
            embedding = self.model.encode(cleaned, normalize_embeddings=True)
            return np.array(embedding, dtype=np.float32)
        except Exception as e:
            logger.error(f"Failed to embed text: {e}")
            raise RuntimeError(f"Embedding generation failure: {e}") from e

    def _get_job_text(self, job: Any) -> str:
        """Helper to format a Job model instance into a single text block for embedding.

        Args:
            job: A Job database model instance.

        Returns:
            A combined string of role title, company name, and job description.
        """
        # Ensure role_title and company_name are strings to prevent None concatenation issues
        role = job.role_title or ""
        company = job.company_name or ""
        jd = job.jd_text or ""
        return f"Role: {role}\nCompany: {company}\nDescription: {jd}"

    def embed_jobs(
        self, db: Session | None = None
    ) -> tuple[list[uuid.UUID], np.ndarray | None]:
        """Queries non-spam, non-empty jobs from the database and generates embeddings.

        Args:
            db: Optional SQLAlchemy Session. If not provided, a new one will be opened and closed.

        Returns:
            A tuple of (list of job UUIDs, 2D float32 numpy array of shape (num_jobs, dimension) or None).
        """
        db_provided = db is not None
        session = db or SessionLocal()

        try:
            from src.models.job import Job

            # Query non-spam jobs with non-empty job descriptions
            query = session.query(Job).filter(
                Job.is_spam == False,  # noqa: E712
                Job.jd_text.isnot(None),
                Job.jd_text != "",
            )
            jobs = query.all()

            if not jobs:
                logger.warning(
                    "No jobs found in the database matching criteria for embedding."
                )
                return [], None

            job_texts = []
            job_ids = []

            for job in jobs:
                text = self._get_job_text(job)
                job_texts.append(text)
                job_ids.append(job.id)

            logger.info(f"Generating embeddings for {len(job_texts)} jobs...")
            embeddings = self.model.encode(job_texts, normalize_embeddings=True)
            embeddings_matrix = np.array(embeddings, dtype=np.float32)

            return job_ids, embeddings_matrix

        except Exception as e:
            logger.error(f"Failed to embed jobs from database: {e}")
            raise RuntimeError(f"Database job embedding failure: {e}") from e
        finally:
            if not db_provided:
                session.close()

    def build_index(self, db: Session | None = None) -> None:
        """Builds a new FAISS index using clean jobs from the database.

        Args:
            db: Optional SQLAlchemy Session.
        """
        db_provided = db is not None
        session = db or SessionLocal()

        try:
            job_ids, embeddings_matrix = self.embed_jobs(session)

            if embeddings_matrix is None or not job_ids:
                logger.warning("No embeddings generated. Setting FAISS index to None.")
                self.index = None
                self.job_metadata = []
                return

            dimension = embeddings_matrix.shape[1]

            # IndexFlatIP uses Inner Product. Since our vectors are L2-normalized,
            # this computes exactly the cosine similarity score.
            index = faiss.IndexFlatIP(dimension)
            index.add(embeddings_matrix)

            self.index = index

            # Store mapping metadata of the index positions
            # We fetch role_title and company_name directly to avoid database queries during search
            from src.models.job import Job

            jobs_map = {
                job.id: job
                for job in session.query(Job).filter(Job.id.in_(job_ids)).all()
            }

            self.job_metadata = []
            for jid in job_ids:
                job = jobs_map.get(jid)
                self.job_metadata.append(
                    {
                        "id": str(jid),
                        "role_title": job.role_title if job else "",
                        "company_name": job.company_name if job else "",
                    }
                )

            logger.info(f"Successfully built FAISS index with {len(job_ids)} vectors.")

        except Exception as e:
            logger.error(f"Failed to build FAISS index: {e}")
            raise RuntimeError(f"FAISS index build failure: {e}") from e
        finally:
            if not db_provided:
                session.close()

    def save_index(self, directory: str | None = None) -> None:
        """Saves the current FAISS index and metadata mapping to disk.

        Args:
            directory: Optional custom path to save index files. Defaults to configured directory.
        """
        target_dir = directory or self.index_dir

        if self.index is None:
            logger.warning("Attempted to save an empty or uninitialized FAISS index.")
            return

        try:
            os.makedirs(target_dir, exist_ok=True)
            index_path = os.path.join(target_dir, "index.faiss")
            meta_path = os.path.join(target_dir, "metadata.json")

            # Write index binary
            faiss.write_index(self.index, index_path)

            # Write metadata mapping
            with open(meta_path, "w", encoding="utf-8") as f:
                json.dump(self.job_metadata, f, ensure_ascii=False, indent=2)

            logger.info(f"Saved FAISS index and metadata successfully to {target_dir}")
        except Exception as e:
            logger.error(f"Failed to save FAISS index: {e}")
            raise RuntimeError(f"FAISS index save failure: {e}") from e

    def load_index(self, directory: str | None = None) -> bool:
        """Loads a FAISS index and metadata mapping from disk if present.

        Args:
            directory: Optional custom path to load index files from. Defaults to configured directory.

        Returns:
            True if loaded successfully, False if files are missing or could not be loaded.
        """
        target_dir = directory or self.index_dir
        index_path = os.path.join(target_dir, "index.faiss")
        meta_path = os.path.join(target_dir, "metadata.json")

        if not os.path.exists(index_path) or not os.path.exists(meta_path):
            logger.warning(f"FAISS index files not found in {target_dir}")
            return False

        try:
            self.index = faiss.read_index(index_path)

            with open(meta_path, encoding="utf-8") as f:
                self.job_metadata = json.load(f)

            logger.info(
                f"Loaded FAISS index with {self.index.ntotal} vectors from {target_dir}"
            )
            return True
        except Exception as e:
            logger.error(f"Failed to load FAISS index from {target_dir}: {e}")
            self.index = None
            self.job_metadata = []
            return False

    def search(self, text: str | None, top_k: int = 5) -> list[dict[str, Any]]:
        """Searches the index for the top_k most similar jobs to the given query text.

        Args:
            text: The search query text (e.g., user profile summary or query).
            top_k: Number of results to return.

        Returns:
            List of dicts representing search matches. Each dict contains:
            - job_id: str
            - role_title: str
            - company_name: str
            - score: float (similarity score)
        """
        if text is None or not text.strip():
            logger.warning("Empty search text provided. Returning empty result list.")
            return []

        # Try to load index dynamically if it is not in memory
        if self.index is None:
            logger.info("FAISS index not in memory. Attempting to load from disk...")
            if not self.load_index():
                logger.warning(
                    "No FAISS index available to search. Returning empty result list."
                )
                return []

        n_vectors = self.index.ntotal
        if n_vectors == 0:
            logger.warning(
                "FAISS index contains 0 vectors. Returning empty result list."
            )
            return []

        # Gracefully handle query vector embedding
        query_vector = self.embed_text(text)
        if query_vector is None:
            return []

        # Query vector shape needs to be (1, dimension) for search
        query_matrix = np.array([query_vector], dtype=np.float32)

        # Ensure top_k is within bounds and reasonable
        actual_k = min(top_k, n_vectors)
        if actual_k <= 0:
            return []

        try:
            scores, indices = self.index.search(query_matrix, actual_k)
            results = []

            for score, idx in zip(scores[0], indices[0]):
                # FAISS returns index -1 if not enough results are found
                if idx == -1:
                    continue

                if 0 <= idx < len(self.job_metadata):
                    meta = self.job_metadata[idx]
                    results.append(
                        {
                            "job_id": meta["id"],
                            "role_title": meta["role_title"],
                            "company_name": meta["company_name"],
                            "score": float(score),
                        }
                    )

            return results
        except Exception as e:
            logger.error(f"Error occurred during FAISS index search: {e}")
            return []


if __name__ == "__main__":
    # Configure root logging for CLI runner compatibility
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    parser = argparse.ArgumentParser(
        description="HireFlow AI CLI tool to build and update the FAISS embedding index."
    )
    parser.add_argument(
        "--embed-jobs",
        action="store_true",
        help="Query all jobs, generate embeddings, build the FAISS index, and save it to disk.",
    )

    args = parser.parse_args()

    if args.embed_jobs:
        logger.info("Starting embed jobs pipeline CLI run...")
        pipeline = EmbeddingPipeline()
        pipeline.build_index()
        pipeline.save_index()
        logger.info("Pipeline CLI run completed successfully.")
    else:
        parser.print_help()
