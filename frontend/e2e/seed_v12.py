"""Crea una base de datos en el estado de una instalación ANTERIOR (esquema 12), como la real del negocio:
productos y ventas en el «Inventario general» (sin grupo), un administrador y un empleado con permisos amplios
que es integrante de un grupo sin inventario propio. Uso: python e2e/seed_v12.py <carpeta de datos>"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

from pospy import db as dbmod
from pospy.core.security import hash_password

data = Path(sys.argv[1])
data.mkdir(parents=True, exist_ok=True)
dbmod.MIGRATIONS = [m for m in dbmod.MIGRATIONS if m[0] <= 12]
dbmod.Database(data / "pospy.db").migrate()
now = "2026-11-12T16:00:00Z"
c = sqlite3.connect(data / "pospy.db")
for uid, name, full, role, pw in ((1, "administrador", "Administrador", "admin", "Clave segura 2026"),
                                  (2, "empleado", "Empleado Mostrador", "employee", "Caja segura 99x")):
    c.execute("INSERT INTO users(id, username, full_name, role, password_hash, created_at, updated_at) VALUES (?,?,?,?,?,?,?)",
              (uid, name, full, role, hash_password(pw), now, now))
for p in ("documentos.anular", "documentos.crear", "documentos.imprimir", "documentos.ver", "finanzas.registrar",
          "inventario.costos", "inventario.editar", "inventario.movimientos", "inventario.ver", "ventas.descuento",
          "ventas.historial", "ventas.vender"):
    c.execute("INSERT INTO user_permissions(user_id, permission) VALUES (2, ?)", (p,))
c.execute("INSERT INTO settings(key, value, updated_at) VALUES ('acceso', ?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
          ('{"login_enabled": true, "setup_completed": true, "setup_step": "listo"}', now))
c.executescript(f"""
    INSERT INTO work_groups(id, public_id, name, owner_id, status, created_at, updated_at) VALUES
      (1,'G-E8748C2B','Casa Renault',1,'cerrado','{now}','{now}'), (2,'G-E8470C68','Casa Renault-PRUEBA',1,'activo','{now}','{now}');
    INSERT INTO work_group_members(group_id, user_id, status, requested_at, joined_at, updated_at) VALUES
      (1,2,'retirado','{now}','{now}','{now}'), (2,2,'activo','{now}','{now}','{now}');
    INSERT INTO products(id, group_id, code, description, price_cents, created_at, updated_at) VALUES
      (1,NULL,'0257','VARILLA ACEITE STEPWAY',2800000,'{now}','{now}'), (2,NULL,'0910','ANILLO EXOSTO LUV1600',1000000,'{now}','{now}');
    INSERT INTO inventory_movements(product_id, kind, qty_milli, stock_after_milli, reason, created_at)
      VALUES (1,'inicial',10000,10000,'Existencia inicial','{now}'), (2,'inicial',4000,4000,'Existencia inicial','{now}');
""")
c.commit()
print("esquema", c.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0])
c.close()
