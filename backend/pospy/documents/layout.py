"""Modelo de plantillas de impresión («layout»), formatos numéricos y cálculos seguros.

Un layout es un diccionario JSON con el diseño de UNA hoja, independiente de Excel:
  cols    anchos de columna (unidades de carácter de Excel), desde la columna A
  rows    altos de fila en puntos, desde la fila 1 (0 = fila oculta)
  cells   {"B8": {"v": valor, "s": índice de estilo, "f": fórmula original (solo informativa)}}
  styles  lista de estilos: font {name,size,b,i,u,color}, fill, h, v, wrap, fmt, border {l,r,t,b: [estilo, color]}
  merges  ["A1:E2", ...]
  images  [{"id","file","mime","col","col_off","row","row_off","w","h","crop":{l,t,r,b}}]  (col/row desde 0, medidas en pt)
  page    papel, orientación, márgenes, escala, área de impresión, filas repetidas, encabezado y pie

Las vinculaciones (qué celda recibe qué dato del POS) se guardan aparte: el layout es el diseño.
Los cálculos usan Decimal y un evaluador propio: nunca se ejecuta código del usuario (ni eval).
"""
from __future__ import annotations

import re
from datetime import date, datetime, time, timedelta
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

# ------------------------------------------------------------------ coordenadas
_CELL = re.compile(r"^\$?([A-Z]{1,3})\$?(\d{1,7})$")


def col_index(letters: str) -> int:
    n = 0
    for ch in letters.upper():
        n = n * 26 + (ord(ch) - 64)
    return n


def col_letter(n: int) -> str:
    out = ""
    while n > 0:
        n, r = divmod(n - 1, 26)
        out = chr(65 + r) + out
    return out


def parse_cell(ref: str) -> tuple[int, int]:
    """'B8' -> (fila 8, columna 2)."""
    m = _CELL.match(str(ref or "").strip().upper())
    if not m:
        raise ValueError(f"«{ref}» no es una celda válida (ej.: B8).")
    row, col = int(m.group(2)), col_index(m.group(1))
    if not (1 <= row <= 1_048_576 and 1 <= col <= 16_384):
        raise ValueError(f"«{ref}» está fuera de la hoja.")
    return row, col


def cell_ref(row: int, col: int) -> str:
    return f"{col_letter(col)}{row}"


def parse_range(ref: str) -> tuple[int, int, int, int]:
    """'A1:E2' -> (fila1, col1, fila2, col2) normalizado. Una sola celda es un rango de 1×1."""
    parts = str(ref).split("!")[-1].replace("$", "").split(":")
    r1, c1 = parse_cell(parts[0])
    r2, c2 = parse_cell(parts[-1])
    return min(r1, r2), min(c1, c2), max(r1, r2), max(c1, c2)


def range_ref(r1: int, c1: int, r2: int, c2: int) -> str:
    a, b = cell_ref(r1, c1), cell_ref(r2, c2)
    return a if a == b else f"{a}:{b}"


def col_points(width_chars: float) -> float:
    """Ancho de columna de Excel (caracteres de Calibri 11) a puntos."""
    if not width_chars:
        return 0.0
    px = int(width_chars * 7 + 5) if width_chars >= 1 else int(width_chars * 12 + 0.5)
    return px * 0.75


def empty_layout(cols: int = 8, rows: int = 30) -> dict:
    return {"v": 1, "cols": [12.0] * cols, "rows": [15.0] * rows, "cells": {}, "styles": [{}], "merges": [],
            "images": [], "page": default_page()}


def default_page() -> dict:
    return {"paper": "letter", "orientation": "portrait", "width_mm": 0, "height_mm": 0,
            "margins": {"l": 1.5, "r": 1.5, "t": 1.5, "b": 1.5}, "scale": 100, "fit_width": True,
            "print_area": "", "repeat_rows": "", "header": "", "footer": "", "row_breaks": []}


PAPERS_MM = {"letter": (215.9, 279.4), "legal": (215.9, 355.6), "a4": (210.0, 297.0), "a5": (148.0, 210.0),
             "roll80": (80.0, 0.0), "roll58": (58.0, 0.0)}
