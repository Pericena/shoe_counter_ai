// Importación Excel/CSV en dos pasos: validar (vista previa e incidencias) → confirmar.
import { api, download } from "../api.js";
import { badge, el, empty, fmt, icon, pageHead, pagedTable, queryString, showError, toast } from "../ui.js";

const KINDS = {
  catalogo: { label: "Catálogo de la tienda", help: "Productos y variantes (código, marca, modelo, SKU, talla, color, costo, precio…). Opcionalmente «cantidad_entrada» registra una entrada de stock." },
  comercio: { label: "Comercio exterior de calzado", help: "Estadísticas por país, flujo, año, código SA6 y socio. Se guardan aparte del inventario de la tienda." },
};

function batchView(batch, onChange) {
  const s = batch.summary || {};
  const errors = (batch.issues || []).filter((i) => i.severity === "error");
  const warnings = (batch.issues || []).filter((i) => i.severity === "advertencia");
  const card = el("div.card", {}, el("h2", {}, `Importación #${batch.id} · ${batch.file_name}`),
    el("p", {}, badge(batch.status === "confirmado" ? "good" : batch.status === "descartado" ? "" : "info", batch.status), " ",
      el("span.small.muted", {}, `${KINDS[batch.kind].label}${s.kind_detected ? " (detectado automáticamente)" : ""}${s.duplicate_policy === "separados" ? " · repetidas como operaciones separadas" : ""} · ${batch.sheet_name ? "hoja «" + batch.sheet_name + "» · " : ""}${fmt.datetime(batch.created_at)} · ${batch.user}`)));
  card.append(el("div.kpis", {},
    ...[["Filas leídas", batch.total_rows], ["Válidas", batch.valid_rows], ["Rechazadas", batch.rejected],
      ["Errores", s.errors ?? errors.length], ["Advertencias", s.warnings ?? warnings.length],
      ...(batch.status === "confirmado" ? [["Añadidas", batch.added], ["Actualizadas", batch.updated], ["Sin cambios", batch.skipped]] : [])]
      .map(([label, value]) => el("div.kpi", {}, el("div.label", {}, label), el("div.value", {}, fmt.int(value))))));
  if (s.suggested_kind) {
    card.append(el("div.alert.warn", {}, el("strong", {}, "Tipo de datos equivocado. "),
      `Este archivo tiene las columnas de «${KINDS[s.suggested_kind].label}». Súbelo de nuevo eligiendo ese tipo.`));
  } else if (s.missing_columns?.length) {
    card.append(el("div.alert.bad", {}, `Faltan columnas obligatorias: ${s.missing_columns.join(", ")}.`));
  }
  if (s.mapping) {
    card.append(el("details", {}, el("summary", {}, "Columnas detectadas"),
      el("p.small", {}, "Asignadas: ", Object.entries(s.mapping).map(([k, v]) => `${v} → ${k}`).join(" · ")),
      s.extra_columns?.length ? el("p.small.muted", {}, `Ignoradas: ${s.extra_columns.join(", ")}`) : null));
  }
  if (s.preview?.length) {
    const columns = Object.keys(s.preview[0]).filter((k) => !k.startsWith("_") && k !== "quality_flags");
    card.append(el("h3", {}, "Vista previa (primeras filas válidas, ya normalizadas)"),
      el("div.table-wrap", {}, el("table", {}, el("thead", {}, el("tr", {}, el("th", {}, "Fila"), columns.map((c) => el("th", {}, c)))),
        el("tbody", {}, s.preview.map((row) => el("tr", {}, el("td", {}, row._row), columns.map((c) => el("td", {}, row[c] === null || row[c] === undefined ? "—" : String(row[c])))))))));
  }
  if (batch.issues?.length) {
    card.append(el("h3", {}, `Incidencias (${batch.issues_total ?? batch.issues.length})`),
      el("div.table-wrap", {}, el("table", {}, el("thead", {}, el("tr", {}, ["Fila", "Columna", "Tipo", "Mensaje"].map((h) => el("th", {}, h)))),
        el("tbody", {}, batch.issues.map((i) => el("tr", {}, el("td", {}, i.row ?? "—"), el("td", {}, i.column || "—"),
          el("td", {}, badge(i.severity === "error" ? "bad" : "warn", i.severity)), el("td.wrap", {}, i.message)))))));
  }
  if (batch.status === "validado") {
    const blocking = s.blocking || batch.valid_rows === 0;
    card.append(el("div.actions", {},
      el("button.btn.primary", {
        type: "button", disabled: blocking,
        on: {
          async click(event) {
            event.target.disabled = true;
            try {
              const result = await api.post(`/api/imports/${batch.id}/confirm`, {});
              toast(`Importación confirmada: ${result.added} añadidas, ${result.updated} actualizadas, ${result.skipped} sin cambios.`, "good");
              onChange(result);
            } catch (e) { showError(e); event.target.disabled = false; }
          },
        },
      }, `Confirmar e importar ${fmt.int(batch.valid_rows)} filas`),
      el("button.btn", { type: "button", on: { click: async () => { try { onChange(await api.post(`/api/imports/${batch.id}/discard`, {})); } catch (e) { showError(e); } } } }, "Descartar"),
      blocking ? el("span.small.field-error", {}, "No se puede confirmar: corrige el archivo y súbelo de nuevo.") :
        batch.rejected ? el("span.small.muted", {}, `Las ${batch.rejected} filas rechazadas no se importarán.`) : null));
  }
  if (batch.status === "confirmado" && batch.kind === "comercio") {
    card.append(el("div.actions", {}, el("a.btn", { href: "#/comercio" }, "Ver análisis comercial"),
      el("button.btn", { type: "button", on: { click: () => download(`/api/exports/calidad_importaciones?format=xlsx&batch_id=${batch.id}`).catch(showError) } }, "Informe de calidad (Excel)")));
  }
  return card;
}

