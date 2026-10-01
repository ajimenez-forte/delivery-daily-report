# Importación de la historia desde Slack

Trae los reportes del canal #wg_delivery_team-internal (`C08AHSM8VRS`) desde el 27 de agosto de 2026 a la base de la app. Usa solo la librería estándar de Python 3.11, sin dependencias.

## Correr la importación

```bash
export SLACK_READONLY_TOKEN=xoxb-...      # permiso channels:history
python -m daily_report.importer           # guarda en data/daily.db
python -m daily_report.admin              # http://127.0.0.1:8765
```

- Si el canal es privado, el token necesita `groups:history` en vez de `channels:history`.
- El token con solo `channels:history` no trae nombres de usuarios. El script usa `user_profile` cuando Slack lo incluye. Si salen IDs en lugar de nombres, crea `people.json` con `{"U123...": "Nombre"}` (está en `.gitignore`).
- `DAILY_IMPORT_DISABLED=1` apaga el script.
- `DAILY_STRICT_MARKS=1` manda a revisión también las líneas marcadas solo con la palabra ("— hecho") sin emoji.

Se puede correr las veces que haga falta. Todo se guarda por el `ts` del mensaje de Slack, así que no duplica. Las correcciones hechas a mano se conservan entre corridas. Si un mensaje ya corregido cambió en Slack, la corrección se mantiene y aparece marcada en Revisión.

## Qué hace

1. Lee el canal con `conversations.history` y cada hilo con `conversations.replies`. El cliente rechaza cualquier otro método antes de salir a la red, así que **nunca escribe en Slack**.
2. Toma como día de Daily cada mensaje que empieza con `Daily Delivery —`. Los `Boletín Daily —` se ignoran.
3. En cada hilo ignora las respuestas del autor del mensaje padre (el dueño) y de bots.
4. **27 ago a 8 sep (texto libre):** guarda el texto completo. Cuenta para la tasa de reporte y no cuenta para el cumplimiento.
5. **Desde el 9 sep (marcas):** separa Ayer, Compromisos de Hoy, Operación y Bloqueos. Cada línea de Ayer queda como compromiso con su marca (✅ hecho, 🔄 pendiente, ⬜ no lo toqué). Guarda el link de Monday si existe. Sin link queda como `sin_link`.
6. Cada registro guarda `origin = 'slack'` y el `slack_ts` del mensaje original.

## Lo que va a revisión (no se adivina)

- Línea de Ayer sin marca, con marca no oficial (COMPLETADO, EN PROGRESO, "Poco avance") o con más de una marca.
- Compromiso de Hoy con marca o con un estado escrito ("Hecho", "EN PROGRESO").
- Línea con más de un link de Monday.
- Texto antes de las secciones ("Buenos días...").
- Mensajes enteros que no parecen reporte ("Gracias", "hoy estoy en cita"). Desde Revisión se marcan como reporte o se descartan.

Se acepta como marca la palabra oficial al final de la línea sin emoji ("Reunión de IA — hecho"). El resumen las cuenta aparte.

## Regla del tercer día con datos históricos

Un compromiso de Hoy sigue la racha si el reporte anterior de la misma persona tenía el mismo compromiso:

- por link de tarea de Monday (`/boards/X/pulses/Y`) cuando ambos lo tienen;
- por texto casi idéntico (similitud ≥ 0,9, sin tildes, mayúsculas ni puntuación) cuando a alguno le falta.

Un link que solo apunta a un tablero (`/boards/X`) no identifica la tarea, así que esos se comparan por texto.

"Reporte anterior" es el último reporte de esa persona, aunque haya faltado algún día. El periodo en texto libre no tiene compromisos separados, así que las rachas empiezan el 9 de septiembre.

## Primer día en la app

La app guarda en las mismas tablas con `origin = 'app'`:

- `bridge.yesterday_for(conn, persona, hoy)` devuelve los Compromisos de Hoy del último reporte. El primer día, ese es el último reporte importado de Slack.
- `streaks.recompute(conn)` sigue la cuenta sobre la historia importada. Si un compromiso llevaba 2 días en Slack, el primer día en la app es el tercero. `bridge.streak_preview(...)` da ese número antes de guardar, para avisar en el formulario.

## Aprobación antes de lanzar

`python -m daily_report.summary` o la página de administrador muestran: días importados, reportes por persona, compromisos con marca y líneas enviadas a revisión.

`summary.launch_allowed(conn)` es `False` hasta que se apruebe la última importación (botón en el administrador o `python -m daily_report.summary --aprobar`). Una nueva corrida o una corrección a mano después de aprobar obligan a aprobar otra vez.

## Pruebas

```bash
python -m unittest
```

Los datos de prueba son inventados y no usan nombres del equipo.
