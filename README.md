# ChatNoob

一个使用 [Rich](https://rich.readthedocs.io/) 渲染、带**本地持久记忆**与 **MCP 工具**的最简聊天机器人（DeepSeek），同时提供 FastAPI + SSE 的 HTTP 服务。

## 使用

```bash
uv sync
cp .env.example .env   # 填入 DEEPSEEK_API_KEY

uv run chatnoob         # 终端交互
uv run chatnoob-serve   # HTTP 服务 + 前端，默认 127.0.0.1:8000
```

环境变量 `CHATNOOB_HOST` / `CHATNOOB_PORT` 可以改监听地址。

## 测试

```bash
uv run --no-sync pytest --cov=chatnoob --cov-report=term-missing
```

测试在 `tests/`，覆盖全部 Python 模块（当前 100%）；不覆盖前端 JS。

## 网页界面

打开 `http://127.0.0.1:8000/`：

- 首页输入用户名「登录」（无鉴权，名字即身份）
- 左栏是该用户的会话列表，可新建、切换、删除
- 主区域是对话，助手回复通过 SSE 逐字流式显示，并按 Markdown 渲染（表格、列表、引用等）
- 代码块带语言标签与复制按钮，由 highlight.js 高亮；用户消息保持纯文本
- 回答里的相对链接会自动补全为 `https://docs.langchain.com/...`，不会指向本地服务
- 模型调用 MCP 工具时，工具名、参数和完成/失败状态显示在回答上方
- Markdown / 高亮 / 消毒库以静态文件放在 `src/chatnoob/static/vendor/`（版本见 `VENDOR.md`），无构建步骤、可离线

前端是原生 HTML/CSS/JS，放在 `src/chatnoob/static/`，由 FastAPI 直接托管，不需要构建步骤。

## HTTP API

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/chat` | `{user, session?, message}`，返回 SSE 流；省略 `session` 时用该用户最近活跃的会话 |
| POST | `/sessions` | `{user}`，新建会话，返回 `{session: n}` |
| GET | `/sessions?user=alice` | 列出会话：编号、消息数、最后活跃的 checkpoint |
| GET | `/sessions/{n}/history?user=alice&limit=10` | 最近若干条历史 |
| DELETE | `/sessions/{n}?user=alice` | 物理删除该会话 |
| GET | `/health` | 存活检查 |
| GET | `/` | 网页界面 |

SSE 事件：

```
event: start   data: {"session": 1}
event: token   data: {"text": "你"}
event: tool    data: {"id": "call_1", "name": "docs_search_docs_by_lang_chain", "input": {"query": "..."}, "status": "start"}
event: tool    data: {"id": "call_1", "name": "docs_search_docs_by_lang_chain", "status": "done"}
event: summary data: {"text": "较早的对话已压缩为摘要"}
event: done    data: {"session": 1, "reply": "...", "stats": {"duration_ms": 1200, "tool_calls": 2, "tokens": 3456}}
event: error   data: {"detail": "..."}
```

`tool` 事件在工具失败时 `status` 为 `error`，并带 `error` 字段；`done.stats` 是本次运行的耗时、工具调用次数与 token 用量（取不到用量时没有 `tokens`）。

不同用户/会话可以同时对话（`alice:1` 与 `bob:1` 是完全独立的线程）；同一个会话的并发请求用 `asyncio.Lock` 串行化，避免上下文互相覆盖。SQLite 已开启 WAL 并设置 `busy_timeout=30000`，多进程也只是排队。要跨机器横向扩展应换成 `langgraph-checkpoint-postgres`。

## 实现

- `init_chat_model("deepseek:deepseek-flash")` + `create_agent`，消息由 `MessagesState` 管理；通过 `extra_body` 关闭 DeepSeek 思考模式，降低首字延迟
- MCP 工具通过 `langchain.mcp.MCPAdapter` 加载，配置与 `opencode.json` 一致：
  - `docs` → `https://docs.langchain.com/mcp`（查 LangChain 文档）
  - `reference` → `https://reference.langchain.com/mcp`（查 API 参考）
  - 服务名会给工具加前缀（如 `docs_search_docs_by_lang_chain`）；启动时连不上则降级为纯聊天并打印警告
- `SqliteSaver` / `AsyncSqliteSaver` 把记忆落盘到 `~/.chatnoob/checkpoints.db`
- `thread_id` 形如 `alice:1`：一个用户下可以有多条会话，编号在用户内自增；旧版本留下的裸用户名会在启动时迁移成 `用户名:1`
- 新建但还没发消息的会话没有 checkpoint，编号记在 `chatnoob_sessions` 表里，保证列表能看到、编号不重复
- `SummarizationMiddleware` 的定制版：只在**新的用户轮次**开始时压缩历史（工具循环中途不压缩），避免当前问题被摘要掉；DeepSeek V4.1 Flash 有 1M 上下文，达到 600k tokens 才触发，保留最近 200k tokens
- 不限制工具调用次数，也不截断工具输出；复杂问题可以多次检索、交叉验证
- 模型与工具调用都带自动重试（网络抖动、限流），每次运行记录耗时、工具次数和 token 用量（SSE `done.stats`）
- `stream_events(..., version="v3")` 流式输出，CLI 用 Rich `Live` 实时渲染；工具调用与回答 token 并发消费
- 终端命令（CLI 固定使用每个用户的第 1 个会话）：
  - `/switch [用户]` 切换用户，无参数切回 `default`；输入提示会显示当前用户名
  - `/history [条数]` 打印当前用户最近的历史消息，无参数打印最近 10 条
  - `/clear [用户]` 物理删除该用户第 1 个会话的 checkpoint，无参数清理当前用户
  - `/exit` 退出

代码分布：`__init__.py`（CLI）、`agent.py`（模型、MCP 工具与中间件装配）、`middleware.py`（轮次感知摘要）、`stream.py`（统一消费 v3 流）、`store.py`（会话标识与枚举）、`api.py`（HTTP 服务）、`static/`（网页界面）。
