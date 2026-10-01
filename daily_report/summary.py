"""Resumen de la importación y aprobación antes de lanzar.

    python -m daily_report.summary            # imprime el resumen
    python -m daily_report.summary --aprobar  # registra la aprobación
"""
import argparse
import json
import os
import sys
from datetime import datetime, timezone

from . import config, db


def build_summary(conn, data=None):
    """Resumen de lo importado. Con `data` (el JSON) lo compara contra su "resumen"."""
    q = lambda sql, *a: conn.execute(sql, a).fetchall()
    one = lambda sql, *a: conn.execute(sql, a).fetchone()[0]
    run = conn.execute("SELECT * FROM import_runs ORDER BY id DESC LIMIT 1").fetchone()
    days = {r["format"]: r["n"] for r in q("SELECT format, COUNT(*) n FROM days WHERE origin='slack' GROUP BY format")}
    first_last = conn.execute("SELECT MIN(day), MAX(day) FROM days WHERE origin='slack'").fetchone()
    per_person = []
    for p in q("SELECT id, name FROM people ORDER BY name"):
        rep = conn.execute(
            """SELECT SUM(CASE WHEN r.format='libre' THEN 1 ELSE 0 END) libre, SUM(CASE WHEN r.format='marcas' THEN 1 ELSE 0 END) marcas, COUNT(*) total
               FROM reports r WHERE r.origin='slack' AND r.person_id=?""", (p["id"],)).fetchone()
        pto = one("""SELECT COUNT(*) FROM pto t JOIN days d ON d.day = t.day
                     WHERE t.person_id = ? AND d.origin = 'slack'""", p["id"])
        workdays = sum(days.values()) - pto
        marks = {r["mark"]: r["n"] for r in q(
            """SELECT c.mark, COUNT(*) n FROM commitments c JOIN reports r ON r.id = c.report_id
               WHERE r.person_id = ? AND c.origin='slack' AND c.section='ayer' AND c.is_extra=0
               GROUP BY c.mark""", p["id"])}
        to_review = one("""SELECT COUNT(*) FROM review_items WHERE person_id = ? AND kind='linea'
                           AND section='ayer'""", p["id"])
        per_person.append({
            "persona": p["name"], "libre": rep["libre"] or 0, "marcas": rep["marcas"] or 0,
            "total": rep["total"], "dias_pto": pto, "dias_habiles_sin_pto": workdays,
            "tasa_reporte_pct": round(100 * rep["total"] / workdays, 1) if workdays else None,
            "ayer": {"hecho": marks.get("hecho", 0), "pendiente": marks.get("pendiente", 0),
                     "no_tocado": marks.get("no_tocado", 0), "sin_marca": to_review},
            "ayer_en_la_app": one("""SELECT COUNT(*) FROM commitments c JOIN reports r ON r.id = c.report_id
                                     WHERE r.person_id = ? AND c.starting_point = 1""", p["id"]),
        })
    marks = {(r["is_extra"], r["mark"]): r["n"] for r in q(
        """SELECT is_extra, mark, COUNT(*) n FROM commitments WHERE origin='slack' AND section='ayer'
           GROUP BY is_extra, mark""")}
    mk = lambda extra: {"hecho": marks.get((extra, "hecho"), 0), "pendiente": marks.get((extra, "pendiente"), 0),
                        "no_tocado": marks.get((extra, "no_tocado"), 0)}
    streak_diff = [dict(r) for r in q(
        """SELECT p.name AS persona, c.text, c.monday_url, c.file_streak AS archivo, c.streak_days AS app
           FROM commitments c JOIN reports r ON r.id = c.report_id JOIN people p ON p.id = r.person_id
           WHERE c.starting_point = 1 AND c.file_streak IS NOT NULL AND c.file_streak != c.streak_days
           ORDER BY p.name, c.id""")]
    s = {
        "ultima_corrida": dict(run) if run else None,
        "avisos": (json.loads(run["stats_json"]).get("avisos", []) if run and run["stats_json"] else []),
        "dias_importados": {"total": sum(days.values()), "texto_libre": days.get("libre", 0),
                            "con_marcas": days.get("marcas", 0),
                            "desde": first_last[0], "hasta": first_last[1]},
        "reportes_por_persona": per_person,
        "compromisos_con_marca": {
            "ayer": mk(0), "extras": mk(1),
            "total": sum(marks.values()),
            "corregidos_a_mano": one("SELECT COUNT(*) FROM commitments WHERE origin='slack' AND manual=1 "
                                     "AND section='ayer'"),
        },
        "compromisos_de_hoy": {
            "total": one("SELECT COUNT(*) FROM commitments WHERE origin='slack' AND section='hoy'"),
            "sin_link": one("SELECT COUNT(*) FROM commitments WHERE origin='slack' AND section='hoy' "
                            "AND link_status='sin_link'"),
            "con_fecha_cierre": one("SELECT COUNT(*) FROM commitments WHERE origin='slack' AND section='hoy' "
                                    "AND due_date IS NOT NULL"),
            "tercer_dia_o_mas": one("SELECT COUNT(*) FROM commitments WHERE origin='slack' AND section='hoy' "
                                    "AND streak_days >= 3"),
        },
        "punto_de_partida": {
            "compromisos": one("SELECT COUNT(*) FROM commitments WHERE starting_point = 1"),
            "racha_distinta_al_archivo": streak_diff,
        },
        "revision": {
            "lineas_enviadas": one("SELECT COUNT(*) FROM review_items WHERE kind='linea'"),
            "mensajes_enviados": one("SELECT COUNT(*) FROM review_items WHERE kind='mensaje'"),
            "pendientes": one("SELECT COUNT(*) FROM review_items WHERE status='pendiente'"),
            "resueltas": one("SELECT COUNT(*) FROM review_items WHERE status='resuelto'"),
            "descartadas": one("SELECT COUNT(*) FROM review_items WHERE status='descartado'"),
            "cambiaron_en_origen": one("SELECT COUNT(*) FROM review_items WHERE stale=1"),
        },
        "aprobacion": approval_status(conn),
    }
    if data:
        s["contra_archivo"] = compare_with_file(s, data)
    return s


