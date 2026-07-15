"""Tests for the Embedding Pipeline."""

import json
from unittest.mock import MagicMock, patch

import faiss
import numpy as np
import pytest

from src.pipelines.embedding_pipeline import (
    INDEX_FILENAME,
    METADATA_FILENAME,
    EmbeddingPipeline,
)


@pytest.fixture
def mock_sentence_transformer():
    """Mock the SentenceTransformer model to avoid downloading it."""
    with patch("sentence_transformers.SentenceTransformer") as mock_st:
        # Create a mock model instance
        mock_model = MagicMock()
        mock_model.get_sentence_embedding_dimension.return_value = 384

        # When encode is called, return dummy embeddings of size (len(texts), 384)
        def mock_encode(texts, convert_to_numpy=True):
            if isinstance(texts, str):
                texts = [texts]
            # Create a simple deterministic embedding based on length
            embeddings = np.random.rand(len(texts), 384).astype(np.float32)
            # Add some distinctness for tests
            for i, text in enumerate(texts):
                embeddings[i, 0] = len(text)
            return embeddings

        mock_model.encode.side_effect = mock_encode

        # The SentenceTransformer constructor returns this instance
        mock_st.return_value = mock_model
        yield mock_st


@pytest.fixture
def temp_index_dir(tmp_path):
    """Provide a temporary directory for the FAISS index."""
    return tmp_path / "faiss_index"


@pytest.fixture
def pipeline(temp_index_dir, mock_sentence_transformer):
    """Provide an EmbeddingPipeline instance with a temporary index directory."""
    return EmbeddingPipeline(index_dir=temp_index_dir)


def test_embed_text_normal(pipeline):
    """Test embedding a normal string."""
    text = "Machine Learning Engineer"
    embedding = pipeline.embed_text(text)

    assert isinstance(embedding, np.ndarray)
    assert embedding.shape == (1, 384)
    # Check L2 normalization (norm should be ~1.0)
    assert np.isclose(np.linalg.norm(embedding), 1.0, atol=1e-5)


def test_embed_text_empty_and_whitespace(pipeline):
    """Test embedding empty or whitespace-only strings."""
    for text in ["", "   ", "\n\t"]:
        embedding = pipeline.embed_text(text)
        assert isinstance(embedding, np.ndarray)
        assert embedding.shape == (1, 384)
        # Empty text should return a zero vector
        assert np.allclose(embedding, 0.0)


def test_embed_jobs_batch(pipeline):
    """Test embedding a batch of strings."""
    texts = ["Job A", "Job B", "Job C"]
    embeddings = pipeline.embed_jobs(texts)

    assert isinstance(embeddings, np.ndarray)
    assert embeddings.shape == (3, 384)
    # Check L2 normalization for the first vector
    assert np.isclose(np.linalg.norm(embeddings[0]), 1.0, atol=1e-5)


def test_embed_jobs_empty_list(pipeline):
    """Test embedding an empty list of strings."""
    embeddings = pipeline.embed_jobs([])
    assert isinstance(embeddings, np.ndarray)
    assert len(embeddings) == 0


def test_index_build_and_save(pipeline, temp_index_dir):
    """Test building and saving the FAISS index."""
    embeddings = np.random.rand(5, 384).astype(np.float32)
    faiss.normalize_L2(embeddings)

    pipeline._metadata = {
        i: {"job_id": f"job-{i}", "role_title": "Role", "company_name": "Co"}
        for i in range(5)
    }

    pipeline._build_index(embeddings)
    assert pipeline._index.ntotal == 5

    pipeline._save_index()

    # Verify files were created
    assert (temp_index_dir / INDEX_FILENAME).exists()
    assert (temp_index_dir / METADATA_FILENAME).exists()

    # Verify metadata JSON structure
    with open(temp_index_dir / METADATA_FILENAME, "r") as f:
        meta = json.load(f)
        assert "0" in meta
        assert meta["0"]["job_id"] == "job-0"


def test_index_load_and_search(pipeline, temp_index_dir):
    """Test loading the FAISS index and performing a search."""
    # 1. Setup: Create and save an index first
    embeddings = np.random.rand(10, 384).astype(np.float32)
    faiss.normalize_L2(embeddings)

    pipeline._metadata = {
        i: {"job_id": f"job-{i}", "role_title": f"Role {i}", "company_name": "Co"}
        for i in range(10)
    }
    pipeline._build_index(embeddings)
    pipeline._save_index()

    # 2. Reset the pipeline's in-memory state
    pipeline._index = None
    pipeline._metadata = {}

    # 3. Test Search (which should trigger _load_index)
    results = pipeline.search("Search Query", top_k=3)

    assert len(results) == 3
    for res in results:
        assert "job_id" in res
        assert "role_title" in res
        assert "company_name" in res
        assert "score" in res
        assert isinstance(res["score"], float)


def test_search_empty_input(pipeline):
    """Search with empty input should return empty list without error."""
    assert pipeline.search("") == []
    assert pipeline.search("   ") == []


def test_search_when_no_index(pipeline):
    """Search when index doesn't exist should return empty list gracefully."""
    # Ensure directory is empty
    results = pipeline.search("test")
    assert results == []


@patch("src.pipelines.embedding_pipeline.SessionLocal")
def test_run_orchestration(mock_session_local, pipeline, temp_index_dir):
    """Test the end-to-end run method."""
    mock_db = MagicMock()
    mock_session_local.return_value = mock_db

    # Mock the database query chain: db.query().filter().all()
    mock_query = MagicMock()
    mock_filter = MagicMock()

    # Create mock jobs
    mock_job_1 = MagicMock(
        id="uuid-1",
        role_title="Data Scientist",
        company_name="AI Co",
        jd_text="Build models.",
    )
    mock_job_2 = MagicMock(
        id="uuid-2",
        role_title="Backend Engineer",
        company_name="Dev Co",
        jd_text="Write APIs.",
    )

    mock_filter.all.return_value = [mock_job_1, mock_job_2]
    mock_query.filter.return_value = mock_filter
    mock_db.query.return_value = mock_query

    # Execute the run method
    pipeline.run()

    # Verify the database was queried correctly
    mock_db.query.assert_called_once()
    mock_query.filter.assert_called_once()
    mock_db.close.assert_called_once()

    # Verify the index and metadata were saved
    assert (temp_index_dir / INDEX_FILENAME).exists()
    assert (temp_index_dir / METADATA_FILENAME).exists()

    # Verify metadata contents
    with open(temp_index_dir / METADATA_FILENAME, "r") as f:
        meta = json.load(f)
        assert len(meta) == 2
        assert meta["0"]["job_id"] == "uuid-1"
        assert meta["0"]["role_title"] == "Data Scientist"
        assert meta["1"]["job_id"] == "uuid-2"


@patch("src.pipelines.embedding_pipeline.SessionLocal")
def test_run_empty_database(mock_session_local, pipeline, temp_index_dir):
    """Test run when no jobs are returned."""
    mock_db = MagicMock()
    mock_session_local.return_value = mock_db

    mock_query = MagicMock()
    mock_filter = MagicMock()
    mock_filter.all.return_value = []  # No jobs

    mock_query.filter.return_value = mock_filter
    mock_db.query.return_value = mock_query

    pipeline.run()

    # No files should be created because there were no jobs
    assert not (temp_index_dir / INDEX_FILENAME).exists()
    assert not (temp_index_dir / METADATA_FILENAME).exists()
