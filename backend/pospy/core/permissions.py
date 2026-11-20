"""Catálogo de permisos.

El administrador tiene todos. Un empleado tiene solo los asignados por un administrador, y nunca
los marcados como exclusivos de administración (usuarios, configuración, integraciones, respaldos,
auditoría), aunque se intenten asignar.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Permission:
    code: str
    label: str
    group: str
    admin_only: bool = False


CATALOG: tuple[Permission, ...] = (
    Permission("inventario.ver", "Consultar inventario", "Inventario"),
    Permission("inventario.costos", "Ver costos de productos", "Inventario"),
    Permission("inventario.editar", "Crear, editar y desactivar productos", "Inventario"),
    Permission("inventario.movimientos", "Registrar entradas, salidas y ajustes", "Inventario"),
    Permission("inventario.importar", "Importar y exportar inventario", "Inventario"),
    Permission("inventario.columnas", "Administrar las columnas del inventario (agregar, editar, ordenar, archivar y eliminar)",
               "Inventario", admin_only=True),
    Permission("observaciones.ver", "Consultar observaciones de inventario", "Inventario"),
    Permission("observaciones.crear", "Registrar observaciones de inventario y adjuntar archivos", "Inventario"),
    Permission("observaciones.editar", "Editar observaciones de inventario (datos y prioridad)", "Inventario"),
    Permission("observaciones.estado", "Cambiar el estado de las observaciones de inventario", "Inventario"),
    Permission("observaciones.comentar", "Agregar comentarios de seguimiento a observaciones", "Inventario"),
    Permission("observaciones.eliminar", "Eliminar observaciones de inventario (se conserva el historial)", "Inventario"),
    Permission("ventas.vender", "Registrar ventas", "Ventas"),
    Permission("ventas.descuento", "Aplicar descuentos manuales", "Ventas"),
    Permission("ventas.historial", "Consultar historial de ventas", "Ventas"),
    Permission("ventas.anular", "Anular ventas y registrar devoluciones", "Ventas"),
    Permission("documentos.ver", "Consultar cotizaciones y órdenes", "Documentos"),
    Permission("documentos.crear", "Crear cotizaciones y órdenes", "Documentos"),
    Permission("documentos.anular", "Anular cotizaciones y órdenes", "Documentos"),
    Permission("documentos.imprimir", "Imprimir y reimprimir documentos", "Documentos"),
    Permission("finanzas.ver", "Consultar informes financieros", "Finanzas"),
    Permission("finanzas.registrar", "Registrar cobros, pagos, gastos y asientos", "Finanzas"),
    Permission("finanzas.cierres", "Guardar informes de ingresos (cierres), revisarlos y anotar observaciones", "Finanzas"),
    Permission("terceros.gestionar", "Gestionar clientes y proveedores", "Gestión"),
    Permission("tareas.gestionar", "Crear y asignar tareas a cualquier persona", "Gestión"),
    Permission("gestion.usuarios", "Administrar usuarios y permisos", "Gestión", admin_only=True),
    Permission("gestion.configuracion", "Configuración de la empresa, documentos e impresión", "Gestión", admin_only=True),
    Permission("gestion.integraciones", "Conexiones y sincronización de inventario", "Gestión", admin_only=True),
    Permission("gestion.respaldos", "Copias de seguridad y restauración", "Gestión", admin_only=True),
    Permission("gestion.auditoria", "Historial de actividad", "Gestión", admin_only=True),
    Permission("grupos.gestionar", "Crear grupos de trabajo e invitar empleados por enlace", "Gestión", admin_only=True),
)

BY_CODE = {p.code: p for p in CATALOG}
ALL = frozenset(BY_CODE)
ASSIGNABLE_TO_EMPLOYEE = frozenset(p.code for p in CATALOG if not p.admin_only)
DEFAULT_EMPLOYEE = frozenset({
    "inventario.ver", "ventas.vender", "ventas.historial",
    "documentos.ver", "documentos.crear", "documentos.imprimir",
    "observaciones.ver", "observaciones.crear", "observaciones.comentar",
})


# Permisos que se otorgan POR INVENTARIO: en cada inventario el administrador decide qué puede hacer cada
# integrante. El permiso efectivo exige el permiso del usuario Y el del inventario (nunca da más que antes).
INVENTORY_SCOPED = frozenset({
    "inventario.ver", "inventario.costos", "inventario.editar", "inventario.movimientos", "inventario.importar",
    "inventario.columnas", "observaciones.ver", "observaciones.crear", "observaciones.editar", "observaciones.estado",
    "observaciones.comentar", "observaciones.eliminar", "ventas.vender", "ventas.descuento", "ventas.historial",
    "ventas.anular", "documentos.ver", "documentos.crear", "documentos.anular", "documentos.imprimir",
})
DEFAULT_INVENTORY_MEMBER = frozenset({
    "inventario.ver", "ventas.vender", "ventas.historial", "documentos.ver", "documentos.crear", "documentos.imprimir",
    "observaciones.ver", "observaciones.crear", "observaciones.comentar",
})


def effective(role: str, assigned: set[str] | frozenset[str]) -> frozenset[str]:
    if role == "admin":
        return ALL
    return frozenset(assigned) & ASSIGNABLE_TO_EMPLOYEE
