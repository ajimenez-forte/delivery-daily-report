"""Importa la historia del Daily directamente desde Slack.

DESACTIVADO. La historia ahora viene del archivo JSON (ver import_json.py).
Se deja aquí por si se necesita más adelante. Para usarlo:
    DAILY_SLACK_IMPORT_ENABLED=1 SLACK_READONLY_TOKEN=xoxb-... python -m daily_report.importer

Uso original:
    SLACK_READONLY_TOKEN=xoxb-... python -m daily_report.importer

Lee el canal, toma cada mensaje "Daily Delivery —" del dueño del canal y las
respuestas de su hilo. Nunca escribe en Slack. Se puede correr las veces que
sea: todo se guarda por el ts del mensaje original, así que no duplica, y las
correcciones hechas a mano en la tabla de revisión se conservan.
"""
import argparse
import hashlib
import json
import os
import re
import sys
from datetime import datetime, time as dtime, timezone

from . import config, db, streaks
from .parser import looks_like_free_report, parse_structured, slack_to_text

_LEADING_NOISE = re.compile(r"^(?:\s|:[a-z0-9_+\-]+:|[_*~]|[^\w\s])*", re.IGNORECASE)


def _title(text):
    """Primer renglón sin emojis ni formato iniciales."""
    first = slack_to_text(text).strip().splitlines()[0] if (text or "").strip() else ""
    return _LEADING_NOISE.sub("", first).strip()


def is_daily_parent(msg):
    return _title(msg.get("text", "")).startswith(config.DAILY_PREFIX)


def is_bulletin(msg):
    return _title(msg.get("text", "")).startswith(config.BULLETIN_PREFIX)


def ts_to_day(ts):
    return datetime.fromtimestamp(float(ts), tz=timezone.utc).astimezone(config.TZ).date()


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def load_people_file(path):
    if path and os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return {}


def _person(conn, msg, people_map):
    uid = msg["user"]
    prof = msg.get("user_profile") or {}
    name = people_map.get(uid) or prof.get("real_name") or prof.get("display_name") or uid
    row = conn.execute("SELECT id, name FROM people WHERE slack_user_id = ?", (uid,)).fetchone()
    if row:
        if row["name"] == uid and name != uid:
            conn.execute("UPDATE people SET name = ? WHERE id = ?", (name, row["id"]))
        return row["id"]
    return conn.execute("INSERT INTO people (slack_user_id, name) VALUES (?, ?)", (uid, name)).lastrowid


def _upsert_day(conn, day, ts, fmt):
    row = conn.execute("SELECT id, slack_ts FROM days WHERE day = ?", (day.isoformat(),)).fetchone()
    if row:
        if row["slack_ts"] is None or float(ts) < float(row["slack_ts"]):
            conn.execute("UPDATE days SET slack_ts = ? WHERE id = ?", (ts, row["id"]))
        return row["id"]
    return conn.execute("INSERT INTO days (day, origin, slack_ts, format) VALUES (?, 'slack', ?, ?)",
                        (day.isoformat(), ts, fmt)).lastrowid


def _upsert_report(conn, day_id, person_id, ts, fmt):
    row = conn.execute("SELECT id, slack_ts FROM reports WHERE day_id = ? AND person_id = ?",
                       (day_id, person_id)).fetchone()
    if row:
        if row["slack_ts"] is None or float(ts) < float(row["slack_ts"]):
            conn.execute("UPDATE reports SET slack_ts = ? WHERE id = ?", (ts, row["id"]))
        return row["id"]
    return conn.execute(
        """INSERT INTO reports (day_id, person_id, origin, slack_ts, format, counts_for_rate,
                                counts_for_compliance)
           VALUES (?, ?, 'slack', ?, ?, 1, ?)""",
        (day_id, person_id, ts, fmt, 0 if fmt == "libre" else 1)).lastrowid