PAPER_LABELS = {"letter": "Carta", "legal": "Oficio", "a4": "A4", "a5": "A5", "roll80": "Rollo 80 mm",
                "roll58": "Rollo 58 mm", "custom": "Personalizado"}


# ------------------------------------------------------------------ formatos numéricos (estilo Excel, es-CO)
DAYS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
MONTHS = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre",
          "noviembre", "diciembre"]
EPOCH = datetime(1899, 12, 30)


def to_serial(value: datetime | date | time) -> float:
    if isinstance(value, datetime):
        delta = value - EPOCH
    elif isinstance(value, date):
        delta = datetime(value.year, value.month, value.day) - EPOCH
    else:
        return (value.hour * 3600 + value.minute * 60 + value.second) / 86400
    return delta.days + delta.seconds / 86400


def from_serial(serial: float) -> datetime:
    return EPOCH + timedelta(days=float(serial))


def _strip_format(section: str) -> str:
    """Quita colores, condiciones y marcas de idioma; convierte [$$-240A] en el símbolo."""
    section = re.sub(r"\[\$([^\]-]*)-[0-9A-Fa-f]+\]", lambda m: f'"{m.group(1)}"' if m.group(1) else "", section)
    section = re.sub(r"\[(?:[A-Za-z]+|[<>=][^\]]*)\]", "", section)
    return section


_DATE_TOKENS = re.compile(r'("[^"]*"|\\.|yyyy|yy|mmmm|mmm|mm|m|dddd|ddd|dd|d|hh|h|ss|s|AM/PM|am/pm|A/P|\.0+)',
                          re.IGNORECASE)


def _is_date_format(fmt: str) -> bool:
    bare = re.sub(r'"[^"]*"|\\.', "", fmt)
    return bool(re.search(r"[ymdhs]", bare, re.IGNORECASE)) and not re.search(r"[#0?]", bare.split(".")[0])


def _format_date(serial: float, fmt: str) -> str:
    """Excel: «m»/«mm» son minutos si van justo después de h/hh o antes de s/ss; si no, el mes."""
    dt = from_serial(serial)
    parts = [t for t in _DATE_TOKENS.split(fmt) if t]
    is_tok = [bool(_DATE_TOKENS.fullmatch(t)) and not t.startswith(('"', "\\")) for t in parts]
    toks = [p.lower() if k else None for p, k in zip(parts, is_tok, strict=True)]
    has_ampm = any(t in ("am/pm", "a/p") for t in toks if t)
    out = []
    for i, part in enumerate(parts):
        low = toks[i]
        if low is None:
            out.append(part[1:-1] if part.startswith('"') else part[1:] if part.startswith("\\") else part)
            continue
        prev = next((toks[j] for j in range(i - 1, -1, -1) if toks[j]), "")
        nxt = next((toks[j] for j in range(i + 1, len(toks)) if toks[j]), "")
        if low in ("mm", "m") and (prev in ("h", "hh") or nxt in ("s", "ss")):
            out.append(f"{dt.minute:02d}" if low == "mm" else str(dt.minute))
        elif low in ("hh", "h"):
            h = (dt.hour % 12 or 12) if has_ampm else dt.hour
            out.append(f"{h:02d}" if low == "hh" else str(h))
        elif low == "yyyy":
            out.append(f"{dt.year:04d}")
        elif low == "yy":
            out.append(f"{dt.year % 100:02d}")
        elif low == "mmmm":
            out.append(MONTHS[dt.month - 1])
        elif low == "mmm":
            out.append(MONTHS[dt.month - 1][:3])
        elif low == "mm":
            out.append(f"{dt.month:02d}")
        elif low == "m":
            out.append(str(dt.month))
        elif low == "dddd":
            out.append(DAYS[dt.weekday()])
        elif low == "ddd":
            out.append(DAYS[dt.weekday()][:3])
        elif low == "dd":
            out.append(f"{dt.day:02d}")
        elif low == "d":
            out.append(str(dt.day))
        elif low == "ss":
            out.append(f"{dt.second:02d}")
        elif low == "s":
            out.append(str(dt.second))
        elif low in ("am/pm", "a/p"):
            out.append("a. m." if dt.hour < 12 else "p. m.")
    return "".join(out)


def _group(int_part: str) -> str:
    out = []
    while len(int_part) > 3:
        out.insert(0, int_part[-3:])
        int_part = int_part[:-3]
    out.insert(0, int_part)
    return ".".join(out)


