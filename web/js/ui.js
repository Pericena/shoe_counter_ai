// Utilidades de interfaz: creación segura de nodos (sin innerHTML con datos), formato, avisos,
// diálogos, tablas paginadas y estados vacíos/carga.

const ICONS = {
  dashboard: "M3 13h8V3H3zM13 21h8V11h-8zM3 21h8v-6H3zM13 3v6h8V3z",
  box: "M21 8l-9-5-9 5 9 5 9-5zM3 8v8l9 5 9-5V8M12 13v8",
  layers: "M12 2l9 5-9 5-9-5 9-5zM3 12l9 5 9-5M3 17l9 5 9-5",
  swap: "M7 7h13l-3-3M17 17H4l3 3",
  camera: "M3 8h4l2-3h6l2 3h4v12H3zM12 17a4 4 0 1 0 0-8 4 4 0 0 0 0 8z",
  upload: "M12 16V4M7 9l5-5 5 5M4 20h16",
  chart: "M4 20V10M10 20V4M16 20v-7M22 20H2",
  globe: "M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18zM3 12h18M12 3c2.5 3 2.5 15 0 18M12 3c-2.5 3-2.5 15 0 18",
  cart: "M3 4h2l2.4 11h11.2L21 7H6.2M9 20a1 1 0 1 0 0-2 1 1 0 0 0 0 2zM18 20a1 1 0 1 0 0-2 1 1 0 0 0 0 2z",
  users: "M16 19v-1a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v1M9 10a3 3 0 1 0 0-6 3 3 0 0 0 0 6zM22 19v-1a4 4 0 0 0-3-3.9M16 4.1a3 3 0 0 1 0 5.8",
  shield: "M12 3l8 3v6c0 5-3.5 8-8 9-4.5-1-8-4-8-9V6z",
  settings: "M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6zM19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z",
  logout: "M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4M16 17l5-5-5-5M21 12H9",
  menu: "M3 6h18M3 12h18M3 18h18",
  store: "M3 9l1.5-5h15L21 9M3 9v11h18V9M3 9h18M9 20v-6h6v6",
  plus: "M12 5v14M5 12h14",
  download: "M12 4v12M7 11l5 5 5-5M4 20h16",
  tag: "M20 12l-8 8-9-9V3h8zM7.5 7.5h.01",
  close: "M6 6l12 12M18 6L6 18",
  check: "M5 12l5 5L20 7",
  "arrow-left": "M19 12H5M11 6l-6 6 6 6",
  image: "M4 5h16v14H4zM4 15l4-4 3 3 2-2 5 5M8 9h.01",
  key: "M15 7a4 4 0 1 1-3.9 4.9L3 20v-3h3v-3h3l1.1-1.1A4 4 0 0 1 15 7z",
  list: "M8 6h13M8 12h13M8 18h13M3 6h.01M3 12h.01M3 18h.01",
};

export function icon(name, extraClass = "") {
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("viewBox", "0 0 24 24");
  svg.setAttribute("class", `icon ${extraClass}`.trim());
  svg.setAttribute("aria-hidden", "true");
  const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
  path.setAttribute("d", ICONS[name] || ICONS.box);
  svg.append(path);
  return svg;
}