export async function render(root, params) {
  const result = el("div.stack");
  const kind = el("select", {}, new Option("Detectar automáticamente (recomendado)", "auto"),
    Object.entries(KINDS).map(([id, k]) => new Option(k.label, id)));
  const AUTO_HELP = "El sistema reconoce por las columnas si es un catálogo de la tienda o datos de comercio exterior.";
  const help = el("p.small.muted", {}, AUTO_HELP);
  const policy = el("select", {},
    new Option("Rechazar para revisión (recomendado)", "rechazar"),
    new Option("Conservar como operaciones separadas (se suman)", "separados"));
  const policyField = el("label.field", {}, "Filas con la misma clave y valores distintos", policy,
    el("span.small.muted", {}, "Clave: reportante + flujo + año + SA6 + socio. Elige «separados» solo si sabes que son operaciones distintas."));
  kind.addEventListener("change", () => {
    help.textContent = kind.value === "auto" ? AUTO_HELP : KINDS[kind.value].help;
    policyField.classList.toggle("hidden", kind.value === "catalogo");
  });
  const file = el("input", { type: "file", accept: ".xlsx,.csv", required: true });
  const sheet = el("input", { placeholder: "Hoja (opcional; por defecto la primera)", maxlength: 100 });
  const button = el("button.btn.primary", { type: "submit" }, icon("upload"), "Validar archivo");
  const form = el("form.card", {
    on: {
      async submit(event) {
        event.preventDefault();
        if (!file.files[0]) return;
        const data = new FormData();
        data.append("kind", kind.value);
        data.append("file", file.files[0]);
        if (kind.value !== "catalogo") data.append("duplicate_policy", policy.value);
        if (sheet.value.trim()) data.append("sheet", sheet.value.trim());
        button.disabled = true;
        result.replaceChildren(el("div.loading", {}, el("span.spinner"), " Leyendo y validando…"));
        try {
          const batch = await api.upload("/api/imports", data);
          show(batch);
          history.reload();
        } catch (e) { showError(e); result.replaceChildren(); } finally { button.disabled = false; }
      },
    },
  }, el("h2", {}, "1. Subir y validar"),
  el("p.small.muted", {}, "Nada se guarda hasta que confirmes. Formatos: .xlsx (sin macros) o .csv (separador coma, punto y coma o tabulador; UTF-8 o Latin-1)."),
  el("div.form.two", {}, el("label.field", {}, "Tipo de datos", kind, help), el("label.field", {}, "Archivo", file, sheet), policyField),
  el("div.actions", {}, button,
    el("button.btn", { type: "button", on: { click: () => download(`/api/imports/templates/${kind.value === "auto" ? "comercio" : kind.value}.csv`).catch(showError) } }, icon("download"), "Descargar plantilla")));

  function show(batch) {
    result.replaceChildren(batchView(batch, (updated) => { show(updated); history.reload(false); }));
  }

  const history = pagedTable({
    pageSize: 10,
    fetchPage: ({ limit, offset }) => api.get("/api/imports" + queryString({ limit, offset })),
    emptyNode: empty("Sin importaciones", "El historial de archivos importados aparecerá aquí."),
    columns: [
      { label: "#", render: (b) => el("a", { href: `#/importar/${b.id}` }, `#${b.id}`) },
      { label: "Fecha", render: (b) => fmt.datetime(b.created_at) },
      { label: "Tipo", render: (b) => KINDS[b.kind].label },
      { label: "Archivo", render: (b) => b.file_name },
      { label: "Usuario", render: (b) => b.user },
      { label: "Válidas / rechazadas", className: "num", render: (b) => `${b.valid_rows} / ${b.rejected}` },
      { label: "Añad. / act. / sin cambios", className: "num", render: (b) => b.status === "confirmado" ? `${b.added} / ${b.updated} / ${b.skipped}` : "—" },
      { label: "Estado", render: (b) => badge(b.status === "confirmado" ? "good" : b.status === "descartado" ? "" : "info", b.status) },
    ],
  });

  root.append(pageHead("Importar Excel / CSV", "Validación previa, detección de duplicados, informe de filas rechazadas y registro de cada importación."),
    el("div.stack", {}, form, result, el("div.card", {}, el("h2", {}, "Historial de importaciones"), history.node)));
  history.reload();
  if (params[0]) {
    try { show(await api.get(`/api/imports/${Number(params[0])}`)); } catch (e) { showError(e); }
  }
}
