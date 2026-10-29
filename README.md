# ChatNoob

一个使用 [Rich](https://rich.readthedocs.io/) 渲染、带**内存记忆**的最简聊天机器人（DeepSeek）。

## 使用

```bash
uv sync
cp .env.example .env   # 填入 DEEPSEEK_API_KEY
uv run chatnoob
```

## 实现

- `init_chat_model("deepseek:deepseek-chat")` + `create_agent`，消息由 `MessagesState` 管理
- `InMemorySaver` 提供内存记忆（按 `thread_id` 保存，进程退出即清空）
- `stream_events(..., version="v3")` 流式输出，Rich `Live` + `Markdown` 实时渲染
- 命令：`/clear` 换新 `thread_id` 清空记忆，`/exit` 退出

代码只有 `src/chatnoob/__init__.py` 里的 `main()`。
