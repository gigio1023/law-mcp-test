# Legal RAG Chatbot Baseline Plan

## Goal

Build a coding-test baseline for a Korean legal-data RAG chatbot:

- Python `>=3.14` managed by `uv`
- Role-separated Python modules; `main.py` is only the Streamlit entrypoint
- Streamlit WebUI using open-source chat/status components
- Streamlit file watching accelerated by the open-source `watchdog` package
- OpenAI SDK client pointed at OpenRouter
- Default model: `google/gemini-3.5-flash`
- Korean Law MCP as the legal data layer
- Multi-turn chat, streaming answer, source display, and user-type based document scope
- No web search inside the chatbot
- No test-code implementation; demo app only

## Assumptions

- Optional external repositories are referenced only by repository-relative paths such as `../korean-law-mcp`.
- Korean Law MCP is available at `../korean-law-mcp` by default, or another relative path set with `KOREAN_LAW_MCP_DIR`, and is built with `npm run build`.
- Legal data calls require the 법제처 key stored as `MCP_API_KEY` in `.env`; `LAW_OC` and `KOREAN_LAW_API_KEY` remain compatibility aliases.
- OpenRouter calls require `OPENROUTER_API_KEY`.
- Authentication/authorization is intentionally not implemented; user persona is a UI/runtime selector.

## Change Management Rule

When requirements change, update this `plan.md` before implementation. This keeps the demo target, architecture, and known tradeoffs synchronized with the newest user request.

## Current Requirement Update

- Prepare a clean, logical git history and push it:
  - Add `CONTRIBUTING.md` with commit hygiene, history rewrite, and secret-safety rules.
  - Update `AGENTS.md` so future commit work follows `CONTRIBUTING.md`.
  - Before committing or pushing, verify `.env` and other local secrets are not tracked or staged.
  - Rebuild the branch history into clear logical commits because the user explicitly requested replacing the existing commit log.
  - Push the rewritten `main` branch with a lease-aware force push.
- Remove local absolute paths from code-facing defaults and project documentation:
  - Do not document machine-specific paths.
  - Prefer repository-relative paths such as `../korean-law-mcp` or `docs/...`.
  - Interpret configurable relative paths from the repository root.
- Make optimized defaults explicit:
  - Default maximum tool-calling/planning iterations is `MAX_TOOL_ROUNDS=10`.
  - Prefix caching is always enabled in code through stable system `cache_control` plus OpenRouter `session_id`; it is no longer an optional env switch.
  - Keep evidence-memory settings configurable, but ship tuned defaults in `.env.sample` and README.
- Move prompt-like runtime injections out of Python and into Jinja2 templates:
  - Tool catalog context, custom instruction context, prior evidence context, re-entry checkpoint, and final answer instruction live under `prompts/*.j2`.
  - Python only chooses which template to render and supplies structured variables.
  - When max iterations are exhausted, the final-answer instruction must explicitly tell the model that not all useful information may have been found, but the answer should start because fixed cost/latency limits have been reached.
- Keep verification demo-first and lightweight:
  - Do not add automated test code, unit test files, fixtures, or test frameworks.
  - Prefer compile checks, app boot checks, log inspection, and manual chatbot prompts from `tests/*.md`.
  - Use temporary one-off smoke snippets only for immediate debugging; do not commit them as test code.
- Diagnose and fix the case where MCP calls finish but no final answer appears:
  - Add file-based `loguru` diagnostics around planning rounds, MCP calls, final streaming chunks, finish reasons, usage, and fallback behavior.
  - Detect an empty final streaming response and retry once with a non-streaming final answer request using the same prepared messages.
  - Surface the fallback path in the Streamlit trace so UI behavior matches the log file.
  - Keep generated logs out of git via `.gitignore`.
- Improve Streamlit live tool status readability:
  - Wrap live JSON payloads in collapsed/controlled detail containers instead of dumping large raw JSON blocks directly into the status container.
  - Preserve full JSON auditability while avoiding a huge visible body during normal query execution.
