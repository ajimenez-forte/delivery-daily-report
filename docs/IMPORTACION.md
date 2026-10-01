# Importación de la historia del Daily

La historia del 27 de agosto al 30 de septiembre de 2026 viene del archivo `daily_historia_2026-08-27_a_09-30.json`, ya extraído de #wg_delivery_team-internal (`C08AHSM8VRS`). La importación lee ese archivo. No se conecta a Slack ni necesita token.

Usa solo la librería estándar de Python 3.11, sin dependencias.

## Correr la importación

```bash
python -m daily_report.import_json        # lee el archivo y guarda en data/daily.db
python -m daily_report.summary            # vuelve a mostrar el resumen
python -m daily_report.admin              # http://127.0.0.1:8765
```

- `--file otra_historia.json` o `DAILY_HISTORY_FILE` para usar otro archivo.
- `DAILY_IMPORT_DISABLED=1` apaga la importación.

Se puede correr las veces que haga falta. Cada línea tiene una clave estable (persona + sección + texto), así que no duplica. Las correcciones hechas a mano en Revisión se conservan entre corridas.

## Cómo se lee el archivo

El archivo se armó desde los mensajes "Por persona" de cada Boletín Daily, no desde la respuesta original de cada persona (ver `meta.advertencias`). Para verificar una línea, hay que abrir el hilo con `slack_ts_disparador`.

| Bloque del archivo | Qué se guarda |
|---|---|
| `personas` | Persona con código, nombre y `slack_id`. El correo no se guarda. |
| `pto` | Días de PTO por persona. |
| `dias[].formato = "libre"` | Reporte con el texto de `ayer_texto`, `hoy_texto` y `bloqueos_texto`. Cuenta para la tasa de reporte y no para el cumplimiento. |
| `dias[].formato = "marcas"` | `ayer` y `extras` con su marca, `compromisos` (Hoy) con link de Monday y fecha de cierre declarada, `operacion` y `bloqueos`. |
| `marca: null` | Va a la tabla de revisión del administrador sin marca. El motivo es la `nota` del archivo. |
| `bloqueos.estado` | `sin_bloqueos` cuenta como campo presente. `campo_ausente` cuenta como faltante. |
| `punto_de_partida` | Lo que cada persona ve como "Ayer" el primer día en la app. |

Cada registro guarda `origin = 'slack'` y el `slack_ts` del Disparador del día. Los compromisos sin link de Monday quedan como `sin_link`.

## Regla del tercer día

Un compromiso de Hoy sigue la racha si el reporte anterior de la misma persona tenía el mismo compromiso. Se compara por link de Monday y por texto, porque hay links que se usan para varias tareas distintas:

- **Mismo link** (de tarea o de tablero): el texto también tiene que ser parecido. Se mide por palabras en común (al menos dos, sin contar palabras vacías) o por caracteres cuando el parecido es alto. Umbral: `LINKED_SIMILARITY_THRESHOLD = 0.5`.
- **Sin link en alguno de los dos:** el texto tiene que ser casi idéntico (`SIMILARITY_THRESHOLD = 0.9`).
- **Links de tarea distintos:** son tareas distintas.

Cada compromiso de ayer se empareja con uno solo de hoy.

Límite conocido: si una tarea se reescribe con otras palabras o se traduce ("Hacer los cambios pendientes de cursos en HS..." y luego "Course changes on Intercom..."), la racha se reinicia aunque el link sea el mismo. Ese error es preferible a contar como repetido algo que no lo es. El resumen muestra los casos del punto de partida donde el número cambió respecto al archivo.

### PTO

Los días de PTO no rompen la racha ni la suman. Solo cuentan los días que la persona reportó. Un reporte hecho en un día de PTO no suma.

Como antes, un día sin reporte que no es PTO tampoco rompe la racha. Se compara siempre con el último reporte de la persona, para que saltarse el reporte no reinicie un compromiso atascado.

El periodo en texto libre no tiene compromisos separados, así que las rachas empiezan el 9 de septiembre.

## Primer día en la app

La app guarda en las mismas tablas con `origin = 'app'`.

- `bridge.yesterday_for(conn, persona, hoy)` devuelve el "Ayer" del día. El primer día son los compromisos del `punto_de_partida` (marcados con `starting_point = 1`).
- Si un compromiso del último reporte no está en el punto de partida, no aparece como Ayer y se avisa en el resumen. Si uno del punto de partida no está en el último reporte, se agrega y también se avisa.
- `streaks.recompute(conn)` sigue la cuenta sobre la historia importada, tomando como base el punto de partida. Si un compromiso llevaba 2 días en Slack, el primer día en la app es el tercero. `bridge.streak_preview(...)` da ese número antes de guardar.
- `dias_seguidos_al_corte` del archivo queda guardado como referencia (`file_streak`). La racha que usa la app es la calculada con la regla de arriba.

## Revisión y aprobación

La página de administrador muestra cada línea en revisión con su texto, link y nota. Se puede guardar como compromiso con marca, como operación o como bloqueo, o se puede descartar.

`python -m daily_report.summary` y la página de administrador muestran:

- días importados;
- reportes, PTO y tasa por persona;
- compromisos con marca;
- líneas enviadas a revisión;
- punto de partida;
- la comparación con el bloque `resumen` del archivo.

`summary.launch_allowed(conn)` es `False` hasta que se apruebe la última importación (botón en el administrador o `python -m daily_report.summary --aprobar`). Una nueva corrida o una corrección a mano después de aprobar obligan a aprobar otra vez.

## Importación directa desde Slack (desactivada)

`daily_report/importer.py` y `daily_report/slack_client.py` siguen en el repo por si se necesitan. Leen el canal con un token de solo lectura y nunca escriben en Slack. Están desactivados:

```bash
DAILY_SLACK_IMPORT_ENABLED=1 SLACK_READONLY_TOKEN=xoxb-... python -m daily_report.importer
```

Sin `DAILY_SLACK_IMPORT_ENABLED=1`, el comando no hace nada y sale con un aviso.

## Pruebas

```bash
python -m unittest
```

Los datos de prueba son inventados y no usan nombres del equipo.
