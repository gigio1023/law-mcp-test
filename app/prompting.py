"""Prompt rendering utilities for the LLM agent.

The system prompt is stored as a Jinja2 template so prompt changes do not
require touching Python orchestration code.
"""

from __future__ import annotations

from typing import Any

from jinja2 import Environment, FileSystemLoader, StrictUndefined

from app.config import AppConfig
from app.models import UserType
from app.permissions import ToolPermissionPolicy


class PromptRenderer:
    """Render the system prompt from ``prompts/system.j2``.

    Background:
        The user requested prompt separation into a ``.j2`` file. Jinja2 keeps
        the prompt readable while still allowing structured runtime context like
        tool catalogs, policy summaries, and custom instructions.
    """

    def __init__(self, config: AppConfig, policy: ToolPermissionPolicy) -> None:
        """Create a Jinja2 environment rooted at the configured prompt folder."""

        self.config = config
        self.policy = policy
        self.environment = Environment(
            loader=FileSystemLoader(str(config.prompt_dir)),
            autoescape=False,
            trim_blocks=True,
            lstrip_blocks=True,
            undefined=StrictUndefined,
        )

    def render_system_prompt(
        self,
        user_type: UserType,
    ) -> str:
        """Render the stable system prompt for one chat turn.

        Function:
            The rendered prompt contains durable behavior, persona policy, and
            local MCP reference notes. Per-turn data such as the live MCP tool
            catalog, custom instruction, and evidence memory are appended as
            later messages so OpenRouter/Gemini can cache this stable prefix.
        """

        template = self.environment.get_template("system.j2")
        return template.render(
            user_type=user_type.value,
            permission_context=self.policy.prompt_context(user_type),
            hidden_tool_context=self.policy.hidden_tool_context(),
            mcp_reference=self.config.load_mcp_reference(),
            max_tool_rounds=self.config.max_tool_rounds,
        )

    def render_tool_catalog_context(self, catalog_json: str) -> str:
        """Render the per-turn MCP catalog context message."""

        return self._render_template("tool_catalog_context.j2", catalog_json=catalog_json)

    def render_custom_instruction_context(self, custom_instruction: str) -> str:
        """Render the per-turn user custom instruction context message."""

        return self._render_template("custom_instruction_context.j2", custom_instruction=custom_instruction)

    def render_prior_evidence_context(self, evidence_json: str) -> str:
        """Render bounded prior MCP evidence memory for multi-turn reasoning."""

        return self._render_template("prior_evidence_context.j2", evidence_json=evidence_json)

    def render_tool_reentry_checkpoint(self, user_type: UserType, catalog_json: str) -> str:
        """Render the one-time checkpoint that lets the model choose more tools."""

        return self._render_template(
            "tool_reentry_checkpoint.j2",
            user_type=user_type.value,
            catalog_json=catalog_json,
        )

    def render_final_answer_instruction(
        self,
        *,
        user_type: UserType,
        max_tool_rounds: int,
        max_tool_rounds_exhausted: bool,
    ) -> str:
        """Render the final synthesis instruction after tool calling ends."""

        return self._render_template(
            "final_answer_instruction.j2",
            user_type=user_type.value,
            max_tool_rounds=max_tool_rounds,
            max_tool_rounds_exhausted=max_tool_rounds_exhausted,
        )

    def _render_template(self, template_name: str, **context: Any) -> str:
        """Render a prompt template by name with strict undefined variables."""

        template = self.environment.get_template(template_name)
        return template.render(**context).strip()
