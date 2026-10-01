"""Sección de administrador: resumen, revisión, aprobación y cumplimiento.

    python -m daily_report.admin      # abre http://127.0.0.1:8765

Cada petición abre una conexión con el rol de la app y declara el correo del
usuario, así que Postgres aplica RLS: solo un admin ve las filas de todos.
Además el servidor responde 403 a quien no es admin. Nunca escribe en Slack.
"""
import argparse
import html
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlencode, urlsplit

from . import config, db, metrics, review, summary

CSS = """
:root{color-scheme:light;--bg:#fcfcfb;--fg:#0b0b0b;--muted:#52514e;--line:#e4e3df;--raw:#f2f1ee;--ok:#1a7f37;--warn:#9a6700;
--series:#2a78d6;--link:#1f5fae}
@media (prefers-color-scheme: dark){:root:not([data-theme="light"]){color-scheme:dark;--bg:#1a1a19;--fg:#fff;--muted:#c3c2b7;
--line:#3a3936;--raw:#252523;--ok:#4ac26b;--warn:#d4a72c;--series:#3987e5;--link:#8ab4f8}}
:root[data-theme="dark"]{color-scheme:dark;--bg:#1a1a19;--fg:#fff;--muted:#c3c2b7;--line:#3a3936;--raw:#252523;--ok:#4ac26b;
--warn:#d4a72c;--series:#3987e5;--link:#8ab4f8}
body{font:15px/1.45 system-ui,sans-serif;margin:24px auto;max-width:1100px;padding:0 16px;color:var(--fg);
background:var(--bg)}
a{color:var(--link)}h1{font-size:22px}h2{font-size:18px;margin-top:28px}
.scroll{overflow-x:auto}table{border-collapse:collapse;width:100%}
td,th{border-bottom:1px solid var(--line);padding:6px 8px;text-align:left;vertical-align:top}
th a{text-decoration:none;color:var(--fg)}td.n,th.n{text-align:right;font-variant-numeric:tabular-nums}
.raw{font-family:ui-monospace,monospace;white-space:pre-wrap;background:var(--raw);padding:4px 6px}
.ok{color:var(--ok);font-weight:600}.warn{color:var(--warn);font-weight:600}.muted{color:var(--muted)}
form.fix{display:grid;grid-template-columns:repeat(6,auto);gap:6px;align-items:center}
form.range{display:flex;gap:8px;flex-wrap:wrap;align-items:center}
input[type=text]{width:100%}textarea{width:100%;min-height:140px;font:inherit}button{cursor:pointer}
nav a{margin-right:14px}.disclaimer{margin-top:16px;color:var(--muted)}
.multiples{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:16px}
.chart svg{width:100%;height:auto}.chart .grid{stroke:var(--line);stroke-width:1}
.chart .axis{fill:var(--muted);font-size:11px}.chart .line{fill:none;stroke:var(--series);stroke-width:2;
stroke-linejoin:round;stroke-linecap:round}.chart .dot{fill:var(--series);stroke:var(--bg);stroke-width:2}
.chart .hit{fill:transparent}.chart .hit:hover+.dot{r:6}
"""


def page(title, body):
    return (f"<!doctype html><html lang='es'><meta charset='utf-8'>"
            f"<meta name='viewport' content='width=device-width,initial-scale=1'>"
            f"<title>{html.escape(title)}</title><style>{CSS}</style>"
            f"<nav><a href='/'>Resumen</a><a href='/revision'>Revisión</a>"
            f"<a href='/carga'>Carga y cumplimiento por persona</a></nav>{body}</html>")


def e(x):
    return html.escape("" if x is None else str(x))


