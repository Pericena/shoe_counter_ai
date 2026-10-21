import { api } from "../api.js";
import { barChart } from "../charts.js";
import { MOVEMENT_LABELS, badge, el, empty, fmt, pageHead, stockBadge } from "../ui.js";

function kpi(label, value, note) {
  return el("div.kpi", {}, el("div.label", {}, label), el("div.value", {}, value), note ? el("div.note", {}, note) : null);
}

export async function render(root, _params, { can }) {
  const data = await api.get("/api/reports/overview");
  const inv = data.inventory;
  root.append(pageHead("Panel", "Existencias, ventas y pedidos de la tienda en este momento."));

  if (inv.variants === 0) {
    root.append(el("div.alert.info", {},
      el("strong", {}, "Todavía no hay productos registrados. "),
      "Empieza en ", el("a", { href: "#/productos" }, "Productos"), " (marca, luego producto, luego tallas y colores), ",
      "o importa tu catálogo desde ", el("a", { href: "#/importar" }, "Importar Excel/CSV"), ". ",
      "Después registra las entradas de stock en ", el("a", { href: "#/inventario" }, "Existencias"), "."));
  }

  root.append(el("div.kpis", {},
    kpi("Productos / variantes", `${fmt.int(inv.products)} / ${fmt.int(inv.variants)}`),
    kpi("Pares disponibles", fmt.int(inv.pairs)),
    kpi("Valor del inventario (costo)", fmt.money(inv.inventory_value_at_cost),
      inv.variants_with_stock_without_cost ? `Incompleto: ${inv.variants_with_stock_without_cost} variantes con stock y sin costo` : "Costo de cada variante por sus pares"),
    kpi("Stock bajo / agotados", `${fmt.int(inv.low)} / ${fmt.int(inv.out)}`),
    kpi("Ventas últimos 30 días", `${fmt.int(data.last_30_days.units_sold)} pares`, "Mostrador y pedidos online, sin restar devoluciones"),
    kpi("Pedidos abiertos", fmt.int(data.orders_open)),
    kpi("Conteos por revisar", fmt.int(data.counts_pending))));

  const grid = el("div.grid.cols-2");
  root.append(grid);

  // Alertas de stock
  const alerts = el("div.card", {}, el("h2", {}, "Alertas de stock"));
  if (!data.alerts.length) {
    alerts.append(empty("Sin alertas", inv.variants ? "Ninguna variante activa está por debajo de su stock mínimo." : "Aún no hay variantes."));
  } else {
    alerts.append(el("div.table-wrap", {}, el("table", {},
      el("thead", {}, el("tr", {}, ["SKU", "Producto", "Talla", "Color", "Stock", "Mín.", "Estado"].map((h) => el("th", {}, h)))),
      el("tbody", {}, data.alerts.map((a) => el("tr", {}, el("td.mono", {}, a.sku), el("td", {}, a.product), el("td", {}, a.size),
        el("td", {}, a.color), el("td.num", {}, a.stock), el("td.num", {}, a.min_stock), el("td", {}, stockBadge(a.state))))))));
  }
  grid.append(alerts);

  // Movimientos (series)
  const chartCard = el("div.card", {}, el("h2", {}, "Entradas y salidas — últimos 30 días"));
  grid.append(chartCard);
  if (can("reports.view")) {
    const series = await api.get("/api/reports/movements?group=week");
    if (!series.series.length) {
      chartCard.append(empty("Sin movimientos en el período", "Registra entradas o ventas para ver la evolución."));
    } else {
      chartCard.append(barChart({
        categories: series.series.map((p) => `Sem. ${p.period.slice(5)}`),
        series: [
          { name: "Entradas (pares)", cls: "s1", values: series.series.map((p) => p.entradas) },
          { name: "Salidas (pares)", cls: "s2", values: series.series.map((p) => p.salidas) },
        ],
        categoryLabel: "Semana (inicio)",
      }));
    }
  } else {
    chartCard.append(el("p.muted", {}, "Tu rol no puede ver el movimiento de pares."));
  }

  // Actividad reciente
  const recent = el("div.card", {}, el("h2", {}, "Movimientos recientes"));
  if (!data.recent_movements.length) {
    recent.append(empty("Sin movimientos", "Cada entrada, venta, devolución o ajuste aparecerá aquí."));
  } else {
    recent.append(el("ul.list", {}, data.recent_movements.map((m) => el("li", {},
      el("span", {}, el("strong", {}, MOVEMENT_LABELS[m.movement_type] || m.movement_type), " · ",
        el("span.mono", {}, m.sku), el("div.small.muted", {}, `${fmt.datetime(m.created_at)} · ${m.user || "sistema"}`)),
      el("span.num", {}, (m.quantity > 0 ? "+" : "") + m.quantity, el("div.small.muted", {}, `saldo ${m.balance_after}`))))));
  }
  grid.append(recent);

  // Estado del sistema
  const status = el("div.card", {}, el("h2", {}, "Detector, comercio e importaciones"));
  const model = data.ai_model;
  status.append(el("ul.list", {},
    el("li", {}, el("span", {}, "Modelo de detección de zapatos"),
      model.installed ? badge("good", `Instalado: ${model.version}`) : badge("warn", "No instalado")),
    !model.installed ? el("li", {}, el("span.small.muted", {}, model.message)) : null,
    el("li", {}, el("span", {}, "Registros de comercio exterior"), el("span", {}, fmt.int(data.trade_records)))));
  if (data.recent_imports.length) {
    status.append(el("h3", {}, "Últimas importaciones"), el("ul.list", {}, data.recent_imports.map((b) => el("li", {},
      el("span", {}, `#${b.id} ${b.file_name}`, el("div.small.muted", {}, `${b.kind} · ${fmt.datetime(b.created_at)}`)),
      el("span", {}, badge(b.status === "confirmado" ? "good" : b.status === "descartado" ? "" : "info", b.status),
        el("div.small.muted", {}, `${b.added} altas · ${b.updated} actualizadas · ${b.rejected} rechazadas`))))));
  }
  status.append(el("div.actions", {},
    can("counts.create") ? el("a.btn.primary", { href: "#/conteo" }, "Nuevo conteo inteligente") : null,
    can("reports.view") ? el("a.btn", { href: "#/reportes" }, "Ver reportes") : null));
  grid.append(status);
}
