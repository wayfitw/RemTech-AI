import { useEffect, useRef, useState } from "react";
import { api, getToken, clearToken, openSocket, fileUrl } from "./api.js";
import { Toaster, toast } from "sonner";
import AdminPanel from "./AdminPanel.jsx";
import Markdown from "./Markdown.jsx";
import logo from "./assets/logo.svg";

function extractText(content) {
  if (typeof content === "string") return content;
  if (Array.isArray(content)) {
    return content
      .filter((b) => b && b.type === "text")
      .map((b) => b.text)
      .join("\n");
  }
  return "";
}

function clearAppCache() {
  if (!window.confirm("Очистить локальный кеш и перезагрузить страницу? Вход сохранится.")) return;
  const token = localStorage.getItem("token");
  const theme = localStorage.getItem("theme");
  localStorage.clear();
  if (token) localStorage.setItem("token", token);
  if (theme) localStorage.setItem("theme", theme);
  location.reload();
}

const EXAMPLES = [
  { icon: "ti-file-text", text: "Составить коммерческое предложение" },
  { icon: "ti-search", text: "Найти цены на запчасти" },
  { icon: "ti-edit", text: "Отредактировать документ" },
  { icon: "ti-photo", text: "Сгенерировать изображение" },
];

function useTheme() {
  const [theme, setTheme] = useState(() => localStorage.getItem("theme") || "dark");
  useEffect(() => {
    document.documentElement.setAttribute("data-theme", theme);
    localStorage.setItem("theme", theme);
  }, [theme]);
  const toggle = () => setTheme((t) => (t === "dark" ? "light" : "dark"));
  return { theme, toggle };
}

function ThemeToggle({ theme, onToggle, className = "" }) {
  return (
    <button
      className={"theme-toggle " + className}
      onClick={onToggle}
      aria-label="Сменить тему"
      title={theme === "dark" ? "Светлая тема" : "Тёмная тема"}
    >
      <i className={theme === "dark" ? "ti ti-sun" : "ti ti-moon"} />
    </button>
  );
}

export default function App() {
  const [authed, setAuthed] = useState(!!getToken());
  const { theme, toggle } = useTheme();
  return (
    <>
      <Toaster theme={theme} position="top-center" closeButton />
      {!authed ? (
        <Login onLogin={() => setAuthed(true)} theme={theme} onToggleTheme={toggle} />
      ) : (
        <Chat
          onLogout={() => { clearToken(); setAuthed(false); }}
          theme={theme}
          onToggleTheme={toggle}
        />
      )}
    </>
  );
}

