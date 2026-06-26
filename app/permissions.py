"""Persona-based permission policy for model-requested MCP calls.

This module is deliberately not an intent classifier. It never inspects the
natural-language user message and does not use keyword matching. It validates
only the exact ``tool_name`` and structured ``arguments`` selected by the LLM
through OpenAI's standard tool calling interface.
"""

from __future__ import annotations

from typing import Any

from app.models import PermissionDecision, UserType


ADVERTISED_TOOL_NAMES = {
    "search_law",
    "get_law_text",
    "get_annexes",
    "search_decisions",
    "get_decision_text",
    "legal_research",
    "legal_analysis",
    "discover_tools",
    "execute_tool",
}

GENERAL_DECISION_DOMAINS = {
    "precedent",
    "interpretation",
    "constitutional",
    "admin_appeal",
}

TAX_ACCOUNTANT_DECISION_DOMAINS = {
    "precedent",
    "interpretation",
    "constitutional",
    "admin_appeal",
    "tax_tribunal",
    "customs",
    "nts",
    "ftc",
    "pipc",
    "nlrc",
    "acr",
    "appeal_review",
    "acr_special",
    "treaty",
    "english_law",
}

GENERAL_RESEARCH_TASKS = {"full_research", "law_system"}
TAX_ACCOUNTANT_RESEARCH_TASKS = {
    "full_research",
    "law_system",
    "action_basis",
    "dispute_prep",
    "amendment_track",
    "ordinance_compare",
    "procedure_detail",
    "document_review",
}

GENERAL_ANALYSIS_MODES = {"verify_citations", "applicable_law"}
TAX_ACCOUNTANT_ANALYSIS_MODES = {
    "verify_citations",
    "cite_check",
    "applicable_law",
    "impact_map",
}

TAX_ACCOUNTANT_HIDDEN_TOOL_NAMES = {
    "search_admin_rule",
    "get_admin_rule",
    "compare_admin_rule_old_new",
    "search_ordinance",
    "get_ordinance",
    "get_linked_ordinances",
    "get_linked_ordinance_articles",
    "get_delegated_laws",
    "get_linked_laws_from_ordinance",
    "get_article_detail",
    "get_batch_articles",
    "get_article_with_precedents",
    "compare_old_new",
    "get_three_tier",
    "compare_articles",
    "get_law_tree",
    "get_law_system_tree",
    "get_article_history",
    "get_law_history",
    "search_historical_law",
    "get_historical_law",
    "search_all",
    "advanced_search",
    "suggest_law_names",
    "parse_jo_code",
    "get_law_abbreviations",
    "search_legal_terms",
    "get_legal_term_kb",
    "get_legal_term_detail",
    "get_daily_term",
    "get_daily_to_legal",
    "get_legal_to_daily",
    "get_term_articles",
    "get_related_laws",
    "search_tax_tribunal_decisions",
    "get_tax_tribunal_decision_text",
    "search_customs_interpretations",
    "get_customs_interpretation_text",
    "analyze_document",
    "verify_citations",
    "impact_map",
    "cite_check",
    "applicable_law",
}


