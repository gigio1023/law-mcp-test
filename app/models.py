"""Pydantic v2 models shared by the chatbot application.

The project uses Pydantic models instead of dataclasses so runtime objects are
validated, serializable, and explicit. These models are intentionally
framework-neutral: Streamlit, OpenAI, and MCP modules import them without
depending on each other.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class UserType(StrEnum):
    """Persona selected in the UI.

    Background:
        The demo distinguishes a general user from a tax accountant. The
        accountant persona is allowed and encouraged to use specialist tax
        sources because detailed materials can be genuinely useful for a
        professional.
    """

    GENERAL = "general"
    TAX_ACCOUNTANT = "tax_accountant"


class ChatRole(StrEnum):
    """Persisted UI chat roles.

    Background:
        Streamlit history stores only user-visible messages. System prompts and
        OpenAI ``role='tool'`` messages are generated inside the agent for the
        current request and are not persisted in the UI history model.
    """

    USER = "user"
    ASSISTANT = "assistant"


class ToolResultState(StrEnum):
    """Normalized state for persisted MCP evidence."""

    OK = "ok"
    ERROR = "error"
    BLOCKED = "blocked"


class TraceEvent(BaseModel):
    """Structured status item rendered by Streamlit.

    Intent:
        Tool calling should be auditable in the UI. Keeping a title plus an
        optional JSON payload lets the live status container and saved history
        render MCP arguments/results as structured blocks instead of opaque
        prose.
    """

    model_config = ConfigDict(extra="forbid")

    title: str
    detail: str = ""
    payload: dict[str, Any] | list[Any] | None = None


class ToolEvidenceEntry(BaseModel):
    """Bounded MCP evidence persisted across chat turns.

    Background:
        OpenAI `role="tool"` messages are only valid beside the assistant
        tool-call message that created them. For later turns, the app preserves
        the model-visible evidence as structured text context instead of
        replaying stale tool-call IDs.
    """

    model_config = ConfigDict(extra="forbid")

    state: ToolResultState
    tool_name: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    result: str

    def as_context_dict(self) -> dict[str, Any]:
        """Return a stable JSON-friendly shape for prompt context."""

        return {
            "state": self.state.value,
            "tool_name": self.tool_name,
            "arguments": self.arguments,
            "result": self.result,
        }


class ChatMessage(BaseModel):
    """Serializable chat history message stored in Streamlit session state.

    Intent:
        Multi-turn behavior depends on preserving previous user and assistant
        messages across Streamlit reruns. Tool traces and source labels are kept
        on assistant messages so users can reopen past status details.
    """

    model_config = ConfigDict(extra="forbid")

    role: ChatRole
    content: str
    trace: list[TraceEvent] = Field(default_factory=list)
    sources: list[str] = Field(default_factory=list)
    evidence: list[ToolEvidenceEntry] = Field(default_factory=list)

    @field_validator("trace", mode="before")
    @classmethod
    def _coerce_legacy_trace(cls, value: object) -> object:
        """Accept pre-structured session-state traces created before this change."""

        if isinstance(value, list):
            return [{"title": item} if isinstance(item, str) else item for item in value]
        return value


class McpToolRequest(BaseModel):
    """Concrete MCP request selected by OpenAI tool calling.

    Background:
        The LLM receives actual MCP tools from ``list_tools()`` converted into
        OpenAI function tools. When it calls one, Python validates the selected
        MCP tool and arguments against persona policy before execution.
    """

    model_config = ConfigDict(extra="forbid")

    tool_name: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    openai_tool_call_id: str


class McpToolResult(BaseModel):
    """Result of executing or rejecting one MCP request."""

    model_config = ConfigDict(extra="forbid")

    request: McpToolRequest
    text: str
    is_error: bool = False
    is_blocked: bool = False


class ToolCatalogEntry(BaseModel):
    """MCP tool metadata shown to the LLM and converted to OpenAI tools."""

    model_config = ConfigDict(extra="forbid")

    name: str
    description: str
    input_schema: dict[str, Any] = Field(default_factory=dict)


class PermissionDecision(BaseModel):
    """Persona policy decision for a model-requested MCP call."""

    model_config = ConfigDict(extra="forbid")

    allowed: bool
    reason: str


class AgentTurnResult(BaseModel):
    """OpenAI message state after the tool-calling phase.

    Function:
        ``messages`` includes the original conversation, assistant tool-call
        messages, and MCP tool result messages. The final streamed answer uses
        this prepared state as its grounding context.
    """

    model_config = ConfigDict(extra="forbid")

    messages: list[dict[str, Any]]
    trace: list[TraceEvent] = Field(default_factory=list)
    sources: list[str] = Field(default_factory=list)
    evidence: list[ToolEvidenceEntry] = Field(default_factory=list)
