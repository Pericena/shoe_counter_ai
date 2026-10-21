// Productos (modelo comercial), variantes (talla+color), fotos y catálogos: marcas, categorías, proveedores.
import { api } from "../api.js";
import { productCard } from "../productcard.js";
import {
  MOVEMENT_LABELS, badge, confirmDialog, el, empty, field, fmt, formValues, icon, modal, options, pageHead, pagedTable,
  queryString, showError, stockBadge, toast,
} from "../ui.js";

let catalogs = { brands: [], categories: [], suppliers: [] };

async function loadCatalogs() {
  const [brands, categories, suppliers] = await Promise.all([
    api.get("/api/brands"), api.get("/api/categories"), api.get("/api/suppliers")]);
  catalogs = { brands: brands.items, categories: categories.items, suppliers: suppliers.items };
}

export async function render(root, params, ctx) {
  await loadCatalogs();
  if (params[0]) return renderDetail(root, Number(params[0]), ctx);
  return renderList(root, ctx);
}

function renderList(root, { can }) {
  const tabs = el("div.tabs", { role: "tablist" });
  const body = el("div");
  const sections = [["Productos", productsTab], ["Marcas", () => simpleCatalog("brands", "marca")],
    ["Categorías", () => simpleCatalog("categories", "categoría")], ["Proveedores", suppliersTab]];
  const manage = can("products.manage");

  function select(index) {
    tabs.querySelectorAll("button").forEach((b, i) => b.setAttribute("aria-selected", i === index));
    body.replaceChildren(sections[index][1]());
  }
  sections.forEach(([label], i) => tabs.append(el("button", { type: "button", role: "tab", on: { click: () => select(i) } }, label)));

  root.append(pageHead("Productos", "Cada producto es un modelo comercial; sus variantes (talla + color) llevan el stock.",
    manage ? el("button.btn.primary", { type: "button", on: { click: () => productDialog() } }, icon("plus"), "Nuevo producto") : null),
  tabs, body);
  select(0);

  function productsTab() {
    const q = el("input", { type: "search", placeholder: "Buscar marca, modelo o código" });
    const brand = options(el("select"), catalogs.brands, { placeholder: "Todas las marcas" });
    const category = options(el("select"), catalogs.categories, { placeholder: "Todas las categorías" });
    const status = options(el("select"), [{ id: "activo", name: "Activos" }, { id: "inactivo", name: "Inactivos" },
      { id: "descontinuado", name: "Descontinuados" }], { placeholder: "Cualquier estado" });
    const table = pagedTable({
      fetchPage: ({ limit, offset }) => api.get("/api/products" + queryString({
        q: q.value, brand_id: brand.value, category_id: category.value, status: status.value, limit, offset })),
      emptyNode: empty("No hay productos", manage ? "Crea el primero con «Nuevo producto» o impórtalos desde Excel/CSV." : "Aún no se registraron productos."),
      columns: [
        { label: "", render: (p) => p.images.length ? el("img.thumb", { src: p.images[0].url, alt: "" }) : el("span.thumb") },
        { label: "Código", render: (p) => el("a.mono", { href: `#/productos/${p.id}` }, p.code) },
        { label: "Marca", render: (p) => p.brand },
        { label: "Modelo", render: (p) => p.model_name },
        { label: "Categoría", render: (p) => p.category || "—" },
        { label: "Variantes", className: "num", render: (p) => fmt.int(p.variant_count) },
        { label: "Pares", className: "num", render: (p) => fmt.int(p.stock_pairs) },
        { label: "Estado", render: (p) => badge(p.status === "activo" ? "good" : "", p.status) },
        { label: "Tienda", render: (p) => p.is_published ? badge("info", "Publicado") : badge("", "No publicado") },
        { label: "", className: "num", render: (p) => manage ? quickPhoto(p, () => table.reload(false)) : null },
      ],
    });
    const filters = el("form.filters", { on: { submit: (e) => { e.preventDefault(); table.reload(); } } },
      q, brand, category, status, el("button.btn", { type: "submit" }, "Filtrar"));
    table.reload();
    return el("div", {}, filters, table.node);
  }

  function simpleCatalog(path, label) {
    const list = el("div");
    async function load() {
      await loadCatalogs();
      const items = catalogs[path];
      list.replaceChildren(items.length ? el("div.table-wrap", {}, el("table", {},
        el("thead", {}, el("tr", {}, el("th", {}, "Nombre"), manage ? el("th", {}, "") : null)),
        el("tbody", {}, items.map((item) => el("tr", {}, el("td", {}, item.name), manage ? el("td.num", {},
          el("button.btn.small", { type: "button", on: { click: () => rename(item) } }, "Renombrar")) : null)))))
        : empty(`No hay ${label}s`, manage ? `Añade la primera ${label}.` : ""));
    }
    async function rename(item) {
      const name = await askName(`Renombrar ${label}`, item.name);
      if (!name) return;
      try { await api.patch(`/api/${path}/${item.id}`, { name }); toast("Guardado", "good"); load(); } catch (e) { showError(e); }
    }
    const add = manage ? el("form.filters", {
      on: {
        async submit(event) {
          event.preventDefault();
          const input = event.currentTarget.elements.name;
          try { await api.post(`/api/${path}`, { name: input.value }); input.value = ""; toast(`${label} creada`, "good"); load(); } catch (e) { showError(e); }
        },
      },
    }, el("input.grow", { name: "name", placeholder: `Nueva ${label}`, required: true, maxlength: 100 }), el("button.btn.primary", { type: "submit" }, "Añadir")) : null;
    load();
    return el("div", {}, add, list);
  }

  function suppliersTab() {
    const list = el("div");
    async function load() {
      await loadCatalogs();
      list.replaceChildren(catalogs.suppliers.length ? el("div.table-wrap", {}, el("table", {},
        el("thead", {}, el("tr", {}, ["Nombre", "Contacto", "Teléfono", "Correo", ""].map((h) => el("th", {}, h)))),
        el("tbody", {}, catalogs.suppliers.map((s) => el("tr", {}, el("td", {}, s.name), el("td", {}, s.contact_name || "—"),
          el("td", {}, s.phone || "—"), el("td", {}, s.email || "—"),
          el("td.num", {}, manage ? el("button.btn.small", { type: "button", on: { click: () => supplierDialog(s, load) } }, "Editar") : null))))))
        : empty("No hay proveedores", manage ? "Registra los proveedores para asociarlos a los productos." : ""));
    }
    load();
    return el("div", {}, manage ? el("div.actions", {}, el("button.btn.primary", { type: "button", on: { click: () => supplierDialog(null, load) } }, icon("plus"), "Nuevo proveedor")) : null,
      el("div", { class: "stack" }, list));
  }
}

