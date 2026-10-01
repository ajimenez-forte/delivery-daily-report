"""Días seguidos de cada compromiso (regla del tercer día).

Un compromiso de "hoy" continúa la racha si el reporte anterior de la misma
persona tenía el mismo compromiso. Se compara por link de Monday y por texto:
  - mismo link (de tarea o de tablero): el texto también debe ser parecido,
    porque hay links que se usan para varias tareas distintas;
  - sin link en alguno de los dos: el texto debe ser casi idéntico;
  - links de tarea distintos: son tareas distintas.

PTO: los días de PTO no rompen la racha ni la suman. Solo cuentan los días
que la persona reportó. Un reporte hecho en un día de PTO no suma.

Funciona igual para datos de Slack y de la app, porque comparten tablas.
Por eso el primer día en la app sigue la cuenta que venía de Slack.
"""
import re
from difflib import SequenceMatcher

from . import config
from .parser import is_item_key, normalize

_STOP = set("""a al and con de del el en for la las los me mi of on para por que se sobre the to un una y
o u e su sus lo le les es hacer hoy ayer""".split())


def _tokens(s):
    return {w[:5] for w in normalize(s).split() if w not in _STOP and len(w) > 1}


def similar(a, b):
    """Similitud de 0 a 1: lo mejor entre caracteres y palabras en común."""
    chars = SequenceMatcher(None, normalize(a), normalize(b)).ratio()
    ta, tb = _tokens(a), _tokens(b)
    words = len(ta & tb) / min(len(ta), len(tb)) if ta and tb else 0.0
    # Una sola palabra en común no basta ("Reporte de Oxford" / "Reporte de Rocket").
    if len(ta & tb) < 2:
        words = min(words, 0.49)
    # Entre textos cortos el parecido por caracteres engaña; solo cuenta si es alto.
    return max(words, chars if chars >= 0.8 else 0.0)


def same_commitment(a, b):
    ka, kb = a["monday_key"], b["monday_key"]
    if ka and kb and ka == kb:
        return similar(a["text"], b["text"]) >= config.LINKED_SIMILARITY_THRESHOLD
    if is_item_key(ka) and is_item_key(kb):
        return False
    return SequenceMatcher(None, normalize(a["text"]), normalize(b["text"])).ratio() \
        >= config.SIMILARITY_THRESHOLD


def match_previous(today, previous):
    """Empareja compromisos de hoy con los del reporte anterior (uno a uno)."""
    cands = []
    for c in today:
        for p in previous:
            if same_commitment(c, p):
                bonus = 1.0 if c["monday_key"] and c["monday_key"] == p["monday_key"] else 0.0
                cands.append((bonus + similar(c["text"], p["text"]), c["id"], p))
    pairs, used = {}, set()
    for _, cid, p in sorted(cands, key=lambda x: -x[0]):
        if cid in pairs or p["id"] in used:
            continue
        pairs[cid] = p
        used.add(p["id"])
    return pairs


def pto_days(conn, person_id):
    return {r["day"] for r in conn.execute("SELECT day FROM pto WHERE person_id = ?", (person_id,))}


def recompute(conn):
    """Recalcula streak_days para todos los compromisos de 'hoy'."""
    people = [r["person_id"] for r in conn.execute("SELECT DISTINCT person_id FROM reports")]
    for pid in people:
        pto = pto_days(conn, pid)
        reports = conn.execute(
            """SELECT r.id, d.day FROM reports r JOIN days d ON d.id = r.day_id
               WHERE r.person_id = ? ORDER BY d.day""", (pid,)).fetchall()
        prev = []
        for r in reports:
            today = [dict(x) for x in conn.execute(
                """SELECT id, text, monday_key, starting_point FROM commitments
                   WHERE report_id = ? AND section = 'hoy' ORDER BY id""", (r["id"],))]
            on_pto = r["day"] in pto
            pairs = match_previous(today, prev)
            for c in today:
                p = pairs.get(c["id"])
                c["streak_days"] = (p["streak_days"] + (0 if on_pto else 1)) if p else (0 if on_pto else 1)
                c["streak_days"] = max(c["streak_days"], 1)
                conn.execute("UPDATE commitments SET streak_days = ?, streak_prev_id = ? WHERE id = ?",
                             (c["streak_days"], p["id"] if p else None, c["id"]))
            if not on_pto:
                # Un reporte en texto libre no tiene compromisos: corta la racha.
                # Si el reporte define el punto de partida, solo sigue lo que se ve como "Ayer".
                marked = [c for c in today if c["starting_point"]]
                prev = marked or today
    conn.commit()
