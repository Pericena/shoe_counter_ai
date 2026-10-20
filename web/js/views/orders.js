import { api, download } from "../api.js";
import { badge, el, empty, field, fmt, icon, modal, options, pageHead, pagedTable, queryString, showError, toast } from "../ui.js";

const LABELS = {
  creado: ["info", "Creado (pendiente de pago)"], pago_confirmado: ["good", "Pago confirmado"], preparado: ["good", "Preparado"],
  enviado: ["good", "Enviado"], entregado: ["good", "Entregado"], cancelado: ["", "Cancelado"], devuelto: ["warn", "Devuelto"],
};
const statusBadge = (s) => badge(...(LABELS[s] || ["", s]));

export async function render(root, params, ctx) {
  if (params[0]) return renderDetail(root, Number(params[0]), ctx);
  const status = options(el("select"), Object.entries(LABELS).map(([id, [, name]]) => ({ id, name })), { placeholder: "Todos los estados" });
  const q = el("input", { type: "search", placeholder: "Código, cliente o correo" });
  const filterParams = () => ({ status: status.value, q: q.value });
  const table = pagedTable({
    fetchPage: ({ limit, offset }) => api.get("/api/orders" + queryString({ ...filterParams(), limit, offset })),
    emptyNode: empty("Sin pedidos", "Los pedidos de la tienda online aparecerán aquí. Publica productos para que se muestren en el catálogo."),
    columns: [
      { label: "Pedido", render: (o) => el("a.mono", { href: `#/pedidos/${o.id}` }, o.code) },
      { label: "Fecha", render: (o) => fmt.datetime(o.created_at) },
      { label: "Cliente", render: (o) => o.customer_name },
      { label: "Correo", render: (o) => o.customer_email },
      { label: "Pares", className: "num", render: (o) => o.items },
      { label: "Total", className: "num", render: (o) => fmt.money(o.total_amount) },
      { label: "Estado", render: (o) => statusBadge(o.status) },
    ],
  });
  root.append(pageHead("Pedidos online", "Cobro manual: el pago se confirma registrando su referencia. No hay pasarela de pago configurada.",
    ctx.can("exports.run") ? el("button.btn", { type: "button", on: { click: () => download("/api/exports/pedidos" + queryString({ status: status.value, format: "xlsx" })).catch(showError) } }, icon("download"), "Excel") : null),
  el("form.filters", { on: { submit: (e) => { e.preventDefault(); table.reload(); } } }, q, status, el("button.btn", { type: "submit" }, "Filtrar")),
  table.node);
  table.reload();
}

async function renderDetail(root, id, { can }) {
  const order = await api.get(`/api/orders/${id}`);
  const reload = () => { root.replaceChildren(); renderDetail(root, id, { can }); };
  root.append(pageHead(`Pedido ${order.code}`, `${fmt.datetime(order.created_at)} · ${order.status_label}`, el("a.btn", { href: "#/pedidos" }, "← Pedidos")));
  const grid = el("div.grid.cols-2");
  grid.append(el("div.card", {}, el("h2", {}, "Cliente"), el("dl.dl", {},
    el("dt", {}, "Nombre"), el("dd", {}, order.customer_name), el("dt", {}, "Correo"), el("dd", {}, order.customer_email),
    el("dt", {}, "Teléfono"), el("dd", {}, order.customer_phone || "—"), el("dt", {}, "Dirección"), el("dd", {}, order.shipping_address || "—"),
    el("dt", {}, "Notas"), el("dd", {}, order.notes || "—"), el("dt", {}, "Ref. de pago"), el("dd", {}, order.payment_reference || "—"))));
  const actions = el("div.card", {}, el("h2", {}, "Estado"), el("p", {}, statusBadge(order.status)));
  if (can("orders.manage") && order.allowed_transitions.length) {
    actions.append(el("div.actions", {}, order.allowed_transitions.map((next) => el(`button.btn${next === "cancelado" || next === "devuelto" ? ".danger" : ".primary"}`, {
      type: "button", on: { click: () => transition(next) },
    }, `→ ${LABELS[next][1]}`))));
    actions.append(el("p.small.muted", {}, "Cancelar repone el stock reservado. «Devuelto» lo repone como devolución de cliente."));
  } else if (!order.allowed_transitions.length) {
    actions.append(el("p.muted", {}, "Estado final."));
  }
  grid.append(actions);
  root.append(grid, el("div.stack", {},
    el("div.card", {}, el("h2", {}, "Productos"), el("div.table-wrap", {}, el("table", {},
      el("thead", {}, el("tr", {}, ["SKU", "Descripción", "Talla", "Color", "Cantidad", "Precio", "Total"].map((h) => el("th", {}, h)))),
      el("tbody", {}, order.items.map((i) => el("tr", {}, el("td.mono", {}, i.sku), el("td", {}, i.description), el("td", {}, i.size), el("td", {}, i.color),
        el("td.num", {}, i.quantity), el("td.num", {}, fmt.money(i.unit_price)), el("td.num", {}, fmt.money(i.line_total)))),
      el("tr", {}, el("td", { colspan: 6 }, el("strong", {}, "Total")), el("td.num", {}, el("strong", {}, fmt.money(order.total_amount)))))))),
    el("div.card", {}, el("h2", {}, "Historial"), el("ul.list", {}, order.history.map((h) => el("li", {},
      el("span", {}, el("strong", {}, h.to_label), h.note ? el("div.small.muted", {}, h.note) : null),
      el("span.small.muted", {}, `${fmt.datetime(h.created_at)} · ${h.user || "cliente web"}`)))))));

  async function transition(next) {
    const payload = await modal(`Cambiar a «${LABELS[next][1]}»`, (body, close, foot) => {
      const reference = el("input", { maxlength: 100, required: true, placeholder: "N.º de transferencia, recibo…" });
      const note = el("textarea", { maxlength: 1000 });
      if (next === "pago_confirmado") body.append(field("Referencia del pago recibido *", reference));
      body.append(field(next === "cancelado" || next === "devuelto" ? "Motivo *" : "Nota", note));
      foot.append(el("button.btn", { type: "button", on: { click: () => close(null) } }, "Cancelar"),
        el("button.btn.primary", {
          type: "button",
          on: {
            click: () => {
              if (next === "pago_confirmado" && !reference.value.trim()) { reference.focus(); return; }
              if ((next === "cancelado" || next === "devuelto") && !note.value.trim()) { note.focus(); return; }
              close({ status: next, note: note.value.trim(), payment_reference: reference.value.trim() });
            },
          },
        }, "Guardar"));
    });
    if (!payload) return;
    try { await api.post(`/api/orders/${id}/status`, payload); toast("Estado actualizado", "good"); reload(); } catch (e) { showError(e); }
  }
}
