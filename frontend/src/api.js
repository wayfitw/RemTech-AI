// Тонкая обёртка над REST API и WebSocket.

export function getToken() {
  return localStorage.getItem("token") || "";
}
export function clearToken() {
  localStorage.removeItem("token");
}

// Единый multipart-аплоад (issue #19 — было два почти идентичных дубля).
async function uploadForm(path, file, fields = {}) {
  const fd = new FormData();
  fd.append("file", file);
  for (const [k, v] of Object.entries(fields)) if (v != null && v !== "") fd.append(k, v);
  const res = await fetch(`/api${path}`, {
    method: "POST",
    headers: { Authorization: `Bearer ${getToken()}` },
    body: fd,
  });
  if (res.status === 401) {
    clearToken();
    throw new Error("Сессия истекла, войдите снова");
  }
  if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || "Ошибка загрузки");
  return res.json();
}

async function req(path, opts = {}) {
  const headers = { ...(opts.headers || {}) };
  const token = getToken();
  if (token) headers.Authorization = `Bearer ${token}`;
  if (opts.json) {
    headers["Content-Type"] = "application/json";
    opts.body = JSON.stringify(opts.json);
    delete opts.json;
  }
  const res = await fetch(`/api${path}`, { ...opts, headers });
  if (res.status === 401) {
    clearToken();
    throw new Error("Сессия истекла, войдите снова");
  }
  if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || `Ошибка ${res.status}`);
  return res.json();
}

export const api = {
  authStatus: () => req("/auth/status"),
  login: (username, password) =>
    req("/login", { method: "POST", json: { username, password } }),
  register: (username, password, full_name) =>
    req("/register", { method: "POST", json: { username, password, full_name } }),
  me: () => req("/me"),
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

export function fileUrl(fileId) {
  return `/api/files/${fileId}?token=${encodeURIComponent(getToken())}`;
}

export async function downloadAuthed(path, filename) {
  const res = await fetch(`/api${path}`, {
    headers: { Authorization: `Bearer ${getToken()}` },
  });
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

export function openSocket() {
  const proto = location.protocol === "https:" ? "wss" : "ws";
  return new WebSocket(`${proto}://${location.host}/ws?token=${encodeURIComponent(getToken())}`);
}