function quickPhoto(product, done) {
  const id = `quick-photo-${product.id}`;
  const input = el("input", { type: "file", accept: "image/jpeg,image/png,image/webp", multiple: true, class: "sr-only", id });
  input.addEventListener("change", async () => {
    const uploaded = await uploadPhotos(product.id, input.files);
    if (uploaded) { toast(`${uploaded} foto(s) subida(s) a ${product.code}`, "good"); done(); }
  });
  return el("span", {}, input, el("label.btn.small", { for: id, title: "Subir fotos" }, icon("camera"), "Foto"));
}

function askName(title, value = "") {
  return modal(title, (body, close, foot) => {
    const input = el("input", { value, maxlength: 100, required: true });
    body.append(field("Nombre", input));
    foot.append(el("button.btn", { type: "button", on: { click: () => close(null) } }, "Cancelar"),
      el("button.btn.primary", { type: "button", on: { click: () => close(input.value.trim() || null) } }, "Guardar"));
  });
}

function supplierDialog(supplier, done) {
  return modal(supplier ? "Editar proveedor" : "Nuevo proveedor", (body, close, foot) => {
    const form = el("form.form.two", {},
      el("label.field.full", {}, "Nombre *", el("input", { name: "name", required: true, maxlength: 150, value: supplier?.name || "" })),
      field("Contacto", el("input", { name: "contact_name", maxlength: 150, value: supplier?.contact_name || "" })),
      field("Teléfono", el("input", { name: "phone", maxlength: 50, value: supplier?.phone || "" })),
      el("label.field.full", {}, "Correo", el("input", { name: "email", type: "email", maxlength: 150, value: supplier?.email || "" })),
      el("label.field.full", {}, "Notas", el("textarea", { name: "notes", maxlength: 2000 }, supplier?.notes || "")));
    body.append(form);
    foot.append(el("button.btn", { type: "button", on: { click: () => close(null) } }, "Cancelar"),
      el("button.btn.primary", {
        type: "button",
        on: {
          async click() {
            if (!form.reportValidity()) return;
            const data = formValues(form, { keepEmpty: supplier ? ["contact_name", "phone", "email", "notes"] : [] });
            try {
              if (supplier) await api.patch(`/api/suppliers/${supplier.id}`, data);
              else await api.post("/api/suppliers", data);
              toast("Proveedor guardado", "good");
              close(true);
              done();
            } catch (e) { showError(e); }
          },
        },
      }, "Guardar"));
  });
}

