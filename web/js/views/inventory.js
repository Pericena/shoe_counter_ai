// Existencias por modelo, talla y color + registro de movimientos (entradas, ventas, devoluciones, ajustes, conteos).
import { api, download } from "../api.js";
import {
  MOVEMENT_LABELS, el, empty, field, fmt, formValues, icon, modal, options, pageHead, pagedTable, queryString,
  showError, stockBadge, toast,
} from "../ui.js";

const SALES_TYPES = ["salida_venta", "devolucion_cliente"];
const MANUAL_TYPES = ["entrada_compra", "salida_venta", "devolucion_cliente", "devolucion_proveedor", "ajuste", "conteo_fisico"];

export function movementDialog(variant, { can, onDone }) {
  const allowed = MANUAL_TYPES.filter((t) => can("inventory.move") || (can("inventory.sell") && SALES_TYPES.includes(t)));
  return modal(`Movimiento · ${variant.sku}`, (body, close, foot) => {
    const type = options(el("select", { name: "movement_type", required: true }), allowed.map((t) => ({ id: t, name: MOVEMENT_LABELS[t] })));
    const qty = el("input", { name: "quantity", type: "number", step: 1, min: 1, required: true });
    const counted = el("input", { name: "counted_quantity", type: "number", step: 1, min: 0 });
    const cost = el("input", { name: "unit_cost", type: "number", min: 0, step: "0.01", value: variant.cost ?? "" });
    const reason = el("textarea", { name: "reason", maxlength: 1000 });
    const qtyField = field("Cantidad de pares *", qty);
    const countField = field("Pares contados físicamente *", counted, `Stock en sistema: ${variant.stock_quantity}. Se registrará la diferencia.`);
    const costField = field("Costo unitario", cost);
    const hint = el("p.small.muted");
    function sync() {
      const t = type.value;
      countField.classList.toggle("hidden", t !== "conteo_fisico");
      qtyField.classList.toggle("hidden", t === "conteo_fisico");
      costField.classList.toggle("hidden", t !== "entrada_compra");
      qty.min = t === "ajuste" ? "" : "1";
      hint.textContent = {
        ajuste: "Usa un número positivo para sumar o negativo para restar. El motivo es obligatorio.",
        salida_venta: `Disponibles: ${variant.stock_quantity} pares. No se permite vender más de lo disponible.`,
        devolucion_proveedor: `Disponibles: ${variant.stock_quantity} pares.`,
      }[t] || "";
    }
    type.addEventListener("change", sync);
    const form = el("form.form", {},
      el("div.alert.info", {}, `${variant.brand} ${variant.model_name} · talla ${variant.size} · ${variant.color} · stock actual ${variant.stock_quantity}`),
      field("Tipo de movimiento *", type), qtyField, countField, costField, hint,
      field("Motivo", reason), field("Referencia (factura, ticket…)", el("input", { name: "reference", maxlength: 100 })));
    sync();
    body.append(form);
    foot.append(el("button.btn", { type: "button", on: { click: () => close(null) } }, "Cancelar"),
      el("button.btn.primary", {
        type: "button",
        on: {
          async click() {
            const data = formValues(form, { ints: ["quantity", "counted_quantity"] });
            if (data.movement_type === "conteo_fisico") {
              delete data.quantity;
              if (Number.isNaN(data.counted_quantity) || data.counted_quantity === undefined) { counted.focus(); return; }
            } else {
              delete data.counted_quantity;
              if (!data.quantity) { qty.focus(); return; }
            }
            if (data.movement_type !== "entrada_compra") delete data.unit_cost;
            data.variant_id = variant.id;
            try {
              const result = await api.post("/api/inventory/movements", data);
              toast(result.movement ? `Registrado. Nuevo saldo: ${result.movement.balance_after} pares.` : result.message, "good");
              close(true);
              onDone();
            } catch (e) { showError(e); }
          },
        },
      }, "Registrar"));
  });
}

