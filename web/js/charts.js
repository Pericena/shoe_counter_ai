// Gráficos SVG sin dependencias. Reglas: un solo eje Y, colores por serie fija (s1 azul, s2 naranja,
// s3 verde agua), leyenda si hay >= 2 series, tooltip al pasar el cursor y tabla equivalente.
import { el, fmt } from "./ui.js";

const NS = "http://www.w3.org/2000/svg";

function svg(tag, attrs = {}, ...children) {
  const node = document.createElementNS(NS, tag);
  for (const [k, v] of Object.entries(attrs)) if (v !== undefined && v !== null) node.setAttribute(k, v);
  for (const c of children) if (c) node.append(c instanceof Node ? c : document.createTextNode(String(c)));
  return node;
}

function niceMax(value) {
  if (value <= 0) return 1;
  const exp = 10 ** Math.floor(Math.log10(value));
  const n = value / exp;
  const step = n <= 1 ? 1 : n <= 2 ? 2 : n <= 5 ? 5 : 10;
  return step * exp;
}

function legend(series) {
  if (series.length < 2) return null;
  return el("div.legend", {}, series.map((s) => el("span", {}, el(`i.${s.cls}`), s.name)));
}

function tableView(categories, series, format, categoryLabel) {
  return el("details.table-view", {},
    el("summary", {}, "Ver datos en tabla"),
    el("div.table-wrap", {}, el("table", {},
      el("thead", {}, el("tr", {}, el("th", {}, categoryLabel), series.map((s) => el("th.num", {}, s.name)))),
      el("tbody", {}, categories.map((c, i) => el("tr", {}, el("td", {}, c),
        series.map((s) => el("td.num", {}, s.values[i] === null || s.values[i] === undefined ? "—" : format(s.values[i])))))))));
}

function attachTooltip(container) {
  const tip = el("div.tooltip.hidden");
  container.append(tip);
  return {
    show(text, x, y) {
      tip.textContent = text;
      tip.classList.remove("hidden");
      tip.style.left = `${x}px`;
      tip.style.top = `${y}px`;
    },
    hide() { tip.classList.add("hidden"); },
  };
}

/** Barras verticales agrupadas. series: [{name, cls: "s1", values: [...]}] */
export function barChart({ categories, series, format = fmt.int, height = 260, categoryLabel = "Categoría", note }) {
  const container = el("div.chart");
  const width = Math.max(320, categories.length * series.length * 26 + 80);
  const pad = { top: 18, right: 10, bottom: 34, left: 56 };
  const innerW = width - pad.left - pad.right;
  const innerH = height - pad.top - pad.bottom;
  const max = niceMax(Math.max(0, ...series.flatMap((s) => s.values.map((v) => Number(v) || 0))));
  const groupW = innerW / Math.max(1, categories.length);
  const barW = Math.max(4, Math.min(34, (groupW - 10) / series.length - 2));
  const root = svg("svg", { viewBox: `0 0 ${width} ${height}`, role: "img", "aria-label": series.map((s) => s.name).join(", ") });
  for (let i = 0; i <= 4; i++) {
    const v = (max / 4) * i;
    const y = pad.top + innerH - (v / max) * innerH;
    root.append(svg("line", { class: i === 0 ? "baseline" : "gridline", x1: pad.left, x2: width - pad.right, y1: y, y2: y }));
    root.append(svg("text", { class: "label", x: pad.left - 6, y: y + 4, "text-anchor": "end" }, fmt.compact(v)));
  }
  const tip = attachTooltip(container);
  categories.forEach((category, ci) => {
    const gx = pad.left + ci * groupW + (groupW - series.length * (barW + 2)) / 2;
    series.forEach((s, si) => {
      const value = Number(s.values[ci]) || 0;
      const h = (value / max) * innerH;
      const x = gx + si * (barW + 2);
      const y = pad.top + innerH - h;
      const r = Math.min(4, barW / 2, h);
      // Barra con extremo de datos redondeado (4px) y anclada a la línea base.
      const d = h <= 0 ? "" : `M${x},${pad.top + innerH} V${y + r} Q${x},${y} ${x + r},${y} H${x + barW - r} Q${x + barW},${y} ${x + barW},${y + r} V${pad.top + innerH} Z`;
      if (d) root.append(svg("path", { class: `bar ${s.cls}`, d }));
      const hit = svg("rect", { class: "hit", x: x - 1, y: pad.top, width: barW + 2, height: innerH });
      hit.addEventListener("mouseenter", () => {
        const box = root.getBoundingClientRect();
        const scale = box.width / width;
        tip.show(`${category} · ${s.name}: ${format(s.values[ci])}`, (x + barW / 2) * scale, y * scale);
      });
      hit.addEventListener("mouseleave", () => tip.hide());
      root.append(hit);
    });
    const label = String(category);
    root.append(svg("text", { class: "label", x: pad.left + ci * groupW + groupW / 2, y: height - 12, "text-anchor": "middle" },
      label.length > 12 ? label.slice(0, 11) + "…" : label));
  });
  container.append(root);
  return el("div", {}, legend(series), container, note ? el("p.chart-note", {}, note) : null,
    tableView(categories, series, format, categoryLabel));
}

