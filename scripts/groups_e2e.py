"""Prueba de extremo a extremo de los grupos de trabajo contra un servidor POS-PY REAL.

Arranca el servidor (uvicorn) con datos temporales y recorre los escenarios A–F con sesiones HTTP
independientes (administrador y dos empleados, cada uno con su propia cookie) y el canal de tiempo
real (SSE) abierto de verdad.

    backend\\.venv\\Scripts\\python.exe scripts\\groups_e2e.py
    backend\\.venv\\Scripts\\python.exe scripts\\groups_e2e.py --port 8790 --public https://xxxx.trycloudflare.com

Con --public, todo el tráfico de administrador y empleados pasa por esa dirección (por ejemplo un
túnel HTTPS hacia Internet). La instalación inicial se hace por la dirección local, porque el servidor
la rechaza si llega a través de un proxy o túnel (eso también se comprueba).
"""
from __future__ import annotations

import argparse
import json
import os
import queue
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
SETUP_CODE = "E2E-GRUPOS-0001"
ADMIN_PW = "Clave segura 2026"
EMP_PW = ["Caja segura 99x", "Bodega firme 88z"]
results: list[tuple[bool, str]] = []


def check(ok: bool, message: str) -> None:
    results.append((bool(ok), message))
    print(("OK    " if ok else "FALLA ") + message, flush=True)


def client(base: str) -> httpx.Client:
    return httpx.Client(base_url=base, headers={"X-Requested-With": "pos-py"}, timeout=30, follow_redirects=False)


PING_S = 10.0   # igual que el navegador (frontend/src/lib/realtime.ts)


class Stream:
    """Canal SSE leído en un hilo; los eventos llegan a una cola. Envía ping como el navegador."""

    def __init__(self, base: str, cookies: httpx.Cookies, name: str):
        self.events: queue.Queue = queue.Queue()
        self.name = name
        self._client = httpx.Client(base_url=base, cookies=cookies, timeout=httpx.Timeout(30, read=60))
        self._stop = threading.Event()
        self._response = None
        self._pinger = httpx.Client(base_url=base, cookies=cookies, timeout=15, headers={"X-Requested-With": "pos-py"})
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        threading.Thread(target=self._ping_loop, daemon=True).start()

    def _ping_loop(self) -> None:
        while not self._stop.is_set():
            try:
                self._pinger.post("/api/realtime/ping")
            except Exception:  # noqa: BLE001, S110 - un ping perdido no importa
                pass
            self._stop.wait(PING_S)

    def _run(self) -> None:
        try:
            with self._client.stream("GET", "/api/realtime/stream", headers={"Accept": "text/event-stream"}) as r:
                self._response = r
                self.events.put(("_status", {"code": r.status_code, "type": r.headers.get("content-type", "")}))
                kind = None
                for line in r.iter_lines():
                    if self._stop.is_set():
                        break
                    if line.startswith("event:"):
                        kind = line[6:].strip()
                    elif line.startswith("data:"):
                        self.events.put((kind, json.loads(line[5:].strip())))
        except Exception as exc:  # noqa: BLE001 - al cerrar a la fuerza
            if not self._stop.is_set():
                self.events.put(("_error", {"error": repr(exc)}))

    def wait(self, kind: str, timeout: float = 10, where=lambda d: True) -> dict | None:
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            try:
                k, data = self.events.get(timeout=max(0.05, end - time.monotonic()))
            except queue.Empty:
                break
            if k == kind and where(data):
                return data
        return None

    def close(self) -> None:
        """Simula la pérdida de conexión: corta el socket sin avisar y deja de enviar ping."""
        self._stop.set()
        self._pinger.close()
        try:
            if self._response is not None:
                self._response.close()
        finally:
            self._client.close()


def wait_health(base: str) -> None:
    for _ in range(80):
        try:
            if httpx.get(base + "/api/health", timeout=3).status_code == 200:
                return
        except httpx.HTTPError:
            pass
        time.sleep(0.5)
    raise SystemExit("El servidor no respondió en " + base)