def _format_number(value: Decimal, fmt: str) -> str:
    literal_before, literal_after, core = [], [], []
    seen_digit = False
    i = 0
    while i < len(fmt):
        ch = fmt[i]
        if ch == '"':
            j = fmt.find('"', i + 1)
            j = len(fmt) if j < 0 else j
            (literal_after if seen_digit else literal_before).append(fmt[i + 1:j])
            i = j + 1
            continue
        if ch == "\\" and i + 1 < len(fmt):
            (literal_after if seen_digit else literal_before).append(fmt[i + 1])
            i += 2
            continue
        if ch == "_":            # espacio del ancho de un carácter
            (literal_after if seen_digit else literal_before).append(" ")
            i += 2
            continue
        if ch == "*":            # relleno: se omite
            i += 2
            continue
        if ch in "#0?,.":
            seen_digit = True
            core.append(ch)
        elif ch == "%":
            literal_after.append("%")
        elif ch in "$-+/():' ":
            (literal_after if seen_digit else literal_before).append(ch)
        i += 1
    pattern = "".join(core)
    if "%" in "".join(literal_after):
        value = value * 100
    if not pattern:
        return ("".join(literal_before) + "".join(literal_after)).strip() or _general(value)
    int_pat, _, dec_pat = pattern.partition(".")
    decimals = len(re.sub(r"[^0?#]", "", dec_pat))
    min_decimals = len(re.sub(r"[^0]", "", dec_pat))
    grouping = "," in int_pat
    scale_down = len(int_pat) - len(int_pat.rstrip(","))   # comas finales dividen entre mil
    value = value / (Decimal(1000) ** scale_down)
    q = value.quantize(Decimal(1).scaleb(-decimals), rounding=ROUND_HALF_UP) if decimals else value.quantize(
        Decimal(1), rounding=ROUND_HALF_UP)
    text = f"{abs(q):.{decimals}f}"
    ip, _, dp = text.partition(".")
    dp = dp.rstrip("0").ljust(min_decimals, "0") if decimals else ""
    min_int = len(re.sub(r"[^0]", "", int_pat))
    ip = ip.lstrip("0").rjust(min_int, "0") if ip != "0" or min_int else ""
    if grouping and ip:
        ip = _group(ip)
    body = ip + ("," + dp if dp else "")
    sign = "-" if q < 0 else ""
    return sign + "".join(literal_before) + body + "".join(literal_after)


def _general(value: Decimal) -> str:
    if value == value.to_integral_value():
        return str(int(value))
    text = format(value.normalize(), "f")
    return text.replace(".", ",")


def format_value(value: Any, fmt: str | None) -> str:
    """Texto que Excel mostraría para el valor con ese formato (subconjunto común, idioma es-CO)."""
    if value is None or value == "":
        return ""
    if isinstance(value, bool):
        return "VERDADERO" if value else "FALSO"
    if isinstance(value, (datetime, date, time)):
        value = to_serial(value)
    if not isinstance(value, (int, float, Decimal)):
        return str(value)
    fmt = (fmt or "General").strip()
    sections = fmt.split(";")
    num = Decimal(str(value))
    if len(sections) >= 3 and num == 0:
        section = sections[2]
    elif len(sections) >= 2 and num < 0:
        section, num = sections[1], -num
    else:
        section = sections[0]
    section = _strip_format(section)
    if section.strip().lower() in ("general", ""):
        return _general(num)
    if section.strip() == "@":
        return _general(num)
    if _is_date_format(section):
        try:
            return _format_date(float(num), section).strip()
        except (OverflowError, ValueError):
            return _general(num)
    return _format_number(num, section).strip()


# ------------------------------------------------------------------ cálculos seguros (Decimal)
class CalcError(ValueError):
    pass


FUNCTIONS = {"SUMA", "REDONDEAR", "MAX", "MIN", "ABS", "SI_CERO"}
_TOKEN = re.compile(r"\s*(?:(\d+(?:[.,]\d+)?)|([A-Za-z_][A-Za-z0-9_]*)|(\*\*|[-+*/()%;]))")


