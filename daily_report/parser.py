"""Interpretación de los reportes de Slack.

Regla general: si una línea no se puede interpretar con seguridad, no se
adivina. Se devuelve en `review` con el motivo, para corregirla a mano.
"""
import hashlib
import re
import unicodedata
from dataclasses import dataclass, field

MARK_EMOJI = {"✅": "hecho", "🔄": "pendiente", "⬜": "no_tocado"}
SHORTCODES = {
    ":white_check_mark:": "✅",
    ":arrows_counterclockwise:": "🔄",
    ":white_large_square:": "⬜",
}
# Palabra oficial que suele ir pegada a la marca. Se quita del texto.
_LABEL_AFTER_MARK = re.compile(
    r"^\s*(hecho|pendiente(?:\s*\(avanc[eé],?\s*no\s+cerr[eé]\))?|avanc[eé]|no\s+lo\s+toqu[eé])(?!\w)\.?",
    re.IGNORECASE)
# Marca escrita solo con la palabra oficial, al final de la línea:
# "Reunión de IA — hecho", "... - pendiente (avancé, no cerré)",
# "... — hecho (con 4 proveedores)".
_WORD_MARK = re.compile(
    r"\s*[—–\-:]\s*(hecho|pendiente(?:\s*\(avanc[eé],?\s*no\s+cerr[eé]\))?|no\s+lo\s+toqu[eé])"
    r"\s*\.?\s*(\([^()]*\))?\s*$",
    re.IGNORECASE)
_WORD_TO_MARK = {"hecho": "hecho", "pendiente": "pendiente", "no lo toque": "no_tocado"}
# Estado escrito dentro de un compromiso de Hoy ("→ link Hecho", "EN PROGRESO").
_STATUS_IN_HOY = re.compile(r"\b(hecho|completado|en progreso|terminado)\b", re.IGNORECASE)
# Marcas no oficiales que vimos en Slack. Solo sirven para dar un mejor motivo.
_UNOFFICIAL = re.compile(r"\b(completado|en progreso|poco avance|avance|terminado|listo|sin enviar)\b",
                         re.IGNORECASE)

MONDAY_URL = re.compile(r"https?://[\w.-]*monday\.com/boards/(\d+)(?:/pulses/(\d+))?[^\s)>]*")
ANY_URL = re.compile(r"https?://[^\s)>]+")
BULLET = re.compile(r"^\s*(?:[•◦▪●\-*–]|\d+[.)])\s+")
DECISION = re.compile(r"\bnivel\s*(?:de\s+decisi[oó]n)?\s*[:=]?\s*([1-5])\b", re.IGNORECASE)

_H_AYER = re.compile(r"^(?:compromisos\s+de\s+)?ayer\s*(?::\s*(.*))?$")
_H_HOY = re.compile(r"^(?:compromisos\s+de\s+hoy|compromisos\s+hoy|hoy\s*[—–-]\s*compromisos|hoy|compromisos)"
                    r"\s*(?::\s*(.*))?$")
_H_OPER = re.compile(r"^(?:hoy\s*[—–-]\s*)?operacion\s*(?::\s*(.*))?$")
_H_BLOQ = re.compile(r"^bloqueos?\s*(?::\s*(.*))?$")
HEADERS = (("ayer", _H_AYER), ("hoy", _H_HOY), ("operacion", _H_OPER), ("bloqueos", _H_BLOQ))


def strip_accents(s):
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")


def slack_to_text(text):
    """Convierte el mrkdwn de Slack a texto plano con URLs completas."""
    text = text or ""
    text = re.sub(r"<@(\w+)\|([^>]+)>", r"@\2", text)
    text = re.sub(r"<@(\w+)>", r"@\1", text)
    text = re.sub(r"<!(\w+)(?:\|[^>]*)?>", r"@\1", text)
    text = re.sub(r"<#\w+\|([^>]+)>", r"#\1", text)
    text = re.sub(r"<(https?://[^>|]+)(?:\|[^>]*)?>", r"\1", text)
    for code, emoji in SHORTCODES.items():
        text = text.replace(code, emoji)
    text = text.replace("️", "")  # selector de variación (✅️)
    return text.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")