def render_summary(conn):
    s = summary.build_summary(conn)
    d, m, h, r, a = (s["dias_importados"], s["compromisos_con_marca"], s["compromisos_de_hoy"],
                     s["revision"], s["aprobacion"])
    rows = "".join(f"<tr><td>{e(p['persona'])}</td><td>{p['libre']}</td><td>{p['marcas']}</td>"
                   f"<td>{p['total']}</td><td>{p['dias_pto']}</td><td>{p['tasa_reporte_pct']}%</td></tr>"
                   for p in s["reportes_por_persona"])
    status = (f"<p class='ok'>Aprobado el {e(a['aprobado_en'])}</p>" if a["aprobado"] else
              "<p class='warn'>Pendiente de aprobación. La app no se lanza hasta aprobar esta importación.</p>"
              "<form method='post' action='/aprobar'><button>Aprobar importación y permitir lanzamiento"
              "</button></form>")
    return page("Resumen de importación", f"""
<h1>Resumen de importación</h1>{status}
<h2>Días importados: {d['total']}</h2>
<p>{e(d['desde'])} a {e(d['hasta'])} · texto libre {d['texto_libre']} · con marcas {d['con_marcas']}</p>
<h2>Reportes por persona</h2>
<table><tr><th>Persona</th><th>Texto libre</th><th>Con marcas</th><th>Total</th><th>PTO</th><th>Tasa</th></tr>{rows}</table>
<h2>Compromisos con marca: {m['total']}</h2>
<p>Ayer: ✅ hecho {m['ayer']['hecho']} · 🔄 pendiente {m['ayer']['pendiente']} · ⬜ no lo toqué {m['ayer']['no_tocado']}<br>
Extras: ✅ {m['extras']['hecho']} · 🔄 {m['extras']['pendiente']} · ⬜ {m['extras']['no_tocado']}<br>
Corregidos a mano: {m['corregidos_a_mano']}</p>
<h2>Compromisos de Hoy: {h['total']}</h2>
<p>Sin link: {h['sin_link']} · con fecha de cierre: {h['con_fecha_cierre']} · en tercer día o más: {h['tercer_dia_o_mas']}</p>
<h2>Punto de partida: {s['punto_de_partida']['compromisos']} compromisos</h2>
<table><tr><th>Persona</th><th>Compromiso</th><th>Días seguidos (archivo)</th><th>Días seguidos (importado)</th></tr>
{"".join(f"<tr><td>{e(x['persona'])}</td><td>{e(x['text'])}</td><td>{x['archivo']}</td><td>{x['app']}</td></tr>" for x in s['punto_de_partida']['racha_distinta_al_archivo'])}</table>
{"<h2>Avisos</h2><ul>" + "".join(f"<li>{e(w)}</li>" for w in s['avisos']) + "</ul>" if s['avisos'] else ""}
<h2>Enviado a revisión</h2>
<p>{r['lineas_enviadas']} líneas y {r['mensajes_enviados']} mensajes · pendientes <b>{r['pendientes']}</b> ·
resueltas {r['resueltas']} · descartadas {r['descartadas']}
{f"· <span class='warn'>{r['cambiaron_en_origen']} cambiaron en el origen</span>" if r['cambiaron_en_origen'] else ""}</p>""")


def _line_form(it):
    sec = it["section"] or ""
    opt = lambda v, label, cur: f"<option value='{v}'{' selected' if v == cur else ''}>{label}</option>"
    return f"""<form class='fix' method='post' action='/revision/{it['id']}'>
<select name='action'>{opt('compromiso','Compromiso','')}{opt('operacion','Operación','')}
{opt('bloqueo','Bloqueo','')}{opt('descartar','Descartar','')}</select>
<select name='section'>{opt('ayer','Ayer',sec)}{opt('extra','Extra',sec)}{opt('hoy','Hoy',sec)}</select>
<select name='mark'>{opt('','(sin marca)','')}{opt('hecho','✅ hecho','')}
{opt('pendiente','🔄 pendiente','')}{opt('no_tocado','⬜ no lo toqué','')}</select>
<input type='text' name='text' placeholder='Texto corregido' value='{e(it["raw_text"] if it["kind"] == "linea" else "")}'>
<input type='text' name='monday_url' placeholder='Link de Monday (opcional)' value='{e(it["monday_url"])}'>
<button>Guardar</button></form>"""


def _message_form(it):
    return f"""<form class='fix' method='post' action='/revision/{it['id']}'>
<select name='action'><option value='reporte'>Sí es reporte</option><option value='descartar'>Descartar</option>
</select><button>Guardar</button></form>"""


def render_review(conn, error=None):
    items = review.pending(conn)
    rows = []
    for it in items:
        form = _message_form(it) if it["kind"] == "mensaje" else _line_form(it)
        stale = "<br><span class='warn'>La línea cambió en el origen después de corregirla</span>" if it["stale"] else ""
        rows.append(f"<tr><td>{e(it['day'])}<br>{e(it['persona'])}<br><small>ts {e(it['slack_ts'])}</small></td>"
                    f"<td>{e(it['kind'])} · {e(it['section'] or '-')}<br><b>{e(it['reason'])}</b>{stale}</td>"
                    f"<td><div class='raw'>{e(it['raw_text'])}</div>"
                    + (f"<small>Link: {e(it['monday_url'])}</small><br>" if it["monday_url"] else "")
                    + (f"<small>Nota: {e(it['note'])}</small>" if it["note"] else "")
                    + f"{form}</td></tr>")
    err = f"<p class='warn'>{e(error)}</p>" if error else ""
    return page("Revisión", f"<h1>Revisión a mano ({len(items)})</h1>{err}"
                "<p>Líneas que la importación no pudo interpretar con seguridad. Nada se adivinó.</p>"
                "<table><tr><th>Día / persona</th><th>Motivo</th><th>Texto original y corrección</th></tr>"
                + "".join(rows) + "</table>")


