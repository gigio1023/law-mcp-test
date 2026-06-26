"""Loguru setup for local chatbot diagnostics.

The demo needs enough runtime detail to debug cases where MCP tool calls finish
but the final answer does not appear. This module keeps logging configuration in
one place so Streamlit reruns do not attach duplicate file sinks.
"""

from __future__ import annotations

from pathlib import Path

from loguru import logger


_CONFIGURED_LOG_FILES: set[Path] = set()


def configure_file_logging(log_file: Path, level: str) -> Path:
    """Configure one idempotent Loguru file sink and return its path.

    Intent:
        Streamlit reruns the Python script often. Without an idempotent guard,
        each rerun would add another sink and duplicate every log line. The log
        captures request flow, tool choices, MCP outcomes, final streaming
        finish reasons, and fallback decisions, while callers avoid logging API
        key values.
    """

    resolved = log_file.expanduser().resolve()
    if resolved in _CONFIGURED_LOG_FILES:
        return resolved

    resolved.parent.mkdir(parents=True, exist_ok=True)
    logger.add(
        resolved,
        level=level.upper(),
        rotation="5 MB",
        retention="7 days",
        compression="zip",
        enqueue=True,
        backtrace=True,
        diagnose=False,
        encoding="utf-8",
    )
    _CONFIGURED_LOG_FILES.add(resolved)
    logger.info("Configured chatbot file logging at {}", resolved)
    return resolved