/** Barras horizontales (ranking de una sola serie). items: [{label, value}] */
export function hBarChart({ items, name, format = fmt.int, cls = "s1", note }) {
  const container = el("div.chart");
  const rowH = 26;
  const width = 640;
  const pad = { left: 150, right: 70, top: 6 };
  const height = pad.top + items.length * rowH + 6;
  const max = Math.max(1, ...items.map((i) => Number(i.value) || 0));
  const root = svg("svg", { viewBox: `0 0 ${width} ${height}`, role: "img", "aria-label": name });
  const tip = attachTooltip(container);
  items.forEach((item, i) => {
    const y = pad.top + i * rowH;
    const w = ((Number(item.value) || 0) / max) * (width - pad.left - pad.right);
    const label = String(item.label);
    root.append(svg("text", { class: "label", x: pad.left - 8, y: y + 16, "text-anchor": "end" },
      label.length > 22 ? label.slice(0, 21) + "…" : label));
    const r = Math.min(4, w);
    const d = w <= 0 ? "" : `M${pad.left},${y + 4} H${pad.left + w - r} Q${pad.left + w},${y + 4} ${pad.left + w},${y + 4 + r} V${y + 20 - r} Q${pad.left + w},${y + 20} ${pad.left + w - r},${y + 20} H${pad.left} Z`;
    if (d) root.append(svg("path", { class: `bar ${cls}`, d }));
    root.append(svg("text", { class: "value-label", x: pad.left + w + 6, y: y + 16 }, format(item.value)));
    const hit = svg("rect", { class: "hit", x: 0, y, width, height: rowH });
    hit.addEventListener("mouseenter", () => {
      const scale = root.getBoundingClientRect().width / width;
      tip.show(`${label}: ${format(item.value)}`, (pad.left + w / 2) * scale, (y + 4) * scale);
    });
    hit.addEventListener("mouseleave", () => tip.hide());
    root.append(hit);
  });
  container.append(root);
  return el("div", {}, container, note ? el("p.chart-note", {}, note) : null,
    tableView(items.map((i) => i.label), [{ name, values: items.map((i) => i.value) }], format, "Elemento"));
}

/** Líneas sobre un eje X ordinal (años, períodos). Huecos (null) cortan la línea. */
export function lineChart({ categories, series, format = fmt.int, height = 240, categoryLabel = "Período", note }) {
  const container = el("div.chart");
  const width = 640;
  const pad = { top: 16, right: 16, bottom: 32, left: 56 };
  const innerW = width - pad.left - pad.right;
  const innerH = height - pad.top - pad.bottom;
  const values = series.flatMap((s) => s.values.filter((v) => v !== null && v !== undefined).map(Number));
  const max = niceMax(Math.max(0, ...values));
  const x = (i) => pad.left + (categories.length === 1 ? innerW / 2 : (i / (categories.length - 1)) * innerW);
  const y = (v) => pad.top + innerH - (v / max) * innerH;
  const root = svg("svg", { viewBox: `0 0 ${width} ${height}`, role: "img", "aria-label": series.map((s) => s.name).join(", ") });
  for (let i = 0; i <= 4; i++) {
    const v = (max / 4) * i;
    root.append(svg("line", { class: i === 0 ? "baseline" : "gridline", x1: pad.left, x2: width - pad.right, y1: y(v), y2: y(v) }));
    root.append(svg("text", { class: "label", x: pad.left - 6, y: y(v) + 4, "text-anchor": "end" }, fmt.compact(v)));
  }
  const step = Math.ceil(categories.length / 10);
  categories.forEach((c, i) => {
    if (i % step === 0) root.append(svg("text", { class: "label", x: x(i), y: height - 10, "text-anchor": "middle" }, c));
  });
  for (const s of series) {
    let d = "";
    s.values.forEach((v, i) => {
      if (v === null || v === undefined) return;
      const prev = i > 0 ? s.values[i - 1] : null;
      d += `${prev === null || prev === undefined || i === 0 ? "M" : "L"}${x(i)},${y(Number(v))} `;
    });
    root.append(svg("path", { class: `line ${s.cls}`, d: d.trim() }));
    s.values.forEach((v, i) => {
      if (v !== null && v !== undefined) root.append(svg("circle", { class: `dot ${s.cls}`, cx: x(i), cy: y(Number(v)), r: 4 }));
    });
  }
  const tip = attachTooltip(container);
  const cross = svg("line", { class: "gridline hidden", y1: pad.top, y2: pad.top + innerH });
  root.append(cross);
  const overlay = svg("rect", { class: "hit", x: pad.left, y: pad.top, width: innerW, height: innerH });
  overlay.addEventListener("mousemove", (event) => {
    const box = root.getBoundingClientRect();
    const scale = box.width / width;
    const px = (event.clientX - box.left) / scale;
    const i = categories.length === 1 ? 0 : Math.round(((px - pad.left) / innerW) * (categories.length - 1));
    const idx = Math.max(0, Math.min(categories.length - 1, i));
    cross.setAttribute("x1", x(idx));
    cross.setAttribute("x2", x(idx));
    cross.classList.remove("hidden");
    const text = `${categories[idx]} — ` + series.map((s) => `${s.name}: ${s.values[idx] === null || s.values[idx] === undefined ? "—" : format(s.values[idx])}`).join(" · ");
    tip.show(text, x(idx) * scale, pad.top * scale + 10);
  });
  overlay.addEventListener("mouseleave", () => { tip.hide(); cross.classList.add("hidden"); });
  root.append(overlay);
  container.append(root);
  return el("div", {}, legend(series), container, note ? el("p.chart-note", {}, note) : null,
    tableView(categories, series, format, categoryLabel));
}
