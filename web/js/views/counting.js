// Conteo inteligente: subir foto → detecciones → revisión (aceptar/rechazar/añadir cajas) →
// confirmación (zapatos, pares, sueltos) → conciliación opcional con el stock de una variante.
import { api } from "../api.js";
import { Camera, cameraError, cameraHelp, cameraSupported } from "../camera.js";
import { productCard } from "../productcard.js";
import {
  badge, confirmDialog, el, empty, field, fmt, icon, modal, options, pageHead, pagedTable, queryString,
  showError, toast,
} from "../ui.js";

const STATUS = {
  revision: ["info", "En revisión"], confirmado: ["warn", "Confirmado (sin aplicar)"],
  aplicado: ["good", "Aplicado al stock"], descartado: ["", "Descartado"],
};
const statusBadge = (s) => badge(...(STATUS[s] || ["", s]));

export async function render(root, params, ctx) {
  if (params[0]) return renderCount(root, Number(params[0]), ctx);
  return renderList(root, ctx);
}

async function renderList(root, { can }) {
  const status = await api.get("/api/ai/status");
  root.append(pageHead("Conteo inteligente", "Detecta zapatos en una foto, revisa el resultado y confírmalo antes de tocar el stock."));
  root.append(status.installed
    ? el("div.alert.good", {}, `Modelo de detección activo: ${status.version}. Umbral de confianza: ${status.confidence_threshold}.`,
      status.metadata?.metrics?.test ? ` Evaluación en test: precisión ${fmt.pct(status.metadata.metrics.test.precision)}, recall ${fmt.pct(status.metadata.metrics.test.recall)}, mAP50 ${fmt.dec(status.metadata.metrics.test.map50, 3)}.` : "")
    : el("div.alert.warn", {}, el("strong", {}, "No hay un modelo de detección instalado. "), status.message,
      " Puedes contar igualmente marcando cada zapato a mano sobre la foto."));

  if (can("counts.create")) {
    const input = el("input", { type: "file", accept: "image/jpeg,image/png,image/webp", class: "sr-only", id: "count-file" });
    const notes = el("input", { placeholder: "Ubicación o nota (opcional): estante, caja, almacén…", maxlength: 200 });
    const zone = el("div.dropzone", {},
      el("p", {}, el("strong", {}, "Arrastra aquí una foto o selecciónala")),
      el("p.small.muted", {}, "JPG, PNG o WEBP, hasta 15 MB. La foto se guarda sin metadatos (EXIF/GPS)."),
      el("div.actions", {}, el("label.btn.primary", { for: "count-file" }, icon("camera"), "Elegir foto"),
        el("label.btn", { for: "count-file-camera" }, "Usar cámara")),
      el("input", { type: "file", accept: "image/*", capture: "environment", class: "sr-only", id: "count-file-camera",
        on: { change: (e) => send(e.target.files[0]) } }),
      el("div.filters", {}, notes), input);
    async function send(file) {
      if (!file) return;
      const form = new FormData();
      form.append("image", file);
      if (notes.value.trim()) form.append("notes", notes.value.trim());
      zone.classList.add("drag");
      zone.querySelector("strong").textContent = "Procesando la foto…";
      try {
        const count = await api.upload("/api/ai/counts", form);
        if (count.message) toast(count.message);
        location.hash = `#/conteo/${count.id}`;
      } catch (e) {
        showError(e);
        zone.classList.remove("drag");
        zone.querySelector("strong").textContent = "Arrastra aquí una foto o selecciónala";
      }
    }
    input.addEventListener("change", () => send(input.files[0]));
    zone.addEventListener("dragover", (e) => { e.preventDefault(); zone.classList.add("drag"); });
    zone.addEventListener("dragleave", () => zone.classList.remove("drag"));
    zone.addEventListener("drop", (e) => { e.preventDefault(); send(e.dataTransfer.files[0]); });
    const live = liveCounter(status);
    const photoTab = el("button.btn", { type: "button", "aria-pressed": "true" }, icon("upload"), "Subir foto");
    const liveTab = el("button.btn", { type: "button", "aria-pressed": "false" }, icon("camera"), "Cámara en vivo");
    const body = el("div", {}, zone);
    function mode(useLive) {
      photoTab.className = useLive ? "btn" : "btn primary";
      liveTab.className = useLive ? "btn primary" : "btn";
      photoTab.setAttribute("aria-pressed", String(!useLive));
      liveTab.setAttribute("aria-pressed", String(useLive));
      if (!useLive) live.stop();
      body.replaceChildren(useLive ? live.node : zone);
    }
    photoTab.addEventListener("click", () => mode(false));
    liveTab.addEventListener("click", () => mode(true));
    mode(false);
    root.append(el("div.card", { class: "stack" }, el("div.mode-switch", {}, photoTab, liveTab), body));
    // Al salir de la pantalla se apaga la cámara.
    window.addEventListener("hashchange", () => live.stop(), { once: true });
  }

  const filter = options(el("select"), Object.entries(STATUS).map(([id, [, name]]) => ({ id, name })), { placeholder: "Todos los estados" });
  const table = pagedTable({
    fetchPage: ({ limit, offset }) => api.get("/api/ai/counts" + queryString({ status: filter.value, limit, offset })),
    emptyNode: empty("Aún no hay conteos", "Sube una foto para crear el primero."),
    columns: [
      { label: "#", render: (c) => el("a", { href: `#/conteo/${c.id}` }, `#${c.id}`) },
      { label: "Fecha", render: (c) => fmt.datetime(c.created_at) },
      { label: "Usuario", render: (c) => c.user || "—" },
      { label: "Modelo", render: (c) => c.model_version || "manual" },
      { label: "Detectados", className: "num", render: (c) => c.detected_count ?? "—" },
      { label: "Confirmados", className: "num", render: (c) => c.confirmed_shoes ?? "—" },
      { label: "Pares / sueltos", className: "num", render: (c) => c.pairs_complete === null ? "—" : `${c.pairs_complete} / ${c.loose_shoes}` },
      { label: "Variante", render: (c) => c.variant_sku || "—" },
      { label: "Diferencia", className: "num", render: (c) => c.difference === null ? "—" : (c.difference > 0 ? "+" : "") + c.difference },
      { label: "Estado", render: (c) => statusBadge(c.status) },
    ],
  });
  filter.addEventListener("change", () => table.reload());
  root.append(el("div.card", { class: "stack" }, el("h2", {}, "Conteos realizados"), el("div.filters", {}, filter), table.node));
  table.reload();
}

