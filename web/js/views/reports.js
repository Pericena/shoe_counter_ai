// Reportes de inventario calculados desde la base de datos.
import { api, download } from "../api.js";
import { barChart, hBarChart } from "../charts.js";
import { MOVEMENT_LABELS, el, empty, fmt, icon, options, pageHead, queryString, showError } from "../ui.js";

function isoDate(date) { return date.toISOString().slice(0, 10); }

export async function render(root, _params, { can }) {
  const [categories, brands] = await Promise.all([api.get("/api/categories"), api.get("/api/brands")]);
  const today = new Date();
  const from = el("input", { type: "date", value: isoDate(new Date(today.getTime() - 89 * 86400000)) });
  const to = el("input", { type: "date", value: isoDate(today) });
  const group = options(el("select"), [{ id: "day", name: "Día" }, { id: "week", name: "Semana" }, { id: "month", name: "Mes" }], { selected: "week" });
  const category = options(el("select"), categories.items, { placeholder: "Todas" });
  const brand = options(el("select"), brands.items, { placeholder: "Todas" });
  const body = el("div.stack");
  const params = () => ({ from: from.value, to: to.value, category_id: category.value, brand_id: brand.value });

  root.append(pageHead("Reportes de inventario", "Indicadores calculados con los movimientos registrados. Las fórmulas se indican bajo cada bloque.",
    can("exports.run") ? el("button.btn", { type: "button", on: { click: () => download("/api/reports/inventario.pdf").catch(showError) } }, icon("download"), "Informe PDF de inventario") : null),
  el("form.filters", { on: { submit: (e) => { e.preventDefault(); load(); } } },
    el("label.field", {}, "Desde", from), el("label.field", {}, "Hasta", to), el("label.field", {}, "Agrupar por", group),
    el("label.field", {}, "Categoría", category), el("label.field", {}, "Marca", brand), el("button.btn.primary", { type: "submit" }, "Actualizar")),
  body);

  async function load() {
    body.replaceChildren(el("div.loading", {}, el("span.spinner"), " Calculando…"));
    try {
      const [series, rotation, adjustments, counts] = await Promise.all([
        api.get("/api/reports/movements" + queryString({ ...params(), group: group.value })),
        api.get("/api/reports/rotation" + queryString(params())),
        api.get("/api/reports/adjustments" + queryString(params())),
        api.get("/api/reports/counts" + queryString({ from: from.value, to: to.value })),
      ]);
      body.replaceChildren();

      const movCard = el("div.card", {}, el("h2", {}, "Entradas y salidas por período (pares)"));
      movCard.append(series.series.length ? barChart({
        categories: series.series.map((p) => p.period),
        series: [{ name: "Entradas", cls: "s1", values: series.series.map((p) => p.entradas) },
          { name: "Salidas", cls: "s2", values: series.series.map((p) => p.salidas) }],
        categoryLabel: "Período",
        note: "Entradas = Σ cantidades positivas; salidas = Σ |cantidades negativas| (ventas, pedidos, devoluciones a proveedor, ajustes y conteos a la baja).",
      }) : empty("Sin movimientos en el período", "Amplía el rango de fechas o registra movimientos."));
      const totals = Object.entries(series.totals_by_type);
      if (totals.length) {
        movCard.append(el("h3", {}, "Totales por tipo"), el("ul.list", {}, totals.map(([type, qty]) =>
          el("li", {}, el("span", {}, MOVEMENT_LABELS[type] || type), el("strong.num", {}, (qty > 0 ? "+" : "") + fmt.int(qty))))));
      }
      body.append(movCard);

      const rotCard = el("div.card", {}, el("h2", {}, "Productos de mayor rotación"));
      if (!rotation.has_data) {
        rotCard.append(empty("Sin datos suficientes", rotation.message));
      } else {
        rotCard.append(hBarChart({
          items: rotation.items.map((i) => ({ label: `${i.sku} (T${i.size})`, value: i.net_units })),
          name: "Unidades vendidas netas",
          note: "Unidades netas = ventas + pedidos online − devoluciones de clientes del período.",
        }));
        rotCard.append(el("div.table-wrap", {}, el("table", {},
          el("thead", {}, el("tr", {}, ["SKU", "Producto", "Vendidas", "Devueltas", "Stock inicio", "Stock fin", "Stock medio", "Rotación"].map((h) => el("th", {}, h)))),
          el("tbody", {}, rotation.items.map((i) => el("tr", {}, el("td.mono", {}, i.sku), el("td", {}, `${i.product} · ${i.color}`),
            el("td.num", {}, i.units_sold), el("td.num", {}, i.returns), el("td.num", {}, i.stock_start), el("td.num", {}, i.stock_end),
            el("td.num", {}, fmt.dec(i.average_stock, 1)), el("td.num", {}, i.rotation === null ? "—" : fmt.dec(i.rotation))))))),
        el("p.chart-note", {}, "Rotación = unidades vendidas netas / stock medio, con stock medio = (stock al inicio + stock al final) / 2 reconstruido del libro de movimientos. No se calcula si el stock medio es 0."));
      }
      body.append(rotCard);

      const adjCard = el("div.card", {}, el("h2", {}, "Ajustes y diferencias de conteo físico"),
        el("div.kpis", {},
          el("div.kpi", {}, el("div.label", {}, "Pares sumados por ajuste"), el("div.value", {}, `+${fmt.int(adjustments.total_positive)}`)),
          el("div.kpi", {}, el("div.label", {}, "Pares restados por ajuste"), el("div.value", {}, `−${fmt.int(adjustments.total_negative)}`)),
          el("div.kpi", {}, el("div.label", {}, "Conteos físicos con diferencia"), el("div.value", {}, fmt.int(adjustments.physical_counts_with_difference)))));
      adjCard.append(adjustments.items.length ? el("div.table-wrap", {}, el("table", {},
        el("thead", {}, el("tr", {}, ["Fecha", "SKU", "Tipo", "Diferencia", "Saldo", "Motivo", "Usuario"].map((h) => el("th", {}, h)))),
        el("tbody", {}, adjustments.items.map((m) => el("tr", {}, el("td", {}, fmt.datetime(m.created_at)), el("td.mono", {}, m.sku),
          el("td", {}, MOVEMENT_LABELS[m.movement_type]), el("td.num", {}, (m.quantity > 0 ? "+" : "") + m.quantity),
          el("td.num", {}, m.balance_after), el("td.wrap", {}, m.reason || "—"), el("td", {}, m.user || "—"))))))
        : empty("Sin ajustes en el período", ""));
      body.append(adjCard);

      const aiCard = el("div.card", {}, el("h2", {}, "Conteos inteligentes"));
      if (!counts.total) {
        aiCard.append(empty("Sin conteos en el período", "Los conteos con foto aparecerán aquí."));
      } else {
        aiCard.append(el("div.kpis", {},
          el("div.kpi", {}, el("div.label", {}, "Conteos"), el("div.value", {}, fmt.int(counts.total))),
          el("div.kpi", {}, el("div.label", {}, "Solo manuales (sin modelo)"), el("div.value", {}, fmt.int(counts.manual_only))),
          el("div.kpi", {}, el("div.label", {}, "Error medio del modelo"), el("div.value", {}, counts.accuracy ? fmt.dec(counts.accuracy.mae) : "—"),
            el("div.note", {}, counts.accuracy ? `zapatos por foto · exactos ${fmt.pct(counts.accuracy.exact_rate)} (${counts.accuracy.counts} conteos confirmados)` : "Sin conteos con modelo confirmados"))));
        aiCard.append(el("p.chart-note", {}, "Error de conteo = |detectados por el modelo − zapatos confirmados por la persona|. Solo cuenta conteos confirmados con modelo."));
        if (counts.applied_differences.length) {
          aiCard.append(el("div.table-wrap", {}, el("table", {},
            el("thead", {}, el("tr", {}, ["Conteo", "SKU", "Stock antes", "Contado", "Diferencia"].map((h) => el("th", {}, h)))),
            el("tbody", {}, counts.applied_differences.map((d) => el("tr", {}, el("td", {}, el("a", { href: `#/conteo/${d.count_id}` }, `#${d.count_id}`)),
              el("td.mono", {}, d.sku), el("td.num", {}, d.stock_before), el("td.num", {}, d.counted), el("td.num", {}, (d.difference > 0 ? "+" : "") + d.difference)))))));
        }
      }
      body.append(aiCard);
    } catch (e) {
      showError(e);
      body.replaceChildren(el("div.alert.bad", {}, e.message));
    }
  }
  load();
}
