"""Pydantic-settings based runtime configuration.

The application reads ``.env`` through ``pydantic-settings`` instead of manual
environment lookup helpers. This keeps configuration typed, validated, and
centralized.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import AliasChoices, Field, computed_field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PROMPT_DIR = PROJECT_ROOT / "prompts"


class AppConfig(BaseSettings):
    """Validated settings for the Streamlit/OpenRouter/MCP demo.

    Intent:
        Centralize model names, local MCP paths, API keys, and loop limits. The
        class uses Pydantic Settings so local ``.env`` values and process
        environment values are parsed in one consistent place.
    """

    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    title: str = Field(default="Korean Law RAG Chatbot", validation_alias="APP_TITLE")
    openrouter_base_url: str = Field(
        default="https://openrouter.ai/api/v1",
        validation_alias="OPENROUTER_BASE_URL",
    )
    default_model: str = Field(default="google/gemini-3.5-flash", validation_alias="OPENROUTER_MODEL")
    korean_law_mcp_dir: Path = Field(
        default=Path("../korean-law-mcp"),
        validation_alias="KOREAN_LAW_MCP_DIR",
    )
    korean_law_mcp_entry: Path | None = Field(default=None, validation_alias="KOREAN_LAW_MCP_ENTRY")
    max_tool_rounds: int = Field(default=10, validation_alias="MAX_TOOL_ROUNDS", ge=1, le=12)
    max_history_messages: int = Field(default=40, validation_alias="MAX_HISTORY_MESSAGES", ge=1, le=200)
    max_mcp_reference_chars: int = Field(default=50000, validation_alias="MAX_MCP_REFERENCE_CHARS", ge=0)
    recent_tool_context_turns: int = Field(default=2, validation_alias="RECENT_TOOL_CONTEXT_TURNS", ge=0, le=20)
    max_tool_evidence_chars: int = Field(default=6000, validation_alias="MAX_TOOL_EVIDENCE_CHARS", ge=500, le=50000)
    max_compacted_evidence_chars: int = Field(default=12000, validation_alias="MAX_COMPACTED_EVIDENCE_CHARS", ge=1000, le=100000)
    log_level: str = Field(default="INFO", validation_alias="LOG_LEVEL")
    log_file: Path = Field(default=Path("logs/chatbot-debug.log"), validation_alias="LOG_FILE")
    openrouter_api_key: str = Field(default="", validation_alias="OPENROUTER_API_KEY")
    openai_api_key: str = Field(default="", validation_alias="OPENAI_API_KEY")
    mcp_api_key: str = Field(
        default="",
        validation_alias=AliasChoices("MCP_API_KEY", "LAW_OC", "KOREAN_LAW_API_KEY"),
    )

    @field_validator("korean_law_mcp_dir", "korean_law_mcp_entry", "log_file", mode="after")
    @classmethod
    def _resolve_repo_relative_path(cls, value: Path | None) -> Path | None:
        """Resolve configurable relative paths from the repository root.

        Background:
            Project files should avoid machine-specific local paths. Operators
            can still provide absolute paths when necessary, but documented and
            default values stay repository-relative.
        """

        if value is None or value.is_absolute():
            return value
        return PROJECT_ROOT / value

    @computed_field
    @property
    def mcp_repo_dir(self) -> Path:
        """Return the local Korean Law MCP repository directory.

        Background:
            The demo prefers a repository-relative local MCP build for stable
            development, but can still fall back to ``npx korean-law-mcp``.
        """

        return self.korean_law_mcp_dir

    @computed_field
    @property
    def mcp_entry(self) -> Path:
        """Return the local MCP server entrypoint path."""

        return self.korean_law_mcp_entry or (self.korean_law_mcp_dir / "build/index.js")

    @computed_field
    @property
    def prompt_dir(self) -> Path:
        """Return the Jinja2 prompt template directory."""

        return PROMPT_DIR

    @property
    def effective_openrouter_api_key(self) -> str:
        """Return OpenRouter key with OpenAI-key fallback for local demos."""

        return self.openrouter_api_key or self.openai_api_key

    @property
    def effective_law_api_key(self) -> str:
        """Return the 법제처 API key passed to Korean Law MCP.

        Background:
            The demo reads `MCP_API_KEY` as the primary local setting because
            that is how the user stores the credential in this repository's
            `.env`. The upstream Korean Law MCP process currently reads
            `LAW_OC` or `KOREAN_LAW_API_KEY`, so `app.mcp_client` maps this
            effective value into the child-process environment.
        """

        return self.mcp_api_key

    def load_mcp_reference(self) -> str:
        """Load optional local Korean Law MCP analysis notes for prompt context.

        Intent:
            The user requested that the LLM receive as much relevant context as
            possible. ``MCP.md`` is included when present, bounded by a setting
            to avoid unbounded prompt growth.
        """

        path = PROJECT_ROOT / "MCP.md"
        if not path.exists() or self.max_mcp_reference_chars == 0:
            return ""
        return path.read_text(encoding="utf-8")[: self.max_mcp_reference_chars]
