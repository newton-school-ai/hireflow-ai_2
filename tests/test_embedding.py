import os
import tempfile
import uuid
import numpy as np
import pytest
from unittest.mock import patch, MagicMock

from src.pipelines.embedding_pipeline import EmbeddingPipeline
from src.models.job import Job


@pytest.fixture
def temp_index_dir():
    with tempfile.TemporaryDirectory() as d:
        yield d


@pytest.fixture
def mock_jobs():
    job1 = Job(
        id=uuid.uuid4(),
        role_title="Python Developer",
        company_name="TechCorp",
        skills_required=["Python", "FastAPI"],
        jd_text="Looking for a Python dev with backend experience.",
    )
    job2 = Job(
        id=uuid.uuid4(),
        role_title="AI Engineer",
        company_name="AI Inc",
        skills_required=["Python", "PyTorch", "LLM"],
        jd_text="Build RAG pipelines and work with large language models.",
    )
    job3 = Job(
        id=uuid.uuid4(),
        role_title="Frontend Developer",
        company_name="Web LLC",
        skills_required=["React", "JS"],
        jd_text="Short JD.",
    )
    return [job1, job2, job3]


def test_embed_text_normal_and_empty(temp_index_dir):
    ep = EmbeddingPipeline(index_dir=temp_index_dir)

    # Normal text
    vec = ep.embed_text("Python dev")
    assert vec.shape == (384,)  # all-MiniLM-L6-v2 dimension
    assert not np.all(vec == 0)

    # Empty text
    empty_vec = ep.embed_text("")
    assert empty_vec.shape == (384,)
    assert np.all(empty_vec == 0)


@patch("src.pipelines.embedding_pipeline.SessionLocal")
def test_build_and_search_normal(mock_session_local, mock_jobs, temp_index_dir):
    mock_session = MagicMock()
    mock_session_local.return_value = mock_session
    mock_session.query.return_value.filter.return_value.all.return_value = mock_jobs

    ep = EmbeddingPipeline(index_dir=temp_index_dir)
    ep.build_index()

    # Check files created
    assert os.path.exists(os.path.join(temp_index_dir, "index.faiss"))
    assert os.path.exists(os.path.join(temp_index_dir, "metadata.json"))

    # Test normal search
    results = ep.search("Looking for Python and FastAPI", top_k=2)
    assert len(results) == 2
    # The highest score should be TechCorp since it matches Python and FastAPI closely
    assert results[0]["company_name"] == "TechCorp"
    assert "score" in results[0]


@patch("src.pipelines.embedding_pipeline.SessionLocal")
def test_search_empty_input(mock_session_local, mock_jobs, temp_index_dir):
    mock_session = MagicMock()
    mock_session_local.return_value = mock_session
    mock_session.query.return_value.filter.return_value.all.return_value = mock_jobs

    ep = EmbeddingPipeline(index_dir=temp_index_dir)
    ep.build_index()

    # Test empty search returns no results
    results = ep.search("", top_k=5)
    assert len(results) == 0


@patch("src.pipelines.embedding_pipeline.SessionLocal")
def test_search_short_jd(mock_session_local, mock_jobs, temp_index_dir):
    mock_session = MagicMock()
    mock_session_local.return_value = mock_session
    mock_session.query.return_value.filter.return_value.all.return_value = mock_jobs

    ep = EmbeddingPipeline(index_dir=temp_index_dir)
    ep.build_index()

    # Search for frontend
    results = ep.search("React Developer", top_k=1)
    assert len(results) == 1
    assert results[0]["company_name"] == "Web LLC"
