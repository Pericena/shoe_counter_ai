// BI de comercio exterior de calzado (caso de estudio). Datos externos: no se mezclan con el stock.
import { api, download } from "../api.js";
import { barChart, hBarChart, lineChart } from "../charts.js";
import { el, empty, fmt, icon, options, pageHead, pagedTable, queryString, showError } from "../ui.js";

export async function render(root, _params, { can }) {
  const opts = await api.get("/api/trade/options");
  root.append(pageHead("Comercio exterior", "Importaciones y exportaciones de calzado por año, socio y categoría. Son datos importados: no son ventas de esta tienda."));
  if (!opts.years.length) {
    root.append(empty("No hay datos comerciales importados",
      "Importa el archivo de comercio exterior (columnas País_reportante, Flujo_comercial, Año, Código_SA6, …) desde «Importar Excel/CSV».",
      can("imports.manage") ? el("a.btn.primary", { href: "#/importar" }, "Ir a importar") : null));
    return;
  }
  const yearFrom = options(el("select"), opts.years.map((y) => ({ id: y, name: y })), { placeholder: "Desde", selected: opts.years[0] });
  const yearTo = options(el("select"), opts.years.map((y) => ({ id: y, name: y })), { placeholder: "Hasta", selected: opts.years.at(-1) });
  const flow = options(el("select"), opts.flows.map((f) => ({ id: f, name: f })), { placeholder: "Todos los flujos" });
  const category = options(el("select"), opts.categories.map((c) => ({ id: c, name: c })), { placeholder: "Todas las categorías" });
  const partner = options(el("select"), opts.partners.map((p) => ({ id: p, name: p })), { placeholder: "Todos los socios" });
  const metric = options(el("select"), [{ id: "value_usd", name: "Valor USD" }, { id: "quantity_pairs", name: "Cantidad de pares" }], { selected: "value_usd" });
  const aggregates = el("input", { type: "checkbox" });
  const body = el("div.stack");
  const filters = () => ({ year_from: yearFrom.value, year_to: yearTo.value, flow: flow.value, category: category.value,
    partner: partner.value, include_aggregates: aggregates.checked ? "1" : "" });

  root.append(el("form.filters", { on: { submit: (e) => { e.preventDefault(); load(); } } },
    el("label.field", {}, "Año desde", yearFrom), el("label.field", {}, "Año hasta", yearTo), el("label.field", {}, "Flujo", flow),
    el("label.field", {}, "Categoría", category), el("label.field", {}, "Socio", partner), el("label.field", {}, "Ranking por", metric),
    el("label.check", {}, aggregates, "Incluir agregados («Mundo»)"), el("button.btn.primary", { type: "submit" }, "Aplicar")),
  body);

  async function load() {
    body.replaceChildren(el("div.loading", {}, el("span.spinner"), " Consultando…"));
    try {
      const [summary, synthesis] = await Promise.all([
        api.get("/api/trade/summary" + queryString({ ...filters(), metric: metric.value })),
        api.get("/api/trade/synthesis" + queryString(filters()))]);
      body.replaceChildren();
      if (!summary.records) { body.append(empty("Sin registros con estos filtros", "Amplía el rango de años o quita un filtro de flujo, categoría o socio.")); return; }
      const flows = [...new Set(summary.by_year_flow.map((r) => r.flow))];
      const years = [...new Set(summary.by_year_flow.map((r) => r.year))].sort();
      const pick = (f, key) => years.map((y) => summary.by_year_flow.find((r) => r.year === y && r.flow === f)?.[key] ?? 0);
      const cls = ["s1", "s2", "s3"];
      const quality = summary.quality;

      body.append(el("div.kpis", {},
        ...flows.map((f) => el("div.kpi", {}, el("div.label", {}, `Valor ${f}`), el("div.value", {}, fmt.compact(pick(f, "value_usd").reduce((a, b) => a + b, 0))), el("div.note", {}, "USD"))),
        el("div.kpi", {}, el("div.label", {}, "Registros analizados"), el("div.value", {}, fmt.int(summary.records)),
          el("div.note", {}, quality.aggregates_excluded ? "Sin agregados (evita doble conteo)" : "Incluye agregados")),
        el("div.kpi", {}, el("div.label", {}, "Completitud"), el("div.value", {}, fmt.pct(quality.completeness)), el("div.note", {}, "Filas con valor y cantidad"))));

      const grid = el("div.grid.cols-2");
      body.append(grid);
      const flowSeries = flows.slice(0, 3).map((f, i) => ({ name: f, cls: cls[i] }));
      grid.append(el("div.card", {}, el("h2", {}, "Valor por flujo y año (USD)"),
        barChart({ categories: years, series: flowSeries.map((s) => ({ ...s, values: pick(s.name, "value_usd") })), format: fmt.int, categoryLabel: "Año" })));
      grid.append(el("div.card", {}, el("h2", {}, "Cantidad por flujo y año (pares)"),
        barChart({ categories: years, series: flowSeries.map((s) => ({ ...s, values: pick(s.name, "quantity_pairs") })), format: fmt.int, categoryLabel: "Año",
          note: "Mismo período en un gráfico aparte: valor y cantidad tienen escalas distintas y no comparten eje." })));
      grid.append(el("div.card", {}, el("h2", {}, `Principales socios por ${metric.value === "value_usd" ? "valor USD" : "pares"}`),
        hBarChart({ items: summary.top_partners.map((p) => ({ label: `${p.partner} (${p.flow})`, value: p[metric.value] })),
          name: metric.value === "value_usd" ? "Valor USD" : "Pares", format: fmt.int })));
      const perPairYears = [...new Set(summary.value_per_pair_by_year.map((r) => r.year))].sort();
      grid.append(el("div.card", {}, el("h2", {}, "Valor aproximado por par (USD)"),
        perPairYears.length ? lineChart({
          categories: perPairYears,
          series: flowSeries.map((s) => ({ ...s, values: perPairYears.map((y) => summary.value_per_pair_by_year.find((r) => r.year === y && r.flow === s.name)?.value_per_pair ?? null) })),
          format: (v) => fmt.dec(v), categoryLabel: "Año",
          note: "Suma del valor en USD dividida entre la suma de pares, solo filas con ambos mayores que 0 y sin agregados. Mezcla productos distintos: no es un precio de venta de la tienda.",
        }) : empty("No calculable", "No hay filas con valor y cantidad válidos.")));

      if (summary.annual_variation.length) {
        body.append(el("div.card", {}, el("h2", {}, "Variación anual del valor"), el("div.table-wrap", {}, el("table", {},
          el("thead", {}, el("tr", {}, el("th", {}, "Flujo"), el("th", {}, "Año"), el("th.num", {}, "Variación vs. año anterior"))),
          el("tbody", {}, summary.annual_variation.map((v) => el("tr", {}, el("td", {}, v.flow), el("td", {}, v.year),
            el("td.num", {}, `${v.value_change_pct > 0 ? "+" : ""}${fmt.dec(v.value_change_pct, 1)} %`))))))));
      }
      if (summary.by_category.length) {
        body.append(el("div.card", {}, el("h2", {}, "Valor y cantidad por categoría"), el("div.table-wrap", {}, el("table", {},
          el("thead", {}, el("tr", {}, ["Categoría", "Flujo", "Valor USD", "Pares"].map((h) => el("th", {}, h)))),
          el("tbody", {}, summary.by_category.map((c) => el("tr", {}, el("td", {}, c.category), el("td", {}, c.flow),
            el("td.num", {}, fmt.int(c.value_usd)), el("td.num", {}, fmt.int(c.quantity_pairs)))))))));
      }

      if (synthesis.available) {
        body.append(el("div.card", {}, el("h2", {}, "Síntesis ejecutiva (calculada)"),
          el("h3", {}, "Hallazgos"), el("ul", {}, synthesis.findings.map((f) => el("li", {}, f))),
          el("h3", {}, "Limitaciones de los datos"), el("ul", {}, synthesis.limitations.map((f) => el("li", {}, f))),
          el("h3", {}, "Pregunta estratégica"), el("p", {}, synthesis.strategic_question),
          el("h3", {}, "Recomendación"), el("p", {}, synthesis.recommendation),
          el("p.small.muted", {}, `Visualizaciones: ${synthesis.visualizations.join(" · ")}. Filas usadas: ${synthesis.records_used}. Generado ${fmt.datetime(synthesis.generated_at)}. `,
            "Evidencia externa: no demuestra por sí sola problemas internos de ninguna empresa (p. ej. Manaco); sirve para formular hipótesis.")));
      }

      const exportBar = el("div.actions", {},
        el("button.btn", { type: "button", on: { click: () => download("/api/exports/comercio" + queryString({ ...filters(), format: "xlsx" })).catch(showError) } }, icon("download"), "Registros filtrados (Excel)"),
        el("button.btn", { type: "button", on: { click: () => download("/api/exports/comercio" + queryString({ ...filters(), format: "csv" })).catch(showError) } }, "CSV"),
        el("button.btn", { type: "button", on: { click: () => download("/api/exports/comercio_resumen" + queryString({ ...filters(), format: "xlsx" })).catch(showError) } }, "Indicadores agregados"),
        el("button.btn", { type: "button", on: { click: () => download("/api/reports/comercio.pdf" + queryString(filters())).catch(showError) } }, "Informe ejecutivo PDF"));
      const records = pagedTable({
        pageSize: 25,
        fetchPage: ({ limit, offset }) => api.get("/api/trade/records" + queryString({ ...filters(), limit, offset })),
        columns: [
          { label: "Año", render: (r) => r.year }, { label: "Flujo", render: (r) => r.flow }, { label: "SA6", render: (r) => el("span.mono", {}, r.hs6_code) },
          { label: "Categoría", className: "wrap", render: (r) => r.category || "—" }, { label: "Socio", render: (r) => r.partner + (r.is_aggregate ? " (agregado)" : "") },
          { label: "Valor USD", className: "num", render: (r) => fmt.int(r.value_usd) }, { label: "Pares", className: "num", render: (r) => fmt.int(r.quantity_pairs) },
          { label: "USD/par", className: "num", render: (r) => r.value_usd_per_pair === null ? "—" : fmt.dec(r.value_usd_per_pair) },
          { label: "Calidad", className: "wrap", render: (r) => r.quality_flags.join(", ") || "—" },
        ],
      });
      body.append(el("div.card", {}, el("h2", {}, "Registros"), can("exports.run") ? exportBar : null, records.node));
      records.reload();
    } catch (e) {
      showError(e);
      body.replaceChildren(el("div.alert.bad", {}, e.message));
    }
  }
  load();
}
