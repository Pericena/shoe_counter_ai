import { api } from "../api.js";
import { badge, el, field, fmt, formValues, icon, modal, options, pageHead, showError, toast } from "../ui.js";

export async function render(root) {
  const roles = (await api.get("/api/roles")).items;
  const list = el("div");
  root.append(pageHead("Usuarios", "Las contraseñas se guardan con hash scrypt. Los usuarios nuevos deben cambiar su contraseña temporal al entrar.",
    el("button.btn.primary", { type: "button", on: { click: () => userDialog(null) } }, icon("plus"), "Nuevo usuario")),
  list,
  el("div.card", { class: "stack" }, el("h2", {}, "Roles y permisos"), el("div.table-wrap", {}, el("table", {},
    el("thead", {}, el("tr", {}, el("th", {}, "Rol"), el("th", {}, "Permisos"))),
    el("tbody", {}, roles.map((r) => el("tr", {}, el("td", {}, el("strong", {}, r.name), el("div.small.muted", {}, r.code)),
      el("td.wrap", {}, r.permissions.join(", ")))))))));

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
