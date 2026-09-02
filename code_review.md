# Financial-Rag Code Review

This document contains a detailed code review of the Financial-Rag codebase, focusing on security, performance, code quality, and architectural considerations.

## 1. Security Vulnerabilities & Risks

### 1.1 Hardcoded Credentials
- **File**: `backend/server.py`
- **Issue**: The `/api/login` endpoint contains a hardcoded password `admin`.
- **Recommendation**: Remove hardcoded credentials. Implement proper authentication using secure password hashing (e.g., `bcrypt`) and a database or rely on a secure identity provider.

### 1.2 Unsanitized Input to Subprocess
- **File**: `frontend/app.py`
- **Issue**: In the ingestion dashboard, `symbol` and `doc_type` inputs are taken from the Streamlit UI and passed directly into a `subprocess.run` command list. While passing as a list prevents standard shell injection, if users pass arguments starting with `--`, they can inject unintended flags into `compilation_bridge.py`.
- **Recommendation**: Validate and sanitize the `symbol` and `doc_type` inputs using regex before passing them to `subprocess.run`. Ensure they strictly contain expected characters (e.g., alphanumeric only).

### 1.3 CORS Configuration
- **File**: `backend/server.py`
- **Issue**: `allow_origins=['*']` is set in `CORSMiddleware`.
- **Recommendation**: In a production environment, restrict CORS to specific domains (e.g., the exact URL where the frontend is hosted).

## 2. Performance & Scalability

### 2.1 Thread Pool Limits and Concurrency
- **File**: `backend/server.py`
- **Issue**: `_QUERY_EXECUTOR` uses a `ThreadPoolExecutor` with `max_workers=4`. While this prevents thread exhaustion from stalled LLM calls, it severely limits the server to handling a maximum of 4 concurrent requests. Furthermore, `asyncio.wait_for` is used to timeout the request, but the underlying thread continues running, potentially tying up a slot in the pool until the LLM call completes or times out naturally.
- **Recommendation**: Transition from synchronous `requests` to an asynchronous HTTP client like `httpx` in the `rag_engine.py`. This would allow native `async/await` execution, eliminating the need for a thread pool and fully leveraging FastAPI's asynchronous capabilities.

### 2.2 Synchronous HTTP Calls
- **File**: `backend/rag/rag_engine.py`
- **Issue**: All LLM provider interactions (Groq, Gemini, Anthropic, OpenRouter) rely on the synchronous `requests` library. This blocks the thread execution during long LLM inference times.
- **Recommendation**: Refactor `_call_gemini`, `_call_anthropic`, and `_call_openai_compat` to use `httpx.AsyncClient`.

### 2.3 Hardcoded Backend URL in Frontend
- **File**: `frontend/app.py`
- **Issue**: `requests.post("http://127.0.0.1:5000/query", ...)` is hardcoded. 
- **Recommendation**: Make the backend URL configurable via an environment variable, allowing the frontend to connect to remote or containerized backends.

## 3. Code Quality & Best Practices

### 3.1 Duplicate Imports
- **File**: `backend/server.py`
- **Issue**: Multiple duplicated imports exist at the top of the file:
  ```python
  from fastapi.staticfiles import StaticFiles
  from fastapi.responses import StreamingResponse
  from fastapi.middleware.cors import CORSMiddleware
  import json
  ```
- **Recommendation**: Consolidate imports for cleaner and more maintainable code.

### 3.2 Dummy Implementations
- **File**: `backend/server.py`
- **Issue**: `/api/documents` relies on a glob pattern over a specific subdirectory structure instead of querying the actual database or MinIO storage. `/api/ingest` is merely a stub returning success.
- **Recommendation**: Implement proper database lookups for the documents API. Ensure `/api/ingest` actually triggers the ingestion pipeline asynchronously (e.g., using Celery or background tasks).

### 3.3 Singleton State Management
- **File**: `backend/rag/rag_engine.py`
- **Issue**: `_get_synthesis_pipeline` uses global variables (`_synthesis_pipeline`, `_synthesis_pipeline_failed_at`) for singleton management. While acceptable for scripts, it can complicate testing and lead to unpredictable state across requests in an application server.
- **Recommendation**: Use FastAPI's dependency injection system to manage the lifecycle and initialization of the synthesis pipeline.

### 3.4 Input Validation
- **File**: `backend/server.py`
- **Issue**: The `QueryRequest` Pydantic model does not enforce constraints on its fields.
- **Recommendation**: Add constraints and validators to `QueryRequest` (e.g., `Field(max_length=500)`, `Field(pattern="^[A-Z0-9]+$")` for symbols) to reject malformed requests early.

## 4. Conclusion
The architecture cleanly separates the backend (FastAPI) and frontend (Streamlit). However, significant improvements are needed in security (removing hardcoded passwords and sanitizing inputs) and concurrency (moving to async HTTP requests). Implementing these changes will ensure the application is secure, robust, and scalable.
