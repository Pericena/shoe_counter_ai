// Cliente HTTP: envía el token CSRF en cada petición que modifica datos y normaliza los errores.
let csrfToken = null;

export class ApiError extends Error {
  constructor(message, status, details) {
    super(message);
    this.status = status;
    this.details = details || null;
  }
}

export function setCsrf(token) {
  csrfToken = token;
}

async function parse(response) {
  const type = response.headers.get("Content-Type") || "";
  if (type.includes("application/json")) return response.json();
  return null;
}

export async function request(method, path, { json, form, signal } = {}) {
  const headers = {};
  let body;
  if (json !== undefined) {
    headers["Content-Type"] = "application/json";
    body = JSON.stringify(json);
  } else if (form) {
    body = form;
  }
  if (method !== "GET" && csrfToken) headers["X-CSRF-Token"] = csrfToken;
  const response = await fetch(path, { method, headers, body, signal, credentials: "same-origin" });
  const data = await parse(response);
  if (!response.ok) {
    const message = (data && data.error) || `Error ${response.status}`;
    if (response.status === 401 && !path.startsWith("/api/auth/") && !location.pathname.endsWith("tienda.html")) {
      const next = encodeURIComponent(location.hash || "#/");
      location.href = `/login.html?next=${next}`;
    }
    if (data && data.details && data.details.must_change_password) {
      location.href = "/login.html#cambiar";
    }
    throw new ApiError(message, response.status, data && data.details);
  }
  return data;
}

export const api = {
  get: (path, options) => request("GET", path, options),
  post: (path, json) => request("POST", path, { json: json ?? {} }),
  put: (path, json) => request("PUT", path, { json }),
  patch: (path, json) => request("PATCH", path, { json }),
  del: (path) => request("DELETE", path, { json: {} }),
  upload: (path, formData) => request("POST", path, { form: formData }),
};

export async function loadSession() {
  const data = await api.get("/api/auth/session");
  setCsrf(data.csrf_token);
  return data;
}

/** Descarga un archivo de la API (exportaciones, PDF) respetando la sesión. */
export async function download(path) {
  const response = await fetch(path, { credentials: "same-origin" });
  if (!response.ok) {
    const data = await parse(response);
    throw new ApiError((data && data.error) || `Error ${response.status}`, response.status);
  }
  const blob = await response.blob();
  const disposition = response.headers.get("Content-Disposition") || "";
  const match = disposition.match(/filename=([^;]+)/);
  const name = match ? match[1].replace(/"/g, "") : "descarga";
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = name;
  document.body.append(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 2000);
  return name;
}
