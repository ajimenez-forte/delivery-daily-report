"""Resumen de la importación y aprobación antes de lanzar.

    python -m daily_report.summary            # imprime el resumen
    python -m daily_report.summary --aprobar  # registra la aprobación
"""
import argparse
import json
import sys
from datetime import datetime, timezone

from . import config, db


def build_summary(conn):
    q = lambda sql, *a: conn.execute(sql, a).fetchall()
    one = lambda sql, *a: conn.execute(sql, a).fetchone()[0]
    run = conn.execute("SELECT * FROM import_runs ORDER BY id DESC LIMIT 1").fetchone()
    days = {r["format"]: r["n"] for r in q("SELECT format, COUNT(*) n FROM days WHERE origin='slack' GROUP BY format")}
    first_last = conn.execute("SELECT MIN(day), MAX(day) FROM days WHERE origin='slack'").fetchone()
    per_person = [dict(r) for r in q(
        """SELECT p.name AS persona,
                  SUM(r.format = 'libre')  AS libre,
                  SUM(r.format = 'marcas') AS marcas,
                  COUNT(*) AS total
           FROM reports r JOIN people p ON p.id = r.person_id
           WHERE r.origin = 'slack' GROUP BY p.id ORDER BY p.name""")]
    marks = {r["mark"]: r["n"] for r in q(
        "SELECT mark, COUNT(*) n FROM commitments WHERE origin='slack' AND section='ayer' GROUP BY mark")}
    return {
        "ultima_corrida": dict(run) if run else None,
        "dias_importados": {"total": sum(days.values()), "texto_libre": days.get("libre", 0),
                            "con_marcas": days.get("marcas", 0),
                            "desde": first_last[0], "hasta": first_last[1]},
        "reportes_por_persona": per_person,
        "compromisos_con_marca": {
            "total": sum(marks.values()),
            "hecho": marks.get("hecho", 0), "pendiente": marks.get("pendiente", 0),
            "no_tocado": marks.get("no_tocado", 0),
            "marca_por_palabra": one("SELECT COUNT(*) FROM commitments WHERE origin='slack' "
                                     "AND mark_source='palabra'"),
            "corregidos_a_mano": one("SELECT COUNT(*) FROM commitments WHERE origin='slack' AND manual=1 "
                                     "AND section='ayer'"),
        },
        "compromisos_de_hoy": {
            "total": one("SELECT COUNT(*) FROM commitments WHERE origin='slack' AND section='hoy'"),
            "sin_link": one("SELECT COUNT(*) FROM commitments WHERE origin='slack' AND section='hoy' "
                            "AND link_status='sin_link'"),
            "tercer_dia_o_mas": one("SELECT COUNT(*) FROM commitments WHERE origin='slack' AND section='hoy' "
                                    "AND streak_days >= 3"),
        },
        "revision": {
            "lineas_enviadas": one("SELECT COUNT(*) FROM review_items WHERE kind='linea'"),
            "mensajes_enviados": one("SELECT COUNT(*) FROM review_items WHERE kind='mensaje'"),
            "pendientes": one("SELECT COUNT(*) FROM review_items WHERE status='pendiente'"),
            "resueltas": one("SELECT COUNT(*) FROM review_items WHERE status='resuelto'"),
            "descartadas": one("SELECT COUNT(*) FROM review_items WHERE status='descartado'"),
            "cambiaron_en_slack": one("SELECT COUNT(*) FROM review_items WHERE stale=1"),
            "por_motivo": [dict(r) for r in q(
                "SELECT reason AS motivo, COUNT(*) n FROM review_items GROUP BY reason ORDER BY n DESC")],
        },
        "aprobacion": approval_status(conn),
    }


def approval_status(conn):
    run = conn.execute("SELECT id, status FROM import_runs ORDER BY id DESC LIMIT 1").fetchone()
    appr = conn.execute("SELECT * FROM launch_approvals ORDER BY id DESC LIMIT 1").fetchone()
    approved = bool(run and appr and appr["import_run_id"] == run["id"] and run["status"] == "ok")
    if approved:
        # Una corrección a mano después de aprobar obliga a aprobar de nuevo.
        later = conn.execute("SELECT COUNT(*) FROM review_items WHERE resolved_at > ?",
                             (appr["approved_at"],)).fetchone()[0]
        approved = later == 0
    return {"aprobado": approved,
            "aprobado_en": appr["approved_at"] if appr else None,
            "corrida_aprobada": appr["import_run_id"] if appr else None,
            "ultima_corrida": run["id"] if run else None}


def launch_allowed(conn):
    """La app no debe abrir hasta que el admin apruebe la última importación."""
    return approval_status(conn)["aprobado"]


def approve(conn):
    run = conn.execute("SELECT id, status FROM import_runs ORDER BY id DESC LIMIT 1").fetchone()
    if not run or run["status"] != "ok":
        raise ValueError("No hay una importación terminada sin errores para aprobar.")
    summary = build_summary(conn)
    summary.pop("aprobacion")
    conn.execute("INSERT INTO launch_approvals (approved_at, import_run_id, summary_json) VALUES (?, ?, ?)",
                 (datetime.now(timezone.utc).isoformat(timespec="seconds"), run["id"],
                  json.dumps(summary, ensure_ascii=False)))
    conn.commit()


def format_summary(s):
    d, m, h, r = s["dias_importados"], s["compromisos_con_marca"], s["compromisos_de_hoy"], s["revision"]
    out = ["RESUMEN DE IMPORTACIÓN",
           f"Días importados: {d['total']} ({d['desde']} a {d['hasta']}) · "
           f"texto libre {d['texto_libre']} · con marcas {d['con_marcas']}",
           "", "Reportes por persona (libre / marcas / total):"]
    for p in s["reportes_por_persona"]:
        out.append(f"  {p['persona']}: {p['libre']} / {p['marcas']} / {p['total']}")
    out += ["",
            f"Compromisos con marca (Ayer): {m['total']} · ✅ {m['hecho']} · 🔄 {m['pendiente']} · "
            f"⬜ {m['no_tocado']}",
            f"  de esos, marca escrita como palabra: {m['marca_por_palabra']} · corregidos a mano: "
            f"{m['corregidos_a_mano']}",
            f"Compromisos de Hoy: {h['total']} · sin link: {h['sin_link']} · en 3er día o más: "
            f"{h['tercer_dia_o_mas']}",
            "",
            f"Enviado a revisión: {r['lineas_enviadas']} líneas, {r['mensajes_enviados']} mensajes · "
            f"pendientes {r['pendientes']} · resueltas {r['resueltas']} · descartadas {r['descartadas']}"]
    if r["cambiaron_en_slack"]:
        out.append(f"  ⚠ {r['cambiaron_en_slack']} correcciones cuyo mensaje cambió en Slack")
    for x in r["por_motivo"]:
        out.append(f"  {x['n']:>4}  {x['motivo']}")
    a = s["aprobacion"]
    out += ["", "Aprobación: " + (f"APROBADO ({a['aprobado_en']})" if a["aprobado"]
                                   else "PENDIENTE. No lanzar hasta aprobar esta importación.")]
    return "\n".join(out)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=config.DB_PATH)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--aprobar", action="store_true", help="aprueba la última importación para lanzar")
    args = ap.parse_args(argv)
    conn = db.connect(args.db)
    if args.aprobar:
        approve(conn)
    s = build_summary(conn)
    print(json.dumps(s, ensure_ascii=False, indent=2) if args.json else format_summary(s))
    return 0


if __name__ == "__main__":
    sys.exit(main())
