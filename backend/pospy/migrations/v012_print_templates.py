VERSION = 12
NAME = "plantillas de impresión: diseño, vinculaciones, versiones e historial de documentos emitidos"

# Compatibilidad: solo tablas nuevas. Los tipos de documento y su plantilla Excel anterior
# (document_types.template_file / mapping) siguen funcionando igual; si un tipo tiene una plantilla
# nueva predeterminada, el PDF se genera con el motor nuevo.
#
# - print_templates: una plantilla por diseño. group_id NULL = inventario general; si no, la del grupo.
#   kind: documento (con document_type_id: cotización, orden u otro tipo creado), venta o recibo.
#   Varias plantillas por tipo; como máximo UNA predeterminada por grupo y tipo (índice parcial).
#   Eliminar es lógico (deleted_at): los documentos emitidos siguen apuntando a su versión.
#   original_file: copia intacta del Excel importado (nunca se modifica ni se ejecuta).
# - print_template_versions: cada guardado crea una versión nueva e INMUTABLE (layout = diseño,
#   bindings = vinculaciones y cálculos). Editar una plantilla no cambia lo ya emitido.
# - print_outputs: cada documento generado: versión usada, operación, archivo PDF, huella y los datos
#   usados (JSON) para poder reproducirlo. Tampoco se modifica.
SQL = r"""
CREATE TABLE print_templates(
  id INTEGER PRIMARY KEY,
  public_id TEXT NOT NULL UNIQUE,
  group_id INTEGER REFERENCES work_groups(id),
  kind TEXT NOT NULL CHECK(kind IN ('documento','venta','recibo')),
  document_type_id INTEGER REFERENCES document_types(id),
  name TEXT NOT NULL CHECK(length(trim(name)) BETWEEN 1 AND 80),
  source TEXT NOT NULL CHECK(source IN ('excel','editor')),
  active INTEGER NOT NULL DEFAULT 0 CHECK(active IN (0,1)),
  is_default INTEGER NOT NULL DEFAULT 0 CHECK(is_default IN (0,1)),
  current_version INTEGER NOT NULL DEFAULT 1,
  original_file TEXT,
  original_name TEXT,
  original_sha256 TEXT,
  sheet TEXT,
  deleted_at TEXT,
  created_by INTEGER REFERENCES users(id),
  updated_by INTEGER REFERENCES users(id),
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  version INTEGER NOT NULL DEFAULT 1,
  CHECK((kind = 'documento') = (document_type_id IS NOT NULL)),
  CHECK(is_default = 0 OR active = 1)
);
CREATE UNIQUE INDEX ux_print_templates_default ON print_templates(COALESCE(group_id, 0), kind, COALESCE(document_type_id, 0))
  WHERE is_default = 1 AND deleted_at IS NULL;
CREATE INDEX ix_print_templates_scope ON print_templates(group_id, kind, deleted_at);

CREATE TABLE print_template_versions(
  id INTEGER PRIMARY KEY,
  template_id INTEGER NOT NULL REFERENCES print_templates(id),
  number INTEGER NOT NULL CHECK(number >= 1),
  layout TEXT NOT NULL,
  bindings TEXT NOT NULL,
  note TEXT NOT NULL DEFAULT '' CHECK(length(note) <= 200),
  created_by INTEGER REFERENCES users(id),
  created_at TEXT NOT NULL,
  UNIQUE(template_id, number)
);
CREATE TRIGGER print_template_versions_immutable BEFORE UPDATE ON print_template_versions
BEGIN SELECT RAISE(ABORT, 'Las versiones de plantilla no se modifican'); END;
CREATE TRIGGER print_template_versions_no_delete BEFORE DELETE ON print_template_versions
BEGIN SELECT RAISE(ABORT, 'Las versiones de plantilla no se eliminan'); END;

CREATE TABLE print_outputs(
  id INTEGER PRIMARY KEY,
  template_version_id INTEGER NOT NULL REFERENCES print_template_versions(id),
  target_type TEXT NOT NULL CHECK(target_type IN ('documento','venta')),
  target_id INTEGER NOT NULL,
  file_name TEXT NOT NULL,
  sha256 TEXT NOT NULL,
  pages INTEGER NOT NULL,
  data TEXT NOT NULL,
  user_id INTEGER REFERENCES users(id),
  created_at TEXT NOT NULL
);
CREATE INDEX ix_print_outputs_target ON print_outputs(target_type, target_id);
CREATE TRIGGER print_outputs_immutable BEFORE UPDATE ON print_outputs
BEGIN SELECT RAISE(ABORT, 'Los documentos emitidos no se modifican'); END;
"""
