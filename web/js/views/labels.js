// Lector de etiquetas: código de barras/QR + OCR. Propone datos; la persona decide qué hacer con ellos.
import { api } from "../api.js";
import { Camera, cameraError, cameraHelp, cameraSupported } from "../camera.js";
import { badge, el, empty, fmt, icon, pageHead, showError, stockBadge } from "../ui.js";
import { movementDialog } from "./inventory.js";
import { openNewProductFromLabel, openNewVariantFromLabel } from "./products.js";
import { productCard } from "../productcard.js";

export async function render(root, _params, ctx) {
  const { can } = ctx;
  const result = el("div.stack");
  const video = el("video", { playsinline: true, muted: true, autoplay: true, "aria-label": "Vista de la cámara" });
  const placeholder = el("div.placeholder", {}, cameraSupported()
    ? "Enfoca la etiqueta, la caja o el código de barras y pulsa «Leer»."
    : cameraHelp());
  const stage = el("div.live", {}, video, placeholder);
  const camera = new Camera(video);
  const startBtn = el("button.btn", { type: "button", disabled: !cameraSupported() }, icon("camera"), "Iniciar cámara");
  const readBtn = el("button.btn.primary", { type: "button", disabled: true }, "Leer etiqueta");
  const switchBtn = el("button.btn", { type: "button", disabled: true }, "Cambiar cámara");
  const fileInput = el("input", { type: "file", accept: "image/jpeg,image/png,image/webp", class: "sr-only", id: "label-file" });

  startBtn.addEventListener("click", async () => {
    try {
      await camera.start();
      placeholder.classList.add("hidden");
      readBtn.disabled = false;
      switchBtn.disabled = false;
    } catch (e) {
      placeholder.textContent = cameraError(e);
    }
  });
  switchBtn.addEventListener("click", () => camera.switch().catch(showError));
  readBtn.addEventListener("click", async () => {
    try { await analyze(await camera.capture(1920, 0.95), "camara.jpg"); } catch (e) { showError(e); }
  });
  fileInput.addEventListener("change", () => { if (fileInput.files[0]) analyze(fileInput.files[0], fileInput.files[0].name); });
  window.addEventListener("hashchange", () => camera.stop(), { once: true });

  async function analyze(blob, name) {
    readBtn.disabled = true;
    result.replaceChildren(el("div.loading", {}, el("span.spinner"), " Leyendo código y texto… (la primera lectura carga el modelo de OCR)"));
    try {
      const form = new FormData();
      form.append("image", blob, name);
      showResult(await api.upload("/api/ocr/analyze", form));
    } catch (e) {
      showError(e);
      result.replaceChildren();
    } finally {
      readBtn.disabled = !camera.active;
    }
  }

  function chips(values, kind = "info") {
    return values.length ? el("div.field-chips", {}, values.map((v) => badge(kind, v))) : el("span.muted", {}, "—");
  }

  function variantRow(v) {
    return el("tr", {}, el("td.mono", {}, v.sku), el("td", {}, `${v.brand} ${v.model_name}`), el("td", {}, v.size),
      el("td", {}, v.color), el("td.num", {}, fmt.int(v.stock_quantity)), el("td", {}, stockBadge(v.stock_state)),
      el("td.num", {}, (can("inventory.move") || can("inventory.sell"))
        ? el("button.btn.small.primary", { type: "button", on: { click: () => movementDialog(v, { can, onDone: () => {} }) } }, "Registrar movimiento")
        : null));
  }

  function showResult(data) {
    const f = data.fields;
    const first = (list) => (list.length ? list[0] : "");
    const variantPrefill = { size: first(f.sizes), color: first(f.colors), price: first(f.prices),
      barcode: first(data.barcodes.map((b) => b.text)), sku: "" };
    const table = (rows) => el("div.table-wrap", {}, el("table", {},
      el("thead", {}, el("tr", {}, ["SKU", "Producto", "Talla", "Color", "Pares", "Estado", ""].map((h) => el("th", {}, h)))),
      el("tbody", {}, rows.map(variantRow))));
    const actions = el("div.actions");
    if (can("products.manage") && !data.matches.length) {
      actions.append(el("button.btn.primary", {
        type: "button",
        on: {
          click: () => openNewProductFromLabel({ brand: first(f.brands), variant: variantPrefill,
            note: "Datos propuestos por el lector de etiquetas: revísalos. Al guardar se propondrá la variante." }),
        },
      }, icon("plus"), "Crear producto con estos datos"));
      if (data.suggestions.length) {
        const productId = data.suggestions[0].product_id;
        actions.append(el("button.btn", { type: "button", on: { click: () => openNewVariantFromLabel(productId, variantPrefill) } },
          `Añadir variante a ${data.suggestions[0].brand} ${data.suggestions[0].model_name}`));
      }
    }
    result.replaceChildren(el("div.grid.cols-2", {},
      el("div.card", {}, el("h2", {}, "Imagen leída"), el("img", { src: data.image_url, alt: "Etiqueta leída", class: "full-img" }),
        el("p.small.muted", {}, `Lectura en ${fmt.int(data.elapsed_ms)} ms · imagen guardada (privada) para trazabilidad.`)),
      el("div.card", {}, el("h2", {}, "Datos detectados"),
        el("div.alert.info", {}, data.note),
        el("dl.dl", {},
          el("dt", {}, "Códigos"), el("dd", {}, data.barcodes.length
            ? el("div.field-chips", {}, data.barcodes.map((b) => badge("good", `${b.text} (${b.format})`))) : el("span.muted", {}, "Ningún código de barras/QR")),
          el("dt", {}, "Marca"), el("dd", {}, chips(f.brands)),
          el("dt", {}, "Talla"), el("dd", {}, chips(f.sizes)),
          el("dt", {}, "Color"), el("dd", {}, chips(f.colors)),
          el("dt", {}, "Precio"), el("dd", {}, chips(f.prices)),
          el("dt", {}, "SKU / código"), el("dd", {}, chips(f.codes))),
        el("h3", {}, "Texto leído (OCR)"),
        el("div.ocr-lines", {}, data.lines.length ? data.lines.map((l) => `${l.text}   (${Math.round(l.confidence * 100)}%)`).join("\n") : "Sin texto legible."))),
    ...data.cards.map((card) => productCard(card, {
      title: data.matches.length ? "Producto registrado reconocido" : "Posible producto (misma marca y talla, sin código exacto)" })),
    el("div.card", {}, el("h2", {}, data.matches.length ? "Variantes encontradas en el inventario" : "Variantes parecidas"),
      data.matches.length ? table(data.matches)
        : data.suggestions.length ? el("div", {}, el("p.muted", {}, "No hay coincidencia exacta de código; variantes de la misma marca y talla:"), table(data.suggestions))
          : empty("Sin coincidencias", "El código o SKU no está registrado. Puedes crear el producto con los datos detectados."),
      actions));
  }

  root.append(pageHead("Lector de etiquetas", "Lee códigos de barras, QR y texto de etiquetas o cajas para buscar el producto o registrarlo."),
    el("div.grid.cols-2", {},
      el("div.card", {}, stage, el("div.actions", { class: "stack" }, startBtn, readBtn, switchBtn,
        fileInput, el("label.btn", { for: "label-file" }, icon("upload"), "Subir foto"))),
      el("div.card", {}, el("h2", {}, "Cómo funciona"), el("ul", {},
        el("li", {}, "El código de barras o QR se busca en SKU, código de barras y código de producto."),
        el("li", {}, "El texto (OCR) propone marca, talla, color y precio. La marca solo se reconoce si está escrita y registrada en «Marcas»: no se identifican logotipos."),
        el("li", {}, "Nada se guarda en el inventario sin que tú lo confirmes en el formulario correspondiente."),
        el("li", {}, "Funciona sin conexión a Internet: los modelos de lectura van incluidos.")))),
    result);
}
