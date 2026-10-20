import { api } from "../api.js";
import { badge, el, fmt, pageHead } from "../ui.js";

export async function render(root, _params, { can, session }) {
  root.append(pageHead("Configuración", "Tu cuenta y el estado del sistema."));
  const grid = el("div.grid.cols-2");
  root.append(grid);
  grid.append(el("div.card", {}, el("h2", {}, "Mi cuenta"), el("dl.dl", {},
    el("dt", {}, "Usuario"), el("dd", {}, session.user.username),
    el("dt", {}, "Nombre"), el("dd", {}, session.user.full_name),
    el("dt", {}, "Rol"), el("dd", {}, session.user.role_name),
    el("dt", {}, "Último acceso"), el("dd", {}, fmt.datetime(session.user.last_login_at))),
  el("div.actions", {}, el("a.btn", { href: "/login.html#cambiar" }, "Cambiar contraseña"))));

  if (can("inventory.view")) {
    const status = await api.get("/api/ai/status");
    const meta = status.metadata || {};
    const card = el("div.card", {}, el("h2", {}, "Detector de zapatos"),
      el("p", {}, status.installed ? badge("good", `Instalado: ${status.version}`) : badge("warn", "No instalado")),
      status.message ? el("p.small.muted", {}, status.message) : null,
      el("dl.dl", {},
        el("dt", {}, "Motor"), el("dd", {}, status.runtime),
        el("dt", {}, "Umbral de confianza"), el("dd", {}, status.confidence_threshold),
        el("dt", {}, "Versiones disponibles"), el("dd", {}, status.versions.join(", ") || "ninguna"),
        meta.created_at ? el("dt", {}, "Entrenado") : null, meta.created_at ? el("dd", {}, fmt.datetime(meta.created_at)) : null,
        meta.base_model ? el("dt", {}, "Modelo base") : null, meta.base_model ? el("dd", {}, meta.base_model) : null));
    const metrics = meta.metrics || {};
    if (Object.keys(metrics).length) {
      card.append(el("h3", {}, "Métricas de evaluación"), el("div.table-wrap", {}, el("table", {},
        el("thead", {}, el("tr", {}, ["Partición", "Precisión", "Recall", "mAP50", "mAP50-95", "MAE conteo", "Exactas"].map((h) => el("th", {}, h)))),
        el("tbody", {}, Object.entries(metrics).map(([split, m]) => el("tr", {}, el("td", {}, split), el("td.num", {}, fmt.dec(m.precision, 3)),
          el("td.num", {}, fmt.dec(m.recall, 3)), el("td.num", {}, fmt.dec(m.map50, 3)), el("td.num", {}, fmt.dec(m.map50_95, 3)),
          el("td.num", {}, fmt.dec(m.counting?.mae, 2)), el("td.num", {}, fmt.pct(m.counting?.exact_rate))))))));
    }
    grid.append(card);
  }

  const health = await api.get("/api/health");
  grid.append(el("div.card", {}, el("h2", {}, "Servicios"), el("ul.list", {},
    el("li", {}, el("span", {}, "API"), badge("good", "En línea")),
    el("li", {}, el("span", {}, "Base de datos"), badge(health.database === "ok" ? "good" : "bad", health.database)),
    el("li", {}, el("span", {}, "Pagos en línea"), badge("warn", "No configurado: cobro manual")),
    el("li", {}, el("span", {}, "Correo de recuperación"), el("span.small.muted", {}, "Se activa con las variables SMTP_*")))));
}
