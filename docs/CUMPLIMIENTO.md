# Carga y cumplimiento por persona

Vista de la sección de administrador. Solo la ve el rol `admin`. El acceso lo aplica Postgres con Row Level Security, no la interfaz.

> **Estado (etapa 0 de la migración):** el servidor de administrador en Python se retiró porque tomaba la identidad de un encabezado o de una variable local. La identidad va a salir solo del token de Supabase. Las pantallas vuelven en Next.js en la etapa 2 (ver `docs/ESPECIFICACION.md`). Mientras tanto, el cálculo vive en `daily_report/metrics.py` y está cubierto por las pruebas.

## Columnas

Rango por defecto: los últimos 30 días contando hoy (hora de Bogotá). El 1 de octubre, por ejemplo, va del 2 de septiembre al 1 de octubre.

| # | Columna | Cálculo | Días que usa |
|---|---|---|---|
| 1 | Días con reporte | Días con reporte / días disponibles (%). Disponibles = días hábiles de la persona sin PTO (ver abajo). Si hubo PTO, se muestra cuántos días entre paréntesis. | Todos |
| 2 | Compromisos por día | Compromisos de Hoy declarados / días que reportó | Marcas |
| 3 | Ayer hechos | ✅ / total marcados (✅ + 🔄 + ⬜) | Marcas |
| 4 | Sin tocar | ⬜ y % sobre total marcados | Marcas |
| 5 | Alertas de tercer día | Compromisos que llegaron a su tercer día seguido. Un compromiso que sigue al cuarto o quinto día no suma otra alerta. | Marcas |
| 6 | Líneas sin marca | Líneas pendientes en la tabla de revisión (Ayer y extras) más líneas de Ayer guardadas sin marca | Marcas |

- En las columnas 3 y 4 no cuentan ni los extras ni las líneas sin marca. Una línea sin marca entra solo cuando el admin le asigna una marca desde Revisión, con la sección Ayer. Desde ese momento sale de la columna 6.
- Si el rango incluye días en formato libre, la vista lo avisa.
- **Días hábiles:** lunes a viernes, sin los festivos oficiales del país de la persona (Colombia, o Costa Rica para Laura) ni los días no hábiles de Forte que agregue el admin. Un día cuenta como disponible desde el primer Daily registrado y solo después del cierre de las 11:30 am, hora de Bogotá. Un PTO que cae en festivo no se cuenta dos veces.
- El orden por defecto es por % de Ayer hechos, de mayor a menor. Cualquier encabezado ordena por esa columna, y un segundo clic invierte el orden. Las personas sin datos van al final.
- Debajo de la tabla siempre aparece este texto: "Todo es autorreportado. Mide cómo reporta cada persona, no cuánto produce. Una tarea de datos y una llamada de seguimiento pesan lo mismo."
- **Exportar a CSV** baja la tabla con el mismo rango y orden. El archivo incluye la nota de formato libre y el texto anterior.

## Dashboard individual

Al hacer clic en una persona se abre `/persona?id=...`:

- Evolución semanal (lunes a domingo, recortada al rango) de las columnas 1, 3 y 4. Hay un gráfico por métrica y una tabla con los mismos números.
- Notas privadas. Solo las ve y las edita el admin que las escribió. Otro admin tampoco las ve.

## Row Level Security

La app entra a Supabase con el token del usuario. Postgres lee la identidad con `auth.uid()` y `auth.jwt()`, y las funciones `app_user_email()`, `app_is_user()`, `app_is_admin()` y `app_person_id()` exigen que:

- el correo del token coincida con el de `auth.users`;
- esté verificado;
- sea exactamente `@forteglobal.com`;
- esté en la lista `users` y activo.

Si algo falla, no se ve nada. Todo está en `supabase/migrations/20261001000100_acceso.sql`.

| Tablas | admin | member | sin acceso |
|---|---|---|---|
| `people`, `users` | todo | solo su fila | nada |
| `days`, `holidays`, `forte_non_working_days` | todo | lectura | nada |
| `reports`, `pto`, `commitments`, `operation_items`, `blockers`, `report_messages` | todo | solo lo suyo | nada |
| `review_items`, `import_runs`, `launch_approvals` | todo | nada | nada |
| `admin_notes` | solo las que escribió | nada | nada |

El rol `anon` (sin sesión) no tiene permisos sobre ninguna tabla. Desde la etapa 2, el servidor además responde 403 a quien no es admin.

El cálculo de esta vista está en `supabase/migrations/20261001000300_calculo.sql` (`carga_cumplimiento`, `evolucion_semanal`). Son funciones `SECURITY INVOKER`, así que RLS aplica: un miembro que las llame solo ve su propia fila.

La configuración de Supabase, las variables y cómo probar RLS con un usuario están en `docs/SUPABASE.md`.
