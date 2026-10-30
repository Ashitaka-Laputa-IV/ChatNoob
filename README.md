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
- `SqliteSaver` 把记忆落盘到 `~/.chatnoob/checkpoints.db`（进程重启后继续上次对话）
- 每个用户一条线程：用户名直接作为 `thread_id`，默认用户是 `default`
- `SummarizationMiddleware` 在历史超过 20 条消息时自动把较早对话摘要压缩，只保留最近 10 条；摘要单独以暗色面板打印，不混进回答
- `stream_events(..., version="v3")` 流式输出，Rich `Live` + `Markdown` 实时渲染
- 命令：
  - `/switch [用户]` 切换用户，无参数切回 `default`；输入提示会显示当前用户名
  - `/history [条数]` 打印当前用户最近的历史消息，无参数打印最近 10 条
  - `/clear [用户]` 物理删除该用户的 checkpoint，无参数清理当前用户
  - `/exit` 退出

代码只有 `src/chatnoob/__init__.py` 里的 `main()`。