def _num(v, suffix=""):
    return "-" if v is None else f"{v}{suffix}"


def _count_pct(n, pct):
    return "-" if pct is None else f"{n} ({pct}%)"


def _range_form(action, start, end, extra=None):
    hidden = "".join(f"<input type='hidden' name='{e(k)}' value='{e(v)}'>" for k, v in (extra or {}).items())
    return (f"<form class='range' method='get' action='{action}'>"
            f"<label>Desde <input type='date' name='desde' value='{start.isoformat()}'></label>"
            f"<label>Hasta <input type='date' name='hasta' value='{end.isoformat()}'></label>{hidden}"
            f"<button>Aplicar</button></form>")


def render_carga(conn, qs):
    start, end = metrics.parse_range(qs)
    sort = qs.get("orden", "pct_hechos")
    desc = qs.get("dir", "desc") != "asc"
    t = metrics.table(conn, start, end, sort, desc)
    base = {"desde": t["desde"], "hasta": t["hasta"]}

    def th(key, label, num=True):
        nxt = "asc" if (t["orden"] == key and t["desc"]) else "desc"
        arrow = (" ↓" if t["desc"] else " ↑") if t["orden"] == key else ""
        q = urlencode({**base, "orden": key, "dir": nxt})
        return f"<th class='{'n' if num else ''}'><a href='/carga?{q}'>{e(label)}{arrow}</a></th>"

    head = "".join(th(k, label, k != "persona") for k, label in metrics.COLUMNS)
    rows = []
    for r in t["filas"]:
        q = urlencode({**base, "id": r["person_id"]})
        rows.append(
            f"<tr><td><a href='/persona?{q}'>{e(r['persona'])}</a></td>"
            f"<td class='n'>{e(metrics.fmt_days(r))}</td>"
            f"<td class='n'>{_num(r['compromisos_por_dia'])}</td>"
            f"<td class='n'>{e(metrics.fmt_ratio(r['hechos'], r['marcados'], r['pct_hechos']))}</td>"
            f"<td class='n'>{_count_pct(r['sin_tocar'], r['pct_sin_tocar'])}</td>"
            f"<td class='n'>{r['alertas_tercer_dia']}</td><td class='n'>{r['sin_marca']}</td></tr>")
    empty = "" if t["dias_en_rango"] else "<p class='muted'>No hay días de Daily en este rango.</p>"
    note = f"<p class='warn'>{e(t['nota_libre'])}</p>" if t["nota_libre"] else ""
    csv_q = urlencode({**base, "orden": t["orden"], "dir": "desc" if t["desc"] else "asc"})
    return page("Carga y cumplimiento por persona", f"""
<h1>Carga y cumplimiento por persona</h1>
{_range_form('/carga', start, end, {"orden": t["orden"], "dir": "desc" if t["desc"] else "asc"})}
<p class='muted'>{t['dias_en_rango']} días de Daily entre {e(t['desde'])} y {e(t['hasta'])}.
Las columnas 2 a 6 usan solo días con formato de marcas.</p>{note}{empty}
<div class='scroll'><table><tr>{head}</tr>{''.join(rows)}</table></div>
<p class='disclaimer'>{e(metrics.DISCLAIMER)}</p>
<p><a href='/carga.csv?{csv_q}'><button type='button'>Exportar a CSV</button></a></p>""")


