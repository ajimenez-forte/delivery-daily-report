# Carga y cumplimiento por persona

Vista de la sección de administrador. Solo la ve el rol `admin`. El acceso lo aplica Postgres con Row Level Security, no la interfaz.

> **Estado (etapa 0 de la migración):** el servidor de administrador en Python se retiró porque tomaba la identidad de un encabezado o de una variable local. La identidad va a salir solo del token de Supabase. Las pantallas vuelven en Next.js en la etapa 2 (ver `docs/ESPECIFICACION.md`). Mientras tanto, el cálculo vive en `daily_report/metrics.py` y está cubierto por las pruebas.

## Columnas

Rango por defecto: los últimos 30 días contando hoy (hora de Bogotá). El 1 de octubre, por ejemplo, va del 2 de septiembre al 1 de octubre.

| # | Columna | Cálculo | Días que usa |
|---|---|---|---|
| 1 | Días con reporte | Días con reporte / días disponibles (%). Disponibles = días de Daily en el rango menos el PTO registrado. Si hubo PTO, se muestra cuántos días entre paréntesis. | Todos |
| 2 | Compromisos por día | Compromisos de Hoy declarados / días que reportó | Marcas |
| 3 | Ayer hechos | ✅ / total marcados (✅ + 🔄 + ⬜) | Marcas |
| 4 | Sin tocar | ⬜ y % sobre total marcados | Marcas |
| 5 | Alertas de tercer día | Compromisos que llegaron a su tercer día seguido. Un compromiso que sigue al cuarto o quinto día no suma otra alerta. | Marcas |
| 6 | Líneas sin marca | Líneas pendientes en la tabla de revisión (Ayer y extras) más líneas de Ayer guardadas sin marca | Marcas |

- En las columnas 3 y 4 no cuentan ni los extras ni las líneas sin marca. Una línea sin marca entra solo cuando el admin le asigna una marca desde Revisión, con la sección Ayer. Desde ese momento sale de la columna 6.
- Si el rango incluye días en formato libre, la vista lo avisa.
- El orden por defecto es por % de Ayer hechos, de mayor a menor. Cualquier encabezado ordena por esa columna, y un segundo clic invierte el orden. Las personas sin datos van al final.
- Debajo de la tabla siempre aparece este texto: "Todo es autorreportado. Mide cómo reporta cada persona, no cuánto produce. Una tarea de datos y una llamada de seguimiento pesan lo mismo."
- **Exportar a CSV** baja la tabla con el mismo rango y orden. El archivo incluye la nota de formato libre y el texto anterior.

## Dashboard individual

Al hacer clic en una persona se abre `/persona?id=...`:

- Evolución semanal (lunes a domingo, recortada al rango) de las columnas 1, 3 y 4. Hay un gráfico por métrica y una tabla con los mismos números.
- Notas privadas. Solo las ve y las edita el admin que las escribió. Otro admin tampoco las ve.

## Row Level Security

Hay dos conexiones a Postgres, con credenciales solo por variables de entorno:

| Variable | Rol | Para qué |
|---|---|---|
| `DATABASE_URL` | dueño de las tablas | importación, migraciones, `users` |
| `DAILY_APP_DATABASE_URL` | `daily_app` (`DAILY_APP_DB_ROLE`), sin `BYPASSRLS` | la app y la sección de administrador |

En cada petición, la app abre la conexión como `daily_app` y declara el correo del usuario (`app.user_email`). Postgres filtra con estas políticas:

| Tablas | admin | member | sin usuario registrado |
|---|---|---|---|
| `people`, `users` | todo | solo su fila | nada |
| `days` | todo | lectura | nada |
| `reports`, `pto`, `commitments`, `operation_items`, `blockers`, `report_messages` | todo | solo lo suyo | nada |
| `review_items`, `import_runs`, `launch_approvals` | todo | nada | nada |
| `admin_notes` | solo las que escribió | nada | nada |

Desde la etapa 2, el servidor además responde 403 a quien no es admin. Pero aunque alguien se salte el servidor y consulte la base con el rol de la app, solo ve sus propias filas.

### Puesta en marcha (una vez, como administrador de Postgres)

```sql
CREATE ROLE daily_owner LOGIN PASSWORD '...';
CREATE ROLE daily_app LOGIN PASSWORD '...' NOSUPERUSER NOBYPASSRLS;
CREATE DATABASE daily OWNER daily_owner ENCODING 'UTF8';
```

Después:

```bash
export DATABASE_URL=postgresql://daily_owner:...@host/daily
export DAILY_APP_DATABASE_URL=postgresql://daily_app:...@host/daily
python -m daily_report.import_json                          # crea tablas, políticas y permisos
python -m daily_report.users add tu-correo@forteglobal.com admin
python -m daily_report.users add persona@forteglobal.com member --persona LT
```

### Quién es el usuario

La identidad sale solo del token firmado por Supabase Auth (login con Google, cuentas @forteglobal.com). La app nunca toma el correo de un parámetro, encabezado o cookie propia. Esto se construye en las etapas 1 y 2.

En las pruebas de Python, la conexión declara el usuario directamente en la base para simular la sesión. Eso no es una vía de entrada para el navegador.
