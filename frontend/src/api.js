// Тонкая обёртка над REST API и WebSocket.
// #4 — токен хранится в httpOnly-cookie (JS не читает → защита от XSS). Авторизация
// идёт cookie (credentials:include). Для мутаций — CSRF (double-submit): читаемый
// cookie rt_csrf эхом кладём в заголовок X-CSRF-Token. rt_authed — нечувствительный
// UX-флаг «залогинен» (НЕ токен), чтобы не мигать экраном входа при загрузке.

export function isAuthed() {
  return !!localStorage.getItem("rt_authed");
}
function _setAuthed() {
  localStorage.setItem("rt_authed", "1");
}
function _clearAuthed() {
  localStorage.removeItem("rt_authed");
}

function csrfToken() {
  const m = document.cookie.match(/(?:^|;\s*)rt_csrf=([^;]+)/);
  return m ? decodeURIComponent(m[1]) : "";
}

const _MUTATING = new Set(["POST", "PUT", "PATCH", "DELETE"]);

// #4 — серверный выход: отзыв токена + очистка cookie на бэкенде, затем локальный флаг.
export async function logout() {
  try {
    await fetch("/api/logout", {
      method: "POST",
      credentials: "include",
      headers: { "X-CSRF-Token": csrfToken() },
    });
  } catch {
    /* сеть недоступна — всё равно выходим локально */
  }
  _clearAuthed();
}

// Единый multipart-аплоад (issue #19 — было два почти идентичных дубля).
async function uploadForm(path, file, fields = {}) {
  const fd = new FormData();
  fd.append("file", file);
  for (const [k, v] of Object.entries(fields)) if (v != null && v !== "") fd.append(k, v);
  const res = await fetch(`/api${path}`, {
    method: "POST",
    credentials: "include",
    headers: { "X-CSRF-Token": csrfToken() },
    body: fd,
  });
  if (res.status === 401) {
    _clearAuthed();
    throw new Error("Сессия истекла, войдите снова");
  }
  if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || "Ошибка загрузки");
  return res.json();
}

async function req(path, opts = {}) {
  const method = (opts.method || "GET").toUpperCase();
  const headers = { ...(opts.headers || {}) };
  if (_MUTATING.has(method)) headers["X-CSRF-Token"] = csrfToken();
  if (opts.json) {
    headers["Content-Type"] = "application/json";
    opts.body = JSON.stringify(opts.json);
    delete opts.json;
  }
  const res = await fetch(`/api${path}`, { ...opts, headers, credentials: "include" });
  if (res.status === 401) {
    _clearAuthed();
    throw new Error("Сессия истекла, войдите снова");
  }
  if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || `Ошибка ${res.status}`);
  return res.json();
}

export const api = {
  authStatus: () => req("/auth/status"),
  login: async (username, password) => {
    const r = await req("/login", { method: "POST", json: { username, password } });
    _setAuthed();
    return r;
  },
  register: async (username, password, full_name) => {
    const r = await req("/register", { method: "POST", json: { username, password, full_name } });
    _setAuthed();
    return r;
  },
  me: () => req("/me"),
  ticket: () => req("/ticket", { method: "POST" }),
  agents: () => req("/agents"),
  adminCreateUser: (username, password, full_name, role) =>
    req("/admin/users", { method: "POST", json: { username, password, full_name, role } }),
  adminResetPassword: (uid, password) =>
    req(`/admin/users/${uid}/password`, { method: "POST", json: { password } }),
  adminSetActive: (uid, active) =>
    req(`/admin/users/${uid}/active?active=${active}`, { method: "POST" }),
  conversations: () => req("/conversations"),
  newConversation: (title) => req("/conversations", { method: "POST", json: { title } }),
  deleteConversation: (id) => req(`/conversations/${id}`, { method: "DELETE" }),
  messages: (id) => req(`/conversations/${id}/messages`),
  adminOverview: () => req("/admin/overview"),
  adminUserConversations: (uid) => req(`/admin/users/${uid}/conversations`),
  adminConversationMessages: (cid) => req(`/admin/conversations/${cid}/messages`),
  adminActivity: (limit = 200) => req(`/admin/activity?limit=${limit}`),
  exportXlsx: () => downloadAuthed("/admin/export/xlsx", "Отчёт_Ремтехника.xlsx"),
  exportDocx: () => downloadAuthed("/admin/export/docx", "Отчёт_Ремтехника.docx"),
  exportUserDocx: (uid, name) =>
    downloadAuthed(`/admin/users/${uid}/export/docx`, `Переписка_${name}.docx`),
  adminModels: () => req("/admin/models"),
  adminTools: () => req("/admin/tools"),
  adminAgents: () => req("/admin/agents"),
  adminCreateAgent: (data) => req("/admin/agents", { method: "POST", json: data }),
  adminDeleteAgent: (id) => req(`/admin/agents/${id}`, { method: "DELETE" }),
  adminKbList: () => req("/admin/kb"),
  adminKbDelete: (id) => req(`/admin/kb/${id}`, { method: "DELETE" }),
  adminKbUpload: (file, ownerRole) =>
    uploadForm("/admin/kb/upload", file, { owner_role: ownerRole }),
  upload: (file, conversationId) =>
    uploadForm("/upload", file, { conversation_id: conversationId }),
};

// #4 — файлы грузим через fetch по cookie (токена в URL нет, GET → CSRF не нужен).
export async function fileBlobUrl(fileId) {
  const res = await fetch(`/api/files/${fileId}`, { credentials: "include" });
  if (!res.ok) throw new Error("Не удалось загрузить файл");
  return URL.createObjectURL(await res.blob());
}

export async function downloadFile(fileId, filename) {
  await downloadAuthed(`/files/${fileId}`, filename);
}

export async function downloadAuthed(path, filename) {
  const res = await fetch(`/api${path}`, { credentials: "include" });
  if (!res.ok) throw new Error("Не удалось сформировать файл");
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

// #4 — WebSocket: одноразовый тикет вместо long-lived JWT в URL.
export async function openSocket() {
  const { ticket } = await api.ticket();
  const proto = location.protocol === "https:" ? "wss" : "ws";
  return new WebSocket(`${proto}://${location.host}/ws?ticket=${encodeURIComponent(ticket)}`);
}