function segment(label, control, choices, current) {
  const buttons = choices.map(([id, name]) => el("button.segment-btn", {
    type: "button",
    "aria-pressed": String(String(current) === id),
    on: {
      click() {
        if (control.type === "checkbox") control.checked = id === "1";
        else control.value = id;
        buttons.forEach((button, index) => button.setAttribute("aria-pressed", String(choices[index][0] === id)));
      },
    },
  }, name));
  control.classList.add("sr-only");
  return el("div.field", {}, el("span", {}, label), el("div.segment", {}, buttons), control);
}

function productForm(product, prefill = {}) {
  const brandId = product?.brand_id ?? catalogs.brands.find((b) => b.name.toLowerCase() === (prefill.brand || "").toLowerCase())?.id;
  if (!catalogs.brands.length) {
    return el("div.alert.warn", {}, "Primero crea al menos una marca en la pestaña «Marcas».");
  }
  return el("form.form.two", {},
    field("Código interno *", el("input", { name: "code", required: true, maxlength: 50, value: product?.code || prefill.code || "" })),
    field("Marca *", options(el("select", { name: "brand_id", required: true }), catalogs.brands, { placeholder: "Selecciona", selected: brandId })),
    el("label.field.full", {}, "Modelo *", el("input", { name: "model_name", required: true, maxlength: 150, value: product?.model_name || prefill.model_name || "" })),
    field("Categoría", options(el("select", { name: "category_id" }), catalogs.categories, { placeholder: "Sin categoría", selected: product?.category_id })),
    field("Tipo de calzado", el("input", { name: "footwear_type", maxlength: 100, value: product?.footwear_type || "", placeholder: "Zapatilla, bota, sandalia…" })),
    field("Proveedor", options(el("select", { name: "supplier_id" }), catalogs.suppliers, { placeholder: "Sin proveedor", selected: product?.supplier_id })),
    segment("Estado en inventario", options(el("select", { name: "status" }), [
      { id: "activo", name: "Activo" }, { id: "inactivo", name: "Inactivo" }, { id: "descontinuado", name: "Descontinuado" },
    ], { selected: product?.status || "activo" }), [["activo", "Activo"], ["inactivo", "Inactivo"]], product?.status || "activo"),
    segment("Tienda", el("input", { type: "checkbox", name: "is_published", checked: Boolean(product?.is_published) }),
      [["0", "No publicar"], ["1", "Publicar"]], product?.is_published ? "1" : "0"),
    el("p.full.small.muted", {}, "Publicar lo muestra en la tienda solo si está activo y la talla tiene precio. No publicar lo deja solo en el inventario."),
    el("label.field.full", {}, "Descripción", el("textarea", { name: "description", maxlength: 5000 }, product?.description || "")),
    photoPicker());
}

