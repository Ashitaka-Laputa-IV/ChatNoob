# ChatNoob

一个使用 [Rich](https://rich.readthedocs.io/) 渲染、带**本地持久记忆**的最简聊天机器人（DeepSeek），同时提供 FastAPI + SSE 的 HTTP 服务。

## 使用

```bash
uv sync
cp .env.example .env   # 填入 DEEPSEEK_API_KEY

uv run chatnoob         # 终端交互
uv run chatnoob-serve   # HTTP 服务 + 前端，默认 127.0.0.1:8000
```

环境变量 `CHATNOOB_HOST` / `CHATNOOB_PORT` 可以改监听地址。

## 网页界面

打开 `http://127.0.0.1:8000/`：

- 首页输入用户名「登录」（无鉴权，名字即身份）
- 左栏是该用户的会话列表，可新建、切换、删除
- 主区域是对话，助手回复通过 SSE 逐字流式显示，并按 Markdown 渲染（表格、列表、引用等）
- 代码块带语言标签与复制按钮，由 highlight.js 高亮；用户消息保持纯文本
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
event: summary data: {"text": "较早的对话已压缩为摘要"}
event: done    data: {"session": 1, "reply": "..."}
event: error   data: {"detail": "..."}
```

不同用户/会话可以同时对话（`alice:1` 与 `bob:1` 是完全独立的线程）；同一个会话的并发请求用 `asyncio.Lock` 串行化，避免上下文互相覆盖。SQLite 已开启 WAL 并设置 `busy_timeout=30000`，多进程也只是排队。要跨机器横向扩展应换成 `langgraph-checkpoint-postgres`。

## 实现

- `init_chat_model("deepseek:deepseek-chat")` + `create_agent`，消息由 `MessagesState` 管理
- `SqliteSaver` / `AsyncSqliteSaver` 把记忆落盘到 `~/.chatnoob/checkpoints.db`
- `thread_id` 形如 `alice:1`：一个用户下可以有多条会话，编号在用户内自增；旧版本留下的裸用户名会在启动时迁移成 `用户名:1`
- 新建但还没发消息的会话没有 checkpoint，编号记在 `chatnoob_sessions` 表里，保证列表能看到、编号不重复
- `SummarizationMiddleware` 在历史超过 20 条消息时自动把较早对话摘要压缩，只保留最近 2 条；摘要单独输出，不混进回答
- `stream_events(..., version="v3")` 流式输出，CLI 用 Rich `Live` 实时渲染
- 终端命令（CLI 固定使用每个用户的第 1 个会话）：
  - `/switch [用户]` 切换用户，无参数切回 `default`；输入提示会显示当前用户名
  - `/history [条数]` 打印当前用户最近的历史消息，无参数打印最近 10 条
  - `/clear [用户]` 物理删除该用户第 1 个会话的 checkpoint，无参数清理当前用户
  - `/exit` 退出

代码分布：`__init__.py`（CLI）、`agent.py`（模型与中间件）、`store.py`（会话标识与枚举）、`api.py`（HTTP 服务）、`static/`（网页界面）。