def member(detail: dict, username: str) -> dict | None:
    return next((m for m in detail["members"] if m["username"] == username), None)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8791)
    parser.add_argument("--public", help="Dirección pública (túnel HTTPS) por la que pasa el tráfico de los usuarios")
    parser.add_argument("--python", default=sys.executable)
    parser.add_argument("--hold", type=float, default=0, help="Segundos para mantener el servidor después (pruebas manuales)")
    args = parser.parse_args()
    local = f"http://127.0.0.1:{args.port}"
    public = (args.public or local).rstrip("/")
    data_dir = tempfile.mkdtemp(prefix="pospy-grupos-")
    env = {**os.environ, "POS_SETUP_CODE": SETUP_CODE}
    if args.public:
        env["POS_PUBLIC_URL"] = public
    server = subprocess.Popen([args.python, "-m", "pospy", "--port", str(args.port), "--data-dir", data_dir],
                              cwd=ROOT / "backend", env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    streams: list[Stream] = []
    try:
        wait_health(local)
        if args.public:
            wait_health(public)
        print(f"Servidor real en {local}; tráfico de usuarios por {public}\n", flush=True)

        # Instalación: solo desde el propio equipo.
        boot = client(local)
        if args.public:
            remote_status = client(public).get("/api/setup/status").json()
            check(remote_status["local"] is False, "Por el túnel la petición NO se considera local")
            denied = client(public).post("/api/setup", json={"code": SETUP_CODE, "username": "gerente",
                                                              "full_name": "Gerente", "password": ADMIN_PW})
            check(denied.status_code == 403, "La instalación inicial se rechaza si llega por Internet")
        r = boot.post("/api/setup", json={"code": SETUP_CODE, "username": "gerente", "full_name": "Gerente General",
                                          "password": ADMIN_PW})
        check(r.status_code == 200, "Instalación local: administrador creado")

        # ---------------------------------------------------------------- A: creación
        admin = client(public)
        r = admin.post("/api/auth/login", json={"username": "gerente", "password": ADMIN_PW})
        check(r.status_code == 200, "A1 El administrador inicia sesión")
        if public.startswith("https://"):
            cookie = r.headers.get("set-cookie", "").lower()
            check("secure" in cookie and "httponly" in cookie, "A1 Cookie de sesión Secure + HttpOnly por HTTPS")
        emps = []
        for i, (username, name) in enumerate((("ana", "Ana Caja"), ("beto", "Beto Bodega"))):
            r = admin.post("/api/users", json={"username": username, "full_name": name, "role": "employee",
                                               "password": EMP_PW[i]})
            check(r.status_code == 200, f"A  Cuenta de empleado «{username}» creada por el administrador")
            c = client(public)
            c.post("/api/auth/login", json={"username": username, "password": EMP_PW[i]})
            if c.get("/api/me").json().get("must_change_password"):
                new_pw = EMP_PW[i] + "N"
                c.post("/api/auth/password", json={"current": EMP_PW[i], "password": new_pw})
            check(c.get("/api/me").status_code == 200, f"B1 «{username}» inicia sesión en su propio cliente (cookie aparte)")
            emps.append(c)
        ana, beto = emps

        g = admin.post("/api/groups", json={"name": "Turno tarde", "description": "Equipo de caja"})
        check(g.status_code == 200, "A3 Grupo creado")
        gid = g.json()["group"]["public_id"]
        inv = admin.post(f"/api/groups/{gid}/invitations", json={"expires_in_hours": 24, "max_uses": 5}).json()
        url = inv["url"]
        token = url.rsplit("/unirse/", 1)[1]
        check(url.startswith(public + "/unirse/"), f"A4 Enlace generado con la dirección pública: {public}/unirse/…")
        detail = admin.get(f"/api/groups/{gid}").json()
        check(detail["invitations"][0]["status"] == "vigente", "A5 La invitación quedó registrada en el servidor")
        spa = httpx.get(url, timeout=30)
        check(spa.status_code in (200, 503), f"B2 El enlace abre la aplicación (HTTP {spa.status_code})")

        # ---------------------------------------------------------------- D: tiempo real
        admin_stream = Stream(public, admin.cookies, "admin")
        streams.append(admin_stream)
        status = admin_stream.wait("_status", 15)
        check(bool(status) and status["code"] == 200 and "text/event-stream" in status["type"],
              "D1 Canal de tiempo real del administrador abierto (text/event-stream)")
        check(admin_stream.wait("hola", 15) is not None, "D1 El servidor saluda por el canal")

        # ---------------------------------------------------------------- B: incorporación
        preview = ana.get(f"/api/invitations/{token}")
        check(preview.status_code == 200 and preview.json()["group"]["name"] == "Turno tarde",
              "B3 El servidor valida el enlace y muestra a qué grupo se une")
        t0 = time.monotonic()
        joined = ana.post(f"/api/invitations/{token}/accept")
        check(joined.status_code == 200 and joined.json()["result"] == "unido", "B4 Ana confirma su ingreso")
        ev = admin_stream.wait("grupo", 10, lambda d: d.get("group") == gid)
        check(ev is not None, f"D2 El administrador recibe el aviso sin recargar ({(time.monotonic() - t0) * 1000:.0f} ms)")
        detail = admin.get(f"/api/groups/{gid}").json()
        check(member(detail, "ana") and member(detail, "ana")["status"] == "activo", "B5 Ana aparece como integrante")

        # ---------------------------------------------------------------- C: varios empleados
        check(beto.post(f"/api/invitations/{token}/accept").json()["result"] == "unido", "C1 Beto usa el mismo enlace")
        check(ana.post(f"/api/invitations/{token}/accept").json()["result"] == "ya_integrante",
              "C2 Abrir el enlace otra vez no duplica")
        detail = admin.get(f"/api/groups/{gid}").json()
        names = sorted(m["username"] for m in detail["members"] if m["status"] == "activo")
        check(names == ["ana", "beto"] and detail["invitations"][0]["uses"] == 2,
              "C3 El administrador ve 2 integrantes, sin duplicados (cupo usado: 2)")

        # ---------------------------------------------------------------- F: presencia y reconexión
        ana_stream = Stream(public, ana.cookies, "ana")
        streams.append(ana_stream)
        check(ana_stream.wait("hola", 15) is not None, "F1 Ana se conecta en tiempo real")
        check(admin_stream.wait("presencia", 10) is not None, "F1 El administrador recibe el cambio de conexión")
        check(member(admin.get(f"/api/groups/{gid}").json(), "ana")["connection"] == "conectado", "F1 Estado: conectado")
        ana_stream.close()   # pierde Internet
        streams.remove(ana_stream)
        # Detrás de un proxy o túnel el corte puede no propagarse: el servidor lo nota al faltar los pings
        # (30 s sin ping + hasta 15 s hasta el siguiente latido).
        got = admin_stream.wait("presencia", 70)
        conn_state = member(admin.get(f"/api/groups/{gid}").json(), "ana")["connection"]
        check(got is not None and conn_state == "reconectando", f"F2 Tras perder la conexión: {conn_state}")
        check(admin.get("/api/groups").status_code == 200, "F2 El administrador sigue trabajando")
        ana_back = Stream(public, ana.cookies, "ana-2")
        streams.append(ana_back)
        check(ana_back.wait("hola", 15) is not None, "F3 Ana recupera la conexión con su misma sesión")
        time.sleep(0.5)
        detail = admin.get(f"/api/groups/{gid}").json()
        check(member(detail, "ana")["connection"] == "conectado" and member(detail, "ana")["status"] == "activo"
              and len(detail["members"]) == 2, "F3 Vuelve a «conectado», sigue en el grupo y sin registros duplicados")
        mine = ana.get(f"/api/groups/{gid}").json()
        check(mine["view"] == "member" and mine["me"]["status"] == "activo", "F3 Ana sincroniza su estado")

        # ---------------------------------------------------------------- E: seguridad
        anon = client(public)
        check(anon.get(f"/api/invitations/{token}").status_code == 401, "E  Sin sesión no se consulta la invitación")
        check(anon.get(f"/api/groups/{gid}").status_code == 401, "E  Sin sesión no se consulta el grupo")
        check(anon.get("/api/realtime/stream").status_code == 401, "E  Sin sesión no hay canal de tiempo real")
        check(ana.get("/api/invitations/" + "x" * 43).status_code == 404, "E  Enlace inválido: 404 con mensaje claro")
        check(ana.post("/api/groups", json={"name": "Propio"}).status_code == 403, "E  Un empleado no crea grupos")
        check(ana.post(f"/api/groups/{gid}/invitations", json={}).status_code == 403, "E  Un empleado no genera enlaces")
        check(ana.post(f"/api/groups/{gid}/members/2/retirar").status_code == 403, "E  Un empleado no expulsa a nadie")
        check(ana.post(f"/api/groups/{gid}/invitations/{inv['invitation']['id']}/revoke").status_code == 403,
              "E  Un empleado no revoca enlaces")
        other = admin.post("/api/groups", json={"name": "Grupo privado"}).json()["group"]["public_id"]
        check(ana.get(f"/api/groups/{other}").status_code == 404, "E  Un empleado no accede a un grupo ajeno")
        csrf = httpx.post(public + f"/api/invitations/{token}/accept", cookies=beto.cookies, timeout=30)
        check(csrf.status_code == 403, "E  Sin la cabecera anti-CSRF se rechaza la operación")
        small = admin.post(f"/api/groups/{gid}/invitations", json={"max_uses": 1}).json()
        t_small = small["url"].rsplit("/unirse/", 1)[1]
        admin.post(f"/api/groups/{gid}/members/{member(detail, 'beto')['user_id']}/retirar")
        check(beto.get(f"/api/groups/{gid}").status_code == 404, "E  Beto retirado: ya no ve el grupo")
        check(beto.post(f"/api/invitations/{token}/accept").status_code == 403,
              "E  Retirado no puede volver con el enlace anterior")
        time.sleep(1.1)
        t_new = admin.post(f"/api/groups/{gid}/invitations", json={"max_uses": 1}).json()["url"].rsplit("/unirse/", 1)[1]
        check(beto.post(f"/api/invitations/{t_new}/accept").json()["result"] == "unido", "E  …pero sí con un enlace nuevo")
        c3 = client(public)
        admin.post("/api/users", json={"username": "caro", "full_name": "Caro", "role": "employee", "password": "Turno noche 55w"})
        c3.post("/api/auth/login", json={"username": "caro", "password": "Turno noche 55w"})
        c3.post("/api/auth/password", json={"current": "Turno noche 55w", "password": "Turno noche 55wN"})
        check(c3.post(f"/api/invitations/{t_new}/accept").status_code == 410, "E  Enlace sin cupo: 410")
        check(c3.post(f"/api/invitations/{t_small}/accept").status_code == 200, "E  Otro enlace con cupo sí funciona")
        admin.post(f"/api/groups/{gid}/invitations/{inv['invitation']['id']}/revoke")
        r = c3.get(f"/api/invitations/{token}")
        check(r.status_code == 410 and r.json()["fields"]["invitacion"] == "revocada", "E  Enlace revocado: 410")
        bad = [c3.get("/api/invitations/" + f"{i:043d}").status_code for i in range(11)]
        check(bad[-1] == 429, f"E  Fuerza bruta sobre enlaces limitada (último intento: HTTP {bad[-1]})")

        # Cambio de permisos en vivo
        ana_id = member(detail, "ana")["user_id"]
        admin.put(f"/api/users/{ana_id}", json={"permissions": ["inventario.ver"]})
        check(ana_back.wait("cuenta", 10) is not None, "D3 Ana recibe en vivo el aviso de cambio de permisos")

        if args.hold:
            print(f"\nServidor disponible {args.hold:.0f} s más en {public} (gerente / {ADMIN_PW}).", flush=True)
            time.sleep(args.hold)
    finally:
        for s in streams:
            s.close()
        server.terminate()
        try:
            server.wait(10)
        except subprocess.TimeoutExpired:
            server.kill()
    failed = [m for ok, m in results if not ok]
    print(f"\n{len(results) - len(failed)}/{len(results)} comprobaciones correctas.")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
