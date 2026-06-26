"""Streamlit entrypoint for the Korean Law RAG chatbot.

This file intentionally stays small. Application behavior lives in the
role-specific modules under ``app/`` so the UI, LLM orchestration, MCP client,
permission policy, and prompt rendering can evolve independently.
"""

from app.ui import run_app


if __name__ == "__main__":
    run_app()
