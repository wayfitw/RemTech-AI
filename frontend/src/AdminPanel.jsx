import { useEffect, useState } from "react";
import { toast } from "sonner";
import { api } from "./api.js";
import Markdown from "./Markdown.jsx";

function msgText(content) {
  if (typeof content === "string") return content;
  if (Array.isArray(content)) {
    return content.filter((b) => b && b.type === "text").map((b) => b.text).join("\n");
  }
  return "";
}

function fmt(ts) {
  if (!ts) return "—";
  const m = ts.match(/(\d{4})-(\d{2})-(\d{2})[ T](\d{2}):(\d{2})/);
  if (!m) return ts;
  return `${m[3]}.${m[2]} ${m[4]}:${m[5]}`;
}

const ACTION_LABEL = {
  login: "Вход",
  register: "Регистрация",
  message: "Сообщение ассистенту",
};

export default function AdminPanel() {
  const [tab, setTab] = useState("stats");
  const [data, setData] = useState(null);
  const [activity, setActivity] = useState([]);
  const [viewUser, setViewUser] = useState(null);
  const [viewConv, setViewConv] = useState(null);
  const [exporting, setExporting] = useState("");

  async function doExport(kind) {
    setExporting(kind);
    try {
      if (kind === "xlsx") await api.exportXlsx();
      else await api.exportDocx();
      toast.success("Отчёт скачан");
    } catch (e) {
      toast.error(e.message);
    } finally {
      setExporting("");
    }
  }

  const load = () => api.adminOverview().then(setData).catch(() => {});
  useEffect(() => { load(); }, []);
  useEffect(() => {
    if (tab === "logs") api.adminActivity().then(setActivity).catch(() => {});
  }, [tab]);

  async function openUser(uid) {
    try {
      const res = await api.adminUserConversations(uid);
      setViewUser(res);
      setViewConv(null);
    } catch (e) { alert(e.message); }
  }
  async function openConv(cid) {
    try {
      setViewConv(await api.adminConversationMessages(cid));
    } catch (e) { alert(e.message); }
  }

  const t = data?.totals;

  return (
    <div className="admin">
      <div className="admin-tabs">
        {[["stats", "ti-chart-bar", "Статистика"],
          ["users", "ti-users", "Сотрудники"],
          ["kb", "ti-database", "База знаний"],
          ["agents", "ti-robot", "Агенты"],
          ["logs", "ti-history", "Журнал"]].map(([id, icon, label]) => (
          <button
            key={id}
            className={"admin-tab" + (tab === id ? " active" : "")}
            onClick={() => { setTab(id); setViewUser(null); setViewConv(null); }}
          >
            <i className={"ti " + icon} />{label}
          </button>
        ))}
        <div className="admin-export">
          <button className="export-btn xlsx" disabled={!!exporting} onClick={() => doExport("xlsx")}>
            <i className="ti ti-file-spreadsheet" />{exporting === "xlsx" ? "Готовлю…" : "Excel"}
          </button>
          <button className="export-btn docx" disabled={!!exporting} onClick={() => doExport("docx")}>
            <i className="ti ti-file-type-doc" />{exporting === "docx" ? "Готовлю…" : "Word"}
          </button>
        </div>
      </div>

      <div className="admin-body">
        {tab === "stats" && (
          <Stats data={data} t={t} />
        )}

        {tab === "users" && !viewUser && (
          <UsersManage users={data?.users || []} onOpen={openUser} onChanged={load} />
        )}

        {tab === "users" && viewUser && !viewConv && (
          <UserChats view={viewUser} onBack={() => setViewUser(null)} onOpen={openConv} />
        )}

        {tab === "users" && viewConv && (
          <ConvView view={viewConv} onBack={() => setViewConv(null)} />
        )}

        {tab === "kb" && <KnowledgeBase />}

        {tab === "agents" && <Agents />}

        {tab === "logs" && <Logs rows={activity} />}
      </div>
    </div>
  );
}

const ROLE_LABEL = { "": "Все сотрудники", user: "Сотрудники", admin: "Только админ" };