- Improve multi-turn context preservation and prefix-cache friendliness:
  - Preserve model-visible MCP evidence across turns instead of only keeping final assistant text.
  - Carry recent tool-call evidence as structured text context for follow-up reasoning.
  - Compact older tool evidence into a stable bounded JSON block instead of endlessly replaying all raw results.
  - Keep large stable prompt context cacheable and move dynamic context into later messages where possible.
  - Add an OpenRouter `session_id` per Streamlit session so provider sticky routing can keep prompt caches warm across turns.
  - Always add Gemini/OpenRouter `cache_control` on the stable system content block.
  - Surface prompt-cache usage metadata in the status trace when the provider returns it.
- Make MCP tool execution transparent in Streamlit:
  - Show every model-selected MCP tool name.
  - Show full MCP call arguments as formatted JSON in the status container.
  - Show blocked/error/completed state clearly.
  - Keep source/evidence expanders JSON-friendly so the user can audit intermediate retrieval, not only final answers.
  - In the final saved "Tool calling status" log below an answer, keep JSON details collapsed by default instead of expanding every payload.
- Treat `.env` key `MCP_API_KEY` as the primary 법제처 API key for Korean Law MCP.
- Pass the effective 법제처 key into the MCP subprocess as `LAW_OC`, because Korean Law MCP expects that environment variable.
- Verify that the local MCP server starts, `list_tools()` returns the actual tool catalog, and that catalog is injected into OpenAI `tools` plus the dynamic runtime context message after the stable system prompt.
- Remove genuinely unused code while preserving the direct MCP-tool architecture.
- Expand English docstrings/comments around MCP startup, live tool-catalog injection, and OpenAI standard tool-calling flow.
- Add Streamlit's recommended `watchdog` dependency through `uv` and set project-local `server.fileWatcherType = "watchdog"` so local file watching uses watchdog during demo runs.
- After implementation work, update `README.md` with compact beginner-friendly documentation. README should include only a Mermaid flow chart diagram and a Mermaid sequence diagram as diagrams.
- README diagram policy update: keep only a flow chart diagram and a sequence diagram as visual diagrams; remove the architecture diagram from README.
- Update `AGENTS.md` so future implementation work always considers README documentation updates.
- When the tool-calling phase appears ready to stop, insert one LLM-controlled auto tool-calling checkpoint. The checkpoint should provide context and let the model decide whether to re-enter MCP tool calling or proceed to final answer, without regex or keyword heuristics.
- Include `tests/*.md` in the repository as manual sample prompts that can be pasted into the chatbot. These are not automated test code.

## Streamlit UI Plan

Based on the cloned Streamlit docs at `../streamlit-dirs/docs`:

- Use `st.session_state.messages` for multi-turn history.
- Render history with `st.chat_message`.
- Capture input with `st.chat_input`.
- Stream the final answer with `st.write_stream`.
- Show retrieval/tool activity with `st.status`.
- Persist assistant trace and source lists in message history so they survive reruns.
- Do not nest chat message containers or status containers.

Key local references:

- Chat tutorial: `../streamlit-dirs/docs/content/develop/tutorials/llms/conversational-apps.md`
- Chat message/input API docs: `../streamlit-dirs/docs/content/develop/api-reference/chat/`
- Streaming docs: `../streamlit-dirs/docs/content/develop/api-reference/write-magic/write_stream.md`
- Status docs: `../streamlit-dirs/docs/content/develop/api-reference/status/status.md`

## Korean Law MCP Function Map

The chatbot uses MCP stdio and reads the current tool list from the local MCP server every turn:

```bash
node ../korean-law-mcp/build/index.js
```

The server advertises 9 tools via `list_tools()`. Those actual MCP tools are converted directly into OpenAI Chat Completions `tools`, so the LLM calls real MCP tool names such as `search_law` and `legal_research`. No custom `korean_law_mcp_call` wrapper is used.

