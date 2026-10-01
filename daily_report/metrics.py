"""Carga y cumplimiento por persona.

Todo se lee con la conexión de la app, así que pasa por RLS: un admin ve a
todos, cualquier otro rol solo vería sus propias filas.

Columnas:
  1. Días con reporte / días disponibles. Usa todos los días (libre y marcas).
     Días disponibles = días de Daily en el rango menos el PTO registrado.
  2. Compromisos por día: promedio de compromisos de Hoy en los días que reportó.
  3. Ítems de Ayer hechos sobre total marcados. Sin extras y sin líneas sin
     marca. Una línea sin marca cuenta solo cuando el admin le asigna una.
  4. Ítems sin tocar (⬜) sobre total marcados.
  5. Alertas de tercer día: compromisos que llegaron a su tercer día seguido.
  6. Líneas sin marca: pendientes en la tabla de revisión (Ayer y extras) más
     líneas de Ayer guardadas sin marca.
Las columnas 2 a 6 solo usan días con formato de marcas (o de la app).
"""
import calendar
import csv
import io
from datetime import date, datetime, timedelta

from . import config

COLUMNS = [
    ("persona", "Persona"),
    ("tasa_reporte", "Días con reporte"),
    ("compromisos_por_dia", "Compromisos por día"),
    ("pct_hechos", "Ayer hechos"),
    ("pct_sin_tocar", "Sin tocar"),
    ("alertas_tercer_dia", "Alertas de tercer día"),
    ("sin_marca", "Líneas sin marca"),
]
SORT_KEYS = {k for k, _ in COLUMNS}
DISCLAIMER = ("Todo es autorreportado. Mide cómo reporta cada persona, no cuánto produce. "
              "Una tarea de datos y una llamada de seguimiento pesan lo mismo.")


def current_month(today=None):
    today = today or datetime.now(config.TZ).date()
    last = calendar.monthrange(today.year, today.month)[1]
    return today.replace(day=1), today.replace(day=last)


def _pct(n, d):
    return round(100.0 * n / d, 1) if d else None


def _person_rows(conn, start, end, person_id=None):
    """Una fila por persona con los conteos crudos del rango [start, end]."""
    a, b = start.isoformat(), end.isoformat()
    days = conn.execute("SELECT day, format FROM days WHERE day BETWEEN ? AND ? ORDER BY day", (a, b)).fetchall()
    day_set = {d["day"] for d in days}
    where_p = "AND p.id = ?" if person_id else ""
    extra = (person_id,) if person_id else ()
    people = conn.execute(f"SELECT p.id, p.name FROM people p WHERE TRUE {where_p} ORDER BY p.name", extra).fetchall()

    def per_person(sql, *args):
        return {r[0]: r for r in conn.execute(sql, (a, b, *args))}

    reports = per_person(
        """SELECT r.person_id, COUNT(*) total,
                  SUM(CASE WHEN d.format <> 'libre' THEN 1 ELSE 0 END) estructurados
           FROM reports r JOIN days d ON d.id = r.day_id
           WHERE d.day BETWEEN ? AND ? GROUP BY r.person_id""")
    pto = per_person(
        """SELECT t.person_id, COUNT(*) n FROM pto t JOIN days d ON d.day = t.day
           WHERE d.day BETWEEN ? AND ? GROUP BY t.person_id""")
    hoy = per_person(
        """SELECT r.person_id, COUNT(*) n,
                  SUM(CASE WHEN c.streak_days = 3 THEN 1 ELSE 0 END) tercer_dia
           FROM commitments c JOIN reports r ON r.id = c.report_id JOIN days d ON d.id = r.day_id
           WHERE d.day BETWEEN ? AND ? AND d.format <> 'libre' AND c.section = 'hoy'
           GROUP BY r.person_id""")
    ayer = per_person(
        """SELECT r.person_id,
                  SUM(CASE WHEN c.mark IS NOT NULL THEN 1 ELSE 0 END) marcados,
                  SUM(CASE WHEN c.mark = 'hecho' THEN 1 ELSE 0 END) hechos,
                  SUM(CASE WHEN c.mark = 'no_tocado' THEN 1 ELSE 0 END) sin_tocar,
                  SUM(CASE WHEN c.mark IS NULL THEN 1 ELSE 0 END) sin_marca
           FROM commitments c JOIN reports r ON r.id = c.report_id JOIN days d ON d.id = r.day_id
           WHERE d.day BETWEEN ? AND ? AND d.format <> 'libre' AND c.section = 'ayer' AND c.is_extra = 0
           GROUP BY r.person_id""")
    review = per_person(
        """SELECT ri.person_id, COUNT(*) n FROM review_items ri JOIN days d ON d.day = ri.day
           WHERE d.day BETWEEN ? AND ? AND d.format <> 'libre' AND ri.kind = 'linea'
             AND ri.status = 'pendiente' AND ri.section IN ('ayer', 'extra')
           GROUP BY ri.person_id""")

    out = []
    for p in people:
        pid = p["id"]
        rep = reports.get(pid)
        total = rep["total"] if rep else 0
        structured = (rep["estructurados"] or 0) if rep else 0
        n_pto = pto[pid]["n"] if pid in pto else 0
        available = len(day_set) - n_pto
        h = hoy.get(pid)
        y = ayer.get(pid)
        marked = (y["marcados"] or 0) if y else 0
        out.append({
            "person_id": pid, "persona": p["name"],
            "dias_reporte": total, "dias_disponibles": available, "dias_pto": n_pto,
            "tasa_reporte": _pct(total, available),
            "dias_marcas_reportados": structured,
            "compromisos": h["n"] if h else 0,
            "compromisos_por_dia": round(h["n"] / structured, 1) if h and structured else (0.0 if structured else None),
            "hechos": (y["hechos"] or 0) if y else 0, "marcados": marked,
            "pct_hechos": _pct((y["hechos"] or 0) if y else 0, marked),
            "sin_tocar": (y["sin_tocar"] or 0) if y else 0,
            "pct_sin_tocar": _pct((y["sin_tocar"] or 0) if y else 0, marked),
            "alertas_tercer_dia": (h["tercer_dia"] or 0) if h else 0,
            "sin_marca": ((y["sin_marca"] or 0) if y else 0) + (review[pid]["n"] if pid in review else 0),
        })
    return out, days