def tokenize(expr: str) -> list[tuple[str, str]]:
    expr = str(expr or "").strip()
    if not expr:
        raise CalcError("La fórmula está vacía.")
    if len(expr) > 300:
        raise CalcError("La fórmula es demasiado larga (máximo 300 caracteres).")
    pos, out = 0, []
    while pos < len(expr):
        m = _TOKEN.match(expr, pos)
        if not m or m.end() == pos:
            if expr[pos:].strip() == "":
                break
            raise CalcError(f"Carácter no permitido en la fórmula: «{expr[pos]}».")
        if m.group(1):
            out.append(("num", m.group(1).replace(",", ".")))
        elif m.group(2):
            out.append(("name", m.group(2)))
        elif m.group(3):
            if m.group(3) == "**":
                raise CalcError("Use * para multiplicar; no se permiten potencias.")
            out.append(("op", m.group(3)))
        pos = m.end()
    return out


class _Parser:
    """expr := term (('+'|'-') term)* ; term := unary (('*'|'/') unary)* ; unary := '-' unary | postfix
    postfix := atom '%'? ; atom := número | nombre | FUNCIÓN '(' args ')' | '(' expr ')'"""

    def __init__(self, tokens: list[tuple[str, str]]):
        self.t = tokens
        self.i = 0

    def peek(self) -> tuple[str, str] | None:
        return self.t[self.i] if self.i < len(self.t) else None

    def take(self, value: str | None = None) -> tuple[str, str]:
        tok = self.peek()
        if tok is None or (value is not None and tok[1] != value):
            raise CalcError(f"Se esperaba «{value}» en la fórmula." if value else "La fórmula está incompleta.")
        self.i += 1
        return tok

    def parse(self):
        node = self.expr()
        if self.peek() is not None:
            raise CalcError(f"Sobra «{self.peek()[1]}» en la fórmula.")
        return node

    def expr(self):
        node = self.term()
        while self.peek() and self.peek()[1] in ("+", "-"):
            op = self.take()[1]
            node = ("bin", op, node, self.term())
        return node

    def term(self):
        node = self.unary()
        while self.peek() and self.peek()[1] in ("*", "/"):
            op = self.take()[1]
            node = ("bin", op, node, self.unary())
        return node

    def unary(self):
        if self.peek() and self.peek()[1] in ("-", "+"):
            op = self.take()[1]
            inner = self.unary()
            return ("neg", inner) if op == "-" else inner
        node = self.atom()
        while self.peek() and self.peek()[1] == "%":
            self.take()
            node = ("bin", "/", node, ("num", Decimal(100)))
        return node

    def atom(self):
        tok = self.take()
        if tok[0] == "num":
            return ("num", Decimal(tok[1]))
        if tok[0] == "name":
            name = tok[1]
            if self.peek() and self.peek()[1] == "(":
                upper = name.upper()
                if upper not in FUNCTIONS:
                    raise CalcError(f"Función no permitida: {name}. Use: {', '.join(sorted(FUNCTIONS))}.")
                self.take("(")
                args = [self.expr()]
                while self.peek() and self.peek()[1] == ";":   # separador de argumentos, como Excel en español
                    self.take(";")
                    args.append(self.expr())
                self.take(")")
                return ("call", upper, args)
            return ("var", name)
        if tok[1] == "(":
            node = self.expr()
            self.take(")")
            return node
        raise CalcError(f"No se esperaba «{tok[1]}» en la fórmula.")


def compile_expr(expr: str, known: set[str], line_names: set[str] | None = None, in_line: bool = False):
    """Analiza y valida la fórmula. known: variables del documento; line_names: variables de cada producto."""
    tree = _Parser(tokenize(expr)).parse()
    line_names = line_names or set()

    def check(node, inside_sum: bool) -> None:
        kind = node[0]
        if kind == "var":
            name = node[1]
            if name in line_names and not (inside_sum or in_line):
                raise CalcError(f"«{name}» es un dato de cada producto: úselo dentro de SUMA(...) o en la tabla de productos.")
            if name not in known and name not in line_names:
                raise CalcError(f"Variable desconocida en la fórmula: «{name}».")
        elif kind == "bin":
            check(node[2], inside_sum)
            check(node[3], inside_sum)
        elif kind == "neg":
            check(node[1], inside_sum)
        elif kind == "call":
            fn, args = node[1], node[2]
            expected = {"SUMA": (1, 1), "REDONDEAR": (1, 2), "ABS": (1, 1), "MAX": (1, 10), "MIN": (1, 10),
                        "SI_CERO": (2, 2)}[fn]
            if not expected[0] <= len(args) <= expected[1]:
                raise CalcError(f"{fn} recibe {expected[0]}" + (f" a {expected[1]}" if expected[1] != expected[0] else "")
                                + " argumento(s).")
            if fn == "SUMA" and (in_line or inside_sum):
                raise CalcError("SUMA no se puede usar dentro de la tabla de productos ni anidada.")
            for a in args:
                check(a, inside_sum or fn == "SUMA")

    check(tree, False)
    return tree