export async function render(root, _params, { can }) {
  const [brands, categories] = await Promise.all([api.get("/api/brands"), api.get("/api/categories")]);
  const summary = el("div.kpis");
  const canMove = can("inventory.move") || can("inventory.sell");
  const q = el("input", { type: "search", placeholder: "Marca, modelo, SKU o código de barras" });
  const brand = options(el("select"), brands.items, { placeholder: "Todas las marcas" });
  const category = options(el("select"), categories.items, { placeholder: "Todas las categorías" });
  const size = el("input", { placeholder: "Talla", size: 6 });
  const color = el("input", { placeholder: "Color", size: 8 });
  const state = options(el("select"), [{ id: "alerta", name: "Bajo o agotado" }, { id: "bajo", name: "Stock bajo" }, { id: "agotado", name: "Agotados" }], { placeholder: "Todos los estados" });
  const filterParams = () => ({ q: q.value, brand_id: brand.value, category_id: category.value, size: size.value, color: color.value, state: state.value });

  const table = pagedTable({
    pageSize: 50,
    fetchPage: ({ limit, offset }) => api.get("/api/inventory/stock" + queryString({ ...filterParams(), limit, offset })),
    onRows: (data) => {
      const s = data.summary;
      summary.replaceChildren(
        el("div.kpi", {}, el("div.label", {}, "Variantes (filtro)"), el("div.value", {}, fmt.int(s.variants))),
        el("div.kpi", {}, el("div.label", {}, "Pares"), el("div.value", {}, fmt.int(s.pairs))),
        el("div.kpi", {}, el("div.label", {}, "Valor a costo"), el("div.value", {}, fmt.money(s.inventory_value_at_cost)),
          s.inventory_value_complete ? null : el("div.note", {}, "Incompleto: hay variantes con stock y sin costo")),
        el("div.kpi", {}, el("div.label", {}, "Bajo / agotado"), el("div.value", {}, `${s.low} / ${s.out}`)));
    },
    emptyNode: empty("No hay variantes con estos filtros", "Crea productos y variantes en «Productos» o importa tu catálogo."),
    columns: [
      { label: "SKU", render: (v) => el("span.mono", {}, v.sku) },
      { label: "Producto", render: (v) => el("a", { href: `#/productos/${v.product_id}` }, `${v.brand} ${v.model_name}`) },
      { label: "Categoría", render: (v) => v.category || "—" },
      { label: "Talla", render: (v) => v.size },
      { label: "Color", render: (v) => v.color },
      { label: "Pares", className: "num", render: (v) => el("strong", {}, fmt.int(v.stock_quantity)) },
      { label: "Mín.", className: "num", render: (v) => v.min_stock },
      { label: "Estado", render: (v) => stockBadge(v.stock_state) },
      { label: "Precio", className: "num", render: (v) => fmt.money(v.price) },
      { label: "Valor costo", className: "num", render: (v) => fmt.money(v.inventory_value) },
      { label: "Vendidos 30 d", className: "num", render: (v) => fmt.int(v.sold_recent ?? 0) },
      { label: "Último mov.", render: (v) => v.last_movement_at ? fmt.date(v.last_movement_at) : "—" },
      { label: "", className: "num", render: (v) => el("span.actions", {},
        canMove ? el("button.btn.small.primary", { type: "button", on: { click: () => movementDialog(v, { can, onDone: () => table.reload(false) }) } }, "Movimiento") : null,
        el("a.btn.small", { href: `#/movimientos/${v.id}` }, "Historial")) },
    ],
  });

  const scan = el("form.filters", {
    on: {
      async submit(event) {
        event.preventDefault();
        const code = event.currentTarget.elements.code.value.trim();
        if (!code) return;
        try {
          const v = await api.get(`/api/variants/lookup?code=${encodeURIComponent(code)}`);
          event.currentTarget.reset();
          if (canMove) movementDialog(v, { can, onDone: () => table.reload(false) });
          else toast(`${v.sku}: ${v.stock_quantity} pares`);
        } catch (e) { showError(e); }
      },
    },
  }, el("input.grow", { name: "code", placeholder: "Escanea o escribe un SKU / código de barras", autocomplete: "off" }),
  el("button.btn", { type: "submit" }, icon("tag"), "Buscar código"));

  root.append(pageHead("Existencias", "Stock por modelo, talla y color. Solo cambia mediante movimientos registrados.",
    can("exports.run") ? el("button.btn", { type: "button", on: { click: () => download("/api/exports/existencias" + queryString({ ...filterParams(), format: "xlsx" })).catch(showError) } }, icon("download"), "Excel") : null,
    can("exports.run") ? el("button.btn", { type: "button", on: { click: () => download("/api/exports/existencias" + queryString({ ...filterParams(), format: "csv" })).catch(showError) } }, "CSV") : null,
    can("exports.run") && can("reports.view") ? el("button.btn", { type: "button", on: { click: () => download("/api/reports/inventario.pdf" + queryString(filterParams())).catch(showError) } }, "PDF") : null,
    el("button.btn", { type: "button", on: { click: checkLedger } }, "Verificar con movimientos")),
  scan, summary,
  el("form.filters", { on: { submit: (e) => { e.preventDefault(); table.reload(); } } }, q, brand, category, size, color, state,
    el("button.btn", { type: "submit" }, "Filtrar")),
  table.node);
  table.reload();

  async function checkLedger() {
    try {
      const r = await api.get("/api/inventory/reconciliation");
      if (r.ok) toast(`Correcto: el stock de ${r.variants_checked} variantes coincide con la suma de sus movimientos.`, "good");
      else toast(`Diferencias en ${r.mismatches.length} variantes: ${r.mismatches.map((m) => m.sku).join(", ")}`, "bad");
    } catch (e) { showError(e); }
  }
}
