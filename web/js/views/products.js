// Productos (modelo comercial), variantes (talla+color), fotos y catálogos: marcas, categorías, proveedores.
import { api } from "../api.js";
import {
  badge, confirmDialog, el, empty, field, fmt, formValues, icon, modal, options, pageHead, pagedTable,
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

function productForm(product) {
  if (!catalogs.brands.length) {
    return el("div.alert.warn", {}, "Primero crea al menos una marca en la pestaña «Marcas».");
  }
  return el("form.form.two", {},
    field("Código interno *", el("input", { name: "code", required: true, maxlength: 50, value: product?.code || "" })),
    field("Marca *", options(el("select", { name: "brand_id", required: true }), catalogs.brands, { placeholder: "Selecciona", selected: product?.brand_id })),
    el("label.field.full", {}, "Modelo *", el("input", { name: "model_name", required: true, maxlength: 150, value: product?.model_name || "" })),
    field("Categoría", options(el("select", { name: "category_id" }), catalogs.categories, { placeholder: "Sin categoría", selected: product?.category_id })),
    field("Tipo de calzado", el("input", { name: "footwear_type", maxlength: 100, value: product?.footwear_type || "", placeholder: "Zapatilla, bota, sandalia…" })),
    field("Proveedor", options(el("select", { name: "supplier_id" }), catalogs.suppliers, { placeholder: "Sin proveedor", selected: product?.supplier_id })),
    field("Estado", options(el("select", { name: "status" }), [{ id: "activo", name: "Activo" }, { id: "inactivo", name: "Inactivo" },
      { id: "descontinuado", name: "Descontinuado" }], { selected: product?.status || "activo" })),
    el("label.field.full", {}, "Descripción", el("textarea", { name: "description", maxlength: 5000 }, product?.description || "")),
    el("label.check.full", {}, el("input", { type: "checkbox", name: "is_published", checked: Boolean(product?.is_published) }),
      "Publicar en la tienda online (solo variantes activas con precio)"));
}

function productDialog(product, done) {
  return modal(product ? "Editar producto" : "Nuevo producto", (body, close, foot) => {
    const form = productForm(product);
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
              const saved = product ? await api.patch(`/api/products/${product.id}`, data) : await api.post("/api/products", data);
              toast("Producto guardado", "good");
              close(saved);
              if (done) done(saved);
              else location.hash = `#/productos/${saved.id}`;
            } catch (e) { showError(e); }
          },
        },
      }, "Guardar") : null);
  });
}

function variantDialog(product, variant, done) {
  return modal(variant ? `Editar variante ${variant.sku}` : "Nueva variante (talla + color)", (body, close, foot) => {
    const form = el("form.form.two", {},
      field("SKU *", el("input", { name: "sku", required: true, maxlength: 60, value: variant?.sku || "" })),
      field("Código de barras", el("input", { name: "barcode", maxlength: 64, value: variant?.barcode || "" })),
      field("Talla *", el("input", { name: "size", required: true, maxlength: 20, value: variant?.size || "" })),
      field("Color *", el("input", { name: "color", required: true, maxlength: 50, value: variant?.color || "" })),
      field("Costo de adquisición", el("input", { name: "cost", type: "number", min: 0, step: "0.01", value: variant?.cost ?? "" })),
      field("Precio de venta", el("input", { name: "price", type: "number", min: 0, step: "0.01", value: variant?.price ?? "" })),
      field("Stock mínimo (alerta)", el("input", { name: "min_stock", type: "number", min: 0, step: 1, value: variant?.min_stock ?? 0 })),
      field("Estado", options(el("select", { name: "status" }), [{ id: "activo", name: "Activo" }, { id: "inactivo", name: "Inactivo" },
        { id: "descontinuado", name: "Descontinuado" }], { selected: variant?.status || "activo" })),
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

async function renderDetail(root, productId, { can }) {
  const manage = can("products.manage");
  const product = await api.get(`/api/products/${productId}`);
  const reload = () => { root.replaceChildren(); renderDetail(root, productId, { can }); };
  root.append(pageHead(`${product.brand} ${product.model_name}`, `Código ${product.code} · ${product.category || "sin categoría"}`,
    el("a.btn", { href: "#/productos" }, "← Volver"),
    manage ? el("button.btn", { type: "button", on: { click: () => productDialog(product, reload) } }, "Editar producto") : null,
    manage ? el("button.btn.primary", { type: "button", on: { click: () => variantDialog(product, null, reload) } }, icon("plus"), "Nueva variante") : null));

  const grid = el("div.grid.cols-2");
  root.append(grid);
  grid.append(el("div.card", {}, el("h2", {}, "Datos del producto"), el("dl.dl", {},
    el("dt", {}, "Marca"), el("dd", {}, product.brand),
    el("dt", {}, "Tipo"), el("dd", {}, product.footwear_type || "—"),
    el("dt", {}, "Proveedor"), el("dd", {}, product.supplier_name || "—"),
    el("dt", {}, "Estado"), el("dd", {}, badge(product.status === "activo" ? "good" : "", product.status)),
    el("dt", {}, "Tienda online"), el("dd", {}, product.is_published ? badge("info", "Publicado") : "No publicado"),
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
    }, "✕") : null)));
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
}
