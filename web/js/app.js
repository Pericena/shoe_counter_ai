// Aplicación interna: sesión, navegación según permisos y enrutador por hash.
import { api, loadSession } from "./api.js";
import { el, empty, icon, showError } from "./ui.js";

const ROUTES = [
  { group: "General" },
  { path: "dashboard", label: "Panel", icon: "dashboard", perm: "dashboard.view", module: "./views/dashboard.js" },
  { group: "Catálogo e inventario" },
  { path: "productos", label: "Productos", icon: "box", perm: "products.view", module: "./views/products.js" },
  { path: "inventario", label: "Existencias", icon: "layers", perm: "inventory.view", module: "./views/inventory.js" },
  { path: "movimientos", label: "Movimientos", icon: "swap", perm: "inventory.view", module: "./views/movements.js" },
  { path: "conteo", label: "Conteo inteligente", icon: "camera", perm: "inventory.view", module: "./views/counting.js" },
  { group: "Ventas" },
  { path: "pedidos", label: "Pedidos online", icon: "cart", perm: "orders.view", module: "./views/orders.js" },
  { path: "tienda", label: "Ver tienda pública", icon: "store", perm: "orders.view", href: "/tienda.html" },
  { group: "Datos y reportes" },
  { path: "reportes", label: "Reportes de inventario", icon: "chart", perm: "reports.view", module: "./views/reports.js" },
  { path: "comercio", label: "Comercio exterior (BI)", icon: "globe", perm: "reports.view", module: "./views/trade.js" },
  { path: "importar", label: "Importar Excel/CSV", icon: "upload", perm: "imports.manage", module: "./views/imports.js" },
  { group: "Administración" },
  { path: "usuarios", label: "Usuarios", icon: "users", perm: "users.manage", module: "./views/users.js" },
  { path: "auditoria", label: "Auditoría", icon: "shield", perm: "audit.view", module: "./views/audit.js" },
  { path: "configuracion", label: "Configuración", icon: "settings", perm: null, module: "./views/settings.js" },
];

export const session = { user: null, permissions: new Set() };
export const can = (permission) => !permission || session.permissions.has(permission);

function buildNav() {
  const nav = document.getElementById("nav");
  nav.replaceChildren();
  let pendingGroup = null;
  for (const route of ROUTES) {
    if (route.group) { pendingGroup = route.group; continue; }
    if (!can(route.perm)) continue;
    if (pendingGroup) { nav.append(el("div.group", {}, pendingGroup)); pendingGroup = null; }
    const link = el("a", { href: route.href || `#/${route.path}`, dataset: { path: route.path },
      target: route.href ? "_blank" : undefined, rel: route.href ? "noopener" : undefined },
      icon(route.icon), route.label);
    nav.append(link);
  }
}

function buildUserBox() {
  const box = document.getElementById("user-box");
  const user = session.user;
  const initials = user.full_name.split(/\s+/).map((p) => p[0]).slice(0, 2).join("").toUpperCase();
  box.replaceChildren(
    el("div.who", {}, el("strong", {}, user.full_name), el("small", {}, `${user.username} · ${user.role_name}`)),
    el("div.avatar", { "aria-hidden": "true" }, initials),
    el("button.btn.ghost.small", { type: "button", title: "Cerrar sesión", on: { click: logout } }, icon("logout"), el("span.sr-only", {}, "Cerrar sesión")));
}

async function logout() {
  try {
    await api.post("/api/auth/logout");
  } finally {
    location.href = "/login.html";
  }
}

let currentToken = 0;

async function route() {
  const token = ++currentToken;
  const [path = "dashboard", ...params] = (location.hash.replace(/^#\/?/, "") || "dashboard").split("/");
  const view = document.getElementById("view");
  const target = ROUTES.find((r) => r.path === path && r.module);
  document.querySelectorAll("#nav a").forEach((a) => a.toggleAttribute("aria-current", a.dataset.path === path));
  document.querySelectorAll("#nav a[aria-current]").forEach((a) => a.setAttribute("aria-current", "page"));
  document.getElementById("sidebar").classList.remove("open");
  if (!target) {
    view.replaceChildren(empty("Página no encontrada", "Usa el menú lateral para navegar."));
    return;
  }
  if (!can(target.perm)) {
    view.replaceChildren(empty("Sin permiso", "Tu rol no tiene acceso a esta sección."));
    return;
  }
  document.getElementById("page-title").textContent = target.label;
  document.title = `${target.label} — Shoe Counter AI`;
  view.replaceChildren(el("div.loading", {}, el("span.spinner"), " Cargando…"));
  try {
    const module = await import(target.module);
    if (token !== currentToken) return;
    const node = el("div");
    view.replaceChildren(node);
    await module.render(node, params.map(decodeURIComponent), { can, session });
    view.focus({ preventScroll: true });
  } catch (error) {
    showError(error);
    if (token === currentToken) view.replaceChildren(el("div.alert.bad", {}, `No se pudo cargar la sección: ${error.message}`));
  }
}

async function start() {
  const menu = document.getElementById("menu-btn");
  menu.append(icon("menu"));
  menu.addEventListener("click", () => {
    const sidebar = document.getElementById("sidebar");
    sidebar.classList.toggle("open");
    menu.setAttribute("aria-expanded", sidebar.classList.contains("open"));
  });
  try {
    const data = await loadSession();
    if (!data.user) {
      location.href = `/login.html?next=${encodeURIComponent(location.hash || "#/")}`;
      return;
    }
    if (data.user.must_change_password) {
      location.href = "/login.html#cambiar";
      return;
    }
    session.user = data.user;
    session.permissions = new Set(data.permissions);
  } catch (error) {
    document.getElementById("view").replaceChildren(el("div.alert.bad", {},
      "No se pudo conectar con el servidor. Comprueba que la aplicación esté en ejecución."));
    return;
  }
  buildNav();
  buildUserBox();
  window.addEventListener("hashchange", route);
  route();
}

start();
