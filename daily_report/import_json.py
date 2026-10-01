"""Importa la historia del Daily desde el archivo JSON ya extraído de Slack.

Uso:
    python -m daily_report.import_json [--file daily_historia_....json]

Respeta la estructura del archivo:
  - personas, pto, dias (formato 'libre' o 'marcas'), punto_de_partida.
  - Las líneas con marca null van a la tabla de revisión, sin marca.
  - Cada registro guarda origin='slack' y el ts del Disparador del día
    (slack_ts_disparador) para poder abrir el hilo original.

Se puede correr las veces que sea: todo se guarda con claves estables, así
que no duplica, y las correcciones hechas a mano se conservan.
"""
import argparse
import hashlib
import json
import sys
from collections import Counter
from datetime import datetime, timezone

from . import config, db, streaks
from .parser import monday_key, normalize

MARKS = {"hecho": "hecho", "pendiente": "pendiente", "no_lo_toque": "no_tocado"}


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class _Keys:
    """Clave estable por línea: persona + sección + hash del texto + aparición."""

    def __init__(self, prefix):
        self.prefix, self.seen = prefix, Counter()

    def __call__(self, section, text):
        h = hashlib.sha1((normalize(text) or text).encode()).hexdigest()[:12]
        base = f"{self.prefix}|{section}|{h}"
        n = self.seen[base]
        self.seen[base] += 1
        return f"{base}-{n}"


def _upsert_person(conn, p):
    row = conn.execute("SELECT id FROM people WHERE code = ? OR slack_user_id = ?",
                       (p["codigo"], p.get("slack_id"))).fetchone()
    if row:
        conn.execute("UPDATE people SET code = ?, slack_user_id = ?, name = ? WHERE id = ?",
                     (p["codigo"], p.get("slack_id"), p["nombre"], row["id"]))
        return row["id"]
    return conn.insert("INSERT INTO people (slack_user_id, code, name) VALUES (?, ?, ?)",
                        (p.get("slack_id"), p["codigo"], p["nombre"]))


def _upsert_day(conn, d):
    row = conn.execute("SELECT id FROM days WHERE day = ?", (d["fecha"],)).fetchone()
    if row:
        conn.execute("UPDATE days SET origin = 'slack', slack_ts = ?, format = ? WHERE id = ?",
                     (d["slack_ts_disparador"], d["formato"], row["id"]))
        return row["id"]
    return conn.insert("INSERT INTO days (day, origin, slack_ts, format) VALUES (?, 'slack', ?, ?)",
                        (d["fecha"], d["slack_ts_disparador"], d["formato"]))


def _upsert_report(conn, day_id, person_id, ts, fmt, raw_text, b_status, b_note):
    has_field = int(b_status not in (None, "campo_ausente"))
    has_blockers = int(b_status not in (None, "campo_ausente", "sin_bloqueos"))
    vals = (ts, fmt, raw_text, 0 if fmt == "libre" else 1, has_field, has_blockers, b_status, b_note)
    row = conn.execute("SELECT id FROM reports WHERE day_id = ? AND person_id = ?",
                       (day_id, person_id)).fetchone()
    if row:
        conn.execute("""UPDATE reports SET origin = 'slack', slack_ts = ?, format = ?, raw_text = ?,
                          counts_for_rate = 1, counts_for_compliance = ?, has_blockers_field = ?,
                          has_blockers = ?, blockers_status = ?, blockers_note = ? WHERE id = ?""",
                     (*vals, row["id"]))
        return row["id"]
    return conn.insert(
        """INSERT INTO reports (day_id, person_id, origin, slack_ts, format, raw_text, counts_for_rate,
             counts_for_compliance, has_blockers_field, has_blockers, blockers_status, blockers_note)
           VALUES (?, ?, 'slack', ?, ?, ?, 1, ?, ?, ?, ?, ?)""", (day_id, person_id, *vals))


def _sync(conn, table, report_id, ts, rows, cols):
    """Deja en `table` exactamente estas filas no manuales del reporte."""
    keys = [r["line_key"] for r in rows]
    conn.execute(f"DELETE FROM {table} WHERE report_id = ? AND manual = 0 AND line_key <> ALL(?::text[])",
                 (report_id, keys))
    sets = ", ".join(f"{c} = excluded.{c}" for c in cols)
    for r in rows:
        conn.execute(
            f"""INSERT INTO {table} (report_id, origin, slack_ts, line_key, {", ".join(cols)})
                VALUES (?, 'slack', ?, ?, {", ".join("?" * len(cols))})
                ON CONFLICT (slack_ts, line_key) DO UPDATE SET report_id = excluded.report_id, {sets}""",
            (report_id, ts, r["line_key"], *[r[c] for c in cols]))


