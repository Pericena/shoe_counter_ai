// Ficha de producto: lo que se muestra cuando un producto registrado es reconocido (cámara, foto u OCR)
// y en el detalle del producto. Todo sale de /api/products/<id>/overview o de las respuestas que la incluyen.
import { badge, el, fmt } from "./ui.js";

const STATE = { ok: "good", bajo: "warn", agotado: "bad" };

export function productCard(card, { title = "Producto reconocido", compact = false } = {}) {
  const p = card.product;
  const t = card.totals;
  const photo = p.images && p.images.length
    ? el("img.card-photo", { src: p.images[0].url, alt: `${p.brand} ${p.model_name}` })
    : el("div.card-photo.empty-photo", {}, "Sin foto");

  const facts = el("dl.dl", {},
    el("dt", {}, "Marca"), el("dd", {}, el("strong", {}, p.brand)),
    el("dt", {}, "Modelo"), el("dd", {}, el("strong", {}, p.model_name)),
    el("dt", {}, "Código"), el("dd", {}, el("span.mono", {}, p.code)),
    el("dt", {}, "Categoría"), el("dd", {}, p.category || "—"),
    el("dt", {}, "Tipo"), el("dd", {}, p.footwear_type || "—"),
    el("dt", {}, "Proveedor"), el("dd", {}, p.supplier || "—"),
    el("dt", {}, "Estado"), el("dd", {}, badge(p.status === "activo" ? "good" : "", p.status === "activo" ? "Activo" : p.status === "inactivo" ? "Inactivo" : p.status)),
    el("dt", {}, "Tienda"), el("dd", {}, p.is_published ? badge("info", "Publicado") : badge("", "No publicado")),
    p.description ? el("dt", {}, "Descripción") : null, p.description ? el("dd", {}, p.description) : null);

  const kpis = el("div.kpis.compact-kpis", {},
    kpi("Pares en stock", fmt.int(t.pairs)),
    kpi("Tallas", `${t.variants} (${t.low} bajas · ${t.out} agotadas)`),
    kpi("Valor a costo", fmt.money(t.value_at_cost), t.cost_complete ? null : "incompleto: hay variantes sin costo"));

  const matrix = el("div.table-wrap", {}, el("table.matrix", {},
    el("thead", {}, el("tr", {}, el("th", {}, "Color \\ Talla"), card.sizes.map((s) => el("th.num", {}, s)))),
    el("tbody", {}, card.colors.map((color) => el("tr", {}, el("th", {}, color), card.sizes.map((size) => {
      const cell = card.matrix[color][size];
      if (!cell) return el("td.num.muted", {}, "·");
      return el(`td.num.cell-${STATE[cell.state] || ""}${cell.highlight ? ".cell-hit" : ""}`,
        { title: `${cell.sku} · ${fmt.pairs(cell.stock)}${cell.highlight ? " · RECONOCIDO" : ""}` }, String(cell.stock));
    }))))));

  const recognized = card.variants.filter((v) => v.highlight);
  const hits = recognized.length ? el("div.alert.good", {},
    el("strong", {}, recognized.length === 1 ? "Variante reconocida: " : "Variantes reconocidas: "),
    recognized.map((v) => `${v.sku} · talla ${v.size} · ${v.color} · ${fmt.pairs(v.stock_quantity)}`).join(" | ")) : null;

  return el("div.card.product-card", {},
    el("div.card-head", {}, el("h2", {}, title), el("a.btn.small", { href: `#/productos/${p.id}` }, "Abrir producto")),
    hits,
    el("div.card-body", {}, photo, el("div", {}, facts)),
    compact ? null : kpis,
    el("h3", {}, "Pares por talla y color"), matrix,
    el("p.small.muted", {}, "Verde: disponible · ámbar: stock bajo · rojo: agotado · recuadro: variante reconocida."));
}

function kpi(label, value, note) {
  return el("div.kpi", {}, el("div.label", {}, label), el("div.value", {}, value), note ? el("div.note", {}, note) : null);
}