function Login({ onLogin, theme, onToggleTheme }) {
  const [mode, setMode] = useState("login"); // login | register
  const [fullName, setFullName] = useState("");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [show, setShow] = useState(false);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [regOpen, setRegOpen] = useState(false);

  useEffect(() => {
    api.authStatus().then((s) => setRegOpen(!!s.registration_open)).catch(() => {});
  }, []);

  const isReg = mode === "register";

  async function submit(e) {
    e.preventDefault();
    setError("");
    if (isReg && password !== confirm) {
      setError("Пароли не совпадают");
      return;
    }
    setBusy(true);
    try {
      const { token } = isReg
        ? await api.register(username, password, fullName)
        : await api.login(username, password);
      localStorage.setItem("token", token);
      onLogin();
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  function switchMode() {
    setMode(isReg ? "login" : "register");
    setError("");
    setPassword("");
    setConfirm("");
  }

  return (
    <div className="login-wrap">
      <div className="login-glow" />
      <ThemeToggle theme={theme} onToggle={onToggleTheme} className="login-theme" />
      <form className="login-card" onSubmit={submit}>
        <div className="login-logo"><img src={logo} alt="РемТехника" /></div>
        <h1>Ремтехника</h1>
        <p className="muted">{isReg ? "Регистрация сотрудника" : "Корпоративный ИИ-ассистент"}</p>

        {isReg && (
          <div className="field">
            <i className="ti ti-id field-icon" />
            <input
              placeholder="Имя и фамилия"
              value={fullName}
              onChange={(e) => setFullName(e.target.value)}
              autoFocus
            />
          </div>
        )}
        <div className="field">
          <i className="ti ti-user field-icon" />
          <input
            placeholder="Логин"
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            autoFocus={!isReg}
          />
        </div>
        <div className="field">
          <i className="ti ti-lock field-icon" />
          <input
            type={show ? "text" : "password"}
            placeholder="Пароль"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
          <button
            type="button"
            className="field-toggle"
            aria-label={show ? "Скрыть пароль" : "Показать пароль"}
            onClick={() => setShow((s) => !s)}
          >
            <i className={show ? "ti ti-eye-off" : "ti ti-eye"} />
          </button>
        </div>
        {isReg && (
          <div className="field">
            <i className="ti ti-lock field-icon" />
            <input
              type={show ? "text" : "password"}
              placeholder="Повторите пароль"
              value={confirm}
              onChange={(e) => setConfirm(e.target.value)}
            />
          </div>
        )}

        {error && <div className="error">{error}</div>}
        <button
          className="login-btn"
          disabled={busy || !username || !password || (isReg && !confirm)}
        >
          {busy ? "Подождите…" : isReg ? "Зарегистрироваться" : "Войти"}
          {!busy && <i className="ti ti-arrow-right" />}
        </button>

        {regOpen && (
          <div className="login-switch">
            {isReg ? "Уже есть аккаунт?" : "Первый запуск — создайте администратора."}
            <button type="button" onClick={switchMode}>
              {isReg ? "Войти" : "Регистрация"}
            </button>
          </div>
        )}
      </form>
    </div>
  );
}

function Chat({ onLogout, theme, onToggleTheme }) {
  const [conversations, setConversations] = useState([]);
  const [activeId, setActiveId] = useState(null);
  const [messages, setMessages] = useState([]);
  const [draft, setDraft] = useState(null); // текущий стримящийся ответ
  const [input, setInput] = useState("");
  const [pending, setPending] = useState([]); // загруженные файлы к отправке
  const [busy, setBusy] = useState(false);
  const [dragOver, setDragOver] = useState(false);
  const [me, setMe] = useState(null);
  const [agents, setAgents] = useState([]);
  const [agentId, setAgentId] = useState("");
  const [view, setView] = useState("chat"); // chat | admin
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [userMenuOpen, setUserMenuOpen] = useState(false);
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const wsRef = useRef(null);
  const scrollRef = useRef(null);
  const activeIdRef = useRef(null);
  const inputRef = useRef(null);
  const userMenuRef = useRef(null);

  useEffect(() => {
    if (!userMenuOpen) return;
    const h = (e) => {
      if (userMenuRef.current && !userMenuRef.current.contains(e.target)) setUserMenuOpen(false);
    };
    document.addEventListener("mousedown", h);
    return () => document.removeEventListener("mousedown", h);
  }, [userMenuOpen]);

  useEffect(() => { activeIdRef.current = activeId; }, [activeId]);

  // загрузка списка чатов и профиля
  useEffect(() => {
    api.conversations().then(setConversations).catch(() => {});
    api.me().then(setMe).catch(() => {});
    api.agents().then(setAgents).catch(() => {});
  }, []);

  // WebSocket
  useEffect(() => {
    connect();
    return () => wsRef.current?.close();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function connect() {
    const ws = openSocket();
    ws.onmessage = (ev) => handleEvent(JSON.parse(ev.data));
    ws.onclose = () => { setBusy(false); };
    wsRef.current = ws;
  }

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [messages, draft]);

  function handleEvent(ev) {
    setDraft((d) => {
      const cur = d || { role: "assistant", text: "", status: "", images: [], docs: [] };
      switch (ev.type) {
        case "status":
        case "tool":
          return { ...cur, status: ev.label || ev.text || "" };
        case "delta":
          return { ...cur, text: cur.text + ev.text, status: "" };
        case "image":
          return { ...cur, images: [...cur.images, { id: ev.file_id, name: ev.name }] };
        case "document":
          return { ...cur, docs: [...cur.docs, { id: ev.file_id, name: ev.name }] };
        case "error":
          return { ...cur, text: (cur.text ? cur.text + "\n\n" : "") + "⚠️ " + ev.text, status: "" };
        default:
          return cur;
      }
    });

    if (ev.type === "conversation") {
      setActiveId(ev.id);
      api.conversations().then(setConversations).catch(() => {});
    }
    if (ev.type === "done") {
      setBusy(false);
      setDraft((d) => {
        const final = d || { role: "assistant", text: "", images: [], docs: [] };
        setMessages((m) => [...m, { ...final, text: ev.text || final.text, status: "" }]);
        return null;
      });
    }
  }

  async function selectConversation(id) {
    setActiveId(id);
    setSidebarOpen(false);
    setDraft(null);
    const hist = await api.messages(id);
    setMessages(
      hist.map((m) => ({
        role: m.role,
        text: extractText(m.content),
        images: [],
        docs: [],
      }))
    );
  }

  function newChat() {
    setActiveId(null);
    setMessages([]);
    setDraft(null);
    setPending([]);
    setSidebarOpen(false);
    setTimeout(() => inputRef.current?.focus(), 0);
  }

  async function deleteChat(id) {
    if (!window.confirm("Удалить этот чат?")) return;
    try {
      await api.deleteConversation(id);
    } catch (err) {
      toast.error(err.message);
      return;
    }
    setConversations((cs) => cs.filter((c) => c.id !== id));
    if (activeIdRef.current === id) newChat();
    toast.success("Чат удалён");
  }

  function useExample(text) {
    setInput(text);
    inputRef.current?.focus();
  }

  async function onFiles(fileList) {
    const files = Array.from(fileList);
    for (const f of files) {
      try {
        const rec = await api.upload(f, activeIdRef.current);
        setPending((p) => [...p, rec]);
        toast.success(`Файл «${rec.name}» прикреплён`);
      } catch (err) {
        toast.error(err.message);
      }
    }
  }

  function send() {
    const text = input.trim();
    if ((!text && pending.length === 0) || busy) return;
    const ws = wsRef.current;
    if (!ws || ws.readyState !== WebSocket.OPEN) {
      connect();
      setTimeout(send, 400);
      return;
    }
    setMessages((m) => [
      ...m,
      { role: "user", text, images: [], docs: [], files: pending },
    ]);
    ws.send(
      JSON.stringify({
        conversation_id: activeId,
        text,
        file_ids: pending.map((p) => p.file_id),
        agent_id: agentId ? Number(agentId) : null,
      })
    );
    setInput("");
    setPending([]);
    setBusy(true);
    setDraft({ role: "assistant", text: "", status: "Думаю...", images: [], docs: [] });
  }

  function onKeyDown(e) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      send();
    }
  }

  return (
    <div className="app">
      <header className="topbar">
        {view === "chat" && (
          <button className="hamburger" onClick={() => setSidebarOpen(true)} aria-label="Меню">
            <i className="ti ti-menu-2" />
          </button>
        )}
        <button className="brand" onClick={() => setView("chat")} title="К чату">
          <img src={logo} className="brand-logo" alt="РемТехника" />
          <span className="brand-name">Ремтехника</span>
          <span className="sub">· ИИ-ассистент</span>
        </button>
        <div className="topbar-right">
          {me?.role === "admin" && (
            <button
              className="nav-toggle"
              onClick={() => setView((v) => (v === "admin" ? "chat" : "admin"))}
            >
              <i className={view === "admin" ? "ti ti-message" : "ti ti-layout-dashboard"} />
              {view === "admin" ? "К чату" : "Панель администратора"}
            </button>
          )}
          <span className="online"><span className="dot" />онлайн</span>
        </div>
      </header>

      {view === "admin" ? (
        <AdminPanel />
      ) : (
      <div className="body">
      {sidebarOpen && <div className="sidebar-backdrop" onClick={() => setSidebarOpen(false)} />}
      <aside className={"sidebar" + (sidebarOpen ? " open" : "")}>
        <button
          className={"new-chat" + (activeId === null ? " active" : "")}
          onClick={newChat}
        >
          <i className="ti ti-plus" />Новый чат
        </button>
        <div className="conv-label">История</div>
        <div className="conv-list">
          {conversations.length === 0 && (
            <div className="conv-empty">Пока нет диалогов</div>
          )}
          {conversations.map((c) => (
            <div
              key={c.id}
              className={"conv-item" + (c.id === activeId ? " active" : "")}
              onClick={() => selectConversation(c.id)}
              title={c.title}
            >
              <i className="ti ti-message-2" />
              <span className="conv-title">{c.title}</span>
              <button
                className="conv-del"
                aria-label="Удалить чат"
                onClick={(e) => { e.stopPropagation(); deleteChat(c.id); }}
              >
                <i className="ti ti-trash" />
              </button>
            </div>
          ))}
        </div>
        {me && (
          <div className="user-block" ref={userMenuRef}>
            {userMenuOpen && (
              <div className="user-menu">
                <button className="user-menu-item" onClick={() => { setSettingsOpen(true); setUserMenuOpen(false); }}>
                  <i className="ti ti-settings" />Настройки
                </button>
                <button className="user-menu-item" onClick={() => { onToggleTheme(); }}>
                  <i className={theme === "dark" ? "ti ti-sun" : "ti ti-moon"} />
                  {theme === "dark" ? "Светлая тема" : "Тёмная тема"}
                </button>
                <button className="user-menu-item" onClick={() => { setUserMenuOpen(false); clearAppCache(); }}>
                  <i className="ti ti-trash" />Очистить кеш
                </button>
                <div className="user-menu-sep" />
                <button className="user-menu-item danger" onClick={onLogout}>
                  <i className="ti ti-logout" />Выйти
                </button>
              </div>
            )}
            <button
              className={"user-row" + (userMenuOpen ? " open" : "")}
              onClick={() => setUserMenuOpen((o) => !o)}
            >
              <div className="user-avatar">
                {(me.name || me.username || "?").slice(0, 1).toUpperCase()}
              </div>
              <div className="user-info">
                <div className="user-name">{me.name || me.username}</div>
                <div className="user-role">
                  {me.role === "admin" ? "Администратор" : "Сотрудник"}
                </div>
              </div>
              <i className="ti ti-selector user-chev" />
            </button>
          </div>
        )}
      </aside>

      <main
        className={"chat" + (dragOver ? " drag" : "")}
        onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
        onDragLeave={() => setDragOver(false)}
        onDrop={(e) => {
          e.preventDefault();
          setDragOver(false);
          onFiles(e.dataTransfer.files);
        }}
      >
        <div className="messages" ref={scrollRef}>
          {messages.length === 0 && !draft ? (
            <div className="welcome">
              <div className="welcome-icon"><img src={logo} alt="" /></div>
              <h2>Чем помочь?</h2>
              <p>Задайте вопрос, создайте документ или перетащите файл в окно</p>
              <div className="examples">
                {EXAMPLES.map((ex, i) => (
                  <button className="example" key={i} onClick={() => useExample(ex.text)}>
                    <i className={"ti " + ex.icon} />
                    <span>{ex.text}</span>
                  </button>
                ))}
              </div>
            </div>
          ) : (
            <>
              {messages.map((m, i) => <Message key={i} m={m} />)}
              {draft && <Message m={draft} streaming />}
            </>
          )}
        </div>

        <div className="composer">
          {agents.length > 0 && (
            <div className="agent-pick">
              <i className="ti ti-robot" />
              <select value={agentId} onChange={(e) => setAgentId(e.target.value)}>
                <option value="">Ассистент (по умолчанию)</option>
                {agents.map((a) => (
                  <option key={a.id} value={a.id}>{a.name}</option>
                ))}
              </select>
            </div>
          )}
          {pending.length > 0 && (
            <div className="pending">
              {pending.map((p, i) => (
                <span className="chip" key={i}>
                  📎 {p.name}
                  <button onClick={() => setPending((x) => x.filter((_, j) => j !== i))}>×</button>
                </span>
              ))}
            </div>
          )}
          <div className="composer-row">
            <label className="attach" title="Прикрепить файл">
              <i className="ti ti-paperclip" />
              <input type="file" multiple hidden onChange={(e) => onFiles(e.target.files)} />
            </label>
            <textarea
              ref={inputRef}
              value={input}
              placeholder="Сообщение..."
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={onKeyDown}
              rows={1}
            />
            <button className="send" onClick={send} disabled={busy} aria-label="Отправить">
              <i className={busy ? "ti ti-loader-2" : "ti ti-arrow-up"} />
            </button>
          </div>
        </div>
      </main>
      </div>
      )}

      {settingsOpen && (
        <SettingsModal
          me={me}
          theme={theme}
          onToggleTheme={onToggleTheme}
          onClose={() => setSettingsOpen(false)}
        />
      )}
    </div>
  );
}

function SettingsModal({ me, theme, onToggleTheme, onClose }) {
  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <div className="modal-head">
          <h2><i className="ti ti-settings" /> Настройки</h2>
          <button className="modal-close" onClick={onClose} aria-label="Закрыть">
            <i className="ti ti-x" />
          </button>
        </div>

        <div className="settings-section">
          <div className="settings-label">Оформление</div>
          <div className="settings-row">
            <div>
              <div className="settings-title">Тема интерфейса</div>
              <div className="settings-sub">Тёмная или светлая</div>
            </div>
            <div className="seg">
              <button
                className={theme === "dark" ? "seg-on" : ""}
                onClick={() => theme !== "dark" && onToggleTheme()}
              >
                <i className="ti ti-moon" />Тёмная
              </button>
              <button
                className={theme === "light" ? "seg-on" : ""}
                onClick={() => theme !== "light" && onToggleTheme()}
              >
                <i className="ti ti-sun" />Светлая
              </button>
            </div>
          </div>
        </div>

        <div className="settings-section">
          <div className="settings-label">Данные</div>
          <div className="settings-row">
            <div>
              <div className="settings-title">Очистить кеш</div>
              <div className="settings-sub">Сбросить локальные данные и перезагрузить</div>
            </div>
            <button className="settings-btn" onClick={clearAppCache}>
              <i className="ti ti-trash" />Очистить
            </button>
          </div>
        </div>

        <div className="settings-section">
          <div className="settings-label">О программе</div>
          <div className="about">
            <div className="about-logo"><img src={logo} alt="" /></div>
            <div className="about-name">Ремтехника · ИИ-ассистент</div>
            <div className="about-ver">Версия 1.0</div>
            <p className="about-desc">
              Корпоративный ИИ-ассистент на базе Claude: чат, создание документов
              Word и PDF, редактирование файлов, генерация изображений. Работает
              в локальной сети компании.
            </p>
            {me && (
              <div className="about-user">
                Вы вошли как <b>{me.name || me.username}</b>
                {me.role === "admin" ? " · администратор" : " · сотрудник"}
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

function docMeta(name) {
  const ext = (name.split(".").pop() || "").toLowerCase();
  if (ext === "pdf") return { cls: "pdf", icon: "ti-file-type-pdf" };
  if (ext === "docx" || ext === "doc") return { cls: "docx", icon: "ti-download" };
  if (ext === "mp4") return { cls: "file", icon: "ti-video" };
  if (ext === "xlsx" || ext === "xls") return { cls: "docx", icon: "ti-file-spreadsheet" };
  return { cls: "file", icon: "ti-download" };
}

function TypingDots() {
  return (
    <span className="typing"><span></span><span></span><span></span></span>
  );
}

function Message({ m, streaming }) {
  return (
    <div className={"msg " + m.role}>
      <div className="bubble">
        {m.status && (
          <div className="status">
            <i className="ti ti-file-text" />{m.status}
            {streaming && !m.text && <TypingDots />}
          </div>
        )}
        {m.text && (
          m.role === "assistant"
            ? <Markdown>{m.text}</Markdown>
            : <div className="text">{m.text}</div>
        )}
        {streaming && m.text && <span className="caret">▋</span>}
        {m.files?.length > 0 && (
          <div className="attachments">
            {m.files.map((f, i) => (
              <span className="chip" key={i}><i className="ti ti-paperclip" /> {f.name}</span>
            ))}
          </div>
        )}
        {m.images?.length > 0 && (
          <div className="images">
            {m.images.map((img, i) => (
              <a key={i} href={fileUrl(img.id)} target="_blank" rel="noreferrer">
                <img src={fileUrl(img.id)} alt={img.name} />
              </a>
            ))}
          </div>
        )}
        {m.docs?.length > 0 && (
          <div className="docs">
            {m.docs.map((d, i) => {
              const meta = docMeta(d.name);
              return (
                <a key={i} className={"doc-link " + meta.cls} href={fileUrl(d.id)}>
                  <i className={"ti " + meta.icon} /> {d.name}
                </a>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}