/** Vista previa en vivo: cada fotograma se analiza sin guardarse; "Registrar" guarda la foto como conteo. */
function liveCounter(status) {
  const video = el("video", { playsinline: true, muted: true, autoplay: true, "aria-label": "Vista de la cámara" });
  const canvas = el("canvas");
  const badge = el("span.live-badge", {}, "Cámara apagada");
  const counter = el("span.live-count.hidden", { "aria-live": "polite" }, "0");
  const placeholder = el("div.placeholder", {}, cameraSupported()
    ? "Pulsa «Iniciar cámara». Apunta a los zapatos con buena luz y sin contraluz."
    : cameraHelp());
  const identity = el("div.live-identity.hidden", { "aria-live": "polite" });
  const stage = el("div.live", {}, video, canvas, placeholder, badge, counter, identity);
  const identityPanel = el("div.stack");
  let identified = null; // {variant, card}
  const notes = el("input", { placeholder: "Ubicación o nota (opcional): estante, caja…", maxlength: 200 });
  const info = el("p.small.muted", {}, status.installed
    ? `Detección en vivo con ${status.version} (umbral ${status.confidence_threshold}). Los fotogramas NO se guardan; solo «Registrar» guarda la foto para revisarla y confirmarla.`
    : "Sin modelo instalado: la vista en vivo no detecta, pero puedes registrar la foto y contar a mano.");
  const camera = new Camera(video);
  let running = false;
  let lastDetections = [];

  const startBtn = el("button.btn.primary", { type: "button", disabled: !cameraSupported() }, icon("camera"), "Iniciar cámara");
  const switchBtn = el("button.btn", { type: "button", disabled: true }, "Cambiar cámara");
  const recordBtn = el("button.btn.primary", { type: "button", disabled: true }, "Registrar foto y contar");
  const stopBtn = el("button.btn", { type: "button", disabled: true }, "Detener");
  const identifyBtn = el("button.btn", { type: "button", disabled: true }, icon("tag"), "Identificar producto");

  function showIdentity() {
    if (!identified) { identity.classList.add("hidden"); return; }
    const v = identified.variant;
    identity.textContent = `${v.brand} ${v.model_name} · ${v.sku} · talla ${v.size} · ${v.color} — sistema: ${fmt.pairs(v.stock_quantity)} · en la foto: ${fmt.shoes(counter.textContent)}`;
    identity.classList.remove("hidden");
  }

  identifyBtn.addEventListener("click", async () => {
    identifyBtn.disabled = true;
    identityPanel.replaceChildren(el("div.loading", {}, el("span.spinner"), " Leyendo código y etiqueta del fotograma…"));
    try {
      const form = new FormData();
      form.append("image", await camera.capture(1920, 0.95), "identificar.jpg");
      const data = await api.upload("/api/ocr/analyze", form);
      identityPanel.replaceChildren();
      if (data.matches.length === 1) {
        identified = { variant: data.matches[0] };
        toast(`Reconocido: ${data.matches[0].brand} ${data.matches[0].model_name} (${data.matches[0].sku})`, "good");
      } else if (data.matches.length > 1) {
        const pick = options(el("select"), data.matches, { label: (v) => `${v.sku} · T${v.size} ${v.color} (stock ${v.stock_quantity})` });
        identified = { variant: data.matches[0] };
        pick.addEventListener("change", () => { identified = { variant: data.matches.find((m) => String(m.id) === pick.value) }; showIdentity(); });
        identityPanel.append(el("div.card", {}, el("p", {}, "Se leyeron varias variantes del mismo producto: elige cuál estás contando."), pick));
      } else {
        identified = null;
        identityPanel.append(el("div.alert.warn", {}, data.barcodes.length
          ? `Código leído (${data.barcodes.map((b) => b.text).join(", ")}) pero no está registrado. Puedes crearlo desde «Lector de etiquetas».`
          : "No se encontró código de barras ni etiqueta legible. Acerca la etiqueta o la caja a la cámara y vuelve a intentarlo."));
      }
      data.cards.forEach((card) => identityPanel.append(productCard(card, { title: data.matches.length ? "Producto reconocido" : "Posible producto" })));
      showIdentity();
    } catch (e) {
      identityPanel.replaceChildren();
      showError(e);
    } finally {
      identifyBtn.disabled = !camera.active;
    }
  });

  function draw() {
    const rect = stage.getBoundingClientRect();
    canvas.width = rect.width;
    canvas.height = rect.height;
    const ctx = canvas.getContext("2d");
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    const vw = video.videoWidth;
    const vh = video.videoHeight;
    if (!vw || !vh) return;
    // object-fit: contain → zona visible del vídeo dentro del contenedor
    const scale = Math.min(rect.width / vw, rect.height / vh);
    const dw = vw * scale;
    const dh = vh * scale;
    const ox = (rect.width - dw) / 2;
    const oy = (rect.height - dh) / 2;
    ctx.lineWidth = 3;
    ctx.font = "bold 13px system-ui, sans-serif";
    lastDetections.forEach((d, i) => {
      const x = ox + d.x1 * dw;
      const y = oy + d.y1 * dh;
      const w = (d.x2 - d.x1) * dw;
      const h = (d.y2 - d.y1) * dh;
      ctx.strokeStyle = "#22c55e";
      ctx.strokeRect(x, y, w, h);
      const label = `${i + 1} · ${Math.round(d.confidence * 100)}%`;
      ctx.fillStyle = "#22c55e";
      ctx.fillRect(x - 1.5, y - 18, ctx.measureText(label).width + 8, 18);
      ctx.fillStyle = "#000";
      ctx.fillText(label, x + 3, y - 5);
    });
  }

  async function loop() {
    while (running && status.installed) {
      const started = performance.now();
      try {
        const frame = await camera.capture(960, 0.8);
        const form = new FormData();
        form.append("frame", frame, "frame.jpg");
        const result = await api.upload("/api/ai/detect", form);
        if (!running) break;
        lastDetections = result.detections || [];
        counter.textContent = String(result.count ?? 0);
        badge.textContent = `En vivo · ${result.inference_ms} ms`;
        draw();
        showIdentity();
      } catch (error) {
        badge.textContent = `Error: ${error.message}`;
        await new Promise((r) => setTimeout(r, 1500));
      }
      const elapsed = performance.now() - started;
      await new Promise((r) => setTimeout(r, Math.max(0, 350 - elapsed)));
    }
  }

  async function start() {
    try {
      await camera.start();
      placeholder.classList.add("hidden");
      counter.classList.toggle("hidden", !status.installed);
      badge.textContent = status.installed ? "En vivo" : "Cámara activa (sin modelo)";
      running = true;
      startBtn.disabled = true;
      [switchBtn, recordBtn, stopBtn, identifyBtn].forEach((b) => { b.disabled = false; });
      loop();
    } catch (error) {
      placeholder.textContent = cameraError(error);
      placeholder.classList.remove("hidden");
    }
  }

  function stop() {
    running = false;
    camera.stop();
    lastDetections = [];
    draw();
    badge.textContent = "Cámara apagada";
    counter.classList.add("hidden");
    placeholder.classList.remove("hidden");
    startBtn.disabled = !cameraSupported();
    [switchBtn, recordBtn, stopBtn, identifyBtn].forEach((b) => { b.disabled = true; });
  }

  startBtn.addEventListener("click", start);
  stopBtn.addEventListener("click", stop);
  switchBtn.addEventListener("click", async () => { try { await camera.switch(); } catch (e) { showError(e); } });
  recordBtn.addEventListener("click", async () => {
    recordBtn.disabled = true;
    try {
      const photo = await camera.capture(1920, 0.92);
      const form = new FormData();
      form.append("image", photo, `camara_${new Date().toISOString().replace(/[:.]/g, "-")}.jpg`);
      if (notes.value.trim()) form.append("notes", notes.value.trim());
      if (identified) form.append("variant_id", String(identified.variant.id));
      const count = await api.upload("/api/ai/counts", form);
      stop();
      toast(`Foto registrada como conteo #${count.id}. Revisa y confirma.`, "good");
      location.hash = `#/conteo/${count.id}`;
    } catch (e) {
      showError(e);
      recordBtn.disabled = false;
    }
  });
  window.addEventListener("resize", draw);
  return { node: el("div.stack", {}, stage, info, el("div.filters", {}, notes),
    el("div.actions", {}, startBtn, identifyBtn, recordBtn, switchBtn, stopBtn),
    el("p.small.muted", {}, "«Identificar producto» lee el código de barras o la etiqueta del fotograma actual para saber qué modelo estás contando y compararlo con su stock."),
    identityPanel), stop };
}

