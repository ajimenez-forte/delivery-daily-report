"""Hilos de Slack inventados con la forma de los reales. Nombres ficticios."""
from datetime import datetime
from zoneinfo import ZoneInfo

TZ = ZoneInfo("America/Bogota")
OWNER = "UOWNER"
ANA, BETO = "UANA", "UBETO"
M1 = "https://forteglobal-squad.monday.com/boards/111/pulses/9001"
M2 = "https://forteglobal-squad.monday.com/boards/111/pulses/9002"
BOARD = "https://forteglobal-squad.monday.com/boards/222"


def ts(y, mo, d, h, mi=0, s=0):
    return f"{datetime(y, mo, d, h, mi, s, tzinfo=TZ).timestamp():.6f}"


def msg(user, t, text, **kw):
    m = {"user": user, "ts": t, "text": text,
         "user_profile": {"real_name": {ANA: "Ana Prueba", BETO: "Beto Prueba"}.get(user, "Dueño")}}
    m.update(kw)
    return m


def daily(d):
    return f":sunrise: Daily Delivery — día {d}\n\nBuenos días equipo. Respondan EN ESTE HILO"


def ana_report(ayer_lines, hoy_lines, extra=""):
    return ("_Ayer:_\n" + "\n".join(ayer_lines) + "\n_Hoy — Compromisos:_\n" + "\n".join(hoy_lines)
            + "\n_Hoy — Operación:_ Intercom y correos\n_Bloqueos:_ Sin bloqueos" + extra)


def build():
    """Devuelve (history, replies_by_parent_ts)."""
    history, replies = [], {}

    # 27 ago: formato libre
    p = ts(2026, 8, 27, 7, 20)
    history.append(msg(OWNER, p, daily("27")))
    replies[p] = [
        msg(ANA, ts(2026, 8, 27, 9), "Ayer: armé el reporte de pagos\nHoy: cierro pagos\nBloqueos: ninguno"),
        msg(BETO, ts(2026, 8, 27, 10), "Gracias!"),  # conversación, no reporte
        msg(OWNER, ts(2026, 8, 27, 15), "<@UBETO|Beto> sin registro"),
    ]
    # Boletín del mismo día: no se importa
    history.append(msg(OWNER, ts(2026, 8, 27, 12), ":clipboard: _Boletín Daily — jueves 27_\n_Por persona:_"))

    # 9 sep: primer día con marcas
    p = ts(2026, 9, 9, 7, 26)
    history.append(msg(OWNER, p, daily("9")))
    replies[p] = [msg(ANA, ts(2026, 9, 9, 9), ana_report(
        ["• Reporte de pagos - :arrows_counterclockwise: pendiente (avancé, no cerré)"],
        [f"• Cerrar pagos a proveedores → <{M1}|{M1[8:]}>",
         "• Hacer el reporte de Oxford",
         f"• Revisar tablero <{BOARD}>"]))]

    # 10 sep
    p = ts(2026, 9, 10, 7, 23)
    history.append(msg(OWNER, p, daily("10")))
    replies[p] = [
        msg(ANA, ts(2026, 9, 10, 9), ana_report(
            [f"• Cerrar pagos a proveedores → <{M1}|x> :arrows_counterclockwise: pendiente",
             "• Hacer el reporte de Oxford — hecho",
             "• Revisar tablero - COMPLETADO",
             "• Extra: reunión con PMO :white_check_mark: hecho"],
            ["BAHAMAS:",
             f"• Cerrar pagos a proveedores (W Learning) → <{M1}|x>",
             "• Hacer el reporte de Oxford.",
             f"• Nueva tarea <{M2}|x>"])),
        msg(BETO, ts(2026, 9, 10, 9, 30), "Hola, hoy estoy en cita médica"),
    ]

    # 11 sep
    p = ts(2026, 9, 11, 7, 23)
    history.append(msg(OWNER, p, daily("11")))
    replies[p] = [
        msg(ANA, ts(2026, 9, 11, 9), ana_report(
            [f"• Cerrar pagos → <{M1}|x> ✅ 🔄"],
            [f"• Cerrar pagos, versión final → <{M1}|x>",
             "• hacer el reporte de oxford"],
            extra="\n• Pago bloqueado por firma, nivel 4")),
        msg(BETO, ts(2026, 9, 11, 10), "Buenos días\n*Ayer:*\n• Algo — :white_large_square: no lo toqué\n"
                                       "*Compromisos de hoy:*\n• Tarea B"),
    ]
    return history, replies


class FakeClient:
    def __init__(self, history, replies):
        self._h, self._r = history, replies
        self.calls = []

    def history(self, channel, oldest, latest=None):
        self.calls.append(("conversations.history", channel))
        return [m for m in self._h if float(m["ts"]) >= float(oldest)]

    def replies(self, channel, ts):
        self.calls.append(("conversations.replies", ts))
        return list(self._r.get(ts, []))