/** el("div.card#id", {attrs}, ...children). Los textos se insertan como texto, nunca como HTML. */
export function el(spec, attrs = {}, ...children) {
  const [tagAndClasses, id] = spec.split("#");
  const [tag, ...classes] = tagAndClasses.split(".");
  const node = document.createElement(tag || "div");
  if (classes.length) node.className = classes.join(" ");
  if (id) node.id = id;
  for (const [key, value] of Object.entries(attrs || {})) {
    if (value === undefined || value === null || value === false) continue;
    if (key === "on") {
      for (const [event, handler] of Object.entries(value)) node.addEventListener(event, handler);
    } else if (key === "dataset") {
      Object.assign(node.dataset, value);
    } else if (key === "class") {
      node.className = [node.className, value].filter(Boolean).join(" ");
    } else if (key in node && typeof value !== "string") {
      node[key] = value;
    } else {
      node.setAttribute(key, value === true ? "" : value);
    }
  }
  for (const child of children.flat()) {
    if (child === null || child === undefined || child === false) continue;
    node.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return node;
}

const numberFmt = new Intl.NumberFormat("es", { maximumFractionDigits: 0 });
const decimalFmt = new Intl.NumberFormat("es", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
export const fmt = {
  int: (v) => (v === null || v === undefined ? "—" : numberFmt.format(Number(v))),
  money: (v) => (v === null || v === undefined || v === "" ? "—" : decimalFmt.format(Number(v))),
  dec: (v, d = 2) => (v === null || v === undefined ? "—" : Number(v).toLocaleString("es", { maximumFractionDigits: d, minimumFractionDigits: d })),
  pct: (v) => (v === null || v === undefined ? "—" : `${(Number(v) * 100).toLocaleString("es", { maximumFractionDigits: 1 })} %`),
  date: (v) => (v ? new Date(v).toLocaleDateString("es", { dateStyle: "medium" }) : "—"),
  datetime: (v) => (v ? new Date(v).toLocaleString("es", { dateStyle: "short", timeStyle: "short" }) : "—"),
  pairs: (n) => `${fmt.int(n)} ${Number(n) === 1 ? "par" : "pares"}`,
  shoes: (n) => `${fmt.int(n)} ${Number(n) === 1 ? "zapato" : "zapatos"}`,
  compact: (v) => new Intl.NumberFormat("es", { notation: "compact", maximumFractionDigits: 1 }).format(Number(v)),
};

export const MOVEMENT_LABELS = {
  entrada_compra: "Entrada por compra",
  salida_venta: "Venta",
  devolucion_cliente: "Devolución de cliente",
  devolucion_proveedor: "Devolución a proveedor",
  ajuste: "Ajuste",
  conteo_fisico: "Conteo físico",
  salida_pedido: "Pedido online",
  cancelacion_pedido: "Cancelación de pedido",
};

export const STOCK_BADGES = { ok: ["good", "Disponible"], bajo: ["warn", "Stock bajo"], agotado: ["bad", "Agotado"] };

export function badge(kind, text) {
  return el(`span.badge.${kind}`, {}, text);
}

export function stockBadge(state) {
  const [kind, text] = STOCK_BADGES[state] || ["", state];
  return badge(kind, text);
}

export function toast(message, kind = "") {
  let holder = document.querySelector(".toasts");
  if (!holder) {
    holder = el("div.toasts", { role: "status", "aria-live": "polite" });
    document.body.append(holder);
  }
  const node = el(`div.toast${kind ? "." + kind : ""}`, {}, message);
  holder.append(node);
  setTimeout(() => node.remove(), kind === "bad" ? 7000 : 4000);
}

export function errorText(error) {
  if (!error) return "Error desconocido";
  const details = error.details && typeof error.details === "object"
    ? Object.entries(error.details).filter(([k]) => k !== "must_change_password")
      .map(([k, v]) => `• ${k}: ${Array.isArray(v) ? v.join(", ") : v}`).join("\n")
    : "";
  return details ? `${error.message}\n${details}` : error.message;
}

export function showError(error) {
  console.error(error);
  toast(errorText(error), "bad");
}

export function loading(text = "Cargando…") {
  return el("div.loading", {}, el("span.spinner"), " ", text);
}

export function empty(title, text, action) {
  return el("div.empty", {}, el("strong", {}, title), text ? el("p", {}, text) : null, action || null);
}

/** Diálogo modal. `build(body, close)` rellena el contenido; devuelve una promesa con el resultado. */
export function modal(title, build, { wide = false } = {}) {
  return new Promise((resolve) => {
    const dialog = el("dialog", { "aria-label": title });
    if (wide) dialog.classList.add("wide");
    const body = el("div.dialog-body");
    const foot = el("div.dialog-foot");
    const close = (value) => {
      dialog.close();
      dialog.remove();
      resolve(value);
    };
    dialog.append(
      el("div.dialog-head", {}, el("h2.m0", {}, title),
        el("button.btn.ghost.small", { type: "button", "aria-label": "Cerrar", on: { click: () => close(null) } }, icon("close"))),
      body, foot);
    dialog.addEventListener("cancel", (e) => { e.preventDefault(); close(null); });
    document.body.append(dialog);
    build(body, close, foot);
    dialog.showModal();
  });
}

export function confirmDialog(title, message, { confirmText = "Confirmar", danger = false, input = null } = {}) {
  return modal(title, (body, close, foot) => {
    body.append(el("p", {}, message));
    let field = null;
    if (input) {
      field = el("textarea", { placeholder: input, required: true });
      body.append(el("label.field", {}, input, field));
    }
    foot.append(
      el("button.btn", { type: "button", on: { click: () => close(null) } }, "Cancelar"),
      el(`button.btn.${danger ? "danger" : "primary"}`, {
        type: "button",
        on: {
          click: () => {
            if (field && !field.value.trim()) { field.focus(); return; }
            close(field ? field.value.trim() : true);
          },
        },
      }, confirmText));
  });
}

/** Lee un formulario a objeto: omite vacíos; convierte a entero los campos indicados. */
export function formValues(form, { ints = [], keepEmpty = [] } = {}) {
  const data = {};
  for (const [key, raw] of new FormData(form).entries()) {
    if (raw instanceof File) continue;
    const value = String(raw).trim();
    if (value === "" && !keepEmpty.includes(key)) continue;
    data[key] = ints.includes(key) ? Number.parseInt(value, 10) : value;
  }
  for (const box of form.querySelectorAll("input[type=checkbox][name]")) data[box.name] = box.checked;
  return data;
}

export function field(label, input, hint) {
  return el("label.field", {}, label, input, hint ? el("span.small.muted", {}, hint) : null);
}

export function options(select, items, { placeholder, value = "id", label = "name", selected } = {}) {
  select.replaceChildren();
  if (placeholder !== undefined) select.append(new Option(placeholder, ""));
  for (const item of items) {
    const option = new Option(typeof label === "function" ? label(item) : item[label], item[value]);
    select.append(option);
  }
  if (selected !== undefined && selected !== null) select.value = String(selected);
  return select;
}

/**
 * Tabla paginada conectada a la API.
 * columns: [{label, render(item) -> Node|string, className}]
 */
export function pagedTable({ columns, fetchPage, pageSize = 25, emptyNode, onRows }) {
  const wrap = el("div");
  const tableWrap = el("div.table-wrap");
  const pager = el("div.pager");
  let offset = 0;
  let total = 0;

  async function load() {
    tableWrap.replaceChildren(loading());
    try {
      const data = await fetchPage({ limit: pageSize, offset });
      total = data.total ?? data.items.length;
      if (!data.items.length) {
        tableWrap.replaceChildren(emptyNode || empty("Sin resultados", "No hay registros con estos filtros."));
        pager.replaceChildren();
        return data;
      }
      const thead = el("thead", {}, el("tr", {}, columns.map((c) => el("th", { class: c.className || "" }, c.label))));
      const tbody = el("tbody", {}, data.items.map((item) => el("tr", {}, columns.map((c) => {
        const value = c.render(item);
        return el("td", { class: c.className || "" }, value ?? "—");
      }))));
      tableWrap.replaceChildren(el("table", {}, thead, tbody));
      const end = Math.min(offset + pageSize, total);
      pager.replaceChildren(
        el("span", {}, `${offset + 1}–${end} de ${fmt.int(total)}`),
        el("span.actions", {},
          el("button.btn.small", { type: "button", disabled: offset === 0, on: { click: () => { offset = Math.max(0, offset - pageSize); load(); } } }, "Anterior"),
          el("button.btn.small", { type: "button", disabled: end >= total, on: { click: () => { offset += pageSize; load(); } } }, "Siguiente")));
      if (onRows) onRows(data);
      return data;
    } catch (error) {
      tableWrap.replaceChildren(el("div.alert.bad", {}, errorText(error)));
      pager.replaceChildren();
      return null;
    }
  }

  wrap.append(tableWrap, pager);
  return { node: wrap, reload: (reset = true) => { if (reset) offset = 0; return load(); } };
}

export function queryString(params) {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== null && value !== "") search.set(key, value);
  }
  const text = search.toString();
  return text ? `?${text}` : "";
}

export function pageHead(title, subtitle, ...actions) {
  return el("div.page-head", {}, el("div", {}, el("h1", {}, title), subtitle ? el("p", {}, subtitle) : null),
    actions.length ? el("div.actions", {}, actions) : null);
}
