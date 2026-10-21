import { api } from "../api.js";
import { badge, el, field, fmt, formValues, icon, modal, options, pageHead, showError, toast } from "../ui.js";

const PERMISSION_LABELS = {
  "dashboard.view": "Ver el panel",
  "products.view": "Ver productos y catálogos",
  "products.manage": "Editar productos, catálogos y fotos",
  "prices.manage": "Modificar costos y precios",
  "inventory.view": "Ver existencias y movimientos",
  "inventory.sell": "Registrar ventas y devoluciones de clientes",
  "inventory.move": "Registrar entradas, ajustes y conteos físicos",
  "locations.manage": "Gestionar tiendas y almacenes",
  "pos.sell": "Vender en el punto de venta",
  "returns.manage": "Procesar devoluciones",
  "counts.create": "Crear conteos con foto",
  "counts.confirm": "Confirmar conteos y conciliar stock",
  "purchases.manage": "Crear y recibir órdenes de compra",
  "purchases.approve": "Aprobar órdenes de compra",
  "imports.manage": "Importar Excel/CSV",
  "exports.run": "Exportar datos e informes",
  "reports.view": "Ver reportes y comercio exterior",
  "bi.view": "Consultar datos analíticos",
  "orders.view": "Ver pedidos online",
  "orders.manage": "Cambiar el estado de los pedidos",
  "integrations.manage": "Configurar integraciones",
  "notifications.view": "Ver notificaciones",
  "users.manage": "Gestionar usuarios",
  "audit.view": "Ver la auditoría",
  "settings.view": "Ver la configuración",
  "settings.manage": "Cambiar parámetros del sistema",
};

export async function render(root) {
  const roles = (await api.get("/api/roles")).items;
  const list = el("div");
  root.append(pageHead("Usuarios", "Las contraseñas se guardan cifradas. Quien entra por primera vez debe cambiar la contraseña temporal.",
    el("button.btn.primary", { type: "button", on: { click: () => userDialog(null) } }, icon("plus"), "Nuevo usuario")),
  list,
  el("div.card", { class: "stack" }, el("h2", {}, "Roles y permisos"), el("div.table-wrap", {}, el("table", {},
    el("thead", {}, el("tr", {}, el("th", {}, "Rol"), el("th", {}, "Permisos"))),
    el("tbody", {}, roles.map((r) => el("tr", {}, el("td", {}, el("strong", {}, r.name)),
      el("td.wrap", {}, r.permissions.map((code) => PERMISSION_LABELS[code] || code).join(" · ")))))))));

  async function load() {
    const users = (await api.get("/api/users")).items;
    list.replaceChildren(el("div.table-wrap", {}, el("table", {},
      el("thead", {}, el("tr", {}, ["Usuario", "Nombre", "Correo", "Rol", "Estado", "Último acceso", ""].map((h) => el("th", {}, h)))),
      el("tbody", {}, users.map((u) => el("tr", {}, el("td.mono", {}, u.username), el("td", {}, u.full_name), el("td", {}, u.email || "—"),
        el("td", {}, u.role_name), el("td", {}, u.is_active ? badge("good", "Activo") : badge("", "Inactivo"),
          u.must_change_password ? badge("warn", "Contraseña temporal") : null),
        el("td", {}, fmt.datetime(u.last_login_at)),
        el("td.num", {}, el("button.btn.small", { type: "button", on: { click: () => userDialog(u) } }, "Editar"))))))));
  }

  function userDialog(user) {
    modal(user ? `Editar ${user.username}` : "Nuevo usuario", (body, close, foot) => {
      const form = el("form.form.two", {},
        user ? null : field("Usuario *", el("input", { name: "username", required: true, minlength: 3, maxlength: 50, pattern: "[a-zA-Z0-9._\\-]+", autocomplete: "off" })),
        field("Nombre completo *", el("input", { name: "full_name", required: true, maxlength: 150, value: user?.full_name || "" })),
        field("Correo", el("input", { name: "email", type: "email", maxlength: 150, value: user?.email || "" })),
        field("Rol *", options(el("select", { name: "role", required: true }), roles, { value: "code", selected: user?.role || "consulta" })),
        field(user ? "Nueva contraseña temporal (opcional)" : "Contraseña temporal *",
          el("input", { name: "password", type: "password", minlength: 10, maxlength: 128, required: !user, autocomplete: "new-password" }),
          "Mínimo 10 caracteres con letras y números. El usuario deberá cambiarla."),
        user ? el("label.check.full", {}, el("input", { type: "checkbox", name: "is_active", checked: user.is_active }), "Usuario activo") : null);
      body.append(form);
      foot.append(el("button.btn", { type: "button", on: { click: () => close(null) } }, "Cancelar"),
        el("button.btn.primary", {
          type: "button",
          on: {
            async click() {
              if (!form.reportValidity()) return;
              const data = formValues(form, { keepEmpty: user ? ["email"] : [] });
              try {
                if (user) await api.patch(`/api/users/${user.id}`, data);
                else await api.post("/api/users", data);
                toast("Usuario guardado", "good");
                close(true);
                load();
              } catch (e) { showError(e); }
            },
          },
        }, "Guardar"));
    });
  }
  load();
}
