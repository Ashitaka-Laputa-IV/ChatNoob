# AGENTS.md

ChatNoob is a Python 3.14 project managed with `uv` (package `chatnoob`, layout `src/chatnoob`). Early stage: no tests or linters.

## Commands

`.venv` is local and git-ignored.

- Run CLI: `uv run chatnoob`
- Run server: `uv run chatnoob-serve` (FastAPI + SSE on `127.0.0.1:8000`, override with `CHATNOOB_HOST` / `CHATNOOB_PORT`)
- Sync: `uv sync`
- Add dependency: `uv add <package>`
- Pin interpreter: `uv venv --python 3.14`
- Test: `uv run --no-sync pytest --cov=chatnoob --cov-report=term-missing`（`chatnoob-serve` 占用 exe 时也能跑；首次先 `uv sync`。Python 覆盖率 100%，保持住）

## Conventions

- Add packages with `uv add` (updates `pyproject.toml` and `uv.lock`); don't edit them by hand.
- Keep committed files LF (`.gitattributes` is `* text=auto`) to avoid CRLF churn.
- Secrets live in git-ignored `.env` (`DEEPSEEK_API_KEY`); keep `.env.example` empty.
- Verify proportionately: one quick run that proves the feature works.

## Shell quirks

The shell splits arguments on spaces even inside quotes, and the quote characters leak into the first token. So `uv run python -c "import sys"` fails (`SyntaxError: unterminated string literal`), `git commit -m "my msg"` leaks words into pathspecs, and `rg "two words"` truncates the pattern.

- Pipe multi-word code through stdin; this needs no writes, so it is the only option in plan mode:
  - `echo import sys; print(sys.version) | uv run python -`
  - `echo print('a b') | uv run python -`
  - Multi-line: `echo exec('import sys\nprint(sys.version)') | uv run python -`
- Otherwise write a temp file in `C:\Users\Ashit\AppData\Local\Temp\opencode\` (no spaces) and run `uv run python <path>`; delete it after.
- Git: write the message to a temp file, then `git commit -F <file>`.
- Never retry a failed command with different quote styles; switch to a pipe or a file.
- Piped code must avoid `|`, `<`, `>`, `&`, `%`, `^`; a leading `(` is cmd grouping and fails.

## Documentation lookup

LangChain docs MCP servers are configured in `opencode.json` (`docs-langchain`, `reference-langchain`).

- Query them before relying on memory for LangChain/LangGraph/LangSmith usage or versions, and cite the page.
- Report wrong or outdated pages through `submit_feedback`.
