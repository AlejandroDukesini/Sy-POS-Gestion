"""Consola de administración local (equivale a acceso administrativo al equipo).

  python -m pospy.cli create-admin      crea el primer administrador (pide la contraseña sin mostrarla)
  python -m pospy.cli reset-password U  asigna una contraseña temporal a U y la desbloquea
  python -m pospy.cli status            estado de instalación, usuarios y esquema (sin secretos)
  python -m pospy.cli backup            crea una copia de seguridad verificada
"""
from __future__ import annotations

import argparse
import getpass
import sys

from .config import Config
from .context import AppContext
from .core.actor import SYSTEM
from .core.audit import record
from .core.errors import DomainError
from .core.security import check_policy, hash_password


def _password(prompt: str, username: str) -> str:
    first = getpass.getpass(prompt)
    if first != getpass.getpass("Repita la contraseña: "):
        raise SystemExit("Las contraseñas no coinciden.")
    check_policy(first, username)
    return first


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="pospy.cli")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("create-admin")
    reset = sub.add_parser("reset-password")
    reset.add_argument("username")
    sub.add_parser("status")
    sub.add_parser("backup")
    args = parser.parse_args(argv)
    ctx = AppContext(Config.from_env())
    try:
        if args.cmd == "create-admin":
            if not ctx.auth.needs_setup():
                print("Ya existe al menos un usuario. Use Gestión › Usuarios para crear más.")
                return 1
            username = input("Usuario administrador: ").strip().lower()
            full_name = input("Nombre completo: ").strip()
            code = ctx.config.setup_code or ctx.auth.setup_file.read_text(encoding="utf-8").strip()
            ctx.auth.setup_admin(code, username, full_name, _password("Contraseña: ", username))
            print("Administrador creado.")
        elif args.cmd == "reset-password":
            with ctx.db.read() as conn:
                user = conn.execute("SELECT id, username FROM users WHERE username = ?", (args.username,)).fetchone()
            if not user:
                print("Usuario no encontrado.")
                return 1
            password = _password("Contraseña temporal: ", user["username"])
            with ctx.db.tx() as conn:
                conn.execute("UPDATE users SET password_hash = ?, must_change_password = 1, failed_attempts = 0,"
                             " locked_until = NULL, active = 1, session_version = session_version + 1 WHERE id = ?",
                             (hash_password(password), user["id"]))
                record(conn, SYSTEM, "usuario.restablecer_contrasena_consola", "user", user["id"])
            print("Contraseña temporal asignada; se pedirá cambiarla al ingresar.")
        elif args.cmd == "status":
            with ctx.db.read() as conn:
                users = conn.execute("SELECT username, role, active, locked_until FROM users ORDER BY username").fetchall()
            print(f"Datos: {ctx.config.data_dir}\nEsquema: v{ctx.db.schema_version()}\nUsuarios: {len(users)}")
            for u in users:
                print(f"  {u['username']:<20} {u['role']:<9} {'activo' if u['active'] else 'inactivo'}"
                      f"{' (bloqueado)' if u['locked_until'] else ''}")
            if ctx.auth.needs_setup():
                print(f"Pendiente de instalación. Código en: {ctx.auth.setup_file}")
        elif args.cmd == "backup":
            print("Copia creada:", ctx.backups.create(SYSTEM, "consola")["file"])
    except DomainError as exc:
        print(f"Error: {exc.detail} {exc.fields or ''}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
