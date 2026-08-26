"""
Unit tests for the embedding pipeline and FAISS index.

Includes tests for embedding generation, handling of empty/short texts,
FAISS search functionality, saving and loading of index files, and DB integration.
"""

import os
import tempfile
import uuid
from unittest.mock import patch

import numpy as np
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.config.database import Base
from src.models.job import Job
from src.pipelines.embedding_pipeline import EmbeddingPipeline


class MockSentenceTransformer:
    """Mock implementation of SentenceTransformer to run tests offline."""

    def __init__(self, model_name: str = "dummy-model") -> None:
        self.model_name = model_name
        self.dimension = 128  # Small dimension for fast test execution

    def encode(
        self, texts: str | list[str], normalize_embeddings: bool = True
    ) -> np.ndarray:
        """Generates mock embeddings of shape (128,) or (N, 128)."""
        if isinstance(texts, str):
            # 1D unit vector
            vector = np.zeros(self.dimension, dtype=np.float32)
            # Hash-based element to make different texts produce different vectors
            idx = abs(hash(texts)) % self.dimension
            vector[idx] = 1.0
            return vector
        else:
            # 2D unit vectors
            matrix = np.zeros((len(texts), self.dimension), dtype=np.float32)
            for i, text in enumerate(texts):
                idx = abs(hash(text)) % self.dimension
                matrix[i, idx] = 1.0
            return matrix


@pytest.fixture
def mock_transformer():
    """Fixture to patch the get_embedding_model utility to return a mock model."""
    mock_model = MockSentenceTransformer()
    with patch(
        "src.pipelines.embedding_pipeline.get_embedding_model", return_value=mock_model
    ) as mocked:
        yield mocked


@pytest.fixture
def db_session():
    """Fixture for in-memory SQLite database session."""
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}
    )
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    Base.metadata.create_all(bind=engine)
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)


def test_embed_text_valid(mock_transformer):
    """Checks that embed_text generates a normalized vector of correct dimension."""
    pipeline = EmbeddingPipeline()
    vector = pipeline.embed_text("Python Developer")

    assert vector is not None
    assert isinstance(vector, np.ndarray)
    assert vector.dtype == np.float32
    assert vector.shape == (128,)
    # Verify L2 normalized (norm should be close to 1)
    norm = np.linalg.norm(vector)
    assert pytest.approx(norm, abs=1e-5) == 1.0


def test_embed_text_edge_cases(mock_transformer):
    """Verifies that embed_text handles None, empty strings, and short texts."""
    pipeline = EmbeddingPipeline()

    # None input
    assert pipeline.embed_text(None) is None

    # Empty string input
    assert pipeline.embed_text("") is None
    assert pipeline.embed_text("   ") is None

    # Very short text (should still succeed, but should not crash)
    vec = pipeline.embed_text("a")
    assert vec is not None
    assert vec.shape == (128,)


def test_embed_jobs_filtering(mock_transformer, db_session):
    """Verifies that embed_jobs processes non-spam jobs and ignores spam/empty jobs."""
    # Seed mock database with mix of clean, spam, and empty description jobs
    job_clean1 = Job(
        id=uuid.uuid4(),
        company_name="Company A",
        role_title="Engineer 1",
        jd_text="Clean job description listing skills.",
        is_spam=False,
        listing_type="job",
        application_url="https://example.com/apply1",
    )
    job_clean2 = Job(
        id=uuid.uuid4(),
        company_name="Company B",
        role_title="Engineer 2",
        jd_text="Another clean job listing.",
        is_spam=False,
        listing_type="job",
        application_url="https://example.com/apply2",
    )
    job_spam = Job(
        id=uuid.uuid4(),
        company_name="Spam Corp",
        role_title="Get Rich Fast",
        jd_text="Vague description of easy money.",
        is_spam=True,
        listing_type="job",
        application_url="https://example.com/apply_spam",
    )
    job_empty_jd = Job(
        id=uuid.uuid4(),
        company_name="Company C",
        role_title="Engineer 3",
        jd_text="",
        is_spam=False,
        listing_type="job",
        application_url="https://example.com/apply3",
    )

    db_session.add_all([job_clean1, job_clean2, job_spam, job_empty_jd])
    db_session.commit()

    pipeline = EmbeddingPipeline()
    job_ids, embeddings = pipeline.embed_jobs(db_session)

    # Should only embed clean1 and clean2 (len == 2)
    assert len(job_ids) == 2
    assert job_clean1.id in job_ids
    assert job_clean2.id in job_ids
    assert job_spam.id not in job_ids
    assert job_empty_jd.id not in job_ids

    assert embeddings is not None
    assert embeddings.shape == (2, 128)


