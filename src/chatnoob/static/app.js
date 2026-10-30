const state = { user: null, session: null, sessions: [], sending: false };

const el = (id) => document.getElementById(id);
const loginView = el("login");
const appView = el("app");
const messagesView = el("messages");

function showApp() {
  loginView.classList.add("hidden");
  appView.classList.remove("hidden");
}

async function api(path, options) {
  const res = await fetch(path, options);
  if (!res.ok) {
    let detail = res.statusText;
    try {
      detail = (await res.json()).detail ?? detail;
    } catch {}
    throw new Error(detail);
  }
  return res;
}

/* ---------- 侧栏 ---------- */

async function loadSessions() {
  const res = await api(`/sessions?user=${encodeURIComponent(state.user)}`);
  state.sessions = await res.json();
  renderSessions();
}

function renderSessions() {
  const list = el("session-list");
  list.replaceChildren();
  for (const item of state.sessions) {
    const li = document.createElement("li");
    if (item.session === state.session) li.classList.add("active");

    const name = document.createElement("button");
    name.className = "session-name";
    name.textContent = `会话 ${item.session}`;
    const meta = document.createElement("small");
    meta.textContent = `${item.messages} 条`;
    name.append(meta);
    name.onclick = () => selectSession(item.session);

    const remove = document.createElement("button");
    remove.className = "session-delete";
    remove.textContent = "×";
    remove.title = "删除会话";
    remove.onclick = () => deleteSession(item.session);

    li.append(name, remove);
    list.append(li);
  }
}

/* ---------- 会话 ---------- */

async function selectSession(session) {
  state.session = session;
  localStorage.setItem(`chatnoob_session_${state.user}`, String(session));
  renderSessions();
  await loadHistory();
}

async function loadHistory() {
  messagesView.replaceChildren();
  if (state.session === null) return;
  const res = await api(
    `/sessions/${state.session}/history?user=${encodeURIComponent(state.user)}&limit=100`,
  );
  const data = await res.json();
  for (const message of data.messages) addMessage(message.role, message.text);
}

async function createSession() {
  const res = await api("/sessions", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ user: state.user }),
  });
  const { session } = await res.json();
  await loadSessions();
  await selectSession(session);
}

async function deleteSession(session) {
  if (!confirm(`删除会话 ${session}？历史将无法恢复。`)) return;
  await api(`/sessions/${session}?user=${encodeURIComponent(state.user)}`, {
    method: "DELETE",
  });
  if (session === state.session) state.session = null;
  await loadSessions();
  if (state.sessions.length === 0) {
    await createSession();
  } else if (state.session === null) {
    await selectSession(state.sessions[state.sessions.length - 1].session);
  }
}

/* ---------- 消息渲染 ---------- */

const LABELS = { user: () => state.user, assistant: "ChatNoob", summary: "摘要", tool: "工具", system: "系统" };

function addMessage(role, text) {
  const wrap = document.createElement("div");
  wrap.className = `msg ${role}`;

  const who = document.createElement("span");
  who.className = "who";
  const label = LABELS[role] ?? role;
  who.textContent = typeof label === "function" ? label() : label;

  const body = document.createElement("div");
  body.className = "body";
  body.textContent = text;

  wrap.append(who, body);
  messagesView.append(wrap);
  messagesView.scrollTop = messagesView.scrollHeight;
  return body;
}

/* ---------- SSE ---------- */

function handleFrame(frame, body) {
  let event = "message";
  let data = "";
  for (const line of frame.split("\n")) {
    if (line.startsWith("event:")) event = line.slice(6).trim();
    else if (line.startsWith("data:")) data += line.slice(5).trim();
  }
  if (!data) return;
  const payload = JSON.parse(data);
  if (event === "token") {
    body.textContent += payload.text;
    messagesView.scrollTop = messagesView.scrollHeight;
  } else if (event === "summary") {
    addMessage("summary", payload.text);
  } else if (event === "done" && state.session === null) {
    state.session = payload.session;
    renderSessions();
  } else if (event === "error") {
    body.textContent = `出错了：${payload.detail}`;
  }
}

async function send(text) {
  if (state.sending || !text.trim()) return;
  state.sending = true;
  addMessage("user", text);
  const body = addMessage("assistant", "");
  body.parentElement.classList.add("streaming");

  try {
    const res = await api("/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        user: state.user,
        session: state.session,
        message: text,
      }),
    });
    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      let index;
      while ((index = buffer.indexOf("\n\n")) >= 0) {
        handleFrame(buffer.slice(0, index), body);
        buffer = buffer.slice(index + 2);
      }
    }
    messagesView.scrollTop = messagesView.scrollHeight;
  } catch (error) {
    body.textContent = `出错了：${error.message}`;
  } finally {
    body.parentElement.classList.remove("streaming");
    state.sending = false;
    loadSessions();
  }
}

/* ---------- 启动 ---------- */

async function enter(name) {
  state.user = name;
  localStorage.setItem("chatnoob_user", name);
  el("current-user").textContent = name;
  el("login-name").value = "";
  showApp();
  await loadSessions();
  const stored = Number(localStorage.getItem(`chatnoob_session_${name}`));
  const target = state.sessions.find((item) => item.session === stored);
  if (target) await selectSession(target.session);
  else if (state.sessions.length > 0) await selectSession(state.sessions[0].session);
  else await createSession();
}

el("login-form").addEventListener("submit", (event) => {
  event.preventDefault();
  const name = el("login-name").value.trim();
  if (!name) return;
  if (name.includes(":")) {
    alert("用户名不能包含 ':'");
    return;
  }
  enter(name).catch((error) => alert(error.message));
});

el("logout").addEventListener("click", () => {
  localStorage.removeItem("chatnoob_user");
  location.reload();
});

el("new-session").addEventListener("click", () => {
  createSession().catch((error) => alert(error.message));
});

el("chat-form").addEventListener("submit", (event) => {
  event.preventDefault();
  const input = el("chat-input");
  const text = input.value;
  if (!text.trim()) return;
  input.value = "";
  input.style.height = "auto";
  send(text);
});

el("chat-input").addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    el("chat-form").requestSubmit();
  }
});

const remembered = localStorage.getItem("chatnoob_user");
if (remembered) enter(remembered).catch((error) => alert(error.message));
