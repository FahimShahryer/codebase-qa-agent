# Codebase Q&A Agent

A production-grade agentic Q&A system over a real-world public GitHub codebase. Built as a take-home submission for Ajentica.

The agent answers natural-language questions about a target Python codebase — architecture decisions, function behaviour, file relationships, usage examples — using AST-aware chunking, hybrid (vector + BM25) retrieval, cross-encoder reranking, and a 7-tool LangGraph agent. Every answer carries deterministic citations (`file:line-range`); out-of-scope questions are refused, not hallucinated.

---

## Chosen Repository

**[pallets/flask](https://github.com/pallets/flask)** — Python web framework. ~200 files, **998 indexable chunks** (80 file + 63 class + 523 function + 332 method) after AST-aware chunking.

---

## Architecture (one-paragraph summary)

Tree-sitter parses Python into AST nodes, producing hierarchical chunks at three granularities (file / class / function). Each chunk gets a 1-2 sentence LLM-generated summary at indexing time; that summary + the docstring + the code body is what we embed (OpenAI `text-embedding-3-small`, with a local `bge-small-en` fallback). Chunks land in a multi-tenant Weaviate collection with property-weighted BM25 + HNSW vector indexes. At query time, a 7-stage pipeline (alpha auto-detect → optional HyDE → hybrid retrieval over-fetching 20 → bge-reranker-base → 1-hop context expansion → dedupe → numbered packing) feeds a LangGraph agent that picks between 7 tools (`search_code`, `read_file`, `list_directory`, `summarize_module`, `find_callers`, `find_importers`, `find_definition`). Streaming responses arrive in the Next.js UI via SSE with a thinking-trace timeline and a click-to-open citation panel.

---

## Setup & Installation

**Prereqs:** Docker Desktop (or equivalent) + Docker Compose v2. Nothing else — no host-installed Python or Node required.

```bash
# 1. Clone
git clone https://github.com/FahimShahryer/codebase-qa-agent.git
cd codebase-qa-agent

# 2. Copy env template and fill in keys
cp .env.example .env
# Edit .env: paste your OPENAI_API_KEY (or switch providers — see below).

# 3. Spin up the stack
docker compose up -d
```

**Two paths to a ready-to-query index:**

```bash
# Fast path (~30 s)  — restore the pre-built Flask index from indexes/flask-v1.tar.gz
./backend/scripts/restore_index.sh flask-v1
docker compose restart backend

# Full path (~7 min) — clone Flask and index it from scratch
mkdir -p repos && git clone --depth 1 https://github.com/pallets/flask repos/flask
docker compose exec backend python -m src.cli index --repo flask --drop
```

Open [http://localhost:3000](http://localhost:3000) for the chat UI.
The backend API is at [http://localhost:8000](http://localhost:8000).

### Local-only mode (no cloud API keys)

```bash
docker compose --profile local-llm up -d
docker exec -it ajentica-ollama ollama pull qwen2.5-coder:7b
# In .env, set LLM_PROVIDER=ollama and EMBED_PROVIDER=sbert
docker compose restart backend
```

Runs Ollama in-cluster with `qwen2.5-coder:7b` for answering, `bge-small-en-v1.5` for embeddings. Fully offline-capable.

---

## Usage

The UI opens at `http://localhost:3000`. The sidebar lists past chats (persisted), the header has a repo dropdown, and the main pane shows the conversation. Type a question, press Enter — tool calls stream in above the answer (the "thinking trace"), then the answer streams token-by-token with inline `[path:start-end]` citations that you can click to open the file at the right line range in a side panel.

### Example queries

| Query | What the agent does |
|---|---|
| _How does Flask handle URL routing?_ | calls `search_code` → finds `Scaffold.add_url_rule` + tests + class chunks → cites with line ranges |
| _What calls `make_response`?_ | calls `find_callers` (reverse-call-graph filter) → returns 7 callers |
| _Where is `dispatch_request` defined?_ | calls `search_code` (BM25-heavy alpha) → top-2 are `Flask.dispatch_request` + `View.dispatch_request` |
| _Of those callers, which one is canonical?_ | follow-up — uses thread history from the prior turn, names `finalize_request` |
| _How does Django configure CSRF middleware?_ | **refuses** politely (off-topic) — refusal gate fires at rerank score 0.005 |

### CLI alternative

For headless use:
```bash
docker compose exec backend python -m src.cli chat --session-id demo --query "How does URL routing work?"
```

---

## Tech Stack

| Layer | Choice |
|---|---|
| Chunking | `tree-sitter` + `tree-sitter-python`, hierarchical (file/class/function/method) |
| Embeddings | OpenAI `text-embedding-3-small` (1536-dim) / local `bge-small-en-v1.5` (toggle) |
| Vector store | Weaviate v4 (multi-tenant, hybrid BM25 + HNSW cosine, BYO vectors) |
| Reranker | `BAAI/bge-reranker-base` (local cross-encoder, sigmoid-normalized scores) |
| Agent | LangChain V1 `create_agent` + LangGraph `AsyncSqliteSaver` (7 tools) |
| Backend | FastAPI + SSE streaming (10 REST endpoints) |
| Frontend | Next.js 15 (App Router) + React 19 + react-markdown |
| LLM | `gpt-4o-mini` (default) / Ollama (local profile) |

---

## Evaluation

Ran a 30-query gold set + 10-query refusal set against the indexed Flask repo. Reproduce with:
```bash
docker compose exec backend python -m evals.run_retrieval_eval
```

### Retrieval — 30 queries, 5 categories

| Category | N | Recall@k | MRR |
|---|---|---|---|
| **Overall** | **30** | **0.933** | **0.639** |
| conceptual           | 6 | 1.000 | 0.708 |
| cross_reference      | 6 | 1.000 | 0.722 |
| identifier_lookup    | 6 | 0.833 | 0.394 |
| symbol_summary       | 6 | 0.833 | 0.597 |
| usage_example        | 6 | 1.000 | 0.774 |

### Refusal — 10 off-topic queries

| Metric | Result |
|---|---|
| Correct-refusal rate | **100%** (10/10) |
| Top rerank score on out-of-scope | 0.000 – 0.005 (well below the 0.3 gate) |

### Latency

| Metric | Value |
|---|---|
| Retrieval pipeline p50 | 5.95 s |
| Retrieval pipeline p95 | 7.61 s |

(Latency includes embedding + Weaviate hybrid + bge-reranker forward pass + 1-hop expansion. LLM answer streaming adds another ~3-8 s typical.)

---

## Backend API

10 endpoints. Only `POST /chat` is SSE; everything else is plain JSON.

| Method | Path | Purpose |
|---|---|---|
| `GET`    | `/health` | liveness |
| `GET`    | `/repos` | list indexed repos |
| `POST`   | `/repos/{repo}/index` | trigger async indexing |
| `GET`    | `/repos/{repo}/status` | indexing state + chunk_count |
| `POST`   | `/chat` | streaming SSE chat (`tool_start` / `tool_end` / `token` / `citations` / `done` / `error`) |
| `GET`    | `/sessions` | sidebar list |
| `GET`    | `/sessions/{id}/messages` | conversation history |
| `DELETE` | `/sessions/{id}` | clear session (drops metadata + checkpoints) |
| `GET`    | `/files` | read file slice (skip-list enforced) |
| `GET`    | `/search` | direct retrieval pipeline (dev-only) |

---

## Project Structure

```
backend/                       # all Python
  src/
    config.py, detect.py, extract.py, summarize.py, embed.py,
    store.py, retrieve.py, tools.py, agent.py, server.py, cli.py, cache.py, index.py, chunks.py
    adapters/{base.py, python.py}
    routes/{health, chat, sessions, repos, files, search}.py
  evals/{gold_set.yaml, refusal_set.yaml, run_retrieval_eval.py}
  scripts/{snapshot_index.sh, restore_index.sh}
  Dockerfile, pyproject.toml

frontend/                      # all TypeScript / Next.js
  app/{layout, page}.tsx
  app/components/{Chat, Message, ThinkingTrace, CitationBadge, CitationPanel, RepoSelector, SessionSidebar}.tsx
  lib/{api.ts, types.ts}
  Dockerfile, package.json

docker-compose.yml, .env.example
indexes/flask-v1.tar.gz        # pre-built Weaviate snapshot (committed)
repos/                         # source repos (gitignored)
```

---

## AI Tool Usage Disclosure

This project was built with AI assistance throughout:

- **Claude (Opus 4.7)** — used for design exploration, architecture review, market research, code generation, and verification of library APIs via the Context7 MCP server. All AI-generated code was reviewed and tested before commit.
- **Context7 MCP** — used as a strict pre-coding step to fetch current library documentation (LangGraph, LangChain V1, Weaviate v4, Vercel AI SDK, Next.js 15, langchain providers, tree-sitter, etc.) so generated code matches the deployed version of each library, not training-cutoff snapshots.

Every design decision, code choice, and architectural tradeoff in this repository was understood and approved by the author. AI was a collaborator and verifier, not a black-box generator.

---

## License

This is a private take-home submission. Not licensed for redistribution.