def test_empty_database_handling(mock_transformer, db_session):
    """Verifies that the pipeline handles an empty database gracefully."""
    pipeline = EmbeddingPipeline()
    job_ids, embeddings = pipeline.embed_jobs(db_session)
    assert job_ids == []
    assert embeddings is None

    # Building index on empty DB should not crash
    pipeline.build_index(db_session)
    assert pipeline.index is None
    assert pipeline.job_metadata == []

    # Searching empty index should return empty list
    results = pipeline.search("test query")
    assert results == []


def test_faiss_search_and_similarity(mock_transformer, db_session):
    """Verifies building the index and executing a similarity search."""
    job1 = Job(
        id=uuid.uuid4(),
        company_name="Google",
        role_title="Staff Software Engineer",
        jd_text="Develop high performance scalable systems in Go/C++.",
        is_spam=False,
        listing_type="job",
        application_url="https://example.com/google1",
    )
    job2 = Job(
        id=uuid.uuid4(),
        company_name="Notion",
        role_title="Frontend Developer",
        jd_text="Build polished user experiences with React, TypeScript, CSS.",
        is_spam=False,
        listing_type="job",
        application_url="https://example.com/notion1",
    )

    db_session.add_all([job1, job2])
    db_session.commit()

    pipeline = EmbeddingPipeline()
    pipeline.build_index(db_session)

    # Search with a query matching job2 features better
    # In our MockSentenceTransformer, we hash the texts.
    # We will just verify the keys in the output.
    results = pipeline.search("Frontend TypeScript", top_k=2)

    assert len(results) <= 2
    for r in results:
        assert "job_id" in r
        assert "role_title" in r
        assert "company_name" in r
        assert "score" in r
        assert isinstance(r["score"], float)
        assert isinstance(r["role_title"], str)
        assert isinstance(r["company_name"], str)

    # Searching with empty/None query
    assert pipeline.search(None) == []
    assert pipeline.search("") == []


def test_save_and_load_index(mock_transformer, db_session):
    """Verifies that saving and loading index returns identical search results."""
    job1 = Job(
        id=uuid.uuid4(),
        company_name="Meta",
        role_title="Research Scientist",
        jd_text="Build PyTorch models for computer vision and NLP.",
        is_spam=False,
        listing_type="job",
        application_url="https://example.com/meta1",
    )
    db_session.add(job1)
    db_session.commit()

    pipeline = EmbeddingPipeline()
    pipeline.build_index(db_session)

    # Perform initial search
    query = "PyTorch Deep Learning"
    initial_results = pipeline.search(query, top_k=1)
    assert len(initial_results) == 1

    # Save to temp directory
    with tempfile.TemporaryDirectory() as temp_dir:
        pipeline.save_index(temp_dir)

        # Ensure files were created
        assert os.path.exists(os.path.join(temp_dir, "index.faiss"))
        assert os.path.exists(os.path.join(temp_dir, "metadata.json"))

        # Load into a new pipeline instance
        new_pipeline = EmbeddingPipeline(index_dir=temp_dir)
        load_success = new_pipeline.load_index()

        assert load_success is True
        assert new_pipeline.index is not None
        assert len(new_pipeline.job_metadata) == 1

        # Perform the same search on the loaded pipeline
        loaded_results = new_pipeline.search(query, top_k=1)
        assert len(loaded_results) == 1

        # Check search results match exactly
        assert loaded_results[0]["job_id"] == initial_results[0]["job_id"]
        assert loaded_results[0]["score"] == pytest.approx(initial_results[0]["score"])
        assert loaded_results[0]["role_title"] == initial_results[0]["role_title"]
        assert loaded_results[0]["company_name"] == initial_results[0]["company_name"]


def test_load_non_existent_index(mock_transformer):
    """Checks that loading a non-existent index fails gracefully without crash."""
    with tempfile.TemporaryDirectory() as temp_dir:
        # Pass non-existent path
        bad_dir = os.path.join(temp_dir, "does_not_exist")
        pipeline = EmbeddingPipeline(index_dir=bad_dir)
        assert pipeline.load_index() is False
        assert pipeline.index is None
        assert pipeline.job_metadata == []
