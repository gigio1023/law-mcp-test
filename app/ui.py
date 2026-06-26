"""Streamlit user interface for the Korean Law RAG chatbot demo.

The UI is intentionally thin. It renders controls, persists chat history, shows
tool-call status, and delegates LLM/MCP behavior to the application services.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Callable, Iterator

import streamlit as st

from app.config import AppConfig, PROJECT_ROOT
from app.llm import OpenRouterLegalAgent
from app.mcp_client import KoreanLawMcpClient
from app.models import AgentTurnResult, ChatMessage, ChatRole, TraceEvent, UserType
from app.observability import configure_file_logging
from app.permissions import ToolPermissionPolicy
from app.prompting import PromptRenderer


class StreamlitChatApp:
    """Render and run the Streamlit chat application.

    Intent:
        Keep Streamlit-specific concerns out of the LLM and MCP modules. This
        class handles reruns, session state, sidebar controls, and status
        containers while the agent handles OpenAI tool calling.
    """

    def __init__(self) -> None:
        """Create immutable config and shared policy objects for one rerun."""

        self.config = AppConfig()
        self.log_file = configure_file_logging(self.config.log_file, self.config.log_level)
        self.policy = ToolPermissionPolicy()
        self.prompt_renderer = PromptRenderer(self.config, self.policy)

    def run(self) -> None:
        """Render the page and respond to one submitted chat prompt."""

        st.set_page_config(page_title=self.config.title, layout="wide")
        self._init_state()
        user_type, model, custom_instruction = self._sidebar()

        st.title(self.config.title)
        st.caption(
            "Streamlit + OpenAI SDK standard tool calling + OpenRouter Gemini 3.5 Flash + Korean Law MCP"
        )
        self._render_history()

        if prompt := st.chat_input("법령, 판례, 해석례 기반으로 질문하세요."):
            self._handle_prompt(prompt, user_type, model, custom_instruction)

    def _init_state(self) -> None:
        """Initialize Streamlit session state keys used by the chat UI."""

        if "messages" not in st.session_state:
            st.session_state.messages = []
        if "openrouter_session_id" not in st.session_state:
            st.session_state.openrouter_session_id = f"streamlit-{uuid.uuid4()}"

    def _sidebar(self) -> tuple[UserType, str, str]:
        """Render runtime controls and return their selected values."""

        with st.sidebar:
            st.header("Settings")
            selected_user_type = st.selectbox(
                "User type",
                options=[UserType.GENERAL.value, UserType.TAX_ACCOUNTANT.value],
                format_func=lambda value: "일반 사용자" if value == UserType.GENERAL.value else "세무사",
            )
            model = st.text_input("OpenRouter model", value=self.config.default_model)
            custom_instruction = st.text_area(
                "Custom instruction",
                placeholder="Injected at the bottom of the system prompt.",
                height=120,
            )
            st.caption(
                "일반 사용자는 법령 중심, 세무사는 조세심판·해석례 등 전문 자료까지 적극 활용하도록 설계했습니다."
            )
            st.caption(f"Debug log: `{self._repo_relative_path(self.log_file)}`")
            if not self.config.effective_openrouter_api_key:
                st.warning("Set OPENROUTER_API_KEY to generate answers.")
            if not self.config.effective_law_api_key:
                st.warning("Set MCP_API_KEY for live law.go.kr retrieval. LAW_OC and KOREAN_LAW_API_KEY also work.")
            if st.button("Clear chat"):
                st.session_state.messages = []
                st.rerun()
        return UserType(selected_user_type), model, custom_instruction

    def _render_history(self) -> None:
        """Replay persisted messages on each Streamlit rerun."""

        for message in st.session_state.messages:
            message = self._coerce_message(message)
            with st.chat_message(message.role.value):
                st.markdown(message.content)
                self._render_trace(message.trace, message.sources)

    def _handle_prompt(self, prompt: str, user_type: UserType, model: str, custom_instruction: str) -> None:
        """Process one user prompt through LLM tool calling and streaming."""

        user_message = ChatMessage(role=ChatRole.USER, content=prompt)
        st.session_state.messages.append(user_message)
        with st.chat_message("user"):
            st.markdown(prompt)

        with st.chat_message("assistant"):
            if not self.config.effective_openrouter_api_key:
                response = "OPENROUTER_API_KEY is not configured."
                st.error(response)
                st.session_state.messages.append(ChatMessage(role=ChatRole.ASSISTANT, content=response))
                return

            mcp_client = KoreanLawMcpClient(self.config, self.config.effective_law_api_key)
            agent = OpenRouterLegalAgent(
                config=self.config,
                openrouter_api_key=self.config.effective_openrouter_api_key,
                mcp_client=mcp_client,
                prompt_renderer=self.prompt_renderer,
                permission_policy=self.policy,
            )

            trace_events: list[TraceEvent] = []
            with st.status("LLM is selecting and calling Korean Law MCP tools...", expanded=True) as status:
                def on_trace(event: TraceEvent) -> None:
                    """Write a tool/status event to UI and retain it for history."""

                    trace_events.append(event)
                    self._render_trace_event(event, status, collapse_payload=True)

                try:
                    prepared = agent.prepare_turn(
                        model=model,
                        session_id=st.session_state.openrouter_session_id,
                        user_type=user_type,
                        custom_instruction=custom_instruction,
                        history=[self._coerce_message(message) for message in st.session_state.messages[:-1]],
                        user_prompt=prompt,
                        on_trace=on_trace,
                    )
                    status.update(label="Tool calling complete", state="complete", expanded=False)
                except Exception as exc:
                    status.update(label="Tool calling failed", state="error", expanded=True)
                    response = f"Tool-calling phase failed: {type(exc).__name__}: {exc}"
                    st.error(response)
                    st.session_state.messages.append(
                        ChatMessage(role=ChatRole.ASSISTANT, content=response, trace=trace_events)
                    )
                    return

            def record_final_trace(event: TraceEvent) -> None:
                """Keep final-stream cache metadata in saved trace history."""

                trace_events.append(event)

            response = st.write_stream(
                self._safe_final_stream(
                    agent,
                    model,
                    st.session_state.openrouter_session_id,
                    prepared,
                    record_final_trace,
                )
            )
            combined_trace = self._dedupe_trace(trace_events + prepared.trace)
            self._render_trace(combined_trace, prepared.sources)
            st.session_state.messages.append(
                ChatMessage(
                    role=ChatRole.ASSISTANT,
                    content=str(response),
                    trace=combined_trace,
                    sources=prepared.sources,
                    evidence=prepared.evidence,
                )
            )

    def _safe_final_stream(
        self,
        agent: OpenRouterLegalAgent,
        model: str,
        session_id: str,
        prepared: AgentTurnResult,
        on_trace: Callable[[TraceEvent], None],
    ) -> Iterator[str]:
        """Yield the final answer while converting runtime errors into text."""

        try:
            yield from agent.stream_final_answer(
                model=model,
                session_id=session_id,
                prepared_turn=prepared,
                on_trace=on_trace,
            )
        except Exception as exc:
            yield f"\n\n[LLM streaming failed] {type(exc).__name__}: {exc}"

    def _render_trace(self, trace: list[TraceEvent] | None, sources: list[str] | None) -> None:
        """Render saved tool traces and source labels below an assistant answer."""

        if trace:
            with st.expander("Tool calling status", expanded=False):
                for event in trace:
                    self._render_trace_event(event, st, collapse_payload=True)
        if sources:
            with st.expander("MCP calls used as sources", expanded=False):
                for source in sources:
                    self._render_jsonish(source)

    def _render_trace_event(self, event: TraceEvent, target: object, collapse_payload: bool) -> None:
        """Render one trace event as text plus optional JSON details.

        Background:
            MCP arguments and result excerpts should be available for audit, but
            large JSON payloads should not flood either the live status
            container or the saved trace below an answer. Both modes therefore
            use a named expander when `collapse_payload` is true.
        """

        target.write(event.title)
        if event.detail:
            target.caption(event.detail)
        if event.payload is not None:
            if collapse_payload:
                expander = getattr(target, "expander", st.expander)
                with expander("JSON details", expanded=False):
                    st.json(event.payload)
            else:
                target.json(event.payload)

    def _repo_relative_path(self, path: object) -> str:
        """Return a display path relative to the repository root when possible."""

        try:
            return str(path.relative_to(PROJECT_ROOT))  # type: ignore[attr-defined]
        except Exception:
            return str(path)

    def _render_jsonish(self, value: str) -> None:
        """Render a JSON string as a JSON block, with a text fallback."""

        try:
            st.json(json.loads(value))
        except Exception:
            st.code(value, language="json")

    def _dedupe_trace(self, events: list[TraceEvent]) -> list[TraceEvent]:
        """Preserve trace order while removing repeated live/saved events."""

        seen: set[str] = set()
        deduped: list[TraceEvent] = []
        for event in events:
            key = event.model_dump_json()
            if key not in seen:
                seen.add(key)
                deduped.append(event)
        return deduped

    def _coerce_message(self, value: object) -> ChatMessage:
        """Convert legacy dict session entries into the Pydantic message model.

        Background:
            Streamlit session state can survive code edits during development.
            This helper keeps reruns stable if an older dict-shaped message is
            still present in memory.
        """

        if isinstance(value, ChatMessage):
            return value
        if isinstance(value, dict):
            return ChatMessage.model_validate(value)
        return ChatMessage(role=ChatRole.ASSISTANT, content=str(value))


def run_app() -> None:
    """Public Streamlit entrypoint imported by ``main.py``."""

    StreamlitChatApp().run()