The server can still execute hidden tools by name. Therefore, scope control is enforced in Python before MCP execution.

| Tool | Main args | Chatbot use | General user | Tax accountant |
|---|---|---|---:|---:|
| `search_law` | `query`, `display` | Find law candidates and `mst` | Yes | Yes |
| `get_law_text` | `mst`/`lawId`, `jo`, `efYd` | Fetch exact article after search | Yes | Yes |
| `get_annexes` | `lawName` | Forms, fee tables, annexes | Yes | Yes |
| `search_decisions` | `domain`, `query`, `display` | Precedents and interpretations | Core domains | Tax-specialist domains too |
| `get_decision_text` | `domain`, `id`, `full` | Decision text | Compact only | Full allowed |
| `legal_research` | `task`, `query`, `scenario`, `text` | Chain-style broad research | Law-centered tasks | All tasks |
| `legal_analysis` | `mode`, mode args | Citation/case/date checks | Basic verification/date modes | All modes |
| `discover_tools` | `intent` | Hidden tool discovery | No | Yes |
| `execute_tool` | `tool_name`, `params` | Hidden tool proxy | No | Tax-accountant allowlist |

General-user decision domains:

```text
precedent, interpretation, constitutional, admin_appeal
```

Tax-accountant adds specialist domains:

```text
tax_tribunal, customs, nts, ftc, pipc, nlrc, acr,
appeal_review, acr_special, treaty, english_law
```

Tax-accountant hidden-tool allowlist starts with:

```text
search_admin_rule, get_admin_rule, search_ordinance, get_ordinance,
get_article_detail, get_batch_articles, get_article_with_precedents,
compare_old_new, get_three_tier, compare_articles, get_article_history,
get_law_history, search_historical_law, get_historical_law,
search_all, advanced_search, suggest_law_names, parse_jo_code,
search_tax_tribunal_decisions, search_customs_interpretations
```

## Retrieval Strategy

For each user message:

1. Start the local Korean Law MCP server over stdio.
2. Call `list_tools()` and convert current MCP tool schemas directly into OpenAI `tools`.
3. Render a stable cacheable system prompt from `prompts/system.j2` with persona policy, local `MCP.md` context, and durable operating rules.
4. Add dynamic context messages after the stable system prompt:
   - current MCP tool catalog from `list_tools()`
   - custom instruction
   - compacted prior MCP evidence
   - recent raw prior MCP evidence
   - visible user/assistant chat history
5. Ask the LLM to select tools using OpenAI standard tool calling with `parallel_tool_calls=True`. First round uses required tool choice; later rounds use auto.
6. Validate each model-selected MCP call with persona policy.
7. Show each selected MCP call and its arguments in the Streamlit status container as structured JSON.
8. Execute allowed MCP calls over stdio and append results as standard OpenAI `role="tool"` messages for the current turn.
9. Persist bounded MCP evidence from the current turn on the assistant message so later turns can reason over prior retrieval.
10. If an auto planning round stops requesting tools, add one checkpoint message and re-enter OpenAI tool calling with `tool_choice="auto"` so the LLM can decide whether more MCP calls are useful.
11. Repeat up to `MAX_TOOL_ROUNDS`, which defaults to 10 planning/tool iterations.
12. Append an explicit final-answer instruction from `prompts/final_answer_instruction.j2` so the final model request does not end immediately after a tool result. If max iterations were exhausted, include the cost/latency bounded-answer notice.
13. Stream the final Gemini answer without tools, grounded by current and preserved prior MCP evidence.
14. If final streaming returns no text, retry once with a non-streaming final request and log both attempts for debugging.

No Python natural-language heuristics:

- No regex intent parsing.
- No keyword-based tax detection.
- No Python-side tool planning.
- The LLM decides whether tax, precedent, interpretation, statute, or specialist material is useful.

Persona behavior:

