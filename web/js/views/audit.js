import { api } from "../api.js";
import { el, empty, fmt, options, pageHead, pagedTable, queryString } from "../ui.js";

export async function render(root) {
  const first = await api.get("/api/audit?limit=1");
  const action = options(el("select"), first.actions.map((a) => ({ id: a, name: a })), { placeholder: "Todas las acciones" });
  const user = el("input", { placeholder: "Usuario" });
  const from = el("input", { type: "date" });
  const to = el("input", { type: "date" });
  const table = pagedTable({
    pageSize: 50,
    fetchPage: ({ limit, offset }) => api.get("/api/audit" + queryString({ action: action.value, username: user.value, from: from.value, to: to.value, limit, offset })),
    emptyNode: empty("Sin registros", ""),
    columns: [
      { label: "Fecha", render: (a) => fmt.datetime(a.created_at) },
      { label: "Usuario", render: (a) => a.username || "—" },
      { label: "Acción", render: (a) => el("strong", {}, a.action) },
      { label: "Entidad", render: (a) => a.entity_type ? `${a.entity_type} #${a.entity_id ?? ""}` : "—" },
      { label: "Detalle", className: "wrap", render: (a) => a.details ? el("span.mono", {}, JSON.stringify(a.details)) : "—" },
      { label: "IP", render: (a) => a.ip_address || "—" },
    ],
  });
  root.append(pageHead("Auditoría", "Registro de inicios de sesión, cambios de catálogo, movimientos, conteos, importaciones, exportaciones y pedidos."),
    el("form.filters", { on: { submit: (e) => { e.preventDefault(); table.reload(); } } },
      el("label.field", {}, "Acción", action), el("label.field", {}, "Usuario", user), el("label.field", {}, "Desde", from),
      el("label.field", {}, "Hasta", to), el("button.btn", { type: "submit" }, "Filtrar")),
    table.node);
  table.reload();
}
