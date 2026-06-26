# Project Agent Instructions

## Project Intent

This repository is a demo baseline for a Korean legal-data RAG chatbot coding test.

Core direction:

- Python `>=3.14` with `uv`.
- Streamlit WebUI for a usable demo.
- OpenAI SDK standard Chat Completions tool calling through OpenRouter.
- Gemini 3.5 Flash by default via OpenRouter.
- Korean Law MCP as the live legal data layer.
- Multi-turn chat, streaming final answer, visible tool/status trace, and source labels.
- No web search inside the chatbot.
- No automated test-code implementation unless explicitly requested later; prioritize rapid demo implementation and practical validation.
- The 법제처 credential is stored as `MCP_API_KEY` in this repo's `.env`; the app must pass it to Korean Law MCP as upstream-compatible `LAW_OC`.

## Requirement Change Rule

When the user changes requirements, update `plan.md` before implementation.

The plan must reflect:

- The newest functional/non-functional requirements.
- Current architecture decisions.
- Persona/user-type policy.
- Any explicitly rejected approach.
- Current run and verification commands.

Do not continue coding after a requirement change until `plan.md` is synchronized.

## Commit And Push Rules

Follow `CONTRIBUTING.md` when the user asks for commits or pushes.

- Split commits into logical units with detailed commit messages.
- Inspect `git status --short` and relevant diffs before committing.
- Do not commit `.env`, `.streamlit/secrets.toml`, logs, API keys, tokens, private keys, or personal credentials.
- Keep `.env.sample` to empty placeholders and safe defaults only.
- Rewrite git history only when the user explicitly requests it. If rewriting history, use lease-aware force push.
- Before pushing, perform a lightweight secret check over tracked/staged content.

## Speed And Parallelism

Always consider parallel work at every step to maximize speed.

- Use parallel shell reads/searches where possible.
- Use parallel subagents aggressively for independent research, repo inspection, verification, or bounded implementation work.
- Keep subagent scopes disjoint and concrete.
- Do not duplicate a subagent's work in the main thread unless integration requires a quick check.

## Architecture Rules

- Avoid machine-specific absolute paths in code defaults and documentation.
- Prefer repository-relative paths such as `../korean-law-mcp` and resolve configurable relative paths from the repository root.
- Keep `main.py` as a small Streamlit entrypoint only.
- Split responsibilities by file:
  - `app/config.py`: Pydantic Settings and `.env` loading.
  - `app/models.py`: Pydantic v2 models and string enums.
  - `app/mcp_client.py`: MCP stdio transport.
  - `app/permissions.py`: persona policy enforcement.
  - `app/prompting.py`: Jinja2 prompt rendering.
  - `app/llm.py`: OpenAI SDK tool-calling loop.
  - `app/ui.py`: Streamlit UI.
  - `prompts/system.j2`: system prompt.
- Use Pydantic v2 for data models. Do not use dataclasses.
- Use `pydantic-settings` for environment configuration. Do not manually call `os.getenv` for app settings or use `python-dotenv` directly.
- Read the law.go.kr/MCP credential through `pydantic-settings`; prefer `MCP_API_KEY`, with `LAW_OC` and `KOREAN_LAW_API_KEY` only as compatibility aliases.
- Put prompts in `.j2` files, not inline Python strings.
- Keep prompt-like runtime injections in `prompts/*.j2` as well, including dynamic tool catalog context, custom instruction context, prior evidence context, tool re-entry checkpoint text, and final answer instructions.

## Tool-Calling Rules

- Do not define a custom wrapper tool such as `korean_law_mcp_call`.
- At each user turn, call the local MCP server's `list_tools()`.
- Convert the current MCP tool list directly into OpenAI Chat Completions `tools`.
- Let the LLM call actual MCP tool names directly.
- First tool-planning round should require tool use when tools are available.
- Later rounds should use `auto` so the LLM can continue or stop.
- Python must not use regex or keyword heuristics to infer user intent, tax topics, law names, article numbers, or case numbers.
- Python only validates persona permission and executes the model-selected MCP calls.

## Persona Policy

User type is a persona selector, not real auth:

- `general`: answer accessibly and prefer statutes/law text. If the user asks about tax law, keep answers law-centered and avoid specialist tax sources unless permitted by policy.
- `tax_accountant`: assume professional tax literacy. The LLM should actively use specialist sources when useful, including tax tribunal decisions, customs/NTS interpretations, amendment history, applicable-law checks, citation verification, chain tools, and full text where allowed.

Policy enforcement belongs in `app/permissions.py`.

## Documentation And Comments

- Add detailed English docstrings for classes and methods.
- Explain intent, background, and function where useful.
- Keep implementation comments useful and sparse; prefer docstrings for module/class/method intent.
- After implementation changes, always consider whether `README.md` needs to be updated.
- Keep `README.md` compact and friendly for a first-time reader. Avoid unnecessary internal jargon.
- README diagrams should be limited to a flow chart and a sequence diagram. Do not add a separate architecture diagram unless the user explicitly changes this rule.
- When flow or request sequencing changes, update those README Mermaid diagrams so they match the implemented app.

## Verification

Demo delivery is the priority. Keep verification lightweight and evidence-oriented:

- Do not add unit test files, integration test files, fixtures, mocks, or test frameworks unless the user explicitly asks.
- Do not expand the `tests/` directory into automated tests; `tests/*.md` are manual sample prompts only.
- Prefer compile checks, Streamlit boot checks, MCP smoke checks, log inspection, and manual chatbot queries.
- Temporary one-off shell/Python snippets are acceptable for debugging, but do not commit them as test code.
- When a bug fix needs evidence, explain the manual or smoke verification performed instead of building a test suite.

Preferred commands:

```bash
uv run python -m py_compile main.py app/*.py
uv run streamlit run main.py --server.headless true
```

Manual prompt verification should use `tests/*.md` samples or a user-provided query pasted into the Streamlit UI.