/** Selector de fotos con vista previa local; se suben al guardar el producto. */
function photoPicker() {
  const input = el("input", { type: "file", name: "photos", accept: "image/jpeg,image/png,image/webp", multiple: true });
  const preview = el("div.photos");
  input.addEventListener("change", () => {
    preview.replaceChildren(...[...input.files].slice(0, 8).map((file) => {
      const url = URL.createObjectURL(file);
      return el("figure", {}, el("img", { src: url, alt: file.name, on: { load: () => URL.revokeObjectURL(url) } }));
    }));
  });
  return el("label.field.full", {}, "Fotografías (JPG, PNG o WEBP; hasta 8)", input, preview,
    el("span.small.muted", {}, "Se guardan sin metadatos (EXIF/GPS). La primera es la portada en la tienda."));
}

async function uploadPhotos(productId, files) {
  let ok = 0;
  for (const file of [...files].slice(0, 8)) {
    const form = new FormData();
    form.append("image", file);
    try { await api.upload(`/api/products/${productId}/images`, form); ok += 1; } catch (e) { showError(e); }
  }
  return ok;
}

function productDialog(product, done, prefill) {
  return modal(product ? "Editar producto" : "Nuevo producto", (body, close, foot) => {
    const form = productForm(product, prefill);
    if (prefill?.note) body.append(el("div.alert.info", {}, prefill.note));
    body.append(form);
    foot.append(el("button.btn", { type: "button", on: { click: () => close(null) } }, "Cancelar"),
      form.tagName === "FORM" ? el("button.btn.primary", {
        type: "button",
        on: {
          async click() {
            if (!form.reportValidity()) return;
            const data = formValues(form, { ints: ["brand_id", "category_id", "supplier_id"], keepEmpty: product ? ["category_id", "supplier_id", "footwear_type", "description"] : [] });
            for (const key of ["category_id", "supplier_id"]) if (Number.isNaN(data[key])) data[key] = null;
            try {
              delete data.photos;
              const saved = product ? await api.patch(`/api/products/${product.id}`, data) : await api.post("/api/products", data);
              const files = form.querySelector("input[name=photos]").files;
              const uploaded = files.length ? await uploadPhotos(saved.id, files) : 0;
              toast(uploaded ? `Producto guardado con ${uploaded} foto(s)` : "Producto guardado", "good");
              close(saved);
              if (done) done(saved);
              else location.hash = `#/productos/${saved.id}`;
            } catch (e) { showError(e); }
          },
        },
      }, "Guardar") : null);
  });
}

function variantDialog(product, variant, done, prefill = {}) {
  return modal(variant ? `Editar variante ${variant.sku}` : "Nueva variante (talla + color)", (body, close, foot) => {
    if (prefill.note) body.append(el("div.alert.info", {}, prefill.note));
    const form = el("form.form.two", {},
      field("SKU *", el("input", { name: "sku", required: true, maxlength: 60, value: variant?.sku || prefill.sku || "" })),
      field("Código de barras", el("input", { name: "barcode", maxlength: 64, value: variant?.barcode || prefill.barcode || "" })),
      field("Talla *", el("input", { name: "size", required: true, maxlength: 20, value: variant?.size || prefill.size || "" })),
      field("Color *", el("input", { name: "color", required: true, maxlength: 50, value: variant?.color || prefill.color || "" })),
      field("Costo de adquisición", el("input", { name: "cost", type: "number", min: 0, step: "0.01", value: variant?.cost ?? "" })),
      field("Precio de venta", el("input", { name: "price", type: "number", min: 0, step: "0.01", value: variant?.price ?? prefill.price ?? "" })),
      field("Stock mínimo (alerta)", el("input", { name: "min_stock", type: "number", min: 0, step: 1, value: variant?.min_stock ?? 0 })),
      segment("Estado de esta talla", options(el("select", { name: "status" }), [
        { id: "activo", name: "Activo" }, { id: "inactivo", name: "Inactivo" }, { id: "descontinuado", name: "Descontinuado" },
      ], { selected: variant?.status || "activo" }), [["activo", "Activo"], ["inactivo", "Inactivo"]], variant?.status || "activo"),
      variant ? null : el("p.full.small.muted", {}, "La variante empieza con 0 pares. El stock se suma registrando una entrada en Existencias."));
    body.append(form);
    foot.append(el("button.btn", { type: "button", on: { click: () => close(null) } }, "Cancelar"),
      el("button.btn.primary", {
        type: "button",
        on: {
          async click() {
            if (!form.reportValidity()) return;
            const data = formValues(form, { ints: ["min_stock"], keepEmpty: variant ? ["barcode", "cost", "price"] : [] });
            for (const key of ["barcode", "cost", "price"]) if (data[key] === "") data[key] = null;
            try {
              if (variant) await api.patch(`/api/variants/${variant.id}`, data);
              else await api.post(`/api/products/${product.id}/variants`, data);
              toast("Variante guardada", "good");
              close(true);
              done();
            } catch (e) { showError(e); }
          },
        },
      }, "Guardar"));
  });
}

