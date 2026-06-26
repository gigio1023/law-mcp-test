# Contributing

This repository is a fast demo baseline. Keep changes focused, auditable, and safe to push.

## Commit Style

- Split commits by logical concern, not by editing session.
- Use detailed commit messages with a concise subject and a body explaining intent, important implementation choices, and verification.
- Do not mix unrelated code, documentation, dependency, and sample-prompt changes unless they are one coherent change.
- Before committing, inspect `git status --short` and the relevant `git diff`.
- If the user explicitly asks to rewrite history, rebuild clean commits and push with `--force-with-lease`. Otherwise, avoid history rewrites.

## Secret Safety

- Never commit `.env`, `.streamlit/secrets.toml`, API keys, tokens, private keys, personal credentials, or local-only logs.
- Keep `.env.sample` limited to empty placeholders and non-secret defaults.
- Before pushing, check tracked files and staged diffs for secrets.
- Generated logs belong under `logs/` and must stay ignored.

## Verification

- This project prioritizes a working demo over a large automated test suite.
- Prefer lightweight verification: Python compile checks, Streamlit boot/health checks, MCP smoke checks, log inspection, and manual prompts from `tests/*.md`.
- Do not add unit/integration test files, fixtures, mocks, or test frameworks unless explicitly requested.

## Documentation

- Update `plan.md` before implementing changed requirements.
- Update `README.md` when setup, runtime flow, diagrams, or user-facing behavior changes.
- Keep prompt-like LLM instructions in `prompts/*.j2`, not inline Python strings.