def evaluate(tree, variables: dict[str, Decimal], lines: list[dict[str, Decimal]] | None = None) -> Decimal:
    def ev(node, scope: dict[str, Decimal]) -> Decimal:
        kind = node[0]
        if kind == "num":
            return node[1]
        if kind == "var":
            if node[1] not in scope:
                raise CalcError(f"Variable sin valor: «{node[1]}».")
            return Decimal(scope[node[1]])
        if kind == "neg":
            return -ev(node[1], scope)
        if kind == "bin":
            a, b = ev(node[2], scope), ev(node[3], scope)
            if node[1] == "+":
                return a + b
            if node[1] == "-":
                return a - b
            if node[1] == "*":
                return a * b
            if b == 0:
                return Decimal(0)        # división por cero: 0 (como un total vacío), nunca un error en la impresión
            return a / b
        fn, args = node[1], node[2]
        if fn == "SUMA":
            return sum((ev(args[0], {**scope, **ln}) for ln in (lines or [])), Decimal(0))
        vals = [ev(a, scope) for a in args]
        if fn == "REDONDEAR":
            places = int(vals[1]) if len(vals) > 1 else 0
            return vals[0].quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP)
        if fn == "ABS":
            return abs(vals[0])
        if fn == "MAX":
            return max(vals)
        if fn == "MIN":
            return min(vals)
        return vals[1] if vals[0] == 0 else vals[0]       # SI_CERO(valor, alternativo)

    try:
        return ev(tree, variables)
    except InvalidOperation:
        raise CalcError("Resultado numérico no válido.") from None


