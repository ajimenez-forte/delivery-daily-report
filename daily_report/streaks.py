"""Días seguidos de cada compromiso (regla del tercer día).

Un compromiso de "hoy" continúa la racha si el reporte anterior de la misma
persona tenía el mismo compromiso:
  - por link de tarea de Monday cuando ambos lo tienen,
  - por texto casi idéntico cuando a alguno le falta.
Un link que solo apunta a un tablero (sin pulse) no identifica la tarea,
así que esos se comparan por texto.

Funciona igual para datos de Slack y de la app, porque comparten tablas.
Por eso el primer día en la app sigue la cuenta que venía de Slack.
"""
from difflib import SequenceMatcher

from . import config
from .parser import is_item_key, normalize


def similar(a, b):
    return SequenceMatcher(None, normalize(a), normalize(b)).ratio()


def same_commitment(a, b, threshold=None):
    threshold = config.SIMILARITY_THRESHOLD if threshold is None else threshold
    ka, kb = a["monday_key"], b["monday_key"]
    if is_item_key(ka) and is_item_key(kb):
        return ka == kb
    return similar(a["text"], b["text"]) >= threshold


def match_previous(today, previous, threshold=None):
    """Empareja compromisos de hoy con los del reporte anterior (uno a uno)."""
    pairs, used = {}, set()
    for c in today:
        best, best_score = None, -1.0
        for p in previous:
            if p["id"] in used or not same_commitment(c, p, threshold):
                continue
            score = 2.0 if is_item_key(c["monday_key"]) and c["monday_key"] == p["monday_key"] \
                else similar(c["text"], p["text"])
            if score > best_score:
                best, best_score = p, score
        if best is not None:
            used.add(best["id"])
            pairs[c["id"]] = best
    return pairs


def recompute(conn):
    """Recalcula streak_days para todos los compromisos de 'hoy'."""
    people = [r["person_id"] for r in conn.execute("SELECT DISTINCT person_id FROM reports")]
    for pid in people:
        reports = conn.execute(
            """SELECT r.id FROM reports r JOIN days d ON d.id = r.day_id
               WHERE r.person_id = ? ORDER BY d.day""", (pid,)).fetchall()
        prev = []
        for r in reports:
            today = [dict(x) for x in conn.execute(
                """SELECT id, text, monday_key FROM commitments
                   WHERE report_id = ? AND section = 'hoy' ORDER BY id""", (r["id"],))]
            pairs = match_previous(today, prev)
            for c in today:
                p = pairs.get(c["id"])
                c["streak_days"] = p["streak_days"] + 1 if p else 1
                conn.execute("UPDATE commitments SET streak_days = ?, streak_prev_id = ? WHERE id = ?",
                             (c["streak_days"], p["id"] if p else None, c["id"]))
            # Un reporte en texto libre no tiene compromisos: corta la racha.
            prev = today
    conn.commit()
