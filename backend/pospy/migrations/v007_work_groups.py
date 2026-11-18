VERSION = 7
NAME = "grupos de trabajo: integrantes, invitaciones por enlace, bitácora y presencia"

# Compatibilidad: solo crea tablas nuevas que referencian users por su id. No modifica datos existentes.
#
# - work_groups.public_id: identificador visible y aleatorio (no el id interno secuencial).
# - work_group_invitations.token_hash: SHA-256 del token del enlace. El token en claro solo se
#   muestra una vez al administrador que lo genera; nunca se guarda.
# - work_group_members: UNIQUE(group_id, user_id) impide integrantes duplicados. Una persona que sale
#   o es retirada conserva su fila (cambia el estado) para no perder el historial.
# - work_group_events: bitácora inmutable del grupo (ingresos, retiros, invitaciones…).
# - user_presence: última conexión en tiempo real conocida (la presencia en vivo está en memoria).
SQL = r"""
CREATE TABLE work_groups(
  id INTEGER PRIMARY KEY,
  public_id TEXT NOT NULL UNIQUE,
  name TEXT NOT NULL CHECK(length(trim(name)) BETWEEN 1 AND 80),
  description TEXT NOT NULL DEFAULT '' CHECK(length(description) <= 500),
  owner_id INTEGER NOT NULL REFERENCES users(id),
  status TEXT NOT NULL DEFAULT 'activo' CHECK(status IN ('activo','cerrado')),
  join_policy TEXT NOT NULL DEFAULT 'automatica' CHECK(join_policy IN ('automatica','aprobacion')),
  members_visible INTEGER NOT NULL DEFAULT 1 CHECK(members_visible IN (0,1)),
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  closed_at TEXT,
  version INTEGER NOT NULL DEFAULT 1
);
CREATE INDEX ix_work_groups_owner ON work_groups(owner_id);
CREATE TRIGGER work_groups_no_delete BEFORE DELETE ON work_groups
BEGIN SELECT RAISE(ABORT, 'Los grupos no se eliminan: ciérrelos'); END;

CREATE TABLE work_group_invitations(
  id INTEGER PRIMARY KEY,
  group_id INTEGER NOT NULL REFERENCES work_groups(id),
  token_hash TEXT NOT NULL UNIQUE,
  hint TEXT NOT NULL,
  created_by INTEGER NOT NULL REFERENCES users(id),
  created_at TEXT NOT NULL,
  expires_at TEXT NOT NULL,
  max_uses INTEGER NOT NULL CHECK(max_uses BETWEEN 1 AND 500),
  uses INTEGER NOT NULL DEFAULT 0 CHECK(uses >= 0 AND uses <= max_uses),
  revoked_at TEXT,
  revoked_by INTEGER REFERENCES users(id)
);
CREATE INDEX ix_work_group_invitations_group ON work_group_invitations(group_id);

CREATE TABLE work_group_members(
  id INTEGER PRIMARY KEY,
  group_id INTEGER NOT NULL REFERENCES work_groups(id),
  user_id INTEGER NOT NULL REFERENCES users(id),
  status TEXT NOT NULL CHECK(status IN ('activo','pendiente','retirado','eliminado','rechazado')),
  invitation_id INTEGER REFERENCES work_group_invitations(id),
  requested_at TEXT NOT NULL,
  joined_at TEXT,
  ended_at TEXT,
  updated_at TEXT NOT NULL,
  UNIQUE(group_id, user_id)
);
CREATE INDEX ix_work_group_members_user ON work_group_members(user_id, status);

CREATE TABLE work_group_events(
  id INTEGER PRIMARY KEY,
  group_id INTEGER NOT NULL REFERENCES work_groups(id),
  created_at TEXT NOT NULL,
  actor_id INTEGER REFERENCES users(id),
  subject_id INTEGER REFERENCES users(id),
  type TEXT NOT NULL,
  details TEXT
);
CREATE INDEX ix_work_group_events_group ON work_group_events(group_id, id);
CREATE TRIGGER work_group_events_no_update BEFORE UPDATE ON work_group_events
BEGIN SELECT RAISE(ABORT, 'La bitácora del grupo es inmutable'); END;
CREATE TRIGGER work_group_events_no_delete BEFORE DELETE ON work_group_events
BEGIN SELECT RAISE(ABORT, 'La bitácora del grupo es inmutable'); END;

CREATE TABLE user_presence(
  user_id INTEGER PRIMARY KEY REFERENCES users(id),
  last_connected_at TEXT,
  last_disconnected_at TEXT
);
"""
