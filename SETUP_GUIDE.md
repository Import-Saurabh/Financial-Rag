# Financial RAG Platform — Complete Setup & Execution Guide 🚀

This guide provides end-to-end, step-by-step instructions to set up, configure, run, and test the **Financial RAG Platform** on your local machine across **Windows**, **macOS**, and **Linux**.

---

## 📋 Table of Contents
1. [Prerequisites & System Requirements](#1-prerequisites--system-requirements)
2. [Project Architecture Overview](#2-project-architecture-overview)
3. [Step 1: Clone or Navigate to Project](#step-1-clone-or-navigate-to-project)
4. [Step 2: Python Environment Setup](#step-2-python-environment-setup)
5. [Step 3: Install Backend Dependencies](#step-3-install-backend-dependencies)
6. [Step 4: Install Frontend Dependencies](#step-4-install-frontend-dependencies)
7. [Step 5: Configure Environment Variables (.env)](#step-5-configure-environment-variables-env)
8. [Step 6: Running the Application](#step-6-running-the-application)
   - [Option A: Full Development Mode (Recommended for Development)](#option-a-full-development-mode-recommended)
   - [Option B: Single-Port Production Mode (FastAPI Serves React SPA)](#option-b-single-port-production-mode)
   - [Option C: Model Context Protocol (MCP) Server](#option-c-model-context-protocol-mcp-server)
9. [Step 7: Accessing the Application & Default Credentials](#step-7-accessing-the-application--default-credentials)
10. [Step 8: Verification & Testing](#step-8-verification--testing)
11. [Troubleshooting & FAQs](#troubleshooting--faqs)

---

## 1. Prerequisites & System Requirements

Ensure the following tools are installed before proceeding:

| Dependency | Minimum Version | Recommended Version | Check Installation Command |
| :--- | :--- | :--- | :--- |
| **Python** | `3.10` | `3.11+` | `python --version` (or `python3 --version`) |
| **Node.js** | `18.0.0` | `20.x` or `22.x LTS` | `node --version` |
| **npm** | `9.0.0` | `10.x+` | `npm --version` |
| **Git** | `2.x` | Latest | `git --version` |

> [!NOTE]
> - **Hardware Recommendation:** 8 GB+ RAM and a modern multi-core CPU. The platform uses local sentence transformers (`all-MiniLM-L6-v2`) and cross-encoders (`ms-marco-MiniLM-L-6-v2`) which download automatically on first run (~150MB).
> - **API Key:** A free [Groq Cloud API Key](https://console.groq.com/keys) is recommended for high-speed LLM inference.

---

## 2. Project Architecture Overview

```
Financial-Rag/
├── backend/
│   ├── server.py              # FastAPI server (REST endpoints, static mounts, auth)
│   ├── mcp_server.py          # FastMCP server for IDEs / Claude / Cursor
│   ├── auth.py                # RBAC authentication & user manager
│   ├── config/settings.py     # Central runtime configuration & model routing
│   ├── rag/                   # Hybrid retrieval engine, OpenKB wiki retriever
│   ├── decomposer/            # Temporal resolver & query decomposition
│   ├── fusion/                # Concall-to-SQL reconciliation & contradiction detector
│   ├── schema_bridge/         # Quantitative HTTP client to serverless SQL Lambda
│   └── data/openkb_wiki/      # Hierarchical structured knowledge store (BSE filings, entities)
├── frontend-app/              # Modern React 19 + Vite + Tailwind CSS UI
│   ├── src/                   # Components (ChatView, AdminDashboard, Watchlist, Auth)
│   └── vite.config.js         # Vite configuration with API reverse proxies
├── deployment/                # OCI / Caddy deployment scripts & guides
├── Requirements.txt           # Python backend dependencies
└── run_tests.py               # Automated query test suite
```

---

## Step 1: Clone or Navigate to Project

Open your terminal or PowerShell and navigate to the project directory:

```bash
# If cloning fresh:
git clone https://github.com/Import-Saurabh/Financial-Rag.git
cd Financial-Rag

# Or if already downloaded:
cd path/to/Financial-Rag
```

---

## Step 2: Python Environment Setup

It is strongly recommended to isolate dependencies inside a virtual environment (`.venv`).

### On Windows (PowerShell / Command Prompt):
```powershell
# 1. Create virtual environment
python -m venv .venv

# 2. If PowerShell script execution is restricted, run:
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass

# 3. Activate the virtual environment
.\.venv\Scripts\Activate.ps1

# (For Command Prompt / cmd.exe use: .\.venv\Scripts\activate.bat)
```

### On macOS / Linux:
```bash
# 1. Create virtual environment
python3 -m venv .venv

# 2. Activate virtual environment
source .venv/bin/activate
```

> [!TIP]
> Once activated, your terminal prompt will be prefixed with `(.venv)`.

---

## Step 3: Install Backend Dependencies

With your virtual environment activated, upgrade `pip` and install all required packages:

```bash
# Upgrade pip, setuptools, and wheel
python -m pip install --upgrade pip setuptools wheel

# Install all backend requirements
pip install -r Requirements.txt
```

*This installs FastAPI, Uvicorn, LangGraph, LangChain, SentenceTransformers, PyTorch, OpenKB, YFinance, Plotly, MinIO client, and utilities.*

---

## Step 4: Install Frontend Dependencies

Open a new terminal tab/window or navigate into the `frontend-app` directory:

```bash
cd frontend-app
npm install
cd ..
```

*This installs React 19, Lucide React, Tailwind CSS v4, and the Vite build toolchain.*

---

## Step 5: Configure Environment Variables (.env)

The application requires an environment file `.env` at the project root. A template `.env.example` is provided.

### 1. Copy the example file:

**Windows (PowerShell):**
```powershell
Copy-Item .env.example .env
```

**Linux / macOS:**
```bash
cp .env.example .env
```

### 2. Configure Required Keys in `.env`:

Open `.env` in your text editor (VS Code, Notepad, Nano) and update the values:

```ini
# =====================================================================
# LLM Providers (Groq is the primary high-speed engine)
# =====================================================================
GROQ_API_KEY=gsk_your_actual_groq_api_key_here
DEEPSEEK_API_KEY=your_deepseek_api_key_here          # Optional: used for complex fallbacks
OPENROUTER_API_KEY=your_openrouter_api_key_here      # Optional
GEMINI_API_KEY=your_gemini_api_key_here              # Optional

# =====================================================================
# Server & Quantitative API Configuration
# =====================================================================
FINRAG_PORT=5000
FINRAG_API_BASE=https://zhwbvtkibdyhjy42gubo3qbsxq0pifuv.lambda-url.ap-south-1.on.aws

# =====================================================================
# Security & JWT Authentication
# =====================================================================
JWT_SECRET=financial_rag_custom_secret_key_change_in_production_2026

# =====================================================================
# Optional: WhatsApp Cloud API Integration
# =====================================================================
WHATSAPP_VERIFY_TOKEN=finrag_verify_token_2026
WHATSAPP_ACCESS_TOKEN=
WHATSAPP_PHONE_NUMBER_ID=
AUTHORIZED_WHATSAPP_NUMBER=
```

> [!IMPORTANT]
> - `GROQ_API_KEY` is required for live chat completions and agent synthesis.
> - `FINRAG_API_BASE` points to the pre-configured serverless AWS Lambda quantitative SQL endpoint that delivers audited financials without needing a local MySQL server.

---

## Step 6: Running the Application

Choose the mode that best fits your workflow:

### Option A: Full Development Mode (Recommended)
*Best for actively modifying frontend or backend code with instant hot-reloading.*

Run the backend and frontend in two separate terminal windows:

#### Terminal 1 — Start Backend Server:
```powershell
# Windows (PowerShell)
.\.venv\Scripts\Activate.ps1
python backend/server.py
```
```bash
# macOS / Linux
source .venv/bin/activate
python backend/server.py
```
- **Backend API URL:** `http://localhost:5000`
- **Swagger Documentation:** `http://localhost:5000/docs`

#### Terminal 2 — Start Frontend Dev Server:
```bash
cd frontend-app
npm run dev
```
- **Frontend UI URL:** `http://localhost:5173`
- *Vite automatically proxies API requests (`/query`, `/v1`, `/auth`, `/admin`) from port `5173` to port `5000`.*

---

### Option B: Single-Port Production Mode
*Builds the React application into static assets and serves both UI and API from FastAPI on port 5000.*

#### Step 1: Build the React Frontend
```bash
cd frontend-app
npm run build
cd ..
```
*(This compiles production assets into `frontend-app/dist/`)*

#### Step 2: Start FastAPI Unified Server
```powershell
# Windows
.\.venv\Scripts\Activate.ps1
python backend/server.py
```
```bash
# macOS / Linux
source .venv/bin/activate
python backend/server.py
```

- **Unified Web Application:** Open `http://localhost:5000` in your web browser.

---

### Option C: Model Context Protocol (MCP) Server
*Exposes 18+ financial analysis tools to MCP-compatible AI environments (Claude Desktop, Cursor IDE, Antigravity).*

#### Running over Standard I/O (Default):
```bash
python backend/mcp_server.py
```

#### Running over SSE (Server-Sent Events) on Port 8100:
```bash
python backend/mcp_server.py --sse
```

#### Adding to Claude Desktop or Cursor Configuration:
Add the following to your `claude_desktop_config.json` or Cursor MCP settings:
```json
{
  "mcpServers": {
    "financial-rag": {
      "command": "python",
      "args": [
        "c:/Users/hp/Downloads/Financial-Rag/backend/mcp_server.py"
      ]
    }
  }
}
```

---

## Step 7: Accessing the Application & Default Credentials

Open `http://localhost:5173` (Dev Mode) or `http://localhost:5000` (Built Mode) in your browser.

The platform includes built-in Role-Based Access Control (RBAC). Default demo accounts are pre-configured:

| Role | Username | Password | Access Capabilities |
| :--- | :--- | :--- | :--- |
| **Administrator** | `admin` | `admin123` | Full Access: Query Chat, Admin Ingestion Dashboard, System Metrics, User Management, Watchlist |
| **Research Analyst** | `user` | `user123` | Research Access: Dual-stream RAG query chat, source inspection, chart visualizations |

*(You can also click **Register** on the UI to create new accounts).*

---

## Step 8: Verification & Testing

Verify that your installation is working correctly with the following test commands:

### 1. Test Backend Health Endpoint:
**PowerShell:**
```powershell
Invoke-RestMethod -Uri http://localhost:5000/health
```
**Linux / macOS:**
```bash
curl -s http://localhost:5000/health | jq
```
*Expected response: `{"status": "ok", "healthy_providers": ..., "system_mode": ...}`*

### 2. Test Live Stock Price Retrieval (Yahoo Finance):
```bash
python test.py
```
*Queries real-time data for `RELIANCE` or `APOLLO` via the live market engine.*

### 3. Test Retrieval Engine & Latency (Single Query):
```bash
python test_single.py
```
*Executes cold-start (Turn 1) and steady-state in-memory warm (Turn 2) RAG queries, displaying response and latency metrics.*

### 4. Run the Full Test Suite:
```bash
python -m unittest discover tests
```
*Runs all unit and integration tests across chart engines, authentication, watchlist, and WhatsApp handlers.*

---

## Troubleshooting & FAQs

### Q1: `Set-ExecutionPolicy` error when activating virtual environment on Windows
**Error:** `File ...\Activate.ps1 cannot be loaded because running scripts is disabled on this system.`  
**Solution:** Run PowerShell as Administrator (or in current session) and execute:
```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
```
Then run `.\.venv\Scripts\Activate.ps1` again.

### Q2: Port 5000 or 5173 is already in use
**Solution:**
- To change the backend port, set `FINRAG_PORT=5001` in `.env`.
- Note: If changing backend port, update `frontend-app/vite.config.js` proxy targets to match the new port.
- On Windows, to kill a dangling process holding port 5000:
  ```powershell
  Get-Process -Id (Get-NetTCPConnection -LocalPort 5000).OwningProcess | Stop-Process -Force
  ```

### Q3: First-time model download is slow or hangs
**Explanation:** On the first query, `SentenceTransformers` downloads `sentence-transformers/all-MiniLM-L6-v2` (~90 MB) and `cross-encoder/ms-marco-MiniLM-L-6-v2` (~80 MB) to your local cache (`~/.cache/huggingface/hub/`).  
**Solution:** Subsequent queries use the warm in-memory model and respond in ~6.5 seconds. Ensure you have an active internet connection on the initial query.

### Q4: Frontend shows "Failed to fetch" or 404 on API requests
**Solution:**
1. Verify the backend is running (`http://localhost:5000/health`).
2. If using Development Mode (`npm run dev`), make sure you are accessing `http://localhost:5173` so Vite proxies requests to port 5000.
3. If accessing `http://localhost:5000` directly, ensure you ran `npm run build` inside `frontend-app/` first.

### Q5: Groq API Rate Limit or 429 Error
**Explanation:** If the primary Groq rate limit is exceeded, the orchestrator automatically cascades to deterministic synthesis or configured fallback providers (`DEEPSEEK_API_KEY` / `OPENROUTER_API_KEY`). Ensure valid fallback keys are provided in `.env` for production setups.

---

## 📞 Support & Documentation Links
- **High-Level Design (HLD):** [docs/HLD.md](file:///c:/Users/hp/Downloads/Financial-Rag/docs/HLD.md)
- **Low-Level Design (LLD):** [docs/LLD.md](file:///c:/Users/hp/Downloads/Financial-Rag/docs/LLD.md)
- **Knowledge Graph Deep Dive:** [docs/SYSTEM_AND_KNOWLEDGE_GRAPH_DEEP_DIVE.md](file:///c:/Users/hp/Downloads/Financial-Rag/docs/SYSTEM_AND_KNOWLEDGE_GRAPH_DEEP_DIVE.md)
- **Cloud Production Deployment (OCI):** [deployment/DEPLOYMENT_GUIDE.md](file:///c:/Users/hp/Downloads/Financial-Rag/deployment/DEPLOYMENT_GUIDE.md)