def _upsert_review(conn, kind, ts, line_key, day, person_id, section, raw, reason):
    row = conn.execute("SELECT id, status FROM review_items WHERE slack_ts = ? AND line_key = ?",
                       (ts, line_key)).fetchone()
    if row:
        if row["status"] == "pendiente":
            conn.execute("UPDATE review_items SET raw_text = ?, reason = ?, section = ?, stale = 0 "
                         "WHERE id = ?", (raw, reason, section, row["id"]))
        else:
            conn.execute("UPDATE review_items SET stale = 0 WHERE id = ?", (row["id"],))
        return row
    conn.execute(
        """INSERT INTO review_items (kind, slack_ts, line_key, day, person_id, section, raw_text, reason)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (kind, ts, line_key, day.isoformat(), person_id, section, raw, reason))
    return None


def _sync_rows(conn, table, ts, report_id, rows, cols):
    keys = [r["line_key"] for r in rows]
    marks = ",".join("?" * len(keys))
    if keys:
        conn.execute(f"DELETE FROM {table} WHERE slack_ts = ? AND manual = 0 AND line_key NOT IN ({marks})",
                     (ts, *keys))
    else:
        conn.execute(f"DELETE FROM {table} WHERE slack_ts = ? AND manual = 0", (ts,))
    for r in rows:
        vals = [r[c] for c in cols]
        sets = ", ".join(f"{c} = excluded.{c}" for c in cols)
        conn.execute(
            f"""INSERT INTO {table} (report_id, origin, slack_ts, line_key, {", ".join(cols)})
                VALUES (?, 'slack', ?, ?, {", ".join("?" * len(cols))})
                ON CONFLICT (slack_ts, line_key) DO UPDATE SET report_id = excluded.report_id, {sets}""",
            (report_id, ts, r["line_key"], *vals))


def _sync_review_lines(conn, ts, day, person_id, items):
    keys = {i["line_key"] for i in items}
    for row in conn.execute("SELECT id, line_key, status FROM review_items "
                            "WHERE slack_ts = ? AND kind = 'linea'", (ts,)).fetchall():
        if row["line_key"] in keys:
            continue
        if row["status"] == "pendiente":
            conn.execute("DELETE FROM review_items WHERE id = ?", (row["id"],))
        else:
            # Ya se corrigió a mano, pero el mensaje cambió en Slack. Se avisa.
            conn.execute("UPDATE review_items SET stale = 1 WHERE id = ?", (row["id"],))
    for i in items:
        _upsert_review(conn, "linea", ts, i["line_key"], day, person_id, i["section"], i["raw"], i["reason"])


def ingest_message(conn, day_id, day, fmt, person_id, ts, raw_text, force_report=False):
    """Guarda un mensaje del hilo. Devuelve el report_id o None si no es reporte."""
    text = slack_to_text(raw_text)
    if fmt == "libre":
        is_report = looks_like_free_report(text)
        parsed = None
    else:
        parsed = parse_structured(text, strict=config.STRICT_MARKS)
        is_report = parsed.recognized

    if not (is_report or force_report):
        _upsert_review(conn, "mensaje", ts, "mensaje", day, person_id, None, text,
                       "no parece un reporte (¿conversación del hilo?)")
        return None
    # Si antes estaba en revisión como mensaje y ahora sí es reporte, se limpia.
    conn.execute("DELETE FROM review_items WHERE slack_ts = ? AND kind = 'mensaje' AND status = 'pendiente'",
                 (ts,))

    report_id = _upsert_report(conn, day_id, person_id, ts, fmt)
    conn.execute(
        """INSERT INTO report_messages (slack_ts, report_id, text_hash, raw_text) VALUES (?, ?, ?, ?)
           ON CONFLICT (slack_ts) DO UPDATE SET report_id = excluded.report_id,
             text_hash = excluded.text_hash, raw_text = excluded.raw_text""",
        (ts, report_id, hashlib.sha1(text.encode()).hexdigest(), text))

    if parsed is not None:
        _sync_rows(conn, "commitments", ts, report_id,
                   [dict(c, is_extra=int(c["is_extra"]),
                         link_status="con_link" if c["monday_url"] else "sin_link") for c in parsed.commitments],
                   ["section", "text", "grp", "mark", "mark_source", "is_extra",
                    "monday_url", "monday_key", "link_status"])
        _sync_rows(conn, "operation_items", ts, report_id, parsed.operation, ["text"])
        _sync_rows(conn, "blockers", ts, report_id, parsed.blockers, ["text", "decision_level"])
        _sync_review_lines(conn, ts, day, person_id, parsed.review)
        if parsed.has_blockers_field:
            conn.execute("UPDATE reports SET has_blockers_field = 1 WHERE id = ?", (report_id,))
    return report_id


def refresh_report(conn, report_id):
    """Texto completo y banderas derivadas del reporte."""
    texts = [r["raw_text"] for r in conn.execute(
        "SELECT raw_text FROM report_messages WHERE report_id = ? ORDER BY CAST(slack_ts AS REAL)",
        (report_id,))]
    n_block = conn.execute("SELECT COUNT(*) FROM blockers WHERE report_id = ?", (report_id,)).fetchone()[0]
    conn.execute("UPDATE reports SET raw_text = ?, has_blockers = ?, "
                 "has_blockers_field = MAX(has_blockers_field, ?) WHERE id = ?",
                 ("\n\n".join(texts), int(n_block > 0), int(n_block > 0), report_id))


def run_import(conn, client, channel=None, people_map=None, log=print):
    if config.IMPORT_DISABLED:
        raise SystemExit("Importación apagada (DAILY_IMPORT_DISABLED=1).")
    channel = channel or config.CHANNEL_ID
    people_map = people_map or {}
    run_id = conn.execute("INSERT INTO import_runs (started_at, status) VALUES (?, 'corriendo')",
                          (_now(),)).lastrowid
    conn.commit()
    stats = {"hilos_daily": 0, "boletines_omitidos": 0, "mensajes_leidos": 0}
    try:
        start = datetime.combine(config.HISTORY_START, dtime.min, tzinfo=config.TZ)
        msgs = client.history(channel, oldest=str(start.timestamp()))
        parents = sorted((m for m in msgs if is_daily_parent(m)), key=lambda m: float(m["ts"]))
        stats["boletines_omitidos"] = sum(1 for m in msgs if is_bulletin(m))
        touched = set()
        for parent in parents:
            day = ts_to_day(parent["ts"])
            if day < config.HISTORY_START:
                continue
            owner = parent.get("user")
            fmt = "libre" if day < config.STRUCTURED_START else "marcas"
            day_id = _upsert_day(conn, day, parent["ts"], fmt)
            stats["hilos_daily"] += 1
            for m in sorted(client.replies(channel, parent["ts"]), key=lambda m: float(m["ts"])):
                if not m.get("user") or m.get("user") == owner or m.get("bot_id"):
                    continue
                if m.get("subtype") not in (None, "thread_broadcast"):
                    continue
                stats["mensajes_leidos"] += 1
                pid = _person(conn, m, people_map)
                prev = conn.execute("SELECT status, resolution FROM review_items "
                                    "WHERE slack_ts = ? AND kind = 'mensaje'", (m["ts"],)).fetchone()
                if prev and prev["status"] == "descartado":
                    continue
                force = bool(prev and prev["status"] == "resuelto")
                rid = ingest_message(conn, day_id, day, fmt, pid, m["ts"], m.get("text", ""), force)
                if rid:
                    touched.add(rid)
            log(f"  {day.isoformat()} ({fmt}) listo")
        for rid in touched:
            refresh_report(conn, rid)
        streaks.recompute(conn)
        conn.execute("UPDATE import_runs SET finished_at = ?, status = 'ok', stats_json = ? WHERE id = ?",
                     (_now(), json.dumps(stats), run_id))
        conn.commit()
    except BaseException:
        conn.rollback()
        conn.execute("UPDATE import_runs SET finished_at = ?, status = 'error' WHERE id = ?", (_now(), run_id))
        conn.commit()
        raise
    return run_id


def main(argv=None):
    from .slack_client import ReadOnlySlackClient
    from .summary import format_summary, build_summary
    ap = argparse.ArgumentParser(description="Importa la historia del Daily desde Slack (solo lectura).")
    ap.add_argument("--db", default=config.DB_PATH)
    ap.add_argument("--channel", default=config.CHANNEL_ID)
    ap.add_argument("--people", default=config.PEOPLE_FILE,
                    help="JSON {slack_user_id: nombre}, por si el token no trae nombres")
    args = ap.parse_args(argv)
    if not config.SLACK_IMPORT_ENABLED:
        print("La importación desde Slack está desactivada. Usa: python -m daily_report.import_json\n"
              "Para activarla: DAILY_SLACK_IMPORT_ENABLED=1", file=sys.stderr)
        return 2
    conn = db.connect(args.db)
    run_import(conn, ReadOnlySlackClient(), args.channel, load_people_file(args.people))
    print()
    print(format_summary(build_summary(conn)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
