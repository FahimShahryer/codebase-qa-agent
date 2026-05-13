# Codebase Q&A Agent

A production-grade agentic Q&A system over a real-world public GitHub codebase. Built as a take-home submission for Ajentica.

The agent answers natural-language questions about a target Python codebase — architecture decisions, function behaviour, file relationships, usage examples — using AST-aware chunking, hybrid (vector + BM25) retrieval, cross-encoder reranking, and a 7-tool LangGraph agent. Every answer carries deterministic citations (`file:line-range`); out-of-scope questions are refused, not hallucinated.

---

## Chosen Repository

**[pallets/flask](https://github.com/pallets/flask)** — Python web framework. ~200 files, ~1500 indexable chunks. _(Subject to confirmation before Step 1.)_

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
# edit .env — add OPENAI_API_KEY (or switch to local Ollama path; see below)

# 3a. Fast path — restore pre-built Flask index (~30 sec)
./scripts/restore_index.sh flask
docker-compose up

# 3b. Full path — build the index from scratch (~5-15 min)
git clone https://github.com/pallets/flask repos/flask
docker-compose up -d weaviate backend
docker-compose exec backend python scripts/index_repo.py --repo flask
docker-compose up
```

Open [http://localhost:3000](http://localhost:3000) for the chat UI.
The backend API is at [http://localhost:8000](http://localhost:8000).

### Local-only mode (no cloud API keys)

```bash
docker-compose --profile local-llm up
```

Runs Ollama in-cluster with `qwen2.5-coder:7b` for answering and `bge-small-en-v1.5` for embeddings. Fully offline-capable.

---

## Usage

> Demo screenshots and example queries will be added at Step 10. Placeholders below.

### Example queries (target repo: Flask)

| Query | What the agent does | Tool(s) used |
|---|---|---|
| _TBD_ | _TBD_ | _TBD_ |

### Sample output

```
TBD — to be added in Step 10
```

---

## Tech Stack

| Layer | Choice |
|---|---|
| Chunking | `tree-sitter` + `tree-sitter-python`, hierarchical (file/class/function) |
| Embeddings | OpenAI `text-embedding-3-small` (1536-dim) / local `bge-small-en-v1.5` (toggle) |
| Vector store | Weaviate v4 (multi-tenant, hybrid search, HNSW cosine) |
| Reranker | `BAAI/bge-reranker-base` (local cross-encoder) |
| Agent | LangGraph `create_agent` + `AsyncSqliteSaver` (7 tools) |
| Backend | FastAPI + SSE streaming (10 REST endpoints) |
| Frontend | Next.js 15 (App Router) + Vercel AI SDK v5 `useChat` |
| LLM | gpt-4o-mini (default) / Ollama (local profile) |

---

## Evaluation

> Numbers will be filled in at Step 10 from the eval harness output.

| Metric | Score |
|---|---|
| Retrieval Recall@5 | _TBD_ |
| Retrieval MRR | _TBD_ |
| Answer faithfulness (LLM-as-judge, 1-5) | _TBD_ |
| Answer completeness | _TBD_ |
| Citation accuracy | _TBD_ |
| Refusal rate on out-of-scope queries | _TBD_ |
| p50 / p95 latency (full answer) | _TBD_ |

---

## AI Tool Usage Disclosure

This project was built with AI assistance throughout:

- **Claude (Opus 4.7)** — used for design exploration, architecture review, market research, code generation, and verification of library APIs via the Context7 MCP server. All AI-generated code was reviewed and tested before commit.
- **Context7 MCP** — used as a strict pre-coding step to fetch current library documentation (LangGraph, Weaviate, Vercel AI SDK, LangChain providers, etc.) so generated code matches the deployed version of each library, not training-cutoff snapshots.

Every design decision, code choice, and architectural tradeoff in this repository was understood and approved by the author. AI was a collaborator and verifier, not a black-box generator.

---

## License

This is a private take-home submission. Not licensed for redistribution.
