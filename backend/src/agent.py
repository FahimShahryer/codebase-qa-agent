"""LangGraph agent — wires the 7 tools, the answering LLM, and the
SqliteSaver-backed thread state.

verified: /websites/langchain_oss_python_langchain (May 2026)
- `from langchain.agents import create_agent` is canonical in V1.x
- model accepts string format "provider:model" (e.g. "openai:gpt-4o-mini",
  "ollama:qwen2.5-coder:7b") OR a constructed chat-model object
- `system_prompt=` (renamed from `prompt=` in create_react_agent)
- `from langchain.chat_models import init_chat_model` for provider-agnostic
  initialisation; forwards extra kwargs to underlying provider class
- `from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver` for thread
  persistence (unchanged from earlier)
"""
from __future__ import annotations

import os
from contextlib import asynccontextmanager
from typing import AsyncIterator

from langchain.agents import create_agent
from langchain.chat_models import init_chat_model
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from src.config import settings
from src.tools import ALL_TOOLS

MEMORY_DB_PATH = "/app/memory/memory.db"


# ── Chat LLM (V1 unified initialiser) ────────────────────────────────
def make_chat_llm():
    """Build the answering LLM via the V1 unified initialiser.

    The model string format is "provider:model_name". Extra kwargs
    (api_key, base_url, temperature) are forwarded to the underlying
    provider class (ChatOpenAI / ChatOllama / etc).
    """
    provider = settings.LLM_PROVIDER.lower()
    model_str = f"{provider}:{settings.LLM_MODEL}"

    # Provider-specific kwargs. OpenAI reads OPENAI_API_KEY from env
    # (docker-compose env_file sets it). Ollama needs base_url since
    # the default is localhost but we run it as the `ollama` service.
    kwargs: dict = {"temperature": 0}
    if provider == "ollama":
        kwargs["base_url"] = settings.OLLAMA_BASE_URL
    elif provider == "openai" and settings.OPENAI_API_KEY:
        kwargs["api_key"] = settings.OPENAI_API_KEY

    return init_chat_model(model_str, **kwargs)


# ── System prompt ────────────────────────────────────────────────────
SYSTEM_PROMPT_TEMPLATE = """You are a code Q&A assistant for the {repo} codebase.

You have these tools available:
- search_code(query, max_results=5): DEFAULT — hybrid semantic+keyword search.
- read_file(path, start, end): read raw file content (use after search).
- list_directory(path): explore repo structure.
- summarize_module(symbol_path): O(1) lookup of a precomputed file/class summary.
- find_callers(symbol_name): reverse call graph — "what calls X?".
- find_importers(module_name): reverse import graph — "who depends on X?".
- find_definition(symbol_name): exact identifier lookup.

TOOL SELECTION GUIDE — prefer the most specific tool:
- "what calls/uses X" → find_callers (NOT search_code)
- "who imports/depends on X" → find_importers
- "where is X defined" → find_definition
- "what does X do" at file/class level → summarize_module
- "show me file Y" → read_file
- "list / what's inside Z" → list_directory
- Everything else → search_code

CITATION RULES — strict:
- After each tool call, cite the source you used with [path:start-end] where
  path/start/end come VERBATIM from the tool output's header line.
- Multiple sources: [src/flask/app.py:967-990][src/flask/views.py:78-83]
- Never invent file paths or line numbers — copy them from tool output.

REFUSAL RULES — strict:
- If retrieved chunks don't answer the question, say so directly:
  "The retrieved code doesn't cover {{topic}}. You might check ..."
- Never speculate beyond what the chunks show.
- Never invent function names, class names, or behaviour.

STYLE:
- Lead with a ONE-sentence direct answer.
- Then briefly explain with code references and short excerpts.
- End by noting what's NOT covered, if relevant.
"""


def system_prompt() -> str:
    return SYSTEM_PROMPT_TEMPLATE.format(repo=settings.REPO_NAME)


# ── Agent builder (async context — owns the checkpointer's lifetime) ─
@asynccontextmanager
async def build_agent() -> AsyncIterator:
    """Build the agent with an AsyncSqliteSaver thread-persistence layer.

    Use as:
        async with build_agent() as agent:
            async for ev in agent.astream(input, config, stream_mode=...):
                ...
    """
    os.makedirs(os.path.dirname(MEMORY_DB_PATH), exist_ok=True)
    async with AsyncSqliteSaver.from_conn_string(MEMORY_DB_PATH) as saver:
        agent = create_agent(
            model=make_chat_llm(),
            tools=ALL_TOOLS,
            system_prompt=system_prompt(),
            checkpointer=saver,
        )
        yield agent