const VARIANT_PREFILL_KEY = "shoe-variant-prefill";

/** Abre «Nuevo producto» con datos leídos de una etiqueta; tras guardarlo propone la variante. */
export async function openNewProductFromLabel(prefill) {
  await loadCatalogs();
  try { sessionStorage.setItem(VARIANT_PREFILL_KEY, JSON.stringify(prefill.variant || {})); } catch { /* sin almacenamiento */ }
  return productDialog(null, null, prefill);
}

/** Abre «Nueva variante» sobre un producto existente con datos leídos de una etiqueta. */
export async function openNewVariantFromLabel(productId, prefill) {
  try { sessionStorage.setItem(VARIANT_PREFILL_KEY, JSON.stringify(prefill)); } catch { /* sin almacenamiento */ }
  location.hash = `#/productos/${productId}`;
}

async function renderDetail(root, productId, { can }) {
  const manage = can("products.manage");
  const [product, overview] = await Promise.all([
    api.get(`/api/products/${productId}`), api.get(`/api/products/${productId}/overview`)]);
  const reload = () => { root.replaceChildren(); renderDetail(root, productId, { can }); };
  root.append(pageHead(`${product.brand} ${product.model_name}`, `Código ${product.code} · ${product.category || "sin categoría"}`,
    el("a.btn", { href: "#/productos" }, icon("arrow-left"), "Productos"),
    manage ? el("button.btn", { type: "button", on: { click: () => productDialog(product, reload) } }, "Editar producto") : null,
    manage ? el("button.btn.primary", { type: "button", on: { click: () => variantDialog(product, null, reload) } }, icon("plus"), "Nueva variante") : null));

  const grid = el("div.grid.cols-2");
  root.append(grid);
  grid.append(el("div.card", {}, el("h2", {}, "Datos del producto"), el("dl.dl", {},
    el("dt", {}, "Marca"), el("dd", {}, product.brand),
    el("dt", {}, "Tipo"), el("dd", {}, product.footwear_type || "—"),
    el("dt", {}, "Proveedor"), el("dd", {}, product.supplier_name || "—"),
    el("dt", {}, "Estado"), el("dd", {}, badge(product.status === "activo" ? "good" : "", product.status === "activo" ? "Activo" : product.status === "inactivo" ? "Inactivo" : product.status)),
    el("dt", {}, "Tienda"), el("dd", {}, product.is_published ? badge("info", "Publicado") : badge("", "No publicado")),
    el("dt", {}, "Creado"), el("dd", {}, fmt.datetime(product.created_at)),
    el("dt", {}, "Descripción"), el("dd", {}, product.description || "—"))));

  const photos = el("div.card", {}, el("h2", {}, "Fotografías"));
  const gallery = el("div.photos", {}, product.images.map((img) => el("figure", {},
    el("img", { src: img.url, alt: `Foto de ${product.model_name}` }),
    manage ? el("button.btn.small.danger", {
      type: "button", title: "Quitar foto",
      on: {
        async click() {
          if (!(await confirmDialog("Quitar foto", "La foto dejará de mostrarse en el catálogo. El archivo se conserva para trazabilidad.", { confirmText: "Quitar", danger: true }))) return;
          try { await api.del(`/api/products/${product.id}/images/${img.id}`); reload(); } catch (e) { showError(e); }
        },
      },
    }, icon("close"), el("span.sr-only", {}, "Quitar foto")) : null)));
  photos.append(product.images.length ? gallery : el("p.muted", {}, "Sin fotos."));
  if (manage) {
    const input = el("input", { type: "file", accept: "image/jpeg,image/png,image/webp", class: "sr-only", id: "photo-input" });
    input.addEventListener("change", async () => {
      if (!input.files[0]) return;
      const form = new FormData();
      form.append("image", input.files[0]);
      try { await api.upload(`/api/products/${product.id}/images`, form); toast("Foto subida", "good"); reload(); } catch (e) { showError(e); }
    });
    photos.append(input, el("label.btn", { for: "photo-input" }, icon("upload"), "Subir foto (JPG, PNG o WEBP)"));
  }
  grid.append(photos);

  const variants = el("div.card", {}, el("h2", {}, `Variantes (${product.variants.length})`));
  variants.append(product.variants.length ? el("div.table-wrap", {}, el("table", {},
    el("thead", {}, el("tr", {}, ["SKU", "Código de barras", "Talla", "Color", "Costo", "Precio", "Pares", "Mín.", "Estado", ""].map((h) => el("th", {}, h)))),
    el("tbody", {}, product.variants.map((v) => el("tr", {},
      el("td.mono", {}, v.sku), el("td.mono", {}, v.barcode || "—"), el("td", {}, v.size), el("td", {}, v.color),
      el("td.num", {}, fmt.money(v.cost)), el("td.num", {}, fmt.money(v.price)), el("td.num", {}, fmt.int(v.stock_quantity)),
      el("td.num", {}, v.min_stock), el("td", {}, stockBadge(v.stock_state)),
      el("td.num", {}, el("a.btn.small", { href: `#/movimientos/${v.id}` }, "Historial"),
        manage ? el("button.btn.small", { type: "button", on: { click: () => variantDialog(product, v, reload) } }, "Editar") : null))))))
    : empty("Sin variantes", manage ? "Añade las tallas y colores con «Nueva variante»." : ""));
  root.append(el("div.stack", {}, variants));
  root.append(el("div.stack", {}, productCard(overview, { title: "Ficha e inventario del producto" })));
  const related = el("div.grid.cols-2.stack");
  related.append(el("div.card", {}, el("h2", {}, "Últimos movimientos"), overview.recent_movements.length
    ? el("ul.list", {}, overview.recent_movements.slice(0, 12).map((m) => el("li", {},
      el("span", {}, el("strong", {}, MOVEMENT_LABELS[m.movement_type] || m.movement_type), " · ", el("span.mono", {}, m.sku),
        el("div.small.muted", {}, `${fmt.datetime(m.created_at)} · ${m.user || "sistema"}${m.reference ? " · " + m.reference : ""}`)),
      el("span.num", {}, (m.quantity > 0 ? "+" : "") + m.quantity, el("div.small.muted", {}, `saldo ${m.balance_after}`)))))
    : empty("Sin movimientos", "Registra la primera entrada en Existencias.")));
  related.append(el("div.card", {}, el("h2", {}, "Conteos aplicados a este producto"), overview.recent_counts.length
    ? el("ul.list", {}, overview.recent_counts.map((c) => el("li", {},
      el("span", {}, el("a", { href: `#/conteo/${c.id}` }, `Conteo #${c.id}`), ` · ${c.variant_sku}`,
        el("div.small.muted", {}, fmt.datetime(c.applied_at || c.created_at))),
      el("span.num", {}, c.difference === null ? "—" : `${c.difference > 0 ? "+" : ""}${c.difference}`))))
    : empty("Sin conteos", "Los conteos con foto conciliados con este producto aparecerán aquí.")));
  root.append(related);
  let pending = null;
  try { pending = JSON.parse(sessionStorage.getItem(VARIANT_PREFILL_KEY) || "null"); sessionStorage.removeItem(VARIANT_PREFILL_KEY); } catch { pending = null; }
  if (manage && pending && Object.values(pending).some(Boolean)) {
    variantDialog(product, null, reload, { ...pending, note: "Datos propuestos por el lector de etiquetas: revísalos antes de guardar." });
  }
}
