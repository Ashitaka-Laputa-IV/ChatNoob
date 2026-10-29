# AGENTS.md

## Repository status

ChatNoob is a Python 3.14 project managed with `uv` (package `chatnoob`, layout `src/chatnoob`). It is early stage: a single `main()` entry point and no tests or linters yet.

## Commands

Environment is managed with `uv`; `.venv` is local and git-ignored.

- Install/sync dependencies: `uv sync`
- Run the app: `uv run chatnoob`
- Add a dependency: `uv add <package>`
- Pin the interpreter: `uv venv --python 3.14`
- Test: none configured yet
- Lint/format: none configured yet
- Typecheck: none configured yet

Do not invent build/test/lint commands. Once tests or linters are added, record the exact commands here, including how to run a single test.

## Conventions

- `.gitattributes` uses `* text=auto`, so Git normalizes text files to LF in the index. Keep committed files LF and avoid introducing CRLF churn.
- Python dependencies are declared in `pyproject.toml` and locked in `uv.lock`; add packages with `uv add` rather than editing by hand.
- Secrets live in `.env` (git-ignored, holds `DEEPSEEK_API_KEY`). Never commit real keys; keep `.env.example` as the template with empty values.
- Keep verification proportionate: a single quick run that proves the feature works is enough; don't add tests or defensive checks nobody asked for.
- The shell here strips double quotes from arguments, so `git commit -m "msg"` fails. Write the message to a temp file and run `git commit -F <file>`.

## Documentation lookup

The project has the official LangChain docs MCP server configured (`docs-langchain` in `opencode.json`, endpoint `https://docs.langchain.com/mcp`).

- When a task involves LangChain, LangGraph, or LangSmith usage or configuration, query this MCP first instead of relying on memory.
- Prefer its returned content over prior knowledge for version-sensitive details, and mention the relevant docs page when answering.
- Report inaccurate or outdated pages via the server's `submit_feedback` tool.
