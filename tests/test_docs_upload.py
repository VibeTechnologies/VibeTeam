import os
import shutil
import pytest
from fastapi.testclient import TestClient
from vibeteam.api.main import app
from agents.shared.docs_tools import _get_uploads_dir, list_uploaded_docs


from agents.shared.docs_tools import _get_uploads_dir, list_uploaded_docs, search_docs, list_docs


@pytest.fixture
def api_client():
    return TestClient(app)


@pytest.fixture
def clean_uploads():
    uploads_dir = _get_uploads_dir()
    # Clean up uploads dir before and after test
    if os.path.exists(uploads_dir):
        shutil.rmtree(uploads_dir)
    yield
    if os.path.exists(uploads_dir):
        shutil.rmtree(uploads_dir)


class TestDocsUpload:
    def test_upload_file(self, api_client, clean_uploads):
        # Create a dummy file
        content = b"This is a test document content."
        files = {"file": ("test_doc.txt", content, "text/plain")}

        response = api_client.post("/v1/docs/upload", files=files)

        assert response.status_code == 200
        data = response.json()
        assert data["filename"] == "test_doc.txt"
        assert "uploaded and indexed" in data["message"]

        # Verify file exists
        uploads_dir = _get_uploads_dir()
        file_path = os.path.join(uploads_dir, "test_doc.txt")
        assert os.path.exists(file_path)
        with open(file_path, "rb") as f:
            assert f.read() == content

        # Verify it's in the list
        docs = list_uploaded_docs()
        assert "test_doc.txt" in docs

        # Verify search finds it
        # Note: We need to wait for index rebuild or force it?
        # The endpoint calls rebuild_index(), which updates the global index.
        results = search_docs("test document content")
        assert "test_doc.txt" in results or "test document content" in results

    def test_upload_markdown_file(self, api_client, clean_uploads):
        # Create a dummy markdown file
        content = b"# New Feature\n\nThis is a markdown document describing a new feature.\nKey point: The magic number is 42."
        files = {"file": ("feature.md", content, "text/plain")}

        response = api_client.post("/v1/docs/upload", files=files)

        assert response.status_code == 200

        # Verify file exists
        uploads_dir = _get_uploads_dir()
        file_path = os.path.join(uploads_dir, "feature.md")
        assert os.path.exists(file_path)

        # Verify search finds it with markdown parsing
        # The search_docs function uses title extraction and snippet generation
        results = search_docs("magic number")

        # Should find the key point
        assert "feature.md" in results
        assert "magic number is 42" in results
        # Should extract title
        assert "New Feature" in results

    def test_upload_with_session_id(self, api_client, clean_uploads):
        content = b"Session specific content"
        files = {"file": ("session_doc.txt", content, "text/plain")}
        session_id = "test-session-123"

        response = api_client.post("/v1/docs/upload", files=files, data={"session_id": session_id})

        assert response.status_code == 200

        # Verify file exists in session subdir
        uploads_dir = _get_uploads_dir()
        file_path = os.path.join(uploads_dir, session_id, "session_doc.txt")
        assert os.path.exists(file_path)

        # Verify listing handles subdirs
        docs = list_uploaded_docs()
        # list_uploaded_docs returns relative paths
        expected_path = os.path.join(session_id, "session_doc.txt")
        assert expected_path in docs
