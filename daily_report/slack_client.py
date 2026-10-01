"""Cliente de Slack de solo lectura.

Solo puede llamar a los métodos de la lista ALLOWED. Cualquier otro método
lanza un error antes de salir a la red, así que el script nunca escribe en
Slack aunque alguien le pase un token con más permisos.
"""
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request

ALLOWED = frozenset({"conversations.history", "conversations.replies"})


class SlackError(RuntimeError):
    pass


class ReadOnlySlackClient:
    def __init__(self, token=None, base_url="https://slack.com/api/"):
        from . import config
        self.token = token or os.environ.get(config.TOKEN_ENV)
        if not self.token:
            raise SlackError(f"Falta la variable de entorno {config.TOKEN_ENV}")
        self.base_url = base_url

    def _get(self, method, params):
        if method not in ALLOWED:
            raise SlackError(f"Método no permitido (solo lectura): {method}")
        url = self.base_url + method + "?" + urllib.parse.urlencode(params)
        req = urllib.request.Request(url, method="GET",
                                     headers={"Authorization": f"Bearer {self.token}"})
        for attempt in range(6):
            try:
                with urllib.request.urlopen(req, timeout=30) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
            except urllib.error.HTTPError as e:
                if e.code == 429:
                    time.sleep(int(e.headers.get("Retry-After", "5")))
                    continue
                raise
            if not data.get("ok"):
                if data.get("error") == "ratelimited":
                    time.sleep(5)
                    continue
                raise SlackError(f"{method}: {data.get('error')}")
            return data
        raise SlackError(f"{method}: demasiados reintentos por rate limit")

    def _paged(self, method, params, key="messages"):
        cursor = None
        while True:
            p = dict(params, limit=200)
            if cursor:
                p["cursor"] = cursor
            data = self._get(method, p)
            yield from data.get(key, [])
            cursor = (data.get("response_metadata") or {}).get("next_cursor")
            if not cursor:
                return

    def history(self, channel, oldest, latest=None):
        params = {"channel": channel, "oldest": oldest, "inclusive": "true"}
        if latest:
            params["latest"] = latest
        return list(self._paged("conversations.history", params))

    def replies(self, channel, ts):
        msgs = list(self._paged("conversations.replies", {"channel": channel, "ts": ts}))
        # El primer mensaje es el padre del hilo.
        return [m for m in msgs if m.get("ts") != ts]
