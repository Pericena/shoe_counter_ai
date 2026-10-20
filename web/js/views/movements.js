import { api, download } from "../api.js";
import { MOVEMENT_LABELS, badge, el, empty, fmt, icon, options, pageHead, pagedTable, queryString, showError } from "../ui.js";

export async function render(root, params, { can }) {
  const variantId = params[0] ? Number(params[0]) : null;
  let variant = null;
  if (variantId) {
    try { variant = await api.get(`/api/variants/${variantId}`); } catch (e) { showError(e); }
  }
  const type = options(el("select"), Object.entries(MOVEMENT_LABELS).map(([id, name]) => ({ id, name })), { placeholder: "Todos los tipos" });
  const from = el("input", { type: "date", "aria-label": "Desde" });
  const to = el("input", { type: "date", "aria-label": "Hasta" });
  const filterParams = () => ({ variant_id: variantId, movement_type: type.value, from: from.value, to: to.value });

  const table = pagedTable({
    pageSize: 50,
    fetchPage: ({ limit, offset }) => api.get("/api/inventory/movements" + queryString({ ...filterParams(), limit, offset })),
    emptyNode: empty("Sin movimientos", "No hay movimientos con estos filtros."),
    columns: [
      { label: "Fecha", render: (m) => fmt.datetime(m.created_at) },
      { label: "SKU", render: (m) => el("a.mono", { href: `#/movimientos/${m.variant_id}` }, m.sku) },
      { label: "Producto", render: (m) => `${m.product} · T${m.size} ${m.color}` },
      { label: "Tipo", render: (m) => badge(m.quantity > 0 ? "good" : "warn", MOVEMENT_LABELS[m.movement_type] || m.movement_type) },
      { label: "Cantidad", className: "num", render: (m) => el("strong", {}, (m.quantity > 0 ? "+" : "") + m.quantity) },
      { label: "Saldo", className: "num", render: (m) => m.balance_after },
      { label: "Costo u.", className: "num", render: (m) => fmt.money(m.unit_cost) },
      { label: "Motivo / referencia", className: "wrap", render: (m) => [m.reason, m.reference].filter(Boolean).join(" · ") || "—" },
      { label: "Usuario", render: (m) => m.user || "sistema" },
    ],
  });
  root.append(pageHead(variant ? `Historial de ${variant.sku}` : "Movimientos de inventario",
    variant ? `Talla ${variant.size} · ${variant.color} · stock actual ${variant.stock_quantity} pares` : "Libro mayor: cada cambio de stock queda registrado y no se puede editar ni borrar.",
    variant ? el("a.btn", { href: "#/movimientos" }, "Ver todos") : null,
    can("exports.run") ? el("button.btn", { type: "button", on: { click: () => download("/api/exports/movimientos" + queryString({ ...filterParams(), format: "xlsx" })).catch(showError) } }, icon("download"), "Excel") : null,
    can("exports.run") ? el("button.btn", { type: "button", on: { click: () => download("/api/exports/movimientos" + queryString({ ...filterParams(), format: "csv" })).catch(showError) } }, "CSV") : null),
  el("form.filters", { on: { submit: (e) => { e.preventDefault(); table.reload(); } } },
    el("label.field", {}, "Tipo", type), el("label.field", {}, "Desde", from), el("label.field", {}, "Hasta", to),
    el("button.btn", { type: "submit" }, "Filtrar")),
  table.node);
  table.reload();
}
