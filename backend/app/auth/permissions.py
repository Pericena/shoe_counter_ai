"""Catálogo canónico de roles y permisos.

Las migraciones siembran estos valores; el servidor siempre verifica contra la base de datos
(rol del usuario -> permisos), nunca contra lo que diga el cliente.
"""

PERMISSIONS = {
    "dashboard.view": "Ver el panel principal",
    "products.view": "Ver productos, variantes, marcas, categorías y proveedores",
    "products.manage": "Crear y editar productos, variantes, marcas, categorías, proveedores y fotos",
    "prices.manage": "Modificar costos y precios",
    "inventory.view": "Ver existencias y movimientos",
    "inventory.sell": "Registrar ventas y devoluciones de clientes",
    "inventory.move": "Registrar cualquier movimiento (entradas, ajustes, bajas, conteos físicos, transferencias)",
    "locations.manage": "Gestionar tiendas, almacenes y ubicaciones",
    "pos.sell": "Vender en el punto de venta",
    "returns.manage": "Procesar devoluciones e inspección",
    "counts.create": "Subir fotos y crear conteos inteligentes / registro por imagen",
    "counts.confirm": "Confirmar conteos y conciliarlos con el stock",
    "purchases.manage": "Crear órdenes de compra, revisar reposición y recibir mercancía",
    "purchases.approve": "Aprobar órdenes de compra y recomendaciones de reposición",
    "imports.manage": "Importar archivos Excel/CSV",
    "exports.run": "Exportar datos e informes",
    "reports.view": "Ver reportes, KPI y BI",
    "bi.view": "Acceder a la API de datos analíticos (Power BI)",
    "orders.view": "Ver pedidos de la tienda online",
    "orders.manage": "Cambiar el estado de los pedidos",
    "integrations.manage": "Configurar integraciones de TPV/e-commerce y revisar su registro",
    "notifications.view": "Ver y gestionar notificaciones",
    "users.manage": "Gestionar usuarios y roles",
    "audit.view": "Ver la auditoría",
    "settings.view": "Ver configuración y estado del sistema",
    "settings.manage": "Cambiar umbrales y parámetros",
}

_CONSULTA = ["dashboard.view", "products.view", "inventory.view", "reports.view", "orders.view", "notifications.view"]
_OPERADOR = _CONSULTA + ["inventory.sell", "counts.create", "orders.manage"]
_VENDEDOR = _CONSULTA + ["inventory.sell", "pos.sell", "returns.manage", "orders.manage", "counts.create"]
_COMPRAS = _CONSULTA + ["purchases.manage", "exports.run", "products.manage", "prices.manage"]
_ANALISTA = _CONSULTA + ["exports.run", "bi.view"]
_AUDITOR = _CONSULTA + ["audit.view", "exports.run", "bi.view", "settings.view"]
_INVENTARIO = sorted(set(_OPERADOR + _VENDEDOR + [
    "products.manage", "prices.manage", "inventory.move", "locations.manage", "counts.confirm",
    "imports.manage", "exports.run", "purchases.manage"]))

ROLES = {
    "admin": ("Administrador", list(PERMISSIONS)),
    "inventario": ("Encargado de inventario", _INVENTARIO),
    "vendedor": ("Vendedor", _VENDEDOR),
    "compras": ("Compras", _COMPRAS),
    "analista": ("Analista", _ANALISTA),
    "auditor": ("Auditor", _AUDITOR),
    "operador": ("Operador", _OPERADOR),
    "consulta": ("Consulta", _CONSULTA),
}