def normalize(s):
    """Texto comparable: sin URLs, marcas, tildes, puntuación ni mayúsculas."""
    s = ANY_URL.sub(" ", s)
    for e in MARK_EMOJI:
        s = s.replace(e, " ")
    s = strip_accents(s).lower()
    s = re.sub(r"[^\w\s]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def monday_key(url):
    m = MONDAY_URL.search(url or "")
    if not m:
        return None
    return f"{m.group(1)}:{m.group(2)}" if m.group(2) else m.group(1)


def is_item_key(key):
    """True si el link apunta a una tarea (pulse) y no solo a un tablero."""
    return bool(key and ":" in key)


def _strip_format(line):
    return re.sub(r"[_*~`]", "", line).strip()


def _match_header(line):
    """Devuelve (sección, contenido_en_línea) o None."""
    raw = _strip_format(line)
    bulleted = bool(BULLET.match(raw))
    body = BULLET.sub("", raw).strip()
    key = re.sub(r"\s+", " ", strip_accents(body).lower())
    for name, rx in HEADERS:
        m = rx.match(key)
        if not m:
            continue
        inline = m.group(1)
        if bulleted and (inline or not body.endswith(":")):
            return None  # "• Operación" suelto no es encabezado, es una línea
        if inline:
            # Recupera el contenido con mayúsculas y tildes originales.
            inline = body.split(":", 1)[1].strip()
        return name, inline or ""
    return None


def _is_group_label(text):
    return (text.endswith(":") and len(text) <= 40 and not ANY_URL.search(text)
            and not any(e in text for e in MARK_EMOJI))


def _clean(text):
    text = ANY_URL.sub(" ", text)
    text = re.sub(r"\(\s*\)", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text.strip(" -—–→:;.,·|").strip()


@dataclass
class Parsed:
    recognized: bool = False
    commitments: list = field(default_factory=list)
    operation: list = field(default_factory=list)
    blockers: list = field(default_factory=list)
    review: list = field(default_factory=list)
    has_blockers_field: bool = False


class _Keys:
    """Clave estable por línea: hash del texto + número de aparición."""

    def __init__(self):
        self.seen = {}

    def __call__(self, raw):
        h = hashlib.sha1(normalize(raw).encode() or raw.encode()).hexdigest()[:12]
        n = self.seen.get(h, 0)
        self.seen[h] = n + 1
        return f"{h}-{n}"


def _read_mark(text, strict):
    """Devuelve (mark, source, texto_sin_marca) o (None, motivo, None)."""
    found = [(text.find(e), e) for e in MARK_EMOJI if e in text]
    if len(found) > 1:
        return None, "tiene más de una marca", None
    if found:
        pos, emoji = found[0]
        if text.count(emoji) > 1:
            return None, "repite la marca", None
        before, after = text[:pos], text[pos + len(emoji):]
        after = _LABEL_AFTER_MARK.sub("", after, count=1)
        return MARK_EMOJI[emoji], "emoji", f"{before} {after}"
    m = _WORD_MARK.search(text)
    if m and not strict:
        word = re.sub(r"\s+", " ", strip_accents(m.group(1)).lower())
        word = "pendiente" if word.startswith("pendiente") else word
        note = m.group(2) or ""
        return _WORD_TO_MARK[word], "palabra", text[:m.start()] + " " + note
    if _UNOFFICIAL.search(text):
        return None, "usa una marca no oficial", None
    if m and strict:
        return None, "marca escrita solo con palabra (modo estricto)", None
    return None, "sin marca", None


def _link(text):
    urls = MONDAY_URL.findall(text)
    if len(urls) > 1:
        return None, "tiene más de un link de Monday"
    m = MONDAY_URL.search(text)
    return (m.group(0) if m else None), None


def parse_structured(text, strict=False):
    """Reporte con secciones y marcas (desde el 9 de septiembre)."""
    out = Parsed()
    key = _Keys()
    section, grp = None, None
    pending = []  # líneas antes de cualquier encabezado

    def handle(line_raw, line, section):
        nonlocal grp
        lk = key(line_raw)
        if section is None:
            pending.append((lk, line_raw))
            return
        body = BULLET.sub("", _strip_format(line)).strip()
        if not body:
            return
        if section == "operacion":
            out.operation.append({"text": _clean(body) or body, "line_key": lk, "raw": line_raw})
            return
        if section == "bloqueos":
            out.has_blockers_field = True
            if re.fullmatch(r"(sin|no hay|ningun|ninguno)( bloqueos?)?", normalize(body)):
                return
            lvl = DECISION.search(body)
            out.blockers.append({"text": body, "decision_level": int(lvl.group(1)) if lvl else None,
                                 "line_key": lk, "raw": line_raw})
            return
        if _is_group_label(body):
            grp = body.rstrip(":").strip()
            return
        url, why = _link(body)
        if why:
            out.review.append({"line_key": lk, "section": section, "raw": line_raw, "reason": why})
            return
        is_extra = bool(re.match(r"extra\s*[:\-—]", strip_accents(body).lower()))
        if is_extra:
            body = re.sub(r"^extra\s*[:\-—]\s*", "", body, flags=re.IGNORECASE)
        mark = source = None
        if section == "ayer":
            mark, source, rest = _read_mark(body, strict)
            if mark is None:
                out.review.append({"line_key": lk, "section": section, "raw": line_raw, "reason": source})
                return
            body = rest
        elif any(e in body for e in MARK_EMOJI):
            out.review.append({"line_key": lk, "section": section, "raw": line_raw,
                               "reason": "compromiso de hoy con marca"})
            return
        elif _STATUS_IN_HOY.search(ANY_URL.sub(" ", body)):
            out.review.append({"line_key": lk, "section": section, "raw": line_raw,
                               "reason": "compromiso de hoy con un estado escrito"})
            return
        clean = _clean(body)
        if not clean:
            out.review.append({"line_key": lk, "section": section, "raw": line_raw,
                               "reason": "sin texto después de quitar link y marca"})
            return
        out.commitments.append({
            "section": section, "text": clean, "grp": grp, "mark": mark, "mark_source": source,
            "is_extra": is_extra, "monday_url": url, "monday_key": monday_key(url),
            "line_key": lk, "raw": line_raw})

    for line_raw in (text or "").splitlines():
        if not line_raw.strip():
            continue
        h = _match_header(line_raw)
        if h:
            out.recognized = True
            section, grp = h[0], None
            if section == "bloqueos":
                out.has_blockers_field = True
            if h[1]:
                handle(line_raw, h[1], section)
            continue
        handle(line_raw, line_raw, section)

    if out.recognized:
        for lk, raw in pending:
            out.review.append({"line_key": lk, "section": None, "raw": raw,
                               "reason": "texto antes de las secciones"})
    return out


def looks_like_free_report(text):
    """Formato libre (27 ago - 8 sep): basta con que hable de ayer/hoy/bloqueos."""
    t = strip_accents(text or "").lower()
    return bool(re.search(r"\b(ayer|hoy|bloqueos?)\b", t))