def table(conn, start, end, sort="pct_hechos", desc=True):
    rows, days = _person_rows(conn, start, end)
    sort = sort if sort in SORT_KEYS else "pct_hechos"

    def key(r):
        v = r[sort]
        # Los vacíos (sin datos) siempre al final, sin importar la dirección.
        return (v is None, v if not isinstance(v, str) else v.lower())

    rows.sort(key=key)
    if desc:
        present = [r for r in rows if r[sort] is not None][::-1]
        rows = present + [r for r in rows if r[sort] is None]
    libre = [d["day"] for d in days if d["format"] == "libre"]
    return {
        "desde": start.isoformat(), "hasta": end.isoformat(), "dias_en_rango": len(days),
        "orden": sort, "desc": desc, "filas": rows,
        "dias_libre": len(libre),
        "nota_libre": (f"El rango incluye {len(libre)} días en formato libre ({libre[0]} a {libre[-1]}). "
                       "Esos días cuentan solo en la columna de días con reporte." if libre else None),
    }


def weekly(conn, person_id, start, end):
    """Evolución semanal (semanas de lunes a domingo) de las columnas 1, 3 y 4."""
    weeks = []
    cur = start - timedelta(days=start.weekday())
    while cur <= end:
        a, b = max(cur, start), min(cur + timedelta(days=6), end)
        rows, days = _person_rows(conn, a, b, person_id)
        if days and rows:
            r = rows[0]
            weeks.append({"semana": cur.isoformat(), "desde": a.isoformat(), "hasta": b.isoformat(),
                          "dias_libre": sum(1 for d in days if d["format"] == "libre"),
                          **{k: r[k] for k in ("dias_reporte", "dias_disponibles", "dias_pto", "tasa_reporte",
                                               "hechos", "marcados", "pct_hechos", "sin_tocar", "pct_sin_tocar")}})
        cur += timedelta(days=7)
    return weeks


def fmt_days(r):
    s = f"{r['dias_reporte']}/{r['dias_disponibles']}"
    s += f" ({r['tasa_reporte']}%)" if r["tasa_reporte"] is not None else " (-)"
    if r["dias_pto"]:
        s += f" ({r['dias_pto']} {'día' if r['dias_pto'] == 1 else 'días'} de PTO)"
    return s


def fmt_ratio(n, d, pct):
    return f"{n} de {d} ({pct}%)" if pct is not None else "-"


def to_csv(result):
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["persona", "dias_con_reporte", "dias_disponibles", "dias_pto", "pct_dias_reporte",
                "compromisos_por_dia", "ayer_hechos", "ayer_marcados", "pct_hechos",
                "sin_tocar", "pct_sin_tocar", "alertas_tercer_dia", "lineas_sin_marca", "desde", "hasta"])
    for r in result["filas"]:
        w.writerow([r["persona"], r["dias_reporte"], r["dias_disponibles"], r["dias_pto"], r["tasa_reporte"],
                    r["compromisos_por_dia"], r["hechos"], r["marcados"], r["pct_hechos"],
                    r["sin_tocar"], r["pct_sin_tocar"], r["alertas_tercer_dia"], r["sin_marca"],
                    result["desde"], result["hasta"]])
    if result["nota_libre"]:
        w.writerow([])
        w.writerow([result["nota_libre"]])
    w.writerow([])
    w.writerow([DISCLAIMER])
    return buf.getvalue()


def get_note(conn, person_id):
    """Nota privada del usuario de la conexión. RLS solo devuelve la suya."""
    row = conn.execute("SELECT body, updated_at FROM admin_notes WHERE person_id = ? "
                       "AND author_email = app_user_email()", (person_id,)).fetchone()
    return (row["body"], row["updated_at"]) if row else ("", None)


def save_note(conn, person_id, body):
    now = datetime.now(config.TZ).isoformat(timespec="seconds")
    conn.execute(
        """INSERT INTO admin_notes (person_id, author_email, body, updated_at)
           VALUES (?, app_user_email(), ?, ?)
           ON CONFLICT (person_id, author_email) DO UPDATE SET body = excluded.body,
             updated_at = excluded.updated_at""", (person_id, body, now))
    conn.commit()


def parse_range(qs, today=None):
    d0, d1 = current_month(today)
    try:
        start = date.fromisoformat(qs.get("desde") or d0.isoformat())
        end = date.fromisoformat(qs.get("hasta") or d1.isoformat())
    except ValueError:
        start, end = d0, d1
    if end < start:
        start, end = end, start
    return start, end
