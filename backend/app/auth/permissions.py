"""Catálogo canónico de roles y permisos.

La migración que crea las tablas siembra estos valores; el servidor siempre verifica
contra la base de datos (rol del usuario -> permisos), nunca contra lo que diga el cliente.
"""

PERMISSIONS = {
    "dashboard.view": "Ver el panel principal",
    "products.view": "Ver productos, variantes, marcas, categorías y proveedores",
    "products.manage": "Crear y editar productos, variantes, marcas, categorías, proveedores y fotos",
    "inventory.view": "Ver existencias y movimientos",
    "inventory.sell": "Registrar ventas y devoluciones de clientes",
    "inventory.move": "Registrar cualquier movimiento (entradas, ajustes, conteos físicos)",
    "counts.create": "Subir fotos y crear conteos inteligentes",
    "counts.confirm": "Confirmar conteos y conciliarlos con el stock",
    "imports.manage": "Importar archivos Excel/CSV",
    "exports.run": "Exportar datos e informes",
    "reports.view": "Ver reportes y BI",
    "orders.view": "Ver pedidos de la tienda online",
    "orders.manage": "Cambiar el estado de los pedidos",
    "users.manage": "Gestionar usuarios y roles",
    "audit.view": "Ver la auditoría",
    "settings.view": "Ver configuración y estado del sistema",
}

_CONSULTA = ["dashboard.view", "products.view", "inventory.view", "reports.view", "orders.view"]
_OPERADOR = _CONSULTA + ["inventory.sell", "counts.create", "orders.manage"]
_INVENTARIO = _OPERADOR + ["products.manage", "inventory.move", "counts.confirm",
                           "imports.manage", "exports.run"]

ROLES = {
    "admin": ("Administrador", list(PERMISSIONS)),
    "inventario": ("Encargado de inventario", _INVENTARIO),
    "operador": ("Operador", _OPERADOR),
    "consulta": ("Consulta", _CONSULTA),
}
