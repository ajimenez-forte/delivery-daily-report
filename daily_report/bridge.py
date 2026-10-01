"""Paso de Slack a la app.

La app guarda sus reportes en las mismas tablas (origin='app'), así que:
  - "Ayer" en el primer día de cada persona son los Compromisos de Hoy de
    su último reporte importado.
  - La racha de días seguidos continúa: si un compromiso llevaba 2 días en
    Slack, el primer día en la app es el tercero.
"""
from . import streaks


def yesterday_for(conn, person_id, today):
    """Lista que la persona debe marcar como "Ayer" el día `today` (YYYY-MM-DD).

    Devuelve None si la persona no tiene reportes anteriores.
    """
    rep = conn.execute(
        """SELECT r.*, d.day FROM reports r JOIN days d ON d.id = r.day_id
           WHERE r.person_id = ? AND d.day < ? ORDER BY d.day DESC LIMIT 1""",
        (person_id, today)).fetchone()
    if not rep:
        return None
    items = conn.execute(
        """SELECT id, text, grp, monday_url, monday_key, link_status, streak_days, origin, slack_ts
           FROM commitments WHERE report_id = ? AND section = 'hoy' ORDER BY id""", (rep["id"],)).fetchall()
    return {"report_id": rep["id"], "day": rep["day"], "origin": rep["origin"], "format": rep["format"],
            # En texto libre no hay compromisos separados; se muestra el texto.
            "raw_text": rep["raw_text"] if rep["format"] == "libre" else None,
            "commitments": [dict(i) for i in items]}


def streak_preview(conn, person_id, today, text, monday_url=None):
    """Días seguidos que tendría un compromiso nuevo, antes de guardarlo.

    Sirve para avisar en el formulario de la app cuando llega al tercer día.
    """
    from .parser import monday_key
    prev = yesterday_for(conn, person_id, today)
    if not prev or not prev["commitments"]:
        return 1
    new = {"id": 0, "text": text, "monday_key": monday_key(monday_url)}
    pairs = streaks.match_previous([new], prev["commitments"])
    p = pairs.get(0)
    return p["streak_days"] + 1 if p else 1