function KnowledgeBase() {
  const [docs, setDocs] = useState([]);
  const [role, setRole] = useState("");
  const [busy, setBusy] = useState(false);

  function load() {
    api.adminKbList().then(setDocs).catch((e) => toast.error(e.message));
  }
  useEffect(() => { load(); }, []);

  async function upload(files) {
    for (const f of Array.from(files)) {
      setBusy(true);
      try {
        const r = await api.adminKbUpload(f, role);
        toast.success(`«${f.name}» — ${r.chunks} фрагментов`);
      } catch (e) {
        toast.error(e.message);
      } finally {
        setBusy(false);
      }
    }
    load();
  }

  async function remove(d) {
    if (!window.confirm(`Удалить «${d.file_name}» из базы знаний?`)) return;
    try {
      await api.adminKbDelete(d.id);
      setDocs((x) => x.filter((y) => y.id !== d.id));
      toast.success("Документ удалён");
    } catch (e) { toast.error(e.message); }
  }

  return (
    <div>
      <div className="kb-upload">
        <div className="kb-upload-row">
          <label className="kb-role">
            Доступ:
            <select value={role} onChange={(e) => setRole(e.target.value)}>
              <option value="">Все сотрудники</option>
              <option value="user">Сотрудники</option>
              <option value="admin">Только админ</option>
            </select>
          </label>
          <label className={"kb-add-btn" + (busy ? " busy" : "")}>
            <i className={busy ? "ti ti-loader-2" : "ti ti-upload"} />
            {busy ? "Загружаю…" : "Загрузить документы"}
            <input type="file" multiple hidden disabled={busy}
                   onChange={(e) => upload(e.target.files)} />
          </label>
        </div>
        <div className="kb-hint">
          PDF, DOCX, XLSX, PPTX, TXT — текст извлекается, векторизуется (bge-m3) и
          добавляется в базу знаний. Агент ищет по ней при ответах.
        </div>
      </div>

      {docs.length === 0 ? (
        <div className="admin-empty">База знаний пуста — загрузите документы.</div>
      ) : (
        <div className="table-wrap">
          <table className="admin-table">
            <thead>
              <tr><th>Документ</th><th>Доступ</th><th>Фрагментов</th><th>Загружен</th><th></th></tr>
            </thead>
            <tbody>
              {docs.map((d) => (
                <tr key={d.id}>
                  <td><div className="cell-user"><i className="ti ti-file-text" style={{ fontSize: 18 }} /> {d.file_name}</div></td>
                  <td>{ROLE_LABEL[d.owner_role || ""] || d.owner_role}</td>
                  <td>{d.chunks}</td>
                  <td className="cell-sub">{fmt(d.created_at)}</td>
                  <td className="row-actions">
                    <button className="icon-act" title="Удалить" onClick={() => remove(d)}>
                      <i className="ti ti-trash" />
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function Stats({ data, t }) {
  if (!data) return <div className="admin-empty">Загрузка…</div>;
  const perDay = data.per_day || [];
  const max = Math.max(1, ...perDay.map((d) => d.count));
  const cards = [
    ["ti-users", "Сотрудников", t.users],
    ["ti-message-2", "Чатов", t.conversations],
    ["ti-messages", "Сообщений", t.user_messages],
    ["ti-file-text", "Документов", t.generated_files],
    ["ti-activity", "Активны сегодня", t.active_today],
  ];
  return (
    <div>
      <div className="stat-cards">
        {cards.map(([icon, label, val]) => (
          <div className="stat-card" key={label}>
            <i className={"ti " + icon} />
            <div className="stat-val">{val ?? 0}</div>
            <div className="stat-label">{label}</div>
          </div>
        ))}
      </div>

      <div className="admin-section">
        <h3>Сообщения за 14 дней</h3>
        {perDay.length === 0 ? (
          <div className="admin-empty">Пока нет данных</div>
        ) : (
          <div className="bars">
            {perDay.map((d) => (
              <div className="bar-col" key={d.day} title={`${d.day}: ${d.count}`}>
                <div className="bar" style={{ height: `${(d.count / max) * 100}%` }} />
                <div className="bar-x">{d.day.slice(8)}</div>
              </div>
            ))}
          </div>
        )}
      </div>

      <div className="admin-section">
        <h3>Активность сотрудников</h3>
        <UsersTable users={data.users || []} compact />
      </div>
    </div>
  );
}

function UsersManage({ users, onOpen, onChanged }) {
  const [adding, setAdding] = useState(false);
  const [form, setForm] = useState({ username: "", full_name: "", password: "", role: "user" });
  const [busy, setBusy] = useState(false);

  async function create(e) {
    e.preventDefault();
    setBusy(true);
    try {
      await api.adminCreateUser(form.username, form.password, form.full_name, form.role);
      toast.success("Сотрудник добавлен");
      setForm({ username: "", full_name: "", password: "", role: "user" });
      setAdding(false);
      onChanged();
    } catch (err) { toast.error(err.message); }
    finally { setBusy(false); }
  }

  async function toggleActive(u) {
    try {
      await api.adminSetActive(u.id, !u.active);
      toast.success(u.active ? "Аккаунт отключён" : "Аккаунт включён");
      onChanged();
    } catch (err) { toast.error(err.message); }
  }

  async function resetPass(u) {
    const p = window.prompt(`Новый пароль для «${u.full_name || u.username}»:`);
    if (!p) return;
    try {
      await api.adminResetPassword(u.id, p);
      toast.success("Пароль сброшен");
    } catch (err) { toast.error(err.message); }
  }

  return (
    <div>
      <div className="users-toolbar">
        <button className="add-user-btn" onClick={() => setAdding((a) => !a)}>
          <i className="ti ti-user-plus" />Добавить сотрудника
        </button>
      </div>
      {adding && (
        <form className="add-user-form" onSubmit={create}>
          <input placeholder="Имя и фамилия" value={form.full_name}
                 onChange={(e) => setForm({ ...form, full_name: e.target.value })} />
          <input placeholder="Логин" value={form.username}
                 onChange={(e) => setForm({ ...form, username: e.target.value })} />
          <input placeholder="Пароль" value={form.password}
                 onChange={(e) => setForm({ ...form, password: e.target.value })} />
          <select value={form.role} onChange={(e) => setForm({ ...form, role: e.target.value })}>
            <option value="user">Сотрудник</option>
            <option value="admin">Администратор</option>
          </select>
          <button disabled={busy || !form.username || !form.password}>
            {busy ? "…" : "Создать"}
          </button>
        </form>
      )}
      <UsersTable users={users} onOpen={onOpen} onToggleActive={toggleActive} onResetPassword={resetPass} />
    </div>
  );
}

function UsersTable({ users, onOpen, compact, onToggleActive, onResetPassword }) {
  if (!users.length) return <div className="admin-empty">Нет сотрудников</div>;
  const manage = onToggleActive || onResetPassword;
  return (
    <div className="table-wrap">
    <table className="admin-table">
      <thead>
        <tr>
          <th>Сотрудник</th><th>Роль</th><th>Чатов</th><th>Сообщений</th><th>Был активен</th>
          {(onOpen || manage) && <th></th>}
        </tr>
      </thead>
      <tbody>
        {users.map((u) => (
          <tr key={u.id}>
            <td>
              <div className="cell-user">
                <span className="mini-avatar">{(u.full_name || u.username || "?").slice(0, 1).toUpperCase()}</span>
                <div>
                  <div className="cell-name">{u.full_name || u.username}</div>
                  <div className="cell-sub">@{u.username}</div>
                </div>
              </div>
            </td>
            <td>
              {u.role === "admin"
                ? <span className="badge badge-admin">Админ</span>
                : <span className="badge">Сотрудник</span>}
              {!u.active && <span className="badge badge-off">Отключён</span>}
            </td>
            <td>{u.conversations}</td>
            <td>{u.messages}</td>
            <td className="cell-sub">{fmt(u.last_active)}</td>
            {(onOpen || manage) && (
              <td className="row-actions">
                {onResetPassword && (
                  <button className="icon-act" title="Сбросить пароль"
                          aria-label="Сбросить пароль" onClick={() => onResetPassword(u)}>
                    <i className="ti ti-key" />
                  </button>
                )}
                {onToggleActive && (
                  <button className="icon-act" title={u.active ? "Отключить" : "Включить"}
                          aria-label="Переключить активность" onClick={() => onToggleActive(u)}>
                    <i className={u.active ? "ti ti-user-off" : "ti ti-user-check"} />
                  </button>
                )}
                {onOpen && (
                  <button className="link-btn" onClick={() => onOpen(u.id)}>
                    Чаты <i className="ti ti-chevron-right" />
                  </button>
                )}
              </td>
            )}
          </tr>
        ))}
      </tbody>
    </table>
    </div>
  );
}

function UserChats({ view, onBack, onOpen }) {
  const [busy, setBusy] = useState(false);
  const name = view.user.full_name || view.user.username;

  async function exportChats() {
    setBusy(true);
    try {
      await api.exportUserDocx(view.user.id, name);
      toast.success("Переписка скачана");
    } catch (e) {
      toast.error(e.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div>
      <button className="back-btn" onClick={onBack}><i className="ti ti-arrow-left" />К сотрудникам</button>
      <div className="user-chats-head">
        <h3>Чаты: {name}</h3>
        {view.conversations.length > 0 && (
          <button className="export-btn docx" disabled={busy} onClick={exportChats}>
            <i className="ti ti-file-type-doc" />{busy ? "Готовлю…" : "Экспорт переписки в Word"}
          </button>
        )}
      </div>
      {view.conversations.length === 0 ? (
        <div className="admin-empty">У сотрудника нет чатов</div>
      ) : (
        <div className="conv-cards">
          {view.conversations.map((c) => (
            <button className="conv-card" key={c.id} onClick={() => onOpen(c.id)}>
              <i className="ti ti-message-2" />
              <div className="conv-card-main">
                <div className="conv-card-title">{c.title}</div>
                <div className="cell-sub">{c.messages} сообщ. · {fmt(c.updated_at)}</div>
              </div>
              <i className="ti ti-chevron-right" />
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

function ConvView({ view, onBack }) {
  return (
    <div>
      <button className="back-btn" onClick={onBack}><i className="ti ti-arrow-left" />К чатам</button>
      <h3>{view.conversation.title}</h3>
      <div className="conv-read">
        {view.messages.map((m, i) => (
          <div className={"msg " + m.role} key={i}>
            <div className="bubble">
              {m.role === "assistant"
                ? <Markdown>{msgText(m.content)}</Markdown>
                : msgText(m.content)}
            </div>
          </div>
        ))}
        {view.messages.length === 0 && <div className="admin-empty">Чат пуст</div>}
      </div>
    </div>
  );
}

function Agents() {
  const [agents, setAgents] = useState([]);
  const [models, setModels] = useState([]);
  // Список инструментов — из единого реестра на бэкенде (issue #18), без хардкода.
  const [toolOptions, setToolOptions] = useState([]);
  const [adding, setAdding] = useState(false);
  const [busy, setBusy] = useState(false);
  const empty = { name: "", system_prompt: "", tools: [], default_model: "", allowed_roles: [] };
  const [form, setForm] = useState(empty);

  function load() { api.adminAgents().then(setAgents).catch((e) => toast.error(e.message)); }
  useEffect(() => {
    load();
    api.adminModels().then(setModels).catch(() => {});
    api.adminTools().then(setToolOptions).catch(() => {});
  }, []);

  const toggle = (list, v) => (list.includes(v) ? list.filter((x) => x !== v) : [...list, v]);
  const modelName = (id) => models.find((m) => m.id === id)?.alias || "по умолчанию";

  async function create(e) {
    e.preventDefault();
    setBusy(true);
    try {
      await api.adminCreateAgent({
        name: form.name, system_prompt: form.system_prompt, tools: form.tools,
        default_model: form.default_model ? Number(form.default_model) : null,
        allowed_roles: form.allowed_roles.join(","),
      });
      toast.success("Агент создан");
      setForm(empty); setAdding(false); load();
    } catch (err) { toast.error(err.message); } finally { setBusy(false); }
  }

  async function remove(a) {
    if (!window.confirm(`Удалить агента «${a.name}»?`)) return;
    try {
      await api.adminDeleteAgent(a.id);
      setAgents((x) => x.filter((y) => y.id !== a.id));
      toast.success("Агент удалён");
    } catch (e) { toast.error(e.message); }
  }

  return (
    <div>
      <div className="users-toolbar">
        <button className="add-user-btn" onClick={() => setAdding((a) => !a)}>
          <i className="ti ti-plus" />Новый агент
        </button>
      </div>
      {adding && (
        <form className="agent-form" onSubmit={create}>
          <input placeholder="Название (напр. «Продажник»)" value={form.name}
                 onChange={(e) => setForm({ ...form, name: e.target.value })} />
          <textarea placeholder="Системный промпт: кто это, как отвечает, какие правила…"
                    rows={3} value={form.system_prompt}
                    onChange={(e) => setForm({ ...form, system_prompt: e.target.value })} />
          <div className="agent-fld">
            <span>Инструменты (пусто = все):</span>
            <div className="chk-grid">
              {toolOptions.map(({ name, label }) => (
                <label key={name}>
                  <input type="checkbox" checked={form.tools.includes(name)}
                         onChange={() => setForm({ ...form, tools: toggle(form.tools, name) })} /> {label}
                </label>
              ))}
            </div>
          </div>
          <div className="agent-fld-row">
            <label className="agent-inline">Модель:
              <select value={form.default_model}
                      onChange={(e) => setForm({ ...form, default_model: e.target.value })}>
                <option value="">по умолчанию</option>
                {models.map((m) => <option key={m.id} value={m.id}>{m.alias} ({m.provider})</option>)}
              </select>
            </label>
            <div className="agent-fld inline">
              <span>Доступ:</span>
              {[["user", "Сотрудники"], ["admin", "Админ"]].map(([r, l]) => (
                <label key={r}>
                  <input type="checkbox" checked={form.allowed_roles.includes(r)}
                         onChange={() => setForm({ ...form, allowed_roles: toggle(form.allowed_roles, r) })} /> {l}
                </label>
              ))}
            </div>
          </div>
          <button disabled={busy || !form.name}>{busy ? "…" : "Создать агента"}</button>
        </form>
      )}
      {agents.length === 0 ? (
        <div className="admin-empty">Агентов пока нет — создайте первого (это «модуль»).</div>
      ) : (
        <div className="table-wrap">
          <table className="admin-table">
            <thead><tr><th>Агент</th><th>Модель</th><th>Инструментов</th><th>Доступ</th><th></th></tr></thead>
            <tbody>
              {agents.map((a) => (
                <tr key={a.id}>
                  <td><div className="cell-user"><i className="ti ti-robot" style={{ fontSize: 18 }} /> {a.name}</div></td>
                  <td>{modelName(a.default_model)}</td>
                  <td>{(a.tools || []).length || "все"}</td>
                  <td>{a.allowed_roles || "все"}</td>
                  <td className="row-actions">
                    <button className="icon-act" title="Удалить" onClick={() => remove(a)}>
                      <i className="ti ti-trash" />
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function Logs({ rows }) {
  if (!rows.length) return <div className="admin-empty">Журнал пуст</div>;
  return (
    <div className="table-wrap">
    <table className="admin-table">
      <thead>
        <tr><th>Время</th><th>Сотрудник</th><th>Действие</th><th>Детали</th></tr>
      </thead>
      <tbody>
        {rows.map((r) => (
          <tr key={r.id}>
            <td className="cell-sub">{fmt(r.created_at)}</td>
            <td>{r.full_name || r.username || "—"}</td>
            <td>{ACTION_LABEL[r.action] || r.action}</td>
            <td className="cell-detail">{r.detail}</td>
          </tr>
        ))}
      </tbody>
    </table>
    </div>
  );
}
