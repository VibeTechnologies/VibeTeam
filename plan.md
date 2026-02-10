# Plan: User Document Upload for Knowledge Base (Issue #47)

## Goal
Enable users to upload documents directly to the agent's knowledge base via the API, allowing the agent to answer questions based on these ad-hoc documents.

## Tasks

- [x] **Infrastructure & Configuration**
    - [x] Define storage directory for uploaded files (e.g., `data/uploads`).
    - [x] Ensure the directory is created if it doesn't exist.

- [x] **API Implementation (`vibeteam/api/main.py`)**
    - [x] Add `POST /v1/docs/upload` endpoint.
    - [x] Handle multipart file uploads.
    - [x] Support `session_id` for namespacing uploads.
    - [x] Save uploaded files to the storage directory.
    - [x] Trigger index rebuild after upload.

- [x] **Docs Tooling (`agents/shared/docs_tools.py`)**
    - [x] Update `DocsIndex` to include the uploads directory in its search paths.
    - [x] Ensure `_find_markdown_files` (or new logic) scans the uploads directory.
    - [x] Add `list_uploaded_docs()` function to list user-uploaded files.
    - [x] Ensure `search_docs` returns results from uploaded files.

- [x] **Verification**
    - [x] Create a test script to upload a file via the API.
    - [x] Verify the file is saved correctly.
    - [x] Verify `search_docs` finds content in the uploaded file.