def money(value: Decimal) -> Decimal:
    return Decimal(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


# ------------------------------------------------------------------ validación del diseño recibido del editor
class LayoutError(ValueError):
    def __init__(self, problems: list[str]):
        self.problems = problems
        super().__init__(" ".join(problems))


BORDER_STYLES = {"hair", "thin", "dotted", "dashed", "dashDot", "dashDotDot", "medium", "mediumDashed", "mediumDashDot",
                 "mediumDashDotDot", "slantDashDot", "thick", "double"}
_HEX = re.compile(r"^#[0-9A-Fa-f]{6}$")
LIMITS = {"cols": 60, "rows": 2000, "cells": 20000, "styles": 5000, "images": 20, "text": 2000}


def _num(value: Any, lo: float, hi: float, name: str, problems: list[str]) -> float:
    try:
        v = float(value)
    except (TypeError, ValueError):
        problems.append(f"{name}: no es un número.")
        return lo
    if v != v or not lo <= v <= hi:   # NaN o fuera de rango
        problems.append(f"{name}: debe estar entre {lo:g} y {hi:g}.")
        return max(lo, min(hi, v)) if v == v else lo
    return v


def _clean_style(st: Any, i: int, problems: list[str]) -> dict:
    if not isinstance(st, dict):
        problems.append(f"Estilo {i}: no válido.")
        return {}
    out: dict[str, Any] = {}
    font = st.get("font")
    if isinstance(font, dict):
        f: dict[str, Any] = {}
        if font.get("name"):
            f["name"] = str(font["name"])[:40]
        if font.get("size") is not None:
            f["size"] = _num(font["size"], 1, 200, f"Estilo {i}: tamaño de letra", problems)
        for k in ("b", "i", "u"):
            if font.get(k):
                f[k] = True
        if font.get("color"):
            if _HEX.match(str(font["color"])):
                f["color"] = str(font["color"]).upper()
            else:
                problems.append(f"Estilo {i}: color de letra no válido.")
        if f:
            out["font"] = f
    if st.get("fill"):
        if _HEX.match(str(st["fill"])):
            out["fill"] = str(st["fill"]).upper()
        else:
            problems.append(f"Estilo {i}: color de relleno no válido.")
    if st.get("h") in ("left", "center", "right"):
        out["h"] = st["h"]
    if st.get("v") in ("top", "center", "bottom"):
        out["v"] = st["v"]
    if st.get("wrap"):
        out["wrap"] = True
    if st.get("fmt"):
        out["fmt"] = str(st["fmt"])[:120]
    border = st.get("border")
    if isinstance(border, dict):
        b = {}
        for side in ("l", "r", "t", "b"):
            val = border.get(side)
            if not val:
                continue
            if (isinstance(val, (list, tuple)) and len(val) == 2 and val[0] in BORDER_STYLES
                    and _HEX.match(str(val[1]))):
                b[side] = [val[0], str(val[1]).upper()]
            else:
                problems.append(f"Estilo {i}: borde {side} no válido.")
        if b:
            out["border"] = b
    return out


def sanitize_layout(raw: Any, image_files: set[str]) -> dict:
    """Valida y normaliza un diseño recibido (editor o importación). Lanza LayoutError con los problemas."""
    problems: list[str] = []
    if not isinstance(raw, dict):
        raise LayoutError(["El diseño no es válido."])
    cols, rows = raw.get("cols"), raw.get("rows")
    if not isinstance(cols, list) or not 1 <= len(cols) <= LIMITS["cols"]:
        raise LayoutError([f"El diseño debe tener entre 1 y {LIMITS['cols']} columnas."])
    if not isinstance(rows, list) or not 1 <= len(rows) <= LIMITS["rows"]:
        raise LayoutError([f"El diseño debe tener entre 1 y {LIMITS['rows']} filas."])
    out: dict[str, Any] = {"v": 1}
    out["cols"] = [round(_num(w, 0, 255, f"Ancho de la columna {col_letter(i + 1)}", problems), 2) for i, w in enumerate(cols)]
    out["rows"] = [round(_num(h, 0, 409, f"Alto de la fila {i + 1}", problems), 2) for i, h in enumerate(rows)]
    styles = raw.get("styles") or [{}]
    if not isinstance(styles, list) or len(styles) > LIMITS["styles"]:
        raise LayoutError(["Demasiados estilos en el diseño."])
    out["styles"] = [_clean_style(st, i, problems) for i, st in enumerate(styles)] or [{}]
    nrows, ncols = len(out["rows"]), len(out["cols"])
    cells_in = raw.get("cells") or {}
    if not isinstance(cells_in, dict) or len(cells_in) > LIMITS["cells"]:
        raise LayoutError(["Demasiadas celdas en el diseño."])
    cells: dict[str, dict] = {}
    for ref, cell in cells_in.items():
        try:
            r, c = parse_cell(ref)
        except ValueError as exc:
            problems.append(str(exc))
            continue
        if r > nrows or c > ncols:
            problems.append(f"La celda {ref} está fuera del diseño.")
            continue
        if not isinstance(cell, dict):
            continue
        entry: dict[str, Any] = {}
        v = cell.get("v")
        if isinstance(v, bool):
            v = str(v)
        if isinstance(v, (int, float)):
            if v != v or abs(v) > 1e15:
                problems.append(f"{ref}: número no válido.")
            else:
                entry["v"] = v
        elif v not in (None, ""):
            entry["v"] = str(v)[:LIMITS["text"]]
        s = cell.get("s", 0)
        if isinstance(s, int) and 0 < s < len(out["styles"]):
            entry["s"] = s
        if cell.get("f"):
            entry["f"] = str(cell["f"])[:500]
        if entry:
            cells[cell_ref(r, c)] = entry
    out["cells"] = cells
    taken: set[tuple[int, int]] = set()
    merges = []
    for m in raw.get("merges") or []:
        try:
            r1, c1, r2, c2 = parse_range(m)
        except (ValueError, TypeError):
            problems.append(f"Combinación no válida: {m}.")
            continue
        if r2 > nrows or c2 > ncols:
            problems.append(f"La combinación {m} está fuera del diseño.")
            continue
        if (r1, c1) == (r2, c2):
            continue
        area = {(r, c) for r in range(r1, r2 + 1) for c in range(c1, c2 + 1)}
        if area & taken:
            problems.append(f"La combinación {m} se superpone con otra.")
            continue
        taken |= area
        merges.append(range_ref(r1, c1, r2, c2))
    out["merges"] = merges
    images = []
    for i, img in enumerate((raw.get("images") or [])[:LIMITS["images"]]):
        if not isinstance(img, dict) or img.get("file") not in image_files:
            problems.append(f"Imagen {i + 1}: el archivo no existe en la plantilla.")
            continue
        crop = img.get("crop") if isinstance(img.get("crop"), dict) else {}
        images.append({
            "id": str(img.get("id") or f"img{i + 1}")[:20], "file": img["file"],
            "mime": "image/png" if str(img["file"]).endswith(".png") else "image/jpeg",
            "col": int(_num(img.get("col", 0), 0, ncols - 1, f"Imagen {i + 1}: columna", problems)),
            "row": int(_num(img.get("row", 0), 0, nrows - 1, f"Imagen {i + 1}: fila", problems)),
            "col_off": round(_num(img.get("col_off", 0), 0, 2000, f"Imagen {i + 1}: desplazamiento", problems), 2),
            "row_off": round(_num(img.get("row_off", 0), 0, 2000, f"Imagen {i + 1}: desplazamiento", problems), 2),
            "w": round(_num(img.get("w", 50), 1, 3000, f"Imagen {i + 1}: ancho", problems), 2),
            "h": round(_num(img.get("h", 50), 1, 3000, f"Imagen {i + 1}: alto", problems), 2),
            "crop": {k: round(_num(crop[k], 0, 0.95, f"Imagen {i + 1}: recorte", problems), 5)
                     for k in ("l", "t", "r", "b") if k in crop},
        })
    out["images"] = images
    page_in = raw.get("page") if isinstance(raw.get("page"), dict) else {}
    page = default_page()
    if page_in.get("paper") in (*PAPERS_MM, "custom"):
        page["paper"] = page_in["paper"]
    elif page_in.get("paper"):
        problems.append("Tamaño de papel no válido.")
    page["orientation"] = "landscape" if page_in.get("orientation") == "landscape" else "portrait"
    if page["paper"] == "custom":
        page["width_mm"] = _num(page_in.get("width_mm", 0), 20, 1200, "Ancho del papel (mm)", problems)
        page["height_mm"] = _num(page_in.get("height_mm", 0), 20, 5000, "Alto del papel (mm)", problems)
    margins = page_in.get("margins") if isinstance(page_in.get("margins"), dict) else {}
    page["margins"] = {k: round(_num(margins.get(k, 1.5), 0, 10, "Márgenes (cm)", problems), 2) for k in ("l", "r", "t", "b")}
    page["scale"] = int(_num(page_in.get("scale", 100), 10, 400, "Escala (%)", problems))
    page["fit_width"] = bool(page_in.get("fit_width"))
    area = str(page_in.get("print_area") or "").strip().upper()
    if area:
        try:
            r1, c1, r2, c2 = parse_range(area)
            if r2 > nrows or c2 > ncols:
                problems.append("El área de impresión está fuera del diseño.")
            page["print_area"] = range_ref(r1, c1, min(r2, nrows), min(c2, ncols))
        except ValueError:
            problems.append("El área de impresión no es válida (ej.: A1:E40).")
    rep = str(page_in.get("repeat_rows") or "").strip()
    if rep:
        m = re.fullmatch(r"(\d{1,4}):(\d{1,4})", rep)
        if not m or not 1 <= int(m.group(1)) <= int(m.group(2)) <= nrows:
            problems.append("Las filas que se repiten deben escribirse como 14:14 y estar dentro del diseño.")
        else:
            page["repeat_rows"] = rep
    page["header"] = str(page_in.get("header") or "")[:200]
    page["footer"] = str(page_in.get("footer") or "")[:200]
    page["row_breaks"] = sorted({int(b) for b in page_in.get("row_breaks") or [] if str(b).isdigit() and 1 <= int(b) <= nrows})
    out["page"] = page
    if problems:
        raise LayoutError(problems[:30])
    return out
