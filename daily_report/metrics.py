"""Carga y cumplimiento por persona.

El cálculo vive en SQL (supabase/migrations/20261001000300_calculo.sql). Este
módulo solo lo llama y da formato. Las funciones SQL son SECURITY INVOKER: un
admin ve a todos y cualquier otro usuario solo sus propias filas.

Columnas:
  1. Días con reporte / días disponibles. Usa todos los días (libre y marcas).
     Días disponibles = días hábiles de la persona (lunes a viernes, sin
     festivos de su país ni días no hábiles de Forte) sin PTO, desde el primer
     Daily y ya cerrados (11:30 am, hora de Bogotá).
  2. Compromisos por día: promedio de compromisos de Hoy en los días que reportó.
  3. Ítems de Ayer hechos sobre total marcados. Sin extras y sin líneas sin
     marca. Una línea sin marca cuenta solo cuando el admin le asigna una.
  4. Ítems sin tocar (⬜) sobre total marcados.
  5. Alertas de tercer día: compromisos que llegaron a su tercer día seguido.
  6. Líneas sin marca: pendientes en la tabla de revisión (Ayer y extras) más
     líneas de Ayer guardadas sin marca.
Las columnas 2 a 6 solo usan días con formato de marcas (o de la app).
"""
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


def last_30_days(today=None):
    """Rango por defecto: los últimos 30 días, contando hoy."""
    today = today or datetime.now(config.TZ).date()
    return today - timedelta(days=29), today


def _person_rows(conn, start, end, person_id=None, now=None):
    """Filas de public.carga_cumplimiento (el cálculo vive en SQL). RLS filtra."""
    sql = "SELECT * FROM carga_cumplimiento(?::date, ?::date" + (", ?::timestamptz)" if now else ")")
    args = [start.isoformat(), end.isoformat()] + ([now.isoformat()] if now else [])
    if person_id:
        sql += " WHERE person_id = ?"
        args.append(person_id)
    rows = [dict(r) for r in conn.execute(sql + " ORDER BY persona", args)]
    days = conn.execute("SELECT day, format FROM days WHERE day BETWEEN ? AND ? ORDER BY day",
                        (start.isoformat(), end.isoformat())).fetchall()
    return rows, days


def table(conn, start, end, sort="pct_hechos", desc=True, now=None):
    rows, days = _person_rows(conn, start, end, now=now)
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


def weekly(conn, person_id, start, end, now=None):
    """Evolución semanal (lunes a domingo) de las columnas 1, 3 y 4. Cálculo en SQL."""
    sql = "SELECT * FROM evolucion_semanal(?, ?::date, ?::date" + (", ?::timestamptz)" if now else ")")
    args = [person_id, start.isoformat(), end.isoformat()] + ([now.isoformat()] if now else [])
    out = []
    for r in conn.execute(sql, args):
        w = dict(r)
        for k in ("semana", "desde", "hasta"):
            w[k] = w[k].isoformat()
        out.append(w)
    return out


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
    d0, d1 = last_30_days(today)
    try:
        start = date.fromisoformat(qs.get("desde") or d0.isoformat())
        end = date.fromisoformat(qs.get("hasta") or d1.isoformat())
    except ValueError:
        start, end = d0, d1
    if end < start:
        start, end = end, start
    return start, end
