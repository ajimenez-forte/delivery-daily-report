"""Corrección a mano de lo que la importación no pudo interpretar."""
import json
from datetime import datetime, timezone

from . import streaks
from .importer import ingest_message, refresh_report
from .parser import monday_key

LINE_ACTIONS = ("compromiso", "operacion", "bloqueo", "descartar")
MESSAGE_ACTIONS = ("reporte", "descartar")
MARKS = ("hecho", "pendiente", "no_tocado")


def pending(conn):
    return conn.execute(
        """SELECT ri.*, p.name AS persona FROM review_items ri
           LEFT JOIN people p ON p.id = ri.person_id
           WHERE ri.status = 'pendiente' OR ri.stale = 1
           ORDER BY ri.day, p.name, CAST(ri.slack_ts AS REAL), ri.id""").fetchall()


def _report_for(conn, slack_ts):
    row = conn.execute("SELECT report_id FROM report_messages WHERE slack_ts = ?", (slack_ts,)).fetchone()
    if not row:
        raise ValueError("El mensaje de esta línea no está asociado a un reporte.")
    return row["report_id"]


def _clear_manual(conn, item_id, slack_ts):
    key = f"review:{item_id}"
    for t in ("commitments", "operation_items", "blockers"):
        conn.execute(f"DELETE FROM {t} WHERE slack_ts = ? AND line_key = ? AND manual = 1", (slack_ts, key))


def resolve(conn, item_id, action, text=None, section=None, mark=None, monday_url=None, decision_level=None):
    item = conn.execute("SELECT * FROM review_items WHERE id = ?", (item_id,)).fetchone()
    if not item:
        raise ValueError("No existe ese ítem de revisión.")
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    text = (text or "").strip()
    monday_url = (monday_url or "").strip() or None
    decision = {"action": action, "text": text, "section": section, "mark": mark,
                "monday_url": monday_url, "decision_level": decision_level}

    if item["kind"] == "mensaje":
        if action not in MESSAGE_ACTIONS:
            raise ValueError(f"Acción no válida para un mensaje: {action}")
        status = "descartado" if action == "descartar" else "resuelto"
        conn.execute("UPDATE review_items SET status = ?, resolution = ?, resolved_at = ?, stale = 0 "
                     "WHERE id = ?", (status, json.dumps(decision), now, item_id))
        if action == "reporte":
            day = conn.execute("SELECT * FROM days WHERE day = ?", (item["day"],)).fetchone()
            from datetime import date
            rid = ingest_message(conn, day["id"], date.fromisoformat(item["day"]), day["format"],
                                 item["person_id"], item["slack_ts"], item["raw_text"], force_report=True)
            refresh_report(conn, rid)
    else:
        if action not in LINE_ACTIONS:
            raise ValueError(f"Acción no válida para una línea: {action}")
        _clear_manual(conn, item_id, item["slack_ts"])
        key = f"review:{item_id}"
        if action != "descartar":
            if not text:
                raise ValueError("Falta el texto.")
            report_id = _report_for(conn, item["slack_ts"])
            if action == "compromiso":
                if section not in ("ayer", "hoy"):
                    raise ValueError("La sección debe ser 'ayer' u 'hoy'.")
                if section == "ayer" and mark not in MARKS:
                    raise ValueError("Una línea de Ayer necesita marca: hecho, pendiente o no_tocado.")
                conn.execute(
                    """INSERT INTO commitments (report_id, section, text, mark, mark_source, monday_url,
                         monday_key, link_status, origin, slack_ts, line_key, manual)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'slack', ?, ?, 1)""",
                    (report_id, section, text, mark if section == "ayer" else None,
                     "manual" if section == "ayer" else None, monday_url, monday_key(monday_url),
                     "con_link" if monday_url else "sin_link", item["slack_ts"], key))
            elif action == "operacion":
                conn.execute("INSERT INTO operation_items (report_id, text, origin, slack_ts, line_key, manual) "
                             "VALUES (?, ?, 'slack', ?, ?, 1)", (report_id, text, item["slack_ts"], key))
            else:
                lvl = int(decision_level) if decision_level not in (None, "") else None
                conn.execute("INSERT INTO blockers (report_id, text, decision_level, origin, slack_ts, line_key, "
                             "manual) VALUES (?, ?, ?, 'slack', ?, ?, 1)",
                             (report_id, text, lvl, item["slack_ts"], key))
            refresh_report(conn, report_id)
        status = "descartado" if action == "descartar" else "resuelto"
        conn.execute("UPDATE review_items SET status = ?, resolution = ?, resolved_at = ?, stale = 0 "
                     "WHERE id = ?", (status, json.dumps(decision), now, item_id))
    streaks.recompute(conn)
    conn.commit()
