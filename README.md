# ChatNoob

一个使用 [Rich](https://rich.readthedocs.io/) 渲染、带**本地持久记忆**的最简聊天机器人（DeepSeek）。

## 使用

```bash
uv sync
cp .env.example .env   # 填入 DEEPSEEK_API_KEY
uv run chatnoob
```

## 实现

- `init_chat_model("deepseek:deepseek-chat")` + `create_agent`，消息由 `MessagesState` 管理
- `SqliteSaver` 把记忆落盘到 `~/.chatnoob/checkpoints.db`（固定 `thread_id="default"`，进程重启后继续上次对话）
- `SummarizationMiddleware` 在历史超过 20 条消息时自动把较早对话摘要压缩，只保留最近 10 条；摘要单独以暗色面板打印，不混进回答
- `stream_events(..., version="v3")` 流式输出，Rich `Live` + `Markdown` 实时渲染
- 命令：`/clear` 物理删除本地 checkpoint 清空记忆，`/exit` 退出

代码只有 `src/chatnoob/__init__.py` 里的 `main()`。