def compare_with_file(s, data):
    """Diferencias entre lo importado y el bloque "resumen" del archivo."""
    ref = data.get("resumen", {})
    diffs = []
    chk = lambda what, mine, theirs: diffs.append(f"{what}: importado {mine}, archivo {theirs}") \
        if theirs is not None and mine != theirs else None
    chk("días importados", s["dias_importados"]["total"], ref.get("dias_importados"))
    chk("días texto libre", s["dias_importados"]["texto_libre"], ref.get("dias_texto_libre"))
    chk("días con marcas", s["dias_importados"]["con_marcas"], ref.get("dias_con_marcas"))
    chk("líneas a revisión", s["revision"]["lineas_enviadas"], ref.get("lineas_a_revision"))
    mine = {p["persona"]: p for p in s["reportes_por_persona"]}
    for name, r in ref.get("por_persona", {}).items():
        p = mine.get(name)
        if not p:
            diffs.append(f"{name}: está en el resumen del archivo y no se importó")
            continue
        chk(f"{name} días reportados", p["total"], r.get("dias_reportados"))
        chk(f"{name} días PTO", p["dias_pto"], r.get("dias_pto_en_periodo"))
        chk(f"{name} tasa de reporte", p["tasa_reporte_pct"], r.get("tasa_reporte_pct"))
        la = r.get("lineas_ayer", {})
        for k_file, k_mine in (("hecho", "hecho"), ("pendiente", "pendiente"),
                               ("no_lo_toque", "no_tocado"), ("sin_marca", "sin_marca")):
            chk(f"{name} Ayer {k_file}", p["ayer"][k_mine], la.get(k_file, 0))
    return diffs


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
    d, m, h, r, sp = (s["dias_importados"], s["compromisos_con_marca"], s["compromisos_de_hoy"],
                      s["revision"], s["punto_de_partida"])
    out = ["RESUMEN DE IMPORTACIÓN",
           f"Días importados: {d['total']} ({d['desde']} a {d['hasta']}) · "
           f"texto libre {d['texto_libre']} · con marcas {d['con_marcas']}",
           "", "Reportes por persona:",
           f"  {'Persona':<24}{'libre':>6}{'marcas':>7}{'total':>6}{'PTO':>5}{'hábiles':>8}{'tasa':>7}"
           f"{'✅':>5}{'🔄':>4}{'⬜':>4}{'rev':>5}{'Ayer app':>9}"]
    for p in s["reportes_por_persona"]:
        a = p["ayer"]
        out.append(f"  {p['persona']:<24}{p['libre']:>6}{p['marcas']:>7}{p['total']:>6}{p['dias_pto']:>5}"
                   f"{p['dias_habiles_sin_pto']:>8}{str(p['tasa_reporte_pct']) + '%':>7}"
                   f"{a['hecho']:>5}{a['pendiente']:>4}{a['no_tocado']:>4}{a['sin_marca']:>5}"
                   f"{p['ayer_en_la_app']:>9}")
    ay, ex = m["ayer"], m["extras"]
    out += ["",
            f"Compromisos con marca: {m['total']}",
            f"  Ayer:   ✅ {ay['hecho']} · 🔄 {ay['pendiente']} · ⬜ {ay['no_tocado']}",
            f"  Extras: ✅ {ex['hecho']} · 🔄 {ex['pendiente']} · ⬜ {ex['no_tocado']}",
            f"  corregidos a mano: {m['corregidos_a_mano']}",
            f"Compromisos de Hoy: {h['total']} · sin link: {h['sin_link']} · con fecha de cierre: "
            f"{h['con_fecha_cierre']} · en 3er día o más: {h['tercer_dia_o_mas']}",
            "",
            f"Enviado a revisión: {r['lineas_enviadas']} líneas, {r['mensajes_enviados']} mensajes · "
            f"pendientes {r['pendientes']} · resueltas {r['resueltas']} · descartadas {r['descartadas']}",
            "",
            f"Punto de partida (\"Ayer\" el primer día en la app): {sp['compromisos']} compromisos"]
    if sp["racha_distinta_al_archivo"]:
        out.append("  Días seguidos distintos a dias_seguidos_al_corte del archivo (link + texto vs solo link):")
        for x in sp["racha_distinta_al_archivo"]:
            out.append(f"    {x['persona']}: «{x['text'][:60]}» archivo {x['archivo']} → importado {x['app']}")
    if s.get("avisos"):
        out += ["", "Avisos de la importación:"] + [f"  - {w}" for w in s["avisos"]]
    if "contra_archivo" in s:
        out += ["", "Comparación con el bloque \"resumen\" del archivo:"]
        out += [f"  - {x}" for x in s["contra_archivo"]] or ["  sin diferencias"]
    a = s["aprobacion"]
    out += ["", "Aprobación: " + (f"APROBADO ({a['aprobado_en']})" if a["aprobado"]
                                   else "PENDIENTE. No lanzar hasta aprobar esta importación.")]
    return "\n".join(out)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=None, help="URL de Postgres (por defecto DATABASE_URL)")
    ap.add_argument("--file", default=config.HISTORY_FILE, help="archivo de historia para comparar")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--aprobar", action="store_true", help="aprueba la última importación para lanzar")
    args = ap.parse_args(argv)
    conn = db.connect(args.db)
    db.migrate(conn)
    if args.aprobar:
        approve(conn)
    data = None
    if args.file and os.path.exists(args.file):
        with open(args.file, encoding="utf-8") as f:
            data = json.load(f)
    s = build_summary(conn, data)
    print(json.dumps(s, ensure_ascii=False, indent=2) if args.json else format_summary(s))
    return 0


if __name__ == "__main__":
    sys.exit(main())
