VERSION = 15
NAME = "equipos autorizados (vinculación de dispositivos)"

# Compatibilidad: no modifica datos. La restricción por equipo está DESACTIVADA hasta que un administrador la active
# (clave «dispositivos» en settings), así que las instalaciones existentes siguen funcionando igual.
# - devices: un equipo = un par de claves ECDSA P-256 generado en ese equipo; el servidor solo guarda la clave
#   PÚBLICA (SPKI, base64) y su huella SHA-256. La privada nunca sale del equipo (WebCrypto, no exportable).
# - sessions.device_id: equipo con el que se abrió la sesión (prueba de posesión de la clave al iniciar sesión).
SQL = r"""
CREATE TABLE devices(
  id INTEGER PRIMARY KEY,
  public_id TEXT NOT NULL UNIQUE,
  name TEXT NOT NULL,
  public_key TEXT NOT NULL,
  key_thumbprint TEXT NOT NULL UNIQUE,
  status TEXT NOT NULL CHECK(status IN ('pendiente','autorizado','revocado','rechazado')),
  user_agent TEXT NOT NULL DEFAULT '',
  requested_by INTEGER REFERENCES users(id),
  decided_by INTEGER REFERENCES users(id),
  created_at TEXT NOT NULL,
  decided_at TEXT,
  last_seen_at TEXT,
  last_user_id INTEGER REFERENCES users(id),
  note TEXT NOT NULL DEFAULT ''
);
CREATE INDEX ix_devices_status ON devices(status);
ALTER TABLE sessions ADD COLUMN device_id INTEGER REFERENCES devices(id);
CREATE INDEX ix_sessions_device ON sessions(device_id);
"""

# Reversión manual (restaure antes una copia de seguridad; requiere SQLite >= 3.35 para DROP COLUMN):
DOWN_SQL = r"""
DROP INDEX IF EXISTS ix_sessions_device;
ALTER TABLE sessions DROP COLUMN device_id;
DROP TABLE IF EXISTS devices;
DELETE FROM settings WHERE key = 'dispositivos';
DELETE FROM schema_migrations WHERE version = 15;
"""
