// Conteo inteligente: subir foto → detecciones → revisión (aceptar/rechazar/añadir cajas) →
// confirmación (zapatos, pares, sueltos) → conciliación opcional con el stock de una variante.
import { api } from "../api.js";
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
    root.append(el("div.card", { class: "stack" }, zone));
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
  root.append(pageHead(`Conteo #${count.id}`, `${fmt.datetime(count.created_at)} · ${count.user || "—"} · ${count.model_version ? "modelo " + count.model_version : "sin modelo (manual)"}`,
    el("a.btn", { href: "#/conteo" }, "← Conteos"),
    el("a.btn", { href: `/api/ai/counts/${count.id}/annotated.jpg`, download: `conteo-${count.id}.jpg` }, icon("download"), "Imagen anotada")),
  el("div.counter", {}, el("div", {}, viewer,
    editable ? el("p.small.muted", {}, "Haz clic en una caja para rechazarla o volver a aceptarla. Arrastra sobre la foto para marcar un zapato que el modelo no vio. Las cajas manuales se eliminan con un clic.") : null),
  side));

  function accepted() { return boxes.filter((b) => b.accepted); }

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
    const search = el("input", { type: "search", placeholder: "Buscar SKU o modelo" });
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
          label: (v) => `${v.sku} · ${v.brand} ${v.model_name} · T${v.size} ${v.color} (sistema: ${v.stock_quantity})` });
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