- General user: if asking about tax law, the prompt instructs the model to prefer statutes and law text first, using basic precedents/interpretations only when helpful.
- Tax accountant: the prompt instructs the model to actively use specialist sources such as tax tribunal decisions, customs/NTS interpretations, amendment history, applicable-law checks, and full text when useful.

## Module Layout

```text
main.py                  Streamlit entrypoint only
app/config.py            Pydantic Settings model; reads .env
app/models.py            Pydantic v2 data models and string enums
app/mcp_client.py        MCP stdio list_tools/call_tool transport
app/permissions.py       Persona policy for model-selected MCP calls
app/prompting.py         Jinja2 prompt renderer
app/llm.py               OpenAI SDK tool-calling loop
app/ui.py                Streamlit chat/status UI
prompts/*.j2             System prompt and runtime prompt-injection templates
.streamlit/config.toml   Streamlit local runtime config
AGENTS.md                Project-specific working rules
```

## Implementation Constraints

- Data models use Pydantic v2 `BaseModel` only.
- Do not use `dataclass`.
- Runtime settings and `.env` values are read through `pydantic-settings`.
- Do not call `python-dotenv` directly.
- Do not use manual natural-language heuristics such as regex intent parsing or keyword-based tax detection.
- Prompts live in `.j2` files.
- Preserve MCP evidence with Pydantic models, not raw ad hoc dicts.
- Bound retained evidence by settings so a long Streamlit session does not grow the prompt without limit.

## Run

```bash
uv run streamlit run main.py
```

Environment:

```bash
OPENROUTER_API_KEY=...
MCP_API_KEY=...
# optional
LAW_OC=...
KOREAN_LAW_API_KEY=...
OPENROUTER_MODEL=google/gemini-3.5-flash
KOREAN_LAW_MCP_DIR=../korean-law-mcp
RECENT_TOOL_CONTEXT_TURNS=2
MAX_TOOL_EVIDENCE_CHARS=6000
MAX_COMPACTED_EVIDENCE_CHARS=12000
MAX_TOOL_ROUNDS=10
LOG_LEVEL=INFO
LOG_FILE=logs/chatbot-debug.log
```

## Verification Plan

- `uv run python -m py_compile main.py`
- `uv run python -m py_compile main.py app/*.py`
- `uv run python -c "import watchdog; print('watchdog installed')"`
- `uv run streamlit run main.py --server.headless true`
- Verify live tool injection: start MCP over stdio, call `list_tools()`, convert the returned tools into OpenAI tool definitions, and add the same catalog as a dynamic runtime context message after the stable system prompt.
- Verify multi-turn evidence preservation: previous assistant MCP evidence is included in later planning/final messages as bounded structured context, while old evidence is compacted.
- Verify OpenRouter request options include a stable `session_id`; when usage metadata is returned, cache read/write token counts appear in the status trace.
- Verify Streamlit trace events include formatted JSON arguments for MCP calls and JSON source/evidence details.
- Verify live and saved Streamlit traces keep large JSON payloads folded under `JSON details`.
- Verify `logs/chatbot-debug.log` captures planning, MCP execution, final streaming, and fallback diagnostics.
- Optional smoke test with `MCP_API_KEY`: ask "민법 제750조 불법행위 요건 알려줘".
- Do not add automated test files for this demo unless explicitly requested later.
- `tests/*.md` are manually runnable sample legal/tax questions, not automated tests.

## Known Limits

- No persistent auth, accounts, or audit log.
- No vector index; this baseline performs live model-selected MCP retrieval.
- Source quality depends on Korean Law MCP and law.go.kr availability.
- If `MCP_API_KEY`, `LAW_OC`, and `KOREAN_LAW_API_KEY` are all missing, the UI still runs but 법제처-backed retrieval will fail or return no live legal data.
- This demo uses bounded evidence memory rather than replaying every raw MCP result forever. That keeps legal context useful while avoiding unbounded prompt growth and cache-window pressure.
