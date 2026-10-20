// Inicio de sesión, cambio de contraseña obligatorio y recuperación por correo (si está configurada).
import { api, loadSession, setCsrf } from "./api.js";
import { el, errorText } from "./ui.js";

const panel = document.getElementById("panel");

function message(kind, text) {
  return el(`div.alert.${kind}`, { role: kind === "bad" ? "alert" : "status" }, text);
}

function nextUrl() {
  const next = new URLSearchParams(location.search).get("next") || "#/";
  return "/" + (next.startsWith("#") ? next : "#/");
}

function loginForm(notice) {
  const status = el("div");
  if (notice) status.append(notice);
  const user = el("input", { name: "username", autocomplete: "username", required: true, maxlength: 50 });
  const pass = el("input", { name: "password", type: "password", autocomplete: "current-password", required: true, maxlength: 128 });
  const button = el("button.btn.primary", { type: "submit" }, "Entrar");
  const form = el("form.form", {
    on: {
      async submit(event) {
        event.preventDefault();
        button.disabled = true;
        status.replaceChildren();
        try {
          const data = await api.post("/api/auth/login", { username: user.value, password: pass.value });
          setCsrf(data.csrf_token);
          if (data.user.must_change_password) changeForm(true);
          else location.href = nextUrl();
        } catch (error) {
          status.replaceChildren(message("bad", errorText(error)));
          pass.value = "";
          pass.focus();
        } finally {
          button.disabled = false;
        }
      },
    },
  },
  el("h1", {}, "Iniciar sesión"),
  status,
  el("label.field", {}, "Usuario", user),
  el("label.field", {}, "Contraseña", pass),
  button,
  el("button.btn.ghost.small", { type: "button", on: { click: () => resetRequestForm() } }, "¿Olvidaste tu contraseña?"));
  panel.replaceChildren(form);
  user.focus();
}

function changeForm(forced) {
  const status = el("div");
  const current = el("input", { type: "password", autocomplete: "current-password", required: true });
  const next = el("input", { type: "password", autocomplete: "new-password", required: true, minlength: 10, maxlength: 128 });
  const repeat = el("input", { type: "password", autocomplete: "new-password", required: true });
  const form = el("form.form", {
    on: {
      async submit(event) {
        event.preventDefault();
        if (next.value !== repeat.value) {
          status.replaceChildren(message("bad", "Las contraseñas nuevas no coinciden."));
          return;
        }
        try {
          const data = await api.post("/api/auth/change-password", { current_password: current.value, new_password: next.value });
          setCsrf(data.csrf_token);
          location.href = nextUrl();
        } catch (error) {
          status.replaceChildren(message("bad", errorText(error)));
        }
      },
    },
  },
  el("h1", {}, "Cambia tu contraseña"),
  forced ? message("info", "Tu contraseña es temporal. Elige una nueva para continuar.") : null,
  status,
  el("label.field", {}, "Contraseña actual", current),
  el("label.field", {}, "Contraseña nueva", next, el("span.small.muted", {}, "Mínimo 10 caracteres, con letras y números.")),
  el("label.field", {}, "Repite la contraseña nueva", repeat),
  el("button.btn.primary", { type: "submit" }, "Guardar y continuar"));
  panel.replaceChildren(form);
  current.focus();
}

function resetRequestForm() {
  const status = el("div");
  const email = el("input", { type: "email", autocomplete: "email", required: true });
  const form = el("form.form", {
    on: {
      async submit(event) {
        event.preventDefault();
        try {
          const data = await api.post("/api/auth/password-reset/request", { email: email.value });
          status.replaceChildren(message(data.email_enabled ? "good" : "warn", data.message));
        } catch (error) {
          status.replaceChildren(message("bad", errorText(error)));
        }
      },
    },
  },
  el("h1", {}, "Recuperar contraseña"),
  status,
  el("label.field", {}, "Correo electrónico de tu usuario", email),
  el("button.btn.primary", { type: "submit" }, "Enviar enlace"),
  el("button.btn.ghost.small", { type: "button", on: { click: () => loginForm() } }, "Volver"));
  panel.replaceChildren(form);
}

function resetConfirmForm(token) {
  const status = el("div");
  const next = el("input", { type: "password", autocomplete: "new-password", required: true, minlength: 10 });
  const form = el("form.form", {
    on: {
      async submit(event) {
        event.preventDefault();
        try {
          const data = await api.post("/api/auth/password-reset/confirm", { token, new_password: next.value });
          history.replaceState(null, "", "/login.html");
          loginForm(message("good", data.message));
        } catch (error) {
          status.replaceChildren(message("bad", errorText(error)));
        }
      },
    },
  },
  el("h1", {}, "Nueva contraseña"), status,
  el("label.field", {}, "Contraseña nueva", next, el("span.small.muted", {}, "Mínimo 10 caracteres, con letras y números.")),
  el("button.btn.primary", { type: "submit" }, "Guardar"));
  panel.replaceChildren(form);
}

async function start() {
  try {
    const data = await loadSession();
    const hash = location.hash;
    if (hash.startsWith("#reset=")) return resetConfirmForm(decodeURIComponent(hash.slice(7)));
    if (data.user && data.user.must_change_password) return changeForm(true);
    if (data.user && hash === "#cambiar") return changeForm(false);
    if (data.user) { location.href = nextUrl(); return; }
    loginForm();
  } catch {
    panel.replaceChildren(message("bad", "No se pudo conectar con el servidor."));
  }
}

start();
