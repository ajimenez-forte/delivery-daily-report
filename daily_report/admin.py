"""Sección de administrador: resumen, revisión a mano y aprobación.

    python -m daily_report.admin      # abre http://127.0.0.1:8765

Solo escucha en 127.0.0.1. Lee y escribe la base local, nunca Slack.
"""
import argparse
import html
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs

from . import config, db, review, summary

CSS = """
body{font:15px/1.45 system-ui,sans-serif;margin:24px auto;max-width:1100px;padding:0 16px;color:#1f2328;background:#fff}
h1{font-size:22px}h2{font-size:18px;margin-top:28px}table{border-collapse:collapse;width:100%}
td,th{border-bottom:1px solid #ddd;padding:6px 8px;text-align:left;vertical-align:top}
.raw{font-family:ui-monospace,monospace;white-space:pre-wrap;background:#f6f8fa;padding:4px 6px}
.ok{color:#1a7f37;font-weight:600}.warn{color:#9a6700;font-weight:600}
form.fix{display:grid;grid-template-columns:repeat(6,auto);gap:6px;align-items:center}
input[type=text]{width:100%}button{cursor:pointer}nav a{margin-right:14px}
"""


def page(title, body):
    return (f"<!doctype html><html lang='es'><meta charset='utf-8'>"
            f"<meta name='viewport' content='width=device-width,initial-scale=1'>"
            f"<title>{html.escape(title)}</title><style>{CSS}</style>"
            f"<nav><a href='/'>Resumen</a><a href='/revision'>Revisión</a></nav>{body}</html>")


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


class Handler(BaseHTTPRequestHandler):
    db_path = None

    def _send(self, body, code=200):
        data = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _redirect(self, to):
        self.send_response(303)
        self.send_header("Location", to)
        self.end_headers()

    def do_GET(self):
        conn = db.connect(self.db_path)
        if self.path == "/":
            self._send(render_summary(conn))
        elif self.path == "/revision":
            self._send(render_review(conn))
        else:
            self._send(page("No existe", "<p>No existe.</p>"), 404)

    def do_POST(self):
        conn = db.connect(self.db_path)
        n = int(self.headers.get("Content-Length", 0))
        form = {k: v[0] for k, v in parse_qs(self.rfile.read(n).decode("utf-8")).items()}
        try:
            if self.path == "/aprobar":
                summary.approve(conn)
                return self._redirect("/")
            if self.path.startswith("/revision/"):
                review.resolve(conn, int(self.path.rsplit("/", 1)[1]), form.get("action"),
                               text=form.get("text"), section=form.get("section"),
                               mark=form.get("mark") or None, monday_url=form.get("monday_url"))
                return self._redirect("/revision")
        except ValueError as ex:
            return self._send(render_review(conn, str(ex)), 400)
        self._send(page("No existe", "<p>No existe.</p>"), 404)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=config.DB_PATH)
    ap.add_argument("--port", type=int, default=8765)
    args = ap.parse_args(argv)
    Handler.db_path = args.db
    print(f"Administrador en http://127.0.0.1:{args.port}")
    ThreadingHTTPServer(("127.0.0.1", args.port), Handler).serve_forever()
    return 0


if __name__ == "__main__":
    sys.exit(main())
