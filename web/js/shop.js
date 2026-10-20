// Tienda pública: catálogo conectado al inventario, carrito local y pedidos.
// El carrito vive en este navegador (localStorage); precios y stock se validan siempre en el servidor.
import { api, loadSession } from "./api.js";
import { el, empty, errorText, field, fmt, modal, options, toast } from "./ui.js";

const CART_KEY = "shoe-shop-cart-v1";
const shop = document.getElementById("shop");
let catalog = { items: [], filters: { sizes: [], colors: [], categories: [] } };

function readCart() {
  try {
    const data = JSON.parse(localStorage.getItem(CART_KEY) || "[]");
    return Array.isArray(data) ? data.filter((l) => Number.isInteger(l.variant_id) && Number.isInteger(l.quantity)) : [];
  } catch { return []; }
}
function writeCart(cart) {
  try { localStorage.setItem(CART_KEY, JSON.stringify(cart)); } catch { /* modo privado */ }
  document.getElementById("cart-count").textContent = cart.reduce((a, l) => a + l.quantity, 0);
}

function addToCart(product, variant) {
  const cart = readCart();
  const line = cart.find((l) => l.variant_id === variant.id);
  if (line) line.quantity = Math.min(10, line.quantity + 1);
  else cart.push({ variant_id: variant.id, quantity: 1, label: `${product.brand} ${product.model_name}`, size: variant.size, color: variant.color, price: variant.price });
  writeCart(cart);
  toast(`Añadido: ${product.model_name} · talla ${variant.size} · ${variant.color}`, "good");
}

function productCard(product) {
  let selected = null;
  const price = el("div.price", {}, product.price_from ? `desde ${fmt.money(product.price_from)}` : "");
  const add = el("button.btn.primary", { type: "button", disabled: true }, "Elegir talla y color");
  const chips = el("div.chips", {}, product.variants.map((v) => {
    const chip = el("button.chip", {
      type: "button", disabled: !v.available, "aria-pressed": "false",
      title: v.available ? (v.low_stock ? "Últimas unidades" : "Disponible") : "Agotado",
      on: {
        click() {
          chips.querySelectorAll(".chip").forEach((c) => c.setAttribute("aria-pressed", "false"));
          chip.setAttribute("aria-pressed", "true");
          selected = v;
          price.textContent = fmt.money(v.price);
          add.disabled = false;
          add.textContent = v.low_stock ? "Añadir (últimas unidades)" : "Añadir al carrito";
        },
      },
    }, `${v.size} · ${v.color}`);
    return chip;
  }));
  add.addEventListener("click", () => selected && addToCart(product, selected));
  const photo = product.images.length
    ? el("img", { src: product.images[0].url, alt: `${product.brand} ${product.model_name}`, loading: "lazy" })
    : el("span.small", {}, "Sin foto");
  return el("article.product", {}, el("div.photo", {}, photo), el("div.info", {},
    el("div.brand", {}, product.brand), el("div.name", {}, product.model_name),
    product.category ? el("div.small.muted", {}, product.category) : null,
    product.description ? el("p.small", {}, product.description.slice(0, 140)) : null,
    price, chips, add));
}

async function loadCatalog(filters = {}) {
  const query = new URLSearchParams(Object.entries(filters).filter(([, v]) => v)).toString();
  catalog = await api.get("/api/shop/products" + (query ? `?${query}` : ""));
}

function renderCatalog(list, filters) {
  list.replaceChildren(catalog.items.length
    ? el("div.products", {}, catalog.items.map(productCard))
    : empty("No hay productos con estos filtros", Object.values(filters).some(Boolean) ? "Prueba con otra talla, color o categoría." : "La tienda aún no tiene productos publicados."));
}

async function start() {
  try { await loadSession(); } catch { /* el catálogo puede verse igualmente */ }
  writeCart(readCart());
  try {
    await loadCatalog();
  } catch (e) {
    shop.replaceChildren(el("div.alert.bad", {}, "No se pudo cargar el catálogo. Inténtalo más tarde."));
    return;
  }
  const q = el("input", { type: "search", placeholder: "Buscar marca o modelo" });
  const size = options(el("select"), catalog.filters.sizes.map((s) => ({ id: s, name: `Talla ${s}` })), { placeholder: "Todas las tallas" });
  const color = options(el("select"), catalog.filters.colors.map((c) => ({ id: c, name: c })), { placeholder: "Todos los colores" });
  const category = options(el("select"), catalog.filters.categories, { placeholder: "Todas las categorías" });
  const available = el("input", { type: "checkbox" });
  const list = el("div");
  const values = () => ({ q: q.value, size: size.value, color: color.value, category_id: category.value, available: available.checked ? "1" : "" });
  shop.append(el("h1", {}, "Catálogo"), el("p.muted", {}, "Disponibilidad en tiempo real."),
    el("form.filters", {
      on: {
        async submit(e) {
          e.preventDefault();
          try { await loadCatalog(values()); renderCatalog(list, values()); } catch (err) { toast(errorText(err), "bad"); }
        },
      },
    }, q, size, color, category, el("label.check", {}, available, "Solo disponibles"), el("button.btn", { type: "submit" }, "Filtrar")),
    list);
  renderCatalog(list, {});
}