async function renderCount(root, countId, { can }) {
  let count = await api.get(`/api/ai/counts/${countId}`);
  const isEditable = () => count.status === "revision" && can("counts.create");
  const editable = isEditable();
  // Estado local de la revisión: cajas del modelo (aceptar/rechazar) y cajas manuales.
  let boxes = count.detections.map((d) => ({ ...d }));
  let dirty = false;

  const viewer = el("div.viewer");
  const image = el("img", { src: count.image_url, alt: `Foto del conteo ${count.id}` });
  const layer = el("div.layer", { "aria-label": "Zona de dibujo de cajas" });
  viewer.append(image, layer);
  const side = el("div.stack");
  const identityBox = el("div.stack.identity-box");
  root.append(pageHead(`Conteo #${count.id}`, `${fmt.datetime(count.created_at)} · ${count.user || "—"} · ${count.model_version ? "modelo " + count.model_version : "sin modelo (manual)"}`,
    el("a.btn", { href: "#/conteo" }, "← Conteos"),
    el("a.btn", { href: `/api/ai/counts/${count.id}/annotated.jpg`, download: `conteo-${count.id}.jpg` }, icon("download"), "Imagen anotada")),
  el("div.counter", {}, el("div", {}, viewer,
    editable ? el("p.small.muted", {}, "Haz clic en una caja para rechazarla o volver a aceptarla. Arrastra sobre la foto para marcar un zapato que el modelo no vio. Las cajas manuales se eliminan con un clic.") : null),
  side), identityBox);

  function accepted() { return boxes.filter((b) => b.accepted); }

  /** Selector de variante (buscar por SKU/modelo). Devuelve {node, value()}. */
  function variantPicker(initialQuery = "", selectedId = null) {
    const search = el("input", { type: "search", placeholder: "Buscar SKU, marca o modelo", value: initialQuery });
    const select = el("select");
    async function find() {
      try {
        const data = await api.get("/api/inventory/stock" + queryString({ q: search.value, limit: 50 }));
        options(select, data.items, { placeholder: data.items.length ? "Selecciona la variante" : "Sin resultados",
          label: (v) => `${v.sku} · ${v.brand} ${v.model_name} · T${v.size} ${v.color} (stock ${v.stock_quantity})`,
          selected: selectedId });
      } catch (e) { showError(e); }
    }
    search.addEventListener("change", find);
    find();
    return { node: el("div.form", {}, field("Buscar", search), field("Variante", select)), value: () => select.value };
  }

  function identityCard() {
    const closed = count.status === "aplicado" || count.status === "descartado";
    const canEdit = !closed && can("counts.create");
    const ident = count.identification || {};
    const changer = () => {
      const picker = variantPicker(count.identified_sku || "", count.identified_variant_id);
      return el("details", {}, el("summary", {}, count.identified ? "Cambiar el producto identificado" : "Identificar el producto a mano"),
        picker.node, el("button.btn", {
          type: "button",
          on: {
            async click() {
              if (!picker.value()) return;
              try {
                count = await api.put(`/api/ai/counts/${count.id}/identify`, { variant_id: Number(picker.value()) });
                toast(`Producto asignado: ${count.identified_sku}`, "good");
                refresh();
              } catch (e) { showError(e); }
            },
          },
        }, "Asignar producto"));
    };
    if (!count.identified) {
      return el("div.card", {}, el("h2", {}, "Producto de la foto"),
        el("p", {}, "No se identificó un producto registrado en esta foto."),
        el("p.small.muted", {}, ident.codes && ident.codes.length
          ? `Códigos leídos: ${ident.codes.join(", ")} (no coinciden con ningún SKU ni código de barras registrado).`
          : "No se vio ningún código de barras ni etiqueta legible. Para que se identifique solo, incluye la etiqueta o el código de la caja en la foto, o usa «Identificar producto» en la cámara en vivo."),
        ident.candidates && ident.candidates.length ? el("p.small", {}, `Posibles: ${ident.candidates.join(", ")}`) : null,
        canEdit ? changer() : null);
    }
    const c = count.comparison;
    const photoPairs = c.photo_pairs_confirmed ?? Math.floor(c.photo_shoes / 2);
    const methodText = { codigo: "por el código de barras de la foto", etiqueta: "por la etiqueta de la foto",
      seleccion_en_vivo: "desde la cámara en vivo", manual: "asignado a mano" }[ident.method] || "";
    return el("div.stack", {},
      el("div.card", {}, el("h2", {}, "Foto frente a inventario"),
        el("p.small.muted", {}, `Producto identificado ${methodText}.`),
        el("div.kpis.compact-kpis", {},
          el("div.kpi", {}, el("div.label", {}, "Variante"), el("div.value", {}, `${c.sku}`), el("div.note", {}, `Talla ${c.size} · ${c.color}`)),
          el("div.kpi", {}, el("div.label", {}, "Stock en sistema"), el("div.value", {}, fmt.pairs(c.system_pairs))),
          el("div.kpi", {}, el("div.label", {}, "En la foto"), el("div.value", {}, fmt.shoes(c.photo_shoes)),
            el("div.note", {}, c.photo_pairs_confirmed !== null && c.photo_pairs_confirmed !== undefined
              ? `${c.photo_pairs_confirmed} pares + ${c.photo_loose_confirmed} sueltos (confirmado)` : `≈ ${fmt.pairs(photoPairs)} (sin confirmar)`)),
          el("div.kpi", {}, el("div.label", {}, "Diferencia orientativa"), el("div.value", {}, `${photoPairs - c.system_pairs > 0 ? "+" : ""}${fmt.pairs(photoPairs - c.system_pairs)}`))),
        el("p.small.muted", {}, c.note),
        canEdit ? changer() : null),
      productCard(count.identified, { title: "Producto identificado en la foto" }));
  }

  function drawBoxes() {
    layer.replaceChildren();
    boxes.forEach((b, index) => {
      const node = el(`div.box${b.source === "manual" ? ".manual" : ""}${b.accepted ? "" : ".rejected"}`);
      node.style.left = `${b.x1 * 100}%`;
      node.style.top = `${b.y1 * 100}%`;
      node.style.width = `${(b.x2 - b.x1) * 100}%`;
      node.style.height = `${(b.y2 - b.y1) * 100}%`;
      const label = b.source === "manual" ? "manual" : `${Math.round(b.confidence * 100)}%`;
      node.append(el("span.tag", {}, `${index + 1} · ${label}${b.accepted ? "" : " ✕"}`));
      if (isEditable()) {
        node.append(el("button", {
          type: "button",
          "aria-label": b.source === "manual" ? `Eliminar caja manual ${index + 1}` : `${b.accepted ? "Rechazar" : "Aceptar"} detección ${index + 1}`,
          on: {
            pointerdown: (e) => e.stopPropagation(),
            click: (e) => {
              e.stopPropagation();
              if (b.source === "manual") boxes = boxes.filter((x) => x !== b);
              else b.accepted = !b.accepted;
              dirty = true;
              refresh();
            },
          },
        }));
      }
      layer.append(node);
    });
  }

  {
    let start = null;
    let ghost = null;
    const point = (e) => {
      const rect = layer.getBoundingClientRect();
      return { x: Math.min(1, Math.max(0, (e.clientX - rect.left) / rect.width)), y: Math.min(1, Math.max(0, (e.clientY - rect.top) / rect.height)) };
    };
    layer.addEventListener("pointerdown", (e) => {
      if (!isEditable()) return;
      start = point(e);
      ghost = el("div.box.drawing");
      layer.append(ghost);
      layer.setPointerCapture(e.pointerId);
    });
    layer.addEventListener("pointermove", (e) => {
      if (!start) return;
      const p = point(e);
      ghost.style.left = `${Math.min(start.x, p.x) * 100}%`;
      ghost.style.top = `${Math.min(start.y, p.y) * 100}%`;
      ghost.style.width = `${Math.abs(p.x - start.x) * 100}%`;
      ghost.style.height = `${Math.abs(p.y - start.y) * 100}%`;
    });
    layer.addEventListener("pointerup", (e) => {
      if (!start) return;
      const p = point(e);
      const box = { x1: Math.min(start.x, p.x), y1: Math.min(start.y, p.y), x2: Math.max(start.x, p.x), y2: Math.max(start.y, p.y),
        source: "manual", accepted: true, confidence: null };
      start = null;
      ghost.remove();
      if (box.x2 - box.x1 > 0.01 && box.y2 - box.y1 > 0.01) {
        boxes.push(box);
        dirty = true;
        refresh();
      }
    });
  }

  async function saveReview() {
    const payload = boxes.map((b) => b.source === "modelo"
      ? { id: b.id, source: "modelo", accepted: b.accepted }
      : { source: "manual", x1: b.x1, y1: b.y1, x2: b.x2, y2: b.y2 });
    count = await api.put(`/api/ai/counts/${count.id}/review`, { detections: payload });
    boxes = count.detections.map((d) => ({ ...d }));
    dirty = false;
  }

  function refresh() {
    drawBoxes();
    identityBox.replaceChildren(identityCard());
    const total = accepted().length;
    const manual = boxes.filter((b) => b.source === "manual" && b.accepted).length;
    const rejected = boxes.filter((b) => b.source === "modelo" && !b.accepted).length;
    side.replaceChildren();
    side.append(el("div.card", {},
      el("div.small.muted", {}, "Zapatos individuales marcados"),
      el("div.count-total", {}, total),
      el("p.small.muted", {}, count.detected_count === null ? "Sin modelo: conteo manual." :
        `El modelo detectó ${count.detected_count}; rechazados ${rejected}; añadidos a mano ${manual}.`),
      el("div.legend-boxes", {}, el("span", {}, "Detección aceptada (con confianza)"), el("span.m", {}, "Añadida manualmente"), el("span.r", {}, "Rechazada (falso positivo)")),
      el("p", {}, statusBadge(count.status)),
      count.notes ? el("p.small", {}, count.notes) : null));

    if (count.status === "revision") {
      if (isEditable()) {
        side.append(el("div.card", {}, el("h3", {}, "1. Guardar revisión"),
          el("p.small.muted", {}, dirty ? "Hay cambios sin guardar." : "Sin cambios pendientes."),
          el("div.actions", {},
            el("button.btn", { type: "button", disabled: !dirty, on: { click: async () => { try { await saveReview(); toast("Revisión guardada", "good"); refresh(); } catch (e) { showError(e); } } } }, "Guardar revisión"),
            el("button.btn.danger", { type: "button", on: { click: discard } }, "Descartar"))));
      }
      if (can("counts.confirm")) {
        const pairs = el("input", { type: "number", min: 0, step: 1, value: Math.floor(total / 2) });
        const loose = el("input", { type: "number", min: 0, step: 1, value: total % 2 });
        const check = el("p.small");
        const updateCheck = () => {
          const sum = Number(pairs.value) * 2 + Number(loose.value);
          check.textContent = sum === total ? `✓ ${pairs.value} pares × 2 + ${loose.value} sueltos = ${total} zapatos` : `✕ ${pairs.value} × 2 + ${loose.value} = ${sum}, pero hay ${total} zapatos marcados`;
          check.className = sum === total ? "small" : "small field-error";
        };
        pairs.addEventListener("input", updateCheck);
        loose.addEventListener("input", updateCheck);
        updateCheck();
        side.append(el("div.card", {}, el("h3", {}, "2. Confirmar conteo"),
          el("p.small.muted", {}, "Dos zapatos detectados no son necesariamente un par comercial: indica cuántos pares completos (mismo modelo, talla y color, izquierdo + derecho) y cuántos zapatos sueltos hay."),
          el("div.form.two", {}, field("Pares completos", pairs), field("Zapatos sueltos", loose)), check,
          el("button.btn.primary", {
            type: "button",
            on: {
              async click() {
                try {
                  if (dirty) await saveReview();
                  count = await api.post(`/api/ai/counts/${count.id}/confirm`, { pairs_complete: Number(pairs.value), loose_shoes: Number(loose.value) });
                  toast("Conteo confirmado. El stock aún no ha cambiado.", "good");
                  boxes = count.detections.map((d) => ({ ...d }));
                  refresh();
                } catch (e) { showError(e); }
              },
            },
          }, "Confirmar conteo")));
      }
    } else if (count.status === "confirmado") {
      side.append(el("div.card", {}, el("h3", {}, "Resultado confirmado"), el("dl.dl", {},
        el("dt", {}, "Zapatos"), el("dd", {}, count.confirmed_shoes), el("dt", {}, "Pares completos"), el("dd", {}, count.pairs_complete),
        el("dt", {}, "Sueltos"), el("dd", {}, count.loose_shoes), el("dt", {}, "Confirmó"), el("dd", {}, `${count.confirmed_by} · ${fmt.datetime(count.confirmed_at)}`))));
      if (can("counts.confirm") && can("inventory.move")) side.append(applyCard());
      if (can("counts.create")) side.append(el("button.btn.danger", { type: "button", on: { click: discard } }, "Descartar conteo"));
    } else if (count.status === "aplicado") {
      side.append(el("div.card", {}, el("h3", {}, "Aplicado al inventario"), el("dl.dl", {},
        el("dt", {}, "Variante"), el("dd", {}, el("a", { href: `#/movimientos/${count.variant_id}` }, count.variant_sku)),
        el("dt", {}, "Stock antes"), el("dd", {}, count.stock_before), el("dt", {}, "Pares contados"), el("dd", {}, count.applied_pairs),
        el("dt", {}, "Diferencia"), el("dd", {}, (count.difference > 0 ? "+" : "") + count.difference),
        el("dt", {}, "Aplicó"), el("dd", {}, `${count.applied_by} · ${fmt.datetime(count.applied_at)}`))));
    }
  }

  function applyCard() {
    const search = el("input", { type: "search", placeholder: "Buscar SKU o modelo", value: count.identified_sku || "" });
    const select = el("select", { required: true });
    const countedPairs = el("input", { type: "number", min: 0, step: 1, value: count.pairs_complete });
    const reason = el("textarea", { placeholder: "Alcance del conteo: p. ej. «estante A completo», «caja 12»", maxlength: 500 });
    const preview = el("p.small");
    let variants = [];
    async function find() {
      try {
        const data = await api.get("/api/inventory/stock" + queryString({ q: search.value, limit: 50 }));
        variants = data.items;
        options(select, variants, { placeholder: variants.length ? "Selecciona la variante contada" : "Sin resultados",
          label: (v) => `${v.sku} · ${v.brand} ${v.model_name} · T${v.size} ${v.color} (sistema: ${v.stock_quantity})`,
          selected: count.identified_variant_id });
        updatePreview();
      } catch (e) { showError(e); }
    }
    function updatePreview() {
      const v = variants.find((x) => String(x.id) === select.value);
      preview.textContent = v ? `Sistema: ${v.stock_quantity} pares → contado: ${countedPairs.value}. Diferencia: ${Number(countedPairs.value) - v.stock_quantity}.` : "";
    }
    search.addEventListener("change", find);
    select.addEventListener("change", updatePreview);
    countedPairs.addEventListener("input", updatePreview);
    find();
    return el("div.card", {}, el("h3", {}, "3. Conciliar con el stock (opcional)"),
      el("p.small.muted", {}, "Registra un movimiento «conteo físico» con la diferencia. Indica los pares que corresponden a UNA variante (la foto puede cubrir solo una parte del stock)."),
      el("div.form", {}, field("Buscar variante", search), field("Variante", select), field("Pares contados de esta variante", countedPairs), field("Motivo / alcance *", reason)),
      preview,
      el("button.btn.primary", {
        type: "button",
        on: {
          async click() {
            if (!select.value || !reason.value.trim()) { toast("Elige la variante e indica el motivo.", "bad"); return; }
            const ok = await confirmDialog("Aplicar al inventario", `${preview.textContent} Se registrará un movimiento de conteo físico a tu nombre.`, { confirmText: "Aplicar" });
            if (!ok) return;
            try {
              const result = await api.post(`/api/ai/counts/${count.id}/apply`, { variant_id: Number(select.value), counted_pairs: Number(countedPairs.value), reason: reason.value.trim() });
              count = result.count;
              toast(result.movement ? `Stock ajustado (${result.movement.quantity > 0 ? "+" : ""}${result.movement.quantity}).` : "El conteo coincide con el stock; no hubo ajuste.", "good");
              refresh();
            } catch (e) { showError(e); }
          },
        },
      }, "Aplicar al inventario"));
  }

  async function discard() {
    const reason = await confirmDialog("Descartar conteo", "El conteo quedará registrado como descartado.", { confirmText: "Descartar", danger: true, input: "Motivo" });
    if (!reason) return;
    try { count = await api.post(`/api/ai/counts/${count.id}/discard`, { reason }); boxes = count.detections.map((d) => ({ ...d })); refresh(); } catch (e) { showError(e); }
  }

  refresh();
}