def _sync_review(conn, report_id, ts, day, person_id, items):
    keys = {i["line_key"] for i in items}
    for row in conn.execute("SELECT id, line_key, status FROM review_items WHERE report_id = ?",
                            (report_id,)).fetchall():
        if row["line_key"] in keys:
            continue
        if row["status"] == "pendiente":
            conn.execute("DELETE FROM review_items WHERE id = ?", (row["id"],))
        else:
            conn.execute("UPDATE review_items SET stale = 1 WHERE id = ?", (row["id"],))
    for i in items:
        row = conn.execute("SELECT id, status FROM review_items WHERE slack_ts = ? AND line_key = ?",
                           (ts, i["line_key"])).fetchone()
        if row:
            if row["status"] == "pendiente":
                conn.execute("UPDATE review_items SET raw_text = ?, reason = ?, section = ?, monday_url = ?, "
                             "note = ?, report_id = ?, stale = 0 WHERE id = ?",
                             (i["text"], i["reason"], i["section"], i["monday_url"], i["note"], report_id,
                              row["id"]))
            else:
                conn.execute("UPDATE review_items SET stale = 0 WHERE id = ?", (row["id"],))
            continue
        conn.execute(
            """INSERT INTO review_items (kind, slack_ts, line_key, day, person_id, report_id, section,
                 raw_text, reason, monday_url, note)
               VALUES ('linea', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (ts, i["line_key"], day, person_id, report_id, i["section"], i["text"], i["reason"],
             i["monday_url"], i["note"]))


def _commitment(key, section, item, is_extra=False):
    url = item.get("link_monday") or None
    raw_mark = item.get("marca") if section == "ayer" else None
    return {"line_key": key(("extra" if is_extra else section), item["texto"]), "section": section,
            "text": item["texto"].strip(), "grp": None,
            "mark": MARKS.get(raw_mark) if raw_mark else None,
            "mark_source": "archivo" if raw_mark else None,
            "is_extra": int(is_extra), "monday_url": url, "monday_key": monday_key(url),
            "link_status": "con_link" if url else "sin_link",
            "note": item.get("nota"), "due_date": item.get("fecha_cierre_declarada"),
            "starting_point": 0, "file_streak": None}


def _ingest_structured(conn, report_id, ts, day, person_id, code, r):
    key = _Keys(code)
    commitments, review = [], []
    for section, is_extra in (("ayer", False), ("extras", True)):
        for item in r.get(section, []):
            c = _commitment(key, "ayer", item, is_extra)
            if item.get("marca") is None:
                # Sin marca segura: a revisión, sin asignarle marca.
                review.append({"line_key": c["line_key"], "section": "extra" if is_extra else "ayer",
                               "text": c["text"], "monday_url": c["monday_url"], "note": c["note"],
                               "reason": c["note"] or "sin marca"})
                continue
            if item["marca"] not in MARKS:
                review.append({"line_key": c["line_key"], "section": "extra" if is_extra else "ayer",
                               "text": c["text"], "monday_url": c["monday_url"], "note": c["note"],
                               "reason": f"marca desconocida en el archivo: {item['marca']}"})
                continue
            commitments.append(c)
    for item in r.get("compromisos", []):
        commitments.append(_commitment(key, "hoy", item))
    ops = []
    if (r.get("operacion") or "").strip():
        ops.append({"line_key": key("operacion", r["operacion"]), "text": r["operacion"].strip()})
    blockers = []
    b = r.get("bloqueos") or {}
    if b.get("estado") not in (None, "campo_ausente", "sin_bloqueos"):
        blockers.append({"line_key": key("bloqueos", b.get("nota") or b["estado"]),
                         "text": b.get("nota") or b["estado"], "decision_level": b.get("nivel")})
    _sync(conn, "commitments", report_id, ts, commitments,
          ["section", "text", "grp", "mark", "mark_source", "is_extra", "monday_url", "monday_key",
           "link_status", "note", "due_date"])
    _sync(conn, "operation_items", report_id, ts, ops, ["text"])
    _sync(conn, "blockers", report_id, ts, blockers, ["text", "decision_level"])
    _sync_review(conn, report_id, ts, day, person_id, review)


def _free_text(r):
    parts = [("Ayer", r.get("ayer_texto")), ("Hoy", r.get("hoy_texto")), ("Bloqueos", r.get("bloqueos_texto"))]
    return "\n".join(f"{k}: {v}" for k, v in parts if v)


def _apply_starting_point(conn, person_id, sp, warnings):
    """Marca qué compromisos ve la persona como "Ayer" el primer día en la app."""
    last = conn.execute(
        """SELECT r.id, d.day, r.slack_ts FROM reports r JOIN days d ON d.id = r.day_id
           WHERE r.person_id = ? AND d.day = ?""", (person_id, sp["fecha_ultimo_reporte"])).fetchone()
    if not last:
        warnings.append(f"{sp['nombre']}: no hay reporte el {sp['fecha_ultimo_reporte']} "
                        "(fecha_ultimo_reporte del punto de partida)")
        return
    conn.execute("UPDATE commitments SET starting_point = 0, file_streak = NULL WHERE report_id IN "
                 "(SELECT id FROM reports WHERE person_id = ?)", (person_id,))
    pool = [dict(c) for c in conn.execute(
        "SELECT id, text, monday_url FROM commitments WHERE report_id = ? AND section = 'hoy' ORDER BY id",
        (last["id"],))]
    used = set()
    for item in sp["ayer_en_la_app"]:
        url = item.get("link_monday") or None
        match = next((c for c in pool if c["id"] not in used and c["text"] == item["texto"].strip()
                      and (c["monday_url"] or None) == url), None)
        if match is None:
            # Está en el punto de partida pero no en el último reporte: se agrega a ese reporte.
            key = _Keys(f"pdp|{person_id}")
            c = _commitment(key, "hoy", item)
            conn.execute(
                """INSERT INTO commitments (report_id, section, text, monday_url, monday_key, link_status,
                     due_date, origin, slack_ts, line_key, manual)
                   VALUES (?, 'hoy', ?, ?, ?, ?, ?, 'slack', ?, ?, 0)
                   ON CONFLICT (slack_ts, line_key) DO UPDATE SET text = excluded.text""",
                (last["id"], c["text"], url, c["monday_key"], c["link_status"], c["due_date"],
                 last["slack_ts"], c["line_key"]))
            match_id = conn.execute("SELECT id FROM commitments WHERE slack_ts = ? AND line_key = ?",
                                    (last["slack_ts"], c["line_key"])).fetchone()["id"]
            warnings.append(f"{sp['nombre']}: «{c['text']}» está en el punto de partida pero no en el "
                            "último reporte; se agregó")
        else:
            match_id = match["id"]
        used.add(match_id)
        conn.execute("UPDATE commitments SET starting_point = 1, file_streak = ? WHERE id = ?",
                     (item.get("dias_seguidos_al_corte"), match_id))
    for c in pool:
        if c["id"] not in used:
            warnings.append(f"{sp['nombre']}: «{c['text']}» está en el último reporte pero no en el "
                            "punto de partida; no aparece como Ayer")


def run_import(conn, data, source="archivo", log=print):
    if config.IMPORT_DISABLED:
        raise SystemExit("Importación apagada (DAILY_IMPORT_DISABLED=1).")
    run_id = conn.insert("INSERT INTO import_runs (started_at, status) VALUES (?, 'corriendo')",
                          (_now(),))
    conn.commit()
    warnings = []
    try:
        people = {p["codigo"]: _upsert_person(conn, p) for p in data["personas"]}
        conn.execute("DELETE FROM pto WHERE origin = 'slack'")
        for entry in data.get("pto", []):
            for day in entry["fechas"]:
                conn.execute("INSERT INTO pto (person_id, day, origin) VALUES (?, ?, 'slack') ON CONFLICT DO NOTHING",
                             (people[entry["persona"]], day))
        for d in data["dias"]:
            day_id = _upsert_day(conn, d)
            ts = d["slack_ts_disparador"]
            for r in d["reportes"]:
                code = r["persona"]
                if code not in people:
                    warnings.append(f"{d['fecha']}: persona desconocida {code}, se omitió")
                    continue
                pid = people[code]
                if d["formato"] == "libre":
                    _upsert_report(conn, day_id, pid, ts, "libre", _free_text(r), None, None)
                    continue
                b = r.get("bloqueos") or {}
                rid = _upsert_report(conn, day_id, pid, ts, "marcas", None, b.get("estado"), b.get("nota"))
                _ingest_structured(conn, rid, ts, d["fecha"], pid, code, r)
            log(f"  {d['fecha']} ({d['formato']}) listo")
        for sp in data.get("punto_de_partida", []):
            _apply_starting_point(conn, people[sp["persona"]], sp, warnings)
        streaks.recompute(conn)
        stats = {"fuente": source, "generado": data.get("meta", {}).get("generado"), "avisos": warnings}
        conn.execute("UPDATE import_runs SET finished_at = ?, status = 'ok', stats_json = ? WHERE id = ?",
                     (_now(), json.dumps(stats, ensure_ascii=False), run_id))
        conn.commit()
    except BaseException:
        conn.rollback()
        conn.execute("UPDATE import_runs SET finished_at = ?, status = 'error' WHERE id = ?", (_now(), run_id))
        conn.commit()
        raise
    return run_id


def load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def main(argv=None):
    from .summary import build_summary, format_summary
    ap = argparse.ArgumentParser(description="Importa la historia del Daily desde el archivo JSON.")
    ap.add_argument("--db", default=None, help="URL de Postgres (por defecto DATABASE_URL)")
    ap.add_argument("--file", default=config.HISTORY_FILE)
    args = ap.parse_args(argv)
    conn = db.connect(args.db)
    db.migrate(conn)
    data = load(args.file)
    run_import(conn, data, source=args.file)
    print()
    print(format_summary(build_summary(conn, data)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