def _svg_line(weeks, key, title, detail):
    """Una serie semanal en porcentaje (0 a 100). Puntos sin datos quedan como hueco."""
    w, h, l, r, tp, b = 340, 170, 36, 22, 12, 26
    pw, ph = w - l - r, h - tp - b
    n = len(weeks)
    x = (lambda i: l + (pw / 2 if n == 1 else pw * i / (n - 1)))
    y = (lambda v: tp + ph * (1 - v / 100))
    parts = [f"<svg viewBox='0 0 {w} {h}' role='img' aria-label='{e(title)}'>"]
    for v in (0, 50, 100):
        parts.append(f"<line class='grid' x1='{l}' x2='{w - r}' y1='{y(v):.1f}' y2='{y(v):.1f}'/>"
                     f"<text class='axis' x='{l - 6}' y='{y(v) + 4:.1f}' text-anchor='end'>{v}%</text>")
    seg, paths = [], []
    for i, wk in enumerate(weeks):
        v = wk[key]
        if v is None:
            if seg:
                paths.append(seg)
            seg = []
        else:
            seg.append(f"{x(i):.1f},{y(v):.1f}")
    if seg:
        paths.append(seg)
    for p in paths:
        if len(p) > 1:
            parts.append(f"<polyline class='line' points='{' '.join(p)}'/>")
    step = max(1, n // 6)
    for i, wk in enumerate(weeks):
        if i % step == 0 or i == n - 1:
            anchor = "end" if (i == n - 1 and n > 1) else "middle"
            parts.append(f"<text class='axis' x='{x(i):.1f}' y='{h - 8}' text-anchor='{anchor}'>"
                         f"{wk['semana'][5:]}</text>")
        if wk[key] is not None:
            tip = f"Semana del {wk['semana']}: {wk[key]}% ({detail(wk)})"
            parts.append(f"<circle class='hit' cx='{x(i):.1f}' cy='{y(wk[key]):.1f}' r='12'><title>{e(tip)}</title>"
                         f"</circle><circle class='dot' cx='{x(i):.1f}' cy='{y(wk[key]):.1f}' r='4'>"
                         f"<title>{e(tip)}</title></circle>")
    parts.append("</svg>")
    return f"<figure class='chart'><figcaption><b>{e(title)}</b></figcaption>{''.join(parts)}</figure>"


def render_person(conn, qs, saved=False):
    start, end = metrics.parse_range(qs)
    try:
        pid = int(qs.get("id", ""))
    except ValueError:
        return None
    person = conn.execute("SELECT id, name FROM people WHERE id = ?", (pid,)).fetchone()
    if not person:
        return None
    t = metrics._person_rows(conn, start, end, pid)[0]
    r = t[0] if t else None
    weeks = metrics.weekly(conn, pid, start, end)
    body, updated = metrics.get_note(conn, pid)
    charts = "".join([
        _svg_line(weeks, "tasa_reporte", "Días con reporte (%)",
                  lambda w: f"{w['dias_reporte']}/{w['dias_disponibles']}"
                            + (f", PTO {w['dias_pto']}" if w["dias_pto"] else "")),
        _svg_line(weeks, "pct_hechos", "Ítems de Ayer hechos (%)",
                  lambda w: f"{w['hechos']} de {w['marcados']}"),
        _svg_line(weeks, "pct_sin_tocar", "Ítems sin tocar (%)",
                  lambda w: f"{w['sin_tocar']} de {w['marcados']}"),
    ]) if weeks else "<p class='muted'>No hay semanas con días de Daily en este rango.</p>"
    table_rows = []
    for w in weeks:
        pto = f" ({w['dias_pto']} PTO)" if w["dias_pto"] else ""
        libre = f"texto libre: {w['dias_libre']} días" if w["dias_libre"] else ""
        table_rows.append(
            f"<tr><td>{w['desde']} a {w['hasta']}</td>"
            f"<td class='n'>{w['dias_reporte']}/{w['dias_disponibles']} ({_num(w['tasa_reporte'], '%')}){pto}</td>"
            f"<td class='n'>{e(metrics.fmt_ratio(w['hechos'], w['marcados'], w['pct_hechos']))}</td>"
            f"<td class='n'>{_count_pct(w['sin_tocar'], w['pct_sin_tocar'])}</td><td>{libre}</td></tr>")
    table_rows = "".join(table_rows)
    back = urlencode({"desde": start.isoformat(), "hasta": end.isoformat()})
    summary_line = (f"<p>{e(metrics.fmt_days(r))} · Ayer hechos "
                    f"{e(metrics.fmt_ratio(r['hechos'], r['marcados'], r['pct_hechos']))} · sin tocar "
                    f"{_count_pct(r['sin_tocar'], r['pct_sin_tocar'])}</p>") if r else ""
    return page(person["name"], f"""
<p><a href='/carga?{back}'>← Carga y cumplimiento</a></p>
<h1>{e(person['name'])}</h1>
{_range_form('/persona', start, end, {"id": pid})}{summary_line}
<h2>Evolución semanal</h2>
<p class='muted'>Semanas de lunes a domingo, recortadas al rango. Los porcentajes de Ayer usan solo días con
formato de marcas.</p>
<div class='multiples'>{charts}</div>
<div class='scroll'><table><tr><th>Semana</th><th class='n'>Días con reporte</th><th class='n'>Ayer hechos</th>
<th class='n'>Sin tocar</th><th></th></tr>{table_rows}</table></div>
<p class='disclaimer'>{e(metrics.DISCLAIMER)}</p>
<h2>Notas privadas</h2>
<p class='muted'>Solo tú las ves y las editas. La base de datos no se las muestra a nadie más, ni a otro admin.</p>
<form method='post' action='/persona/{pid}/notas?{back}'>
<textarea name='body'>{e(body)}</textarea>
<p><button>Guardar notas</button> {f"<span class='ok'>Guardado</span>" if saved else ""}
<span class='muted'>{f"Última edición: {e(updated)}" if updated else ""}</span></p></form>""")


class Forbidden(Exception):
    pass


class Handler(BaseHTTPRequestHandler):
    def _user(self):
        if config.AUTH_HEADER:
            return (self.headers.get(config.AUTH_HEADER) or "").strip().lower() or None
        return (config.DEV_USER or "").strip().lower() or None

    def _conn(self):
        """Conexión como el usuario que hace la petición. Solo deja pasar admins."""
        email = self._user()
        if not email:
            raise Forbidden("No se pudo identificar al usuario.")
        conn = db.connect_app(email)
        if not conn.execute("SELECT app_is_admin()").fetchone()[0]:
            conn.close()
            raise Forbidden("Esta sección es solo para el rol admin.")
        return conn

    def _send(self, body, code=200, ctype="text/html; charset=utf-8", headers=None):
        data = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(data)

    def _redirect(self, to):
        self.send_response(303)
        self.send_header("Location", to)
        self.end_headers()

    def _route(self):
        parts = urlsplit(self.path)
        return parts.path, {k: v[0] for k, v in parse_qs(parts.query).items()}

    def _not_found(self):
        self._send(page("No existe", "<p>No existe.</p>"), 404)

    def do_GET(self):
        path, qs = self._route()
        try:
            conn = self._conn()
        except Forbidden as ex:
            return self._send(page("Sin acceso", f"<p>{e(ex)}</p>"), 403)
        try:
            if path == "/":
                return self._send(render_summary(conn))
            if path == "/revision":
                return self._send(render_review(conn))
            if path == "/carga":
                return self._send(render_carga(conn, qs))
            if path == "/carga.csv":
                start, end = metrics.parse_range(qs)
                t = metrics.table(conn, start, end, qs.get("orden", "pct_hechos"), qs.get("dir", "desc") != "asc")
                name = f"carga_cumplimiento_{t['desde']}_a_{t['hasta']}.csv"
                return self._send("\ufeff" + metrics.to_csv(t), ctype="text/csv; charset=utf-8",
                                  headers={"Content-Disposition": f"attachment; filename={name}"})
            if path == "/persona":
                body = render_person(conn, qs, saved=qs.get("guardado") == "1")
                return self._send(body) if body else self._not_found()
            return self._not_found()
        finally:
            conn.close()

    def _same_origin(self):
        src = self.headers.get("Origin") or self.headers.get("Referer")
        return bool(src) and urlsplit(src).netloc == self.headers.get("Host")

    def do_POST(self):
        path, qs = self._route()
        if not self._same_origin():
            return self._send(page("Sin acceso", "<p>Petición de otro sitio.</p>"), 403)
        try:
            conn = self._conn()
        except Forbidden as ex:
            return self._send(page("Sin acceso", f"<p>{e(ex)}</p>"), 403)
        n = int(self.headers.get("Content-Length", 0))
        form = {k: v[0] for k, v in parse_qs(self.rfile.read(n).decode("utf-8"), keep_blank_values=True).items()}
        try:
            if path == "/aprobar":
                summary.approve(conn)
                return self._redirect("/")
            if path.startswith("/revision/"):
                review.resolve(conn, int(path.rsplit("/", 1)[1]), form.get("action"),
                               text=form.get("text"), section=form.get("section"),
                               mark=form.get("mark") or None, monday_url=form.get("monday_url"))
                return self._redirect("/revision")
            if path.startswith("/persona/") and path.endswith("/notas"):
                pid = int(path.split("/")[2])
                metrics.save_note(conn, pid, form.get("body", ""))
                return self._redirect("/persona?" + urlencode({**qs, "id": pid, "guardado": 1}))
        except ValueError as ex:
            return self._send(render_review(conn, str(ex)), 400)
        finally:
            conn.close()
        self._not_found()


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--host", default="127.0.0.1")
    args = ap.parse_args(argv)
    if not (config.AUTH_HEADER or config.DEV_USER):
        raise SystemExit("Configura DAILY_AUTH_HEADER (producción, detrás del login) o DAILY_DEV_USER (local).")
    print(f"Administrador en http://{args.host}:{args.port}")
    ThreadingHTTPServer((args.host, args.port), Handler).serve_forever()
    return 0


if __name__ == "__main__":
    sys.exit(main())
