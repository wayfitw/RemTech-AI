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

  useEffect(() => { api.adminOverview().then(setData).catch(() => {}); }, []);
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
          <UsersTable users={data?.users || []} onOpen={openUser} />
        )}

        {tab === "users" && viewUser && !viewConv && (
          <UserChats view={viewUser} onBack={() => setViewUser(null)} onOpen={openConv} />
        )}

        {tab === "users" && viewConv && (
          <ConvView view={viewConv} onBack={() => setViewConv(null)} />
        )}

        {tab === "logs" && <Logs rows={activity} />}
      </div>
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

function UsersTable({ users, onOpen, compact }) {
  if (!users.length) return <div className="admin-empty">Нет сотрудников</div>;
  return (
    <div className="table-wrap">
    <table className="admin-table">
      <thead>
        <tr>
          <th>Сотрудник</th><th>Роль</th><th>Чатов</th><th>Сообщений</th><th>Был активен</th>
          {onOpen && <th></th>}
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
            <td>{u.role === "admin"
              ? <span className="badge badge-admin">Админ</span>
              : <span className="badge">Сотрудник</span>}</td>
            <td>{u.conversations}</td>
            <td>{u.messages}</td>
            <td className="cell-sub">{fmt(u.last_active)}</td>
            {onOpen && (
              <td>
                <button className="link-btn" onClick={() => onOpen(u.id)}>
                  Чаты <i className="ti ti-chevron-right" />
                </button>
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
