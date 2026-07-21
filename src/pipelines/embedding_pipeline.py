"""
Embedding pipeline and FAISS vector index management for HireFlow AI.

Converts user profiles and job descriptions into vector embeddings using SentenceTransformers
and maintains a FAISS index for fast similarity search across non-spam job listings.
"""

import argparse
import json
import logging
import os
from typing import Any

import faiss
import numpy as np
from sentence_transformers import SentenceTransformer

from src.config.database import SessionLocal
from src.config.settings import settings
from src.models.job import Job

logger = logging.getLogger(__name__)


class EmbeddingPipeline:
    """Pipeline for generating embeddings and searching jobs using FAISS."""

    def __init__(
        self,
        model_name: str | None = None,
        index_dir: str | None = None,
    ) -> None:
        """Initialize the embedding pipeline.

        Args:
            model_name: SentenceTransformer model name. Defaults to settings.embedding_model.
            index_dir: Directory path for FAISS index persistence. Defaults to settings.faiss_index_dir.
        """
        self.model_name = model_name or settings.embedding_model
        self.index_dir = index_dir or settings.faiss_index_dir

        self._model: SentenceTransformer | None = None
        self.index: faiss.Index | None = None
        self.metadata: list[dict[str, Any]] = []

        # Attempt to load existing index from disk if present
        self.load_index()

    @property
    def model(self) -> SentenceTransformer:
        """Lazy-load the SentenceTransformer embedding model."""
        if self._model is None:
            logger.info(f"Loading SentenceTransformer model: {self.model_name}")
            self._model = SentenceTransformer(self.model_name)
        return self._model

    def embed_text(self, text: str | None) -> np.ndarray:
        """Embed a single text string into a normalized 1D float32 vector array.

        Args:
            text: Text content to embed. Handles empty/short text gracefully.

        Returns:
            np.ndarray: 1D numpy array of float32 values representing the normalized embedding vector.
        """
        clean_text = (text or "").strip()
        if not clean_text:
            clean_text = "empty"

        vector = self.model.encode(
            clean_text,
            normalize_embeddings=True,
            show_progress_bar=False,
        )
        return np.array(vector, dtype=np.float32)

    def embed_jobs(self) -> int:
        """Fetch all non-spam jobs from the database, generate embeddings, build FAISS index, and save to disk.

        Returns:
            int: Count of non-spam jobs embedded and indexed.
        """
        db = SessionLocal()
        try:
            non_spam_jobs = (
                db.query(Job).filter(Job.is_spam == False).all()  # noqa: E712
            )
            logger.info(f"Found {len(non_spam_jobs)} non-spam jobs to embed.")

            if not non_spam_jobs:
                logger.warning("No non-spam jobs found in database to embed.")
                self.index = None
                self.metadata = []
                self.save_index()
                return 0

            texts = []
            metadata_list = []

            for job in non_spam_jobs:
                skills_str = (
                    ", ".join(job.skills_required)
                    if isinstance(job.skills_required, list)
                    else (job.skills_required or "")
                )
                formatted_text = (
                    f"Role: {job.role_title} at {job.company_name}. "
                    f"Location: {job.location or 'N/A'}. "
                    f"Description: {job.jd_text}. "
                    f"Skills: {skills_str}"
                )
                texts.append(formatted_text)

                metadata_list.append(
                    {
                        "job_id": str(job.id),
                        "company_name": job.company_name,
                        "role_title": job.role_title,
                        "location": job.location,
                        "application_url": job.application_url,
                        "listing_type": (
                            str(job.listing_type) if job.listing_type else "job"
                        ),
                        "stipend_salary": job.stipend_salary,
                        "experience_required": job.experience_required,
                        "skills_required": job.skills_required or [],
                    }
                )

            vectors = self.model.encode(
                texts,
                normalize_embeddings=True,
                show_progress_bar=False,
            ).astype(np.float32)

            dimension = vectors.shape[1]
            index = faiss.IndexFlatIP(dimension)
            index.add(vectors)

            self.index = index
            self.metadata = metadata_list

            self.save_index()
            logger.info(
                f"Successfully embedded {len(non_spam_jobs)} jobs and saved index to '{self.index_dir}'."
            )
            return len(non_spam_jobs)

        finally:
            db.close()

    def search(self, query_text: str | None, top_k: int = 5) -> list[dict[str, Any]]:
        """Search the FAISS index for top-K most similar job listings to a query text.

        Args:
            query_text: Text string (e.g. user profile or target role) to match against.
            top_k: Maximum number of similar jobs to return.

        Returns:
            list[dict]: List of dictionaries containing job details and similarity score ('score').
        """
        if not query_text or not query_text.strip():
            return []

        if self.index is None or self.index.ntotal == 0 or not self.metadata:
            logger.warning("FAISS index is empty or not initialized.")
            return []

        query_vector = self.embed_text(query_text)
        query_vector = np.expand_dims(query_vector, axis=0).astype(np.float32)

        k = min(top_k, self.index.ntotal)
        scores, indices = self.index.search(query_vector, k)

        results = []
        for score, idx in zip(scores[0], indices[0]):
            if 0 <= idx < len(self.metadata):
                item = dict(self.metadata[idx])
                item["score"] = float(score)
                results.append(item)

        return results

    def save_index(self, dir_path: str | None = None) -> None:
        """Save the FAISS index vector file and metadata mapping to disk.

        Args:
            dir_path: Target directory path. Defaults to self.index_dir.
        """
        target_dir = dir_path or self.index_dir
        os.makedirs(target_dir, exist_ok=True)

        index_file = os.path.join(target_dir, "index.faiss")
        meta_file = os.path.join(target_dir, "metadata.json")

        if self.index is not None:
            faiss.write_index(self.index, index_file)
        elif os.path.exists(index_file):
            os.remove(index_file)

        with open(meta_file, "w", encoding="utf-8") as f:
            json.dump(self.metadata, f, indent=2)

        logger.info(f"FAISS index and metadata saved to '{target_dir}'.")

    def load_index(self, dir_path: str | None = None) -> bool:
        """Load the FAISS index and metadata mapping from disk if present.

        Args:
            dir_path: Target directory path. Defaults to self.index_dir.

        Returns:
            bool: True if loaded successfully, False otherwise.
        """
        target_dir = dir_path or self.index_dir
        index_file = os.path.join(target_dir, "index.faiss")
        meta_file = os.path.join(target_dir, "metadata.json")

        if os.path.exists(index_file) and os.path.exists(meta_file):
            try:
                self.index = faiss.read_index(index_file)
                with open(meta_file, "r", encoding="utf-8") as f:
                    self.metadata = json.load(f)
                logger.info(
                    f"Loaded FAISS index with {self.index.ntotal} vectors from '{target_dir}'."
                )
                return True
            except Exception as e:
                logger.error(f"Error loading FAISS index from '{target_dir}': {e}")
                self.index = None
                self.metadata = []
                return False

        return False


def main() -> None:
    """CLI entry point for embedding jobs."""
    parser = argparse.ArgumentParser(description="HireFlow AI Embedding Pipeline CLI")
    parser.add_argument(
        "--embed-jobs",
        action="store_true",
        help="Embed all non-spam jobs in the database and save FAISS index to disk.",
    )
    args = parser.parse_args()

    if args.embed_jobs:
        pipeline = EmbeddingPipeline()
        count = pipeline.embed_jobs()
        print(
            f"Successfully embedded {count} non-spam jobs and saved FAISS index to '{pipeline.index_dir}'."
        )


if __name__ == "__main__":
    main()
