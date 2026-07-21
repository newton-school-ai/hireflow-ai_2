import os
import shutil
import tempfile
from unittest.mock import patch

import numpy as np
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.config.database import Base
from src.models.job import Job
from src.pipelines.embedding_pipeline import EmbeddingPipeline

# SQLite in-memory test database
TEST_DB_URL = "sqlite:///:memory:"
engine = create_engine(TEST_DB_URL, connect_args={"check_same_thread": False})
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


@pytest.fixture
def temp_index_dir():
    temp_dir = tempfile.mkdtemp()
    yield temp_dir
    shutil.rmtree(temp_dir, ignore_errors=True)


@pytest.fixture
def clean_db():
    Base.metadata.create_all(bind=engine)
    yield TestingSessionLocal
    Base.metadata.drop_all(bind=engine)


def test_embed_text_shape_and_normalization(temp_index_dir):
    ep = EmbeddingPipeline(index_dir=temp_index_dir)
    text = "Python developer with FastAPI and PostgreSQL experience"
    vec = ep.embed_text(text)

    assert isinstance(vec, np.ndarray)
    assert vec.ndim == 1
    assert vec.shape[0] == 384  # default all-MiniLM-L6-v2 dimension
    assert vec.dtype == np.float32

    # Vector should be normalized to unit length
    norm = np.linalg.norm(vec)
    assert np.isclose(norm, 1.0, atol=1e-3)


def test_embed_text_empty_and_short(temp_index_dir):
    ep = EmbeddingPipeline(index_dir=temp_index_dir)

    # Empty text
    vec_empty = ep.embed_text("")
    assert isinstance(vec_empty, np.ndarray)
    assert vec_empty.shape[0] == 384

    # None text
    vec_none = ep.embed_text(None)
    assert isinstance(vec_none, np.ndarray)
    assert vec_none.shape[0] == 384

    # Very short text
    vec_short = ep.embed_text("AI")
    assert isinstance(vec_short, np.ndarray)
    assert vec_short.shape[0] == 384


def test_embed_jobs_and_search(clean_db, temp_index_dir):
    with patch("src.pipelines.embedding_pipeline.SessionLocal", clean_db):
        db = clean_db()

        job1 = Job(
            company_name="AI Flow",
            role_title="AI Engineer",
            jd_text="Building LangChain RAG pipelines, multi-agent systems, and vector search.",
            skills_required=["Python", "LangChain", "FAISS"],
            stipend_salary="$30/hr",
            application_url="https://example.com/job1",
            listing_type="job",
            is_spam=False,
        )
        job2 = Job(
            company_name="Web Corp",
            role_title="Frontend Developer",
            jd_text="Creating responsive React UI components and CSS styling.",
            skills_required=["React", "TypeScript", "CSS"],
            stipend_salary="$25/hr",
            application_url="https://example.com/job2",
            listing_type="job",
            is_spam=False,
        )
        job_spam = Job(
            company_name="Scam Corp",
            role_title="Spam Role",
            jd_text="Earn money fast from home without any experience required.",
            skills_required=[],
            stipend_salary="$1000/day",
            application_url="https://example.com/job_spam",
            listing_type="job",
            is_spam=True,
        )

        db.add_all([job1, job2, job_spam])
        db.commit()
        db.close()

        ep = EmbeddingPipeline(index_dir=temp_index_dir)
        count = ep.embed_jobs()

        assert count == 2  # Only non-spam jobs embedded
        assert ep.index is not None
        assert ep.index.ntotal == 2

        # Search query matching AI/LangChain role
        results = ep.search(
            "Python AI engineer with RAG and vector database experience", top_k=2
        )

        assert len(results) == 2
        top_match = results[0]
        assert top_match["role_title"] == "AI Engineer"
        assert top_match["company_name"] == "AI Flow"
        assert "score" in top_match
        assert top_match["score"] > 0.4  # Strong similarity score


def test_index_persistence(clean_db, temp_index_dir):
    with patch("src.pipelines.embedding_pipeline.SessionLocal", clean_db):
        db = clean_db()
        job = Job(
            company_name="DataFlow Labs",
            role_title="Data Engineer",
            jd_text="Python ETL pipeline development with PostgreSQL and Spark.",
            skills_required=["Python", "SQL", "Spark"],
            stipend_salary="100k",
            application_url="https://example.com/datajob",
            listing_type="job",
            is_spam=False,
        )
        db.add(job)
        db.commit()
        db.close()

        # Build index and save
        ep1 = EmbeddingPipeline(index_dir=temp_index_dir)
        ep1.embed_jobs()

        assert os.path.exists(os.path.join(temp_index_dir, "index.faiss"))
        assert os.path.exists(os.path.join(temp_index_dir, "metadata.json"))

        # Re-instantiate new pipeline pointing to same temp_index_dir
        ep2 = EmbeddingPipeline(index_dir=temp_index_dir)
        assert ep2.index is not None
        assert ep2.index.ntotal == 1
        assert len(ep2.metadata) == 1
        assert ep2.metadata[0]["company_name"] == "DataFlow Labs"


def test_search_empty_input_and_empty_index(temp_index_dir):
    ep = EmbeddingPipeline(index_dir=temp_index_dir)

    # Search on empty index
    res_empty_index = ep.search("Software engineer")
    assert res_empty_index == []

    # Empty string query
    res_empty_query = ep.search("")
    assert res_empty_query == []

    # None query
    res_none_query = ep.search(None)
    assert res_none_query == []
