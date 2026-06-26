"""OpenRouter/OpenAI SDK orchestration with direct MCP tool schemas.

The agent uses OpenAI's standard Chat Completions tool-calling protocol. It
does not define a custom wrapper function. Instead, every turn starts by asking
the local Korean Law MCP server for ``list_tools()``, converts those MCP tools
into OpenAI function tools, and lets the model call the actual MCP tool names
directly.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable, Iterator
from typing import Any

from loguru import logger
from openai import OpenAI

from app.config import AppConfig
from app.mcp_client import KoreanLawMcpClient
from app.models import (
    AgentTurnResult,
    ChatMessage,
    ChatRole,
    McpToolRequest,
    McpToolResult,
    ToolCatalogEntry,
    ToolEvidenceEntry,
    ToolResultState,
    TraceEvent,
    UserType,
)
from app.permissions import ToolPermissionPolicy
from app.prompting import PromptRenderer


TraceCallback = Callable[[TraceEvent], None]


class OpenRouterLegalAgent:
    """LLM agent that lets the model directly call MCP-listed tools.

    Background:
        The MCP server is the source of truth for tool names, descriptions, and
        argument schemas. Fetching ``list_tools()`` per turn keeps the LLM aligned
        with the local server configuration and avoids a hand-written wrapper
        contract drifting away from the MCP repository.
    """

    def __init__(
        self,
        config: AppConfig,
        openrouter_api_key: str,
        mcp_client: KoreanLawMcpClient,
        prompt_renderer: PromptRenderer,
        permission_policy: ToolPermissionPolicy,
    ) -> None:
        """Create the OpenAI-compatible client and store collaborators.

        Function:
            The OpenAI SDK client points at OpenRouter's OpenAI-compatible base
            URL. MCP transport, prompt rendering, and permission policy remain
            separate modules so each role can be changed independently.
        """

        self.config = config
        self.client = OpenAI(api_key=openrouter_api_key, base_url=config.openrouter_base_url)
        self.mcp_client = mcp_client
        self.prompt_renderer = prompt_renderer
        self.permission_policy = permission_policy

    def prepare_turn(
        self,
        *,
        model: str,
        session_id: str,
        user_type: UserType,
        custom_instruction: str,
        history: list[ChatMessage],
        user_prompt: str,
        on_trace: TraceCallback,
    ) -> AgentTurnResult:
        """Run the model-driven MCP tool-calling phase for one chat turn.

        Intent:
            The first planning round uses ``tool_choice='required'`` when MCP
            tools are available, satisfying the demo requirement that every user
            request performs tool calling. Later rounds use ``auto`` so the LLM
            can continue or stop based on the accumulated MCP results. If an
            auto round stops without tool calls, the agent adds one explicit
            checkpoint message and gives the LLM one more ``auto`` opportunity
            to decide whether additional MCP calls would improve the answer.
        """

        logger.info(
            "prepare_turn started session_id={} model={} user_type={} history_messages={} user_prompt_chars={}",
            session_id,
            model,
            user_type.value,
            len(history),
            len(user_prompt),
        )
        tool_catalog = self._list_mcp_tools(on_trace)
        openai_tools = self._openai_tools_from_catalog(tool_catalog)
        if openai_tools:
            injected_names = ", ".join(tool["function"]["name"] for tool in openai_tools)
            self._emit(on_trace, f"Injected MCP list_tools() catalog into OpenAI tools: {injected_names}.")
        system_prompt = self.prompt_renderer.render_system_prompt(
            user_type=user_type,
        )
        messages = self._build_initial_messages(
            system_prompt=system_prompt,
            history=history,
            user_prompt=user_prompt,
            tool_catalog=tool_catalog,
            custom_instruction=custom_instruction,
        )
        logger.info(
            "prepared initial OpenAI messages session_id={} profile={}",
            session_id,
            self._message_profile(messages),
        )
        trace: list[TraceEvent] = []
        sources: list[str] = []
        evidence: list[ToolEvidenceEntry] = []

        if not openai_tools:
            self._emit(on_trace, "No MCP tools were available; final answer will explain the missing tool context.")
            self._append_final_answer_instruction(messages, user_type, max_tool_rounds_exhausted=False)
            return AgentTurnResult(messages=messages, trace=trace, sources=sources, evidence=evidence)

        checkpoint_used = False
        exhausted_rounds = True
        for round_index in range(self.config.max_tool_rounds):
            tool_choice = "required" if round_index == 0 else "auto"
            self._emit(on_trace, f"LLM planning round {round_index + 1}: tool_choice={tool_choice}.")
            logger.info(
                "planning request session_id={} round={} tool_choice={} message_count={} tool_count={}",
                session_id,
                round_index + 1,
                tool_choice,
                len(messages),
                len(openai_tools),
            )
            completion = self.client.chat.completions.create(
                model=model,
                messages=messages,
                tools=openai_tools,
                tool_choice=tool_choice,
                parallel_tool_calls=True,
                temperature=0.1,
                extra_headers=self._openrouter_headers(session_id),
                extra_body=self._openrouter_extra_body(session_id),
            )
            self._trace_usage(completion, f"planning round {round_index + 1}", on_trace)
            assistant_message = completion.choices[0].message
            tool_calls = assistant_message.tool_calls or []
            logger.info(
                "planning response session_id={} round={} response_id={} finish_reason={} tool_call_count={} content_chars={}",
                session_id,
                round_index + 1,
                self._get_field(completion, "id"),
                self._choice_finish_reason(completion),
                len(tool_calls),
                len(assistant_message.content or ""),
            )
            if not tool_calls:
                if not checkpoint_used and round_index + 1 < self.config.max_tool_rounds:
                    checkpoint_used = True
                    messages.append(self._tool_reentry_checkpoint_message(user_type, tool_catalog))
                    self._emit(on_trace, "LLM paused tool use; added one auto checkpoint for possible MCP re-entry.")
                    continue

                self._emit(on_trace, "LLM chose no additional MCP tools; final answer stage will start.")
                exhausted_rounds = False
                break

            messages.append(assistant_message.model_dump(exclude_none=True))
            results = self._execute_tool_calls(tool_calls, user_type, on_trace)
            for result in results:
                trace.append(self._trace_event(result))
                sources.append(self._source_line(result))
                evidence.append(self._evidence_entry(result))
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": result.request.openai_tool_call_id,
                        "content": self._tool_message_content(result),
                    }
                )

        if exhausted_rounds:
            self._emit(
                on_trace,
                f"Reached MAX_TOOL_ROUNDS={self.config.max_tool_rounds}; final answer stage will start with gathered evidence.",
            )
            logger.warning(
                "max tool rounds exhausted session_id={} max_tool_rounds={} message_count={}",
                session_id,
                self.config.max_tool_rounds,
                len(messages),
            )

        self._append_final_answer_instruction(messages, user_type, max_tool_rounds_exhausted=exhausted_rounds)
        logger.info(
            "prepare_turn completed session_id={} sources={} evidence={} final_message_profile={}",
            session_id,
            len(sources),
            len(evidence),
            self._message_profile(messages),
        )
        return AgentTurnResult(messages=messages, trace=trace, sources=self._dedupe(sources), evidence=evidence)

    def stream_final_answer(
        self,
        *,
        model: str,
        session_id: str,
        prepared_turn: AgentTurnResult,
        on_trace: TraceCallback | None = None,
    ) -> Iterator[str]:
        """Stream the final answer after MCP tool calls are complete.

        Function:
            The final request does not expose tools. The model synthesizes an
            answer from chat history plus MCP tool-result messages already in
            ``prepared_turn.messages``.
        """

        logger.info(
            "final streaming request started session_id={} model={} message_profile={}",
            session_id,
            model,
            self._message_profile(prepared_turn.messages),
        )
        emitted_text = False
        finish_reasons: list[str] = []
        stream = self.client.chat.completions.create(
            model=model,
            messages=prepared_turn.messages,
            temperature=0.2,
            stream=True,
            stream_options={"include_usage": True},
            extra_headers=self._openrouter_headers(session_id),
            extra_body=self._openrouter_extra_body(session_id),
        )
        for chunk in stream:
            self._trace_usage(chunk, "final streaming", on_trace)
            finish_reason = self._choice_finish_reason(chunk)
            if finish_reason:
                finish_reasons.append(str(finish_reason))
                logger.info(
                    "final streaming chunk finish session_id={} response_id={} finish_reason={}",
                    session_id,
                    self._get_field(chunk, "id"),
                    finish_reason,
                )
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta.content
            if delta:
                emitted_text = True
                logger.debug("final streaming delta session_id={} chars={}", session_id, len(delta))
                yield delta

        if emitted_text:
            logger.info("final streaming completed session_id={} finish_reasons={}", session_id, finish_reasons)
            return

        self._emit(
            on_trace,
            "Final streaming returned no text; retrying once with a non-streaming final answer request.",
            payload={"finish_reasons": finish_reasons},
        )
        logger.warning("final streaming returned empty text session_id={} finish_reasons={}", session_id, finish_reasons)
        fallback = self._final_answer_fallback(
            model=model,
            session_id=session_id,
            prepared_turn=prepared_turn,
            on_trace=on_trace,
        )
        if fallback:
            yield fallback
            return

        failure_text = (
            "최종 답변 생성 단계에서 모델이 빈 응답을 반환했습니다. "
            "MCP 호출 결과는 위 Tool calling status에서 확인할 수 있으며, logs/chatbot-debug.log에 진단 로그를 남겼습니다."
        )
        logger.error("final fallback also returned empty text session_id={}", session_id)
        yield failure_text

    def _list_mcp_tools(self, on_trace: TraceCallback) -> list[ToolCatalogEntry]:
        """Fetch the current MCP tool catalog from the local server.

        Background:
            This is the point where the Python app verifies that the MCP server
            can start and advertise tools. A failure here means the LLM will not
            receive legal-data tools for this turn, so the status container shows
            the exception instead of hiding the missing retrieval layer.
        """

        try:
            tools = asyncio.run(self.mcp_client.list_tools())
            self._emit(on_trace, f"Loaded {len(tools)} MCP tools from list_tools().")
            logger.info("loaded MCP tool catalog count={} names={}", len(tools), [tool.name for tool in tools])
            return tools
        except Exception as exc:
            logger.exception("failed to load MCP tool catalog")
            self._emit(on_trace, f"Failed to load MCP tool catalog: {type(exc).__name__}: {exc}")
            return []

    def _openai_tools_from_catalog(self, tool_catalog: list[ToolCatalogEntry]) -> list[dict[str, Any]]:
        """Convert MCP tool metadata into OpenAI Chat Completions tools.

        Background:
            MCP and OpenAI both use JSON Schema-like tool descriptions. This
            conversion preserves the MCP server's actual tool names and input
            schemas instead of inventing a separate application wrapper.

        Function:
            Each returned item has `type='function'` and a `function.name` equal
            to the MCP tool name from `list_tools()`. Because of that identity,
            any model-selected OpenAI tool call can be forwarded to
            `session.call_tool()` after persona validation.
        """

        tools: list[dict[str, Any]] = []
        for entry in tool_catalog:
            parameters = self._sanitize_json_schema(entry.input_schema or {"type": "object", "properties": {}})
            if parameters.get("type") != "object":
                parameters = {"type": "object", "properties": {}, "description": "No structured schema provided."}
            tools.append(
                {
                    "type": "function",
                    "function": {
                        "name": entry.name,
                        "description": entry.description or f"Korean Law MCP tool: {entry.name}",
                        "parameters": parameters,
                    },
                }
            )
        return tools

    def _sanitize_json_schema(self, schema: dict[str, Any]) -> dict[str, Any]:
        """Prepare an MCP JSON Schema object for OpenAI tool registration.

        Background:
            MCP and OpenAI both use JSON Schema-like structures, but MCP schemas
            can contain metadata fields that are unnecessary for OpenAI tool
            calls. This method preserves semantic fields while dropping common
            schema-document metadata.
        """

        sanitized = dict(schema)
        sanitized.pop("$schema", None)
        sanitized.pop("$id", None)
        return sanitized

    def _build_initial_messages(
        self,
        system_prompt: str,
        history: list[ChatMessage],
        user_prompt: str,
        tool_catalog: list[ToolCatalogEntry],
        custom_instruction: str,
    ) -> list[dict[str, Any]]:
        """Build OpenAI messages with stable prefix and dynamic evidence context.

        Background:
            OpenRouter/Gemini prompt caching benefits when the early prompt is
            stable. The system prompt is therefore kept as the first cacheable
            block, while the live MCP catalog, custom instruction, and prior MCP
            evidence are sent as later user-context messages.
        """

        messages: list[dict[str, Any]] = [self._system_message(system_prompt)]
        messages.extend(self._dynamic_context_messages(history, tool_catalog, custom_instruction))
        for message in history[-self.config.max_history_messages :]:
            if message.role in {ChatRole.USER, ChatRole.ASSISTANT}:
                messages.append({"role": message.role.value, "content": message.content})
        messages.append({"role": "user", "content": user_prompt})
        return messages

    def _system_message(self, system_prompt: str) -> dict[str, Any]:
        """Return the stable system prompt marked cacheable for OpenRouter.

        Function:
            OpenRouter documents Gemini prompt caching through `cache_control`
            content blocks. The app always marks only the stable system block,
            avoiding a dynamic tail inside Gemini's normalized system
            instruction while keeping prefix caching active by default.
        """

        return {
            "role": "system",
            "content": [
                {
                    "type": "text",
                    "text": system_prompt,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
        }

    def _dynamic_context_messages(
        self,
        history: list[ChatMessage],
        tool_catalog: list[ToolCatalogEntry],
        custom_instruction: str,
    ) -> list[dict[str, str]]:
        """Create per-turn context messages that should not live in the cacheable prefix."""

        messages: list[dict[str, str]] = [self._tool_catalog_message(tool_catalog)]
        if custom_instruction.strip():
            messages.append(
                {
                    "role": "user",
                    "content": self.prompt_renderer.render_custom_instruction_context(custom_instruction.strip()),
                }
            )
        evidence_message = self._prior_evidence_message(history)
        if evidence_message:
            messages.append(evidence_message)
        return messages

    def _tool_catalog_message(self, tool_catalog: list[ToolCatalogEntry]) -> dict[str, str]:
        """Serialize the live MCP catalog loaded for this request."""

        catalog = [
            {
                "name": tool.name,
                "description": tool.description,
                "input_schema": tool.input_schema,
            }
            for tool in tool_catalog
        ]
        return {
            "role": "user",
            "content": self.prompt_renderer.render_tool_catalog_context(
                json.dumps(catalog, ensure_ascii=False, sort_keys=True)
            ),
        }

    def _prior_evidence_message(self, history: list[ChatMessage]) -> dict[str, str] | None:
        """Build bounded multi-turn MCP evidence memory for the next request.

        Intent:
            Recent evidence stays relatively detailed so follow-up questions can
            reuse legal context. Older evidence is compacted into a bounded JSON
            array so long sessions do not replay every raw MCP result forever.
        """

        assistant_messages = [message for message in history if message.role == ChatRole.ASSISTANT and message.evidence]
        if not assistant_messages:
            return None

        recent_count = self.config.recent_tool_context_turns
        recent_messages = assistant_messages[-recent_count:] if recent_count else []
        older_messages = assistant_messages[: len(assistant_messages) - len(recent_messages)]
        recent_evidence = [entry.as_context_dict() for message in recent_messages for entry in message.evidence]
        older_evidence = [entry.as_context_dict() for message in older_messages for entry in message.evidence]

        payload: dict[str, Any] = {}
        if older_evidence:
            payload["compacted_older_mcp_evidence"] = self._bounded_json_array(
                older_evidence,
                self.config.max_compacted_evidence_chars,
            )
        if recent_evidence:
            payload["recent_raw_mcp_evidence"] = recent_evidence
        if not payload:
            return None
        return {
            "role": "user",
            "content": self.prompt_renderer.render_prior_evidence_context(
                json.dumps(payload, ensure_ascii=False, sort_keys=True)
            ),
        }

    def _bounded_json_array(self, items: list[dict[str, Any]], max_chars: int) -> list[dict[str, Any]]:
        """Keep an older evidence array within a rough serialized character budget."""

        kept: list[dict[str, Any]] = []
        for item in reversed(items):
            candidate = [item] + kept
            if len(json.dumps(candidate, ensure_ascii=False, sort_keys=True)) > max_chars and kept:
                break
            kept = candidate
        if len(kept) < len(items):
            omitted = len(items) - len(kept)
            kept.insert(0, {"state": "compacted", "omitted_older_evidence_count": omitted})
        return kept

    def _tool_reentry_checkpoint_message(
        self,
        user_type: UserType,
        tool_catalog: list[ToolCatalogEntry],
    ) -> dict[str, Any]:
        """Create the one-time checkpoint that lets the LLM re-enter tool use.

        Intent:
            The checkpoint is not an intent classifier and does not inspect the
            user's text. It gives the model the current persona, the already
            available conversation/tool-result context, and the live MCP tool
            catalog again, then asks the model to either call more tools or make
            no tool call. The final natural-language answer is still generated
            by ``stream_final_answer`` after this planning phase ends.
        """

        catalog = [
            {
                "name": tool.name,
                "description": tool.description,
                "input_schema": tool.input_schema,
            }
            for tool in tool_catalog
        ]
        content = self.prompt_renderer.render_tool_reentry_checkpoint(
            user_type=user_type,
            catalog_json=json.dumps(catalog, ensure_ascii=False),
        )
        return {"role": "user", "content": content}

    def _append_final_answer_instruction(
        self,
        messages: list[dict[str, Any]],
        user_type: UserType,
        max_tool_rounds_exhausted: bool,
    ) -> None:
        """Append an explicit final-synthesis request after tool calling.

        Background:
            Some providers are reliable when a final request immediately follows
            a ``role='tool'`` message, but others can end the stream without text
            because the conversation has no final user-visible synthesis
            instruction. This message makes the transition from retrieval to
            answer generation explicit without adding any regex or Python-side
            intent logic.
        """

        messages.append(
            {
                "role": "user",
                "content": self.prompt_renderer.render_final_answer_instruction(
                    user_type=user_type,
                    max_tool_rounds=self.config.max_tool_rounds,
                    max_tool_rounds_exhausted=max_tool_rounds_exhausted,
                ),
            }
        )

    def _execute_tool_calls(self, tool_calls: list[Any], user_type: UserType, on_trace: TraceCallback) -> list[McpToolResult]:
        """Validate and execute one assistant message's MCP tool calls.

        Intent:
            The model is responsible for reasoning about which tools and
            arguments are useful. Python only converts the OpenAI SDK objects to
            typed requests, applies persona policy, and executes approved calls.
            Invalid JSON arguments and blocked calls are returned as tool
            messages so the model can recover in a later auto tool round.
        """

        approved: list[McpToolRequest] = []
        immediate_results: list[McpToolResult] = []

        for tool_call in tool_calls:
            request_or_error = self._request_from_openai_tool_call(tool_call)
            if isinstance(request_or_error, McpToolResult):
                immediate_results.append(request_or_error)
                logger.warning("invalid model tool call returned as MCP error text={}", request_or_error.text)
                self._emit(on_trace, request_or_error.text)
                continue

            request = request_or_error
            decision = self.permission_policy.validate(user_type, request.tool_name, request.arguments)
            if not decision.allowed:
                result = McpToolResult(
                    request=request,
                    text=f"BLOCKED by persona policy: {decision.reason}",
                    is_error=True,
                    is_blocked=True,
                )
                immediate_results.append(result)
                logger.warning(
                    "blocked MCP call user_type={} tool={} reason={} arguments={}",
                    user_type.value,
                    request.tool_name,
                    decision.reason,
                    request.arguments,
                )
                self._emit(
                    on_trace,
                    f"Blocked `{request.tool_name}`: {decision.reason}",
                    payload={"tool_name": request.tool_name, "arguments": request.arguments},
                )
                continue

            approved.append(request)
            self._emit(
                on_trace,
                f"Calling `{request.tool_name}` with model-selected arguments.",
                payload={"tool_name": request.tool_name, "arguments": request.arguments},
            )

        return immediate_results + self._call_mcp(approved, on_trace)

    def _request_from_openai_tool_call(self, tool_call: Any) -> McpToolRequest | McpToolResult:
        """Convert an OpenAI direct function call into an MCP request.

        Function:
            The function name is already the actual MCP tool name because the
            OpenAI ``tools`` list was generated from MCP ``list_tools()``.

        Background:
            This method deliberately does not translate through an application
            wrapper such as ``korean_law_mcp_call``. Preserving the tool name is
            what lets the local MCP server remain the source of truth for tool
            contracts.
        """

        function = tool_call.function
        try:
            arguments = json.loads(function.arguments or "{}")
            if not isinstance(arguments, dict):
                raise TypeError("tool arguments must decode to an object")
            return McpToolRequest(
                tool_name=function.name,
                arguments=arguments,
                openai_tool_call_id=tool_call.id,
            )
        except Exception as exc:
            request = McpToolRequest(
                tool_name=function.name,
                arguments={},
                openai_tool_call_id=tool_call.id,
            )
            return McpToolResult(request=request, text=f"Invalid tool-call arguments: {type(exc).__name__}: {exc}", is_error=True)

    def _call_mcp(self, requests: list[McpToolRequest], on_trace: TraceCallback) -> list[McpToolResult]:
        """Execute approved MCP requests through the stdio client."""

        if not requests:
            return []
        try:
            logger.info(
                "calling MCP tools count={} tools={}",
                len(requests),
                [{"name": request.tool_name, "arguments": request.arguments} for request in requests],
            )
            results = asyncio.run(self.mcp_client.call_many(requests))
            for result in results:
                state = "failed" if result.is_error else "completed"
                logger.info(
                    "MCP tool completed tool={} state={} text_chars={} arguments={}",
                    result.request.tool_name,
                    self._result_state(result).value,
                    len(result.text),
                    result.request.arguments,
                )
                self._emit(
                    on_trace,
                    f"MCP `{result.request.tool_name}` {state}.",
                    payload={
                        "state": self._result_state(result).value,
                        "tool_name": result.request.tool_name,
                        "arguments": result.request.arguments,
                        "result_excerpt": self._truncate(result.text, self.config.max_tool_evidence_chars),
                    },
                )
            return results
        except Exception as exc:
            logger.exception("MCP execution failed for {} requests", len(requests))
            self._emit(on_trace, f"MCP execution failed: {type(exc).__name__}: {exc}")
            return [
                McpToolResult(
                    request=request,
                    text=f"MCP execution failed: {type(exc).__name__}: {exc}",
                    is_error=True,
                )
                for request in requests
            ]

    def _tool_message_content(self, result: McpToolResult) -> str:
        """Serialize an MCP result into an OpenAI ``role='tool'`` message."""

        state = "blocked" if result.is_blocked else "error" if result.is_error else "ok"
        return json.dumps(
            {
                "state": state,
                "tool_name": result.request.tool_name,
                "arguments": result.request.arguments,
                "result": result.text,
            },
            ensure_ascii=False,
        )

    def _trace_event(self, result: McpToolResult) -> TraceEvent:
        """Create a structured status entry for the Streamlit trace expander."""

        state = self._result_state(result)
        return TraceEvent(
            title=f"{state.value}: {result.request.tool_name}",
            payload={
                "state": state.value,
                "tool_name": result.request.tool_name,
                "arguments": result.request.arguments,
                "result_excerpt": self._truncate(result.text, self.config.max_tool_evidence_chars),
            },
        )

    def _evidence_entry(self, result: McpToolResult) -> ToolEvidenceEntry:
        """Convert one MCP result into bounded multi-turn evidence memory."""

        return ToolEvidenceEntry(
            state=self._result_state(result),
            tool_name=result.request.tool_name,
            arguments=result.request.arguments,
            result=self._truncate(result.text, self.config.max_tool_evidence_chars),
        )

    def _result_state(self, result: McpToolResult) -> ToolResultState:
        """Normalize MCP result flags into one persisted state value."""

        if result.is_blocked:
            return ToolResultState.BLOCKED
        if result.is_error:
            return ToolResultState.ERROR
        return ToolResultState.OK

    def _source_line(self, result: McpToolResult) -> str:
        """Create an auditable source label from the executed MCP call."""

        return json.dumps(
            {"tool": result.request.tool_name, "arguments": result.request.arguments},
            ensure_ascii=False,
        )

    def _emit(self, on_trace: TraceCallback | None, title: str, payload: dict[str, Any] | list[Any] | None = None) -> None:
        """Send a structured trace event if the UI supplied a callback."""

        if on_trace:
            on_trace(TraceEvent(title=title, payload=payload))

    def _trace_usage(self, response: Any, stage: str, on_trace: TraceCallback | None) -> None:
        """Record OpenRouter prompt-cache usage when the provider returns it."""

        usage = getattr(response, "usage", None)
        if usage is None:
            return
        prompt_details = getattr(usage, "prompt_tokens_details", None)
        if prompt_details is None and isinstance(usage, dict):
            prompt_details = usage.get("prompt_tokens_details")
        if prompt_details is None:
            return
        cached_tokens = self._get_field(prompt_details, "cached_tokens")
        cache_write_tokens = self._get_field(prompt_details, "cache_write_tokens")
        if cached_tokens is None and cache_write_tokens is None:
            return
        self._emit(
            on_trace,
            f"OpenRouter cache usage for {stage}.",
            payload={
                "stage": stage,
                "cached_tokens": cached_tokens,
                "cache_write_tokens": cache_write_tokens,
            },
        )
        logger.info(
            "OpenRouter usage stage={} cached_tokens={} cache_write_tokens={}",
            stage,
            cached_tokens,
            cache_write_tokens,
        )

    def _final_answer_fallback(
        self,
        *,
        model: str,
        session_id: str,
        prepared_turn: AgentTurnResult,
        on_trace: TraceCallback | None,
    ) -> str:
        """Retry final synthesis once without streaming when streaming is empty."""

        try:
            completion = self.client.chat.completions.create(
                model=model,
                messages=prepared_turn.messages,
                temperature=0.2,
                extra_headers=self._openrouter_headers(session_id),
                extra_body=self._openrouter_extra_body(session_id),
            )
            self._trace_usage(completion, "final non-stream fallback", on_trace)
            message = completion.choices[0].message
            text = message.content or ""
            logger.info(
                "final fallback response session_id={} response_id={} finish_reason={} content_chars={}",
                session_id,
                self._get_field(completion, "id"),
                self._choice_finish_reason(completion),
                len(text),
            )
            if text:
                self._emit(on_trace, "Final answer recovered by non-streaming fallback.")
            return text
        except Exception as exc:
            logger.exception("final fallback request failed session_id={}", session_id)
            self._emit(on_trace, f"Final fallback failed: {type(exc).__name__}: {exc}")
            return ""

    def _get_field(self, value: Any, field: str) -> Any:
        """Read a field from either SDK objects or plain dictionaries."""

        if isinstance(value, dict):
            return value.get(field)
        return getattr(value, field, None)

    def _choice_finish_reason(self, response: Any) -> Any:
        """Return the first choice finish reason from an SDK object or dict."""

        choices = self._get_field(response, "choices") or []
        if not choices:
            return None
        first = choices[0]
        if isinstance(first, dict):
            return first.get("finish_reason")
        return getattr(first, "finish_reason", None)

    def _message_profile(self, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Return a compact log-safe profile of OpenAI messages.

        Function:
            The profile is enough to debug sequencing mistakes, such as ending a
            final request on a tool result, without writing the full prompt body
            to every log line.
        """

        profile: list[dict[str, Any]] = []
        for index, message in enumerate(messages):
            content = message.get("content", "")
            if isinstance(content, list):
                content_chars = sum(len(str(part)) for part in content)
            else:
                content_chars = len(str(content))
            profile.append(
                {
                    "index": index,
                    "role": message.get("role"),
                    "content_chars": content_chars,
                    "has_tool_calls": bool(message.get("tool_calls")),
                    "tool_call_id": message.get("tool_call_id"),
                }
            )
        return profile

    def _truncate(self, text: str, max_chars: int) -> str:
        """Bound stored tool output while preserving the leading evidence text."""

        if len(text) <= max_chars:
            return text
        return text[:max_chars] + f"\n...[truncated {len(text) - max_chars} chars]"

    def _openrouter_headers(self, session_id: str) -> dict[str, str]:
        """Return optional OpenRouter attribution headers."""

        return {
            "HTTP-Referer": "http://localhost:8501",
            "X-Title": self.config.title,
            "x-session-id": session_id,
        }

    def _openrouter_extra_body(self, session_id: str) -> dict[str, str]:
        """Return OpenRouter-specific body fields passed through the OpenAI SDK."""

        return {"session_id": session_id}

    def _dedupe(self, values: list[str]) -> list[str]:
        """Preserve-order deduplication for UI source labels."""

        seen: set[str] = set()
        output: list[str] = []
        for value in values:
            if value not in seen:
                seen.add(value)
                output.append(value)
        return output