class ToolPermissionPolicy:
    """Validate MCP calls against the selected user persona.

    Intent:
        General users should get accessible, statute-centered answers. Tax
        accountants should be allowed to use richer and more technical sources
        such as tax tribunal decisions, customs interpretations, NTS materials,
        amendment history, and professional chain tools when those sources help
        solve the problem.
    """

    def validate(self, user_type: UserType, tool_name: str, arguments: dict[str, Any]) -> PermissionDecision:
        """Return whether a concrete MCP call may execute.

        Function:
            The method validates structured MCP call requests selected by the
            model. It does not parse user intent, classify tax topics, or inspect
            raw Korean text. That reasoning belongs to the LLM.
        """

        if tool_name == "search_decisions":
            return self._validate_decision_search(user_type, arguments)
        if tool_name == "get_decision_text":
            return self._validate_decision_text(user_type, arguments)
        if tool_name == "legal_research":
            return self._validate_legal_research(user_type, arguments)
        if tool_name == "legal_analysis":
            return self._validate_legal_analysis(user_type, arguments)
        if tool_name == "discover_tools":
            return PermissionDecision(
                allowed=user_type == UserType.TAX_ACCOUNTANT,
                reason="discover_tools is tax-accountant-only",
            )
        if tool_name == "execute_tool":
            return self._validate_execute_tool(user_type, arguments)
        if tool_name in ADVERTISED_TOOL_NAMES:
            return PermissionDecision(allowed=True, reason="advertised MCP tool")
        if user_type == UserType.TAX_ACCOUNTANT and tool_name in TAX_ACCOUNTANT_HIDDEN_TOOL_NAMES:
            return PermissionDecision(allowed=True, reason="tax-accountant hidden MCP tool")
        return PermissionDecision(allowed=False, reason=f"tool '{tool_name}' is not allowed for {user_type.value}")

    def prompt_context(self, user_type: UserType) -> str:
        """Return a persona policy summary for the system prompt.

        Background:
            The prompt tells the LLM which sources it should prefer for each
            persona. Runtime enforcement still happens in ``validate`` because a
            prompt is not a security boundary.
        """

        if user_type == UserType.GENERAL:
            return (
                "General user persona: answer in accessible language. If the topic is tax-related, "
                "prefer statutes and core law text first. Use basic precedents or interpretations only "
                "when necessary to clarify the statute. Do not request specialist tax tribunal, customs, "
                "NTS, hidden tools, discover_tools, execute_tool, or full specialist decision text."
            )
        return (
            "Tax accountant persona: assume professional tax literacy. Actively use specialist materials "
            "when they improve the answer: tax tribunal decisions, customs interpretations, NTS materials, "
            "amendment history, applicable-law checks, citation verification, chain tools, and full text. "
            "Use those sources as explicit grounds in the final answer."
        )

    def hidden_tool_context(self) -> str:
        """Return tax-accountant hidden tool names for prompt context."""

        return ", ".join(sorted(TAX_ACCOUNTANT_HIDDEN_TOOL_NAMES))

    def _validate_decision_search(self, user_type: UserType, arguments: dict[str, Any]) -> PermissionDecision:
        """Validate ``search_decisions`` domain access."""

        domain = str(arguments.get("domain", ""))
        allowed = (
            TAX_ACCOUNTANT_DECISION_DOMAINS
            if user_type == UserType.TAX_ACCOUNTANT
            else GENERAL_DECISION_DOMAINS
        )
        return PermissionDecision(allowed=domain in allowed, reason=f"search_decisions domain={domain}")

    def _validate_decision_text(self, user_type: UserType, arguments: dict[str, Any]) -> PermissionDecision:
        """Validate ``get_decision_text`` domain and full-text access."""

        domain = str(arguments.get("domain", ""))
        full = bool(arguments.get("full", False))
        if user_type == UserType.GENERAL:
            allowed = domain in GENERAL_DECISION_DOMAINS and not full
            return PermissionDecision(allowed=allowed, reason=f"general domain={domain}, full={full}")
        return PermissionDecision(
            allowed=domain in TAX_ACCOUNTANT_DECISION_DOMAINS,
            reason=f"tax_accountant domain={domain}, full={full}",
        )

    def _validate_legal_research(self, user_type: UserType, arguments: dict[str, Any]) -> PermissionDecision:
        """Validate ``legal_research`` task scope."""

        task = str(arguments.get("task", "full_research"))
        allowed = (
            TAX_ACCOUNTANT_RESEARCH_TASKS
            if user_type == UserType.TAX_ACCOUNTANT
            else GENERAL_RESEARCH_TASKS
        )
        return PermissionDecision(allowed=task in allowed, reason=f"legal_research task={task}")

    def _validate_legal_analysis(self, user_type: UserType, arguments: dict[str, Any]) -> PermissionDecision:
        """Validate ``legal_analysis`` mode scope."""

        mode = str(arguments.get("mode", ""))
        allowed = (
            TAX_ACCOUNTANT_ANALYSIS_MODES
            if user_type == UserType.TAX_ACCOUNTANT
            else GENERAL_ANALYSIS_MODES
        )
        return PermissionDecision(allowed=mode in allowed, reason=f"legal_analysis mode={mode}")

    def _validate_execute_tool(self, user_type: UserType, arguments: dict[str, Any]) -> PermissionDecision:
        """Validate hidden-tool proxy access through ``execute_tool``."""

        hidden_name = str(arguments.get("tool_name", ""))
        allowed = user_type == UserType.TAX_ACCOUNTANT and hidden_name in TAX_ACCOUNTANT_HIDDEN_TOOL_NAMES
        return PermissionDecision(allowed=allowed, reason=f"execute_tool tool_name={hidden_name}")