function cartDialog() {
  modal("Tu carrito", (body, close, foot) => {
    const cart = readCart();
    if (!cart.length) {
      body.append(empty("El carrito está vacío", "Elige talla y color en el catálogo."));
      foot.append(el("button.btn", { type: "button", on: { click: () => close() } }, "Seguir comprando"));
      return;
    }
    const lines = el("div");
    const total = el("p", {}, "");
    function draw() {
      const current = readCart();
      lines.replaceChildren(...current.map((l) => {
        const qty = el("input", { type: "number", min: 1, max: 10, value: l.quantity, "aria-label": "Cantidad" });
        qty.addEventListener("change", () => {
          const c = readCart();
          const line = c.find((x) => x.variant_id === l.variant_id);
          line.quantity = Math.max(1, Math.min(10, Number(qty.value) || 1));
          writeCart(c);
          draw();
        });
        return el("div.cart-line", {}, el("div", {}, el("strong", {}, l.label), el("div.small.muted", {}, `Talla ${l.size} · ${l.color} · ${fmt.money(l.price)} c/u`)),
          qty, el("button.btn.small", { type: "button", on: { click: () => { writeCart(readCart().filter((x) => x.variant_id !== l.variant_id)); draw(); } } }, "Quitar"));
      }));
      const sum = current.reduce((a, l) => a + Number(l.price) * l.quantity, 0);
      total.replaceChildren(el("strong", {}, `Total estimado: ${fmt.money(sum)}`), el("span.small.muted", {}, " (el servidor confirma precios y stock)"));
    }
    draw();
    const form = el("form.form.two", {},
      field("Nombre *", el("input", { name: "customer_name", required: true, maxlength: 150, autocomplete: "name" })),
      field("Correo *", el("input", { name: "customer_email", type: "email", required: true, maxlength: 150, autocomplete: "email" })),
      field("Teléfono", el("input", { name: "customer_phone", maxlength: 50, autocomplete: "tel" })),
      field("Dirección de entrega", el("input", { name: "shipping_address", maxlength: 1000, autocomplete: "street-address" })),
      el("label.field.full", {}, "Notas", el("textarea", { name: "notes", maxlength: 1000 })),
      el("p.small.muted.full", {}, "No se cobra en línea ni se piden datos de tarjeta: la tienda te contactará para coordinar el pago."));
    body.append(lines, total, el("h3", {}, "Tus datos"), form);
    foot.append(el("button.btn", { type: "button", on: { click: () => close() } }, "Seguir comprando"),
      el("button.btn.primary", {
        type: "button",
        on: {
          async click(event) {
            if (!form.reportValidity()) return;
            const data = Object.fromEntries(new FormData(form).entries());
            data.items = readCart().map((l) => ({ variant_id: l.variant_id, quantity: l.quantity }));
            event.target.disabled = true;
            try {
              const order = await api.post("/api/shop/orders", data);
              writeCart([]);
              body.replaceChildren(el("div.alert.good", {}, el("strong", {}, `Pedido ${order.code} registrado. `),
                `Total ${fmt.money(order.total_amount)}. Guarda el código: con él y tu correo puedes consultar el estado.`));
              foot.replaceChildren(el("button.btn.primary", { type: "button", on: { click: () => { close(); location.reload(); } } }, "Listo"));
            } catch (e) {
              toast(errorText(e), "bad");
              event.target.disabled = false;
            }
          },
        },
      }, "Confirmar pedido"));
  });
}

function lookupDialog() {
  modal("Estado de mi pedido", (body, close, foot) => {
    const code = el("input", { placeholder: "PED-XXXXXXXX", required: true, maxlength: 20 });
    const email = el("input", { type: "email", required: true });
    const result = el("div");
    body.append(field("Código del pedido", code), field("Correo usado en el pedido", email), result);
    foot.append(el("button.btn", { type: "button", on: { click: () => close() } }, "Cerrar"),
      el("button.btn.primary", {
        type: "button",
        on: {
          async click() {
            try {
              const order = await api.post("/api/shop/orders/lookup", { code: code.value, email: email.value });
              result.replaceChildren(el("div.alert.info", {}, el("strong", {}, order.status_label), ` · total ${fmt.money(order.total_amount)}`),
                el("ul.list", {}, order.history.map((h) => el("li", {}, el("span", {}, h.to_label), el("span.small.muted", {}, fmt.datetime(h.created_at))))));
            } catch (e) { result.replaceChildren(el("div.alert.bad", {}, errorText(e))); }
          },
        },
      }, "Consultar"));
  });
}

document.getElementById("cart-btn").addEventListener("click", cartDialog);
document.getElementById("lookup-btn").addEventListener("click", lookupDialog);
start();
