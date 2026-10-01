# Daily Delivery · Especificación

Dueño: Alejo Jiménez (admin). Versión del 1 de octubre de 2026.
Esta es la referencia para construir y revisar la app. Si algo del código contradice este archivo, gana este archivo, salvo que Alejo apruebe el cambio.

## Qué reemplaza

Hoy el daily funciona con dos tareas programadas en Slack, en #wg_delivery_team-internal: el Disparador (7:20 am, pide el reporte en un hilo) y el Boletín (12:00 pm, resume quién reportó, compromisos repetidos y errores de formato). La app reemplaza las dos y respeta las reglas que el equipo ya usa.

## Stack

- Next.js (App Router) con TypeScript.
- Supabase: Postgres con RLS y Supabase Auth.
- Vercel para publicar. Cuentas de Supabase y Vercel a nombre de Forte, no personales.
- El script de importación puede seguir en Python como tarea manual.
- La llave `service_role` de Supabase solo existe en el servidor y en el script de importación. Nunca llega al navegador.

## Usuarios y acceso

- Login con Google mediante Supabase Auth. Solo cuentas @forteglobal.com con correo verificado.
- El dominio se valida en la base (funciones de RLS y hook de registro). El parámetro `hd` de Google no cuenta como protección.
- Además del dominio, el correo tiene que estar en la lista permitida que administra Alejo.
- RLS lee la identidad del token firmado por Supabase (`auth.jwt()`). La app nunca toma el correo de un parámetro, encabezado o cookie.
- Roles: `member` y `admin`. Alejo es el único admin al inicio.
- Equipo inicial: 6 personas en Colombia. Zona horaria fija: America/Bogota.
- Interfaz en español. Los nombres de tareas de Monday se muestran tal cual, aunque estén en inglés.

## Horarios

- El reporte del día abre a las 7:00 am y cierra a las 11:30 am.
- Quien no reporte antes de las 11:30 queda como "sin reporte", salvo que tenga PTO registrado ese día.
- Solo días hábiles. Si hoy es lunes, "ayer" es el viernes.
- Cada persona hace un reporte por día y puede editarlo hasta las 11:59 pm.

## Flujo del miembro

Una pantalla con pasos, en este orden.

1. **Ayer.** Título: "Estas fueron tus tareas reportadas el día de ayer". Muestra exactamente los compromisos del último reporte de la persona, sin poder reescribirlos. Cada uno lleva una marca obligatoria: ✅ Hecho, 🔄 Pendiente (avancé, no cerré) o ⬜ No lo toqué. Observaciones opcionales por compromiso. Botón "Agregar extra" para lo que hizo y no estaba en la lista; los extras no cuentan para el cumplimiento. No se avanza sin marcar todo.
2. **Hoy: Compromisos.** Solo cosas con final y fecha de cierre. Cada uno exige nombre y link de una tarea en forteglobal-squad.monday.com. Sin link no se guarda, con el mensaje: "Si no está en Monday, no es un compromiso. Créala primero." Dictado por voz con la Web Speech API del navegador: transcribe y separa en compromisos que la persona revisa y completa con el link. Si el navegador no la soporta, solo se escribe.
3. **Hoy: Operación.** Un campo para lo continuo (Intercom, monitoreo, correos, RFPs, subir archivos). No se marca ni cuenta para ninguna métrica.
4. **Regla del tercer día.** Si un compromiso aparece por tercera vez seguida, no se guarda solo: pide fecha nueva de cierre o un bloqueo ligado a ese compromiso. Muestra "Este compromiso lleva X días seguidos". El mismo compromiso se reconoce por link de Monday y texto parecido, no solo por link, porque hay links compartidos entre tareas distintas. Los días de PTO pausan la cuenta: no la rompen ni la suman.
5. **Bloqueos (obligatorio).** Descripción y nivel de decisión: 1 decido yo y no aviso, 2 decido yo e informo, 3 decidimos juntos, 4 decide Alejo con mi recomendación, 5 decide Alejo. Si no hay, marca "Sin bloqueos". No se envía con el campo vacío.
6. **PTO.** La persona registra sus días libres futuros desde su perfil.
7. **Cumplimiento del daily.** Gráfica semanal de su cumplimiento y su tasa de reporte contra el promedio del equipo, con la meta de reporte del 85% como línea. Cumplimiento: Hecho = 1, Pendiente = 0,5, No lo toqué = 0, dividido por el total marcado. Tasa de reporte: días reportados sobre días hábiles sin PTO. No usar "desempeño" ni "productividad" en ninguna parte de la interfaz. La persona nunca ve datos individuales de otros: se aplica con RLS y el promedio del equipo llega ya agregado desde el servidor.

## Sección de administrador

Solo rol admin, aplicado con RLS y con 403 en el servidor.

- **Boletín del día:** sin reporte (excluyendo PTO), compromisos repetidos con días seguidos y ⚠️ desde el tercero, bloqueos agrupados por nivel con 4 y 5 arriba, y el reporte completo de cada persona.
- **Carga y cumplimiento por persona:** filtro de fechas, por defecto los últimos 30 días contando hoy. Columnas: días con reporte sobre disponibles; compromisos por día; ítems de Ayer hechos sobre total marcados (sin extras ni líneas sin marca); ítems sin tocar; alertas de tercer día (una por compromiso, el día que llega al tercero); líneas sin marca (de Ayer y de extras pendientes en revisión). Las columnas 2 a 6 solo usan días con marcas. Texto fijo debajo: "Todo es autorreportado. Mide cómo reporta cada persona, no cuánto produce. Una tarea de datos y una llamada de seguimiento pesan lo mismo." Exportar a CSV.
- **Dashboard individual:** evolución semanal (semanas de lunes a domingo) de días con reporte, ítems hechos e ítems sin tocar, y notas privadas que solo ve y edita el admin que las escribió.
- **Revisión:** tabla con las líneas sin marca para que el admin les asigne una.
- **Usuarios:** agregar o desactivar correos, rol, Slack user ID y PTO.

## Slack

- Botón "Enviar boletín a Slack" con vista previa. Solo envía cuando Alejo confirma. Nunca envía solo.
- Mismo orden del boletín. Menciona a cada persona con su Slack user ID en formato <@ID>.
- Incoming Webhook a un solo canal, con la URL en una variable de entorno.
- Interruptor SLACK_ENABLED=true/false.
- Canal de destino: pendiente de decisión de Alejo (canal del equipo o DM).

## Notificaciones

- Bloqueo de nivel 4 o 5: aviso a Alejo en el momento.
- 11:00 am: recordatorio a quien no ha reportado y no tiene PTO.
- Como el login es con Google, la app no envía correos por sí sola. Proponer el canal de aviso (correo con un servicio de envío en cuenta de Forte, o DM de Slack) antes de construirlo.
- Interruptor NOTIFICATIONS_ENABLED.

## Diseño

- Tokens en un solo archivo (forte-tokens.css). Los colores y fuentes de marca están pendientes: salen del Brand Kit "NEW Forte Branding 2.0" en Canva. Mientras tanto se usan los provisionales del archivo.
- Debe funcionar bien en celular.

## Historia importada

- Archivo daily_historia_2026-08-27_a_09-30.json, del 27 de agosto al 30 de septiembre. Las advertencias en "meta" explican cómo se armó.
- Los días de formato libre cuentan para la tasa de reporte, no para el cumplimiento.
- Las líneas con marca null van a la tabla de revisión. No se les asigna marca automáticamente.
- "punto_de_partida" define qué ve cada persona como "Ayer" el primer día.
- El script de Slack queda en el repo, desactivado.

## Forma de trabajar

- Antes de cambios grandes, mostrar el plan y esperar aprobación.
- Trabajar en ramas. No hacer merge a main sin aprobación de Alejo.
- Cada etapa termina con instrucciones para probarla.
- README con los pasos de configuración de Supabase, Vercel, Google y Slack, escrito para alguien que no es desarrollador.
- Al terminar, la app se registra en el registro de automatizaciones de Forte con Alejo como dueño.

## Cambios aprobados

Registro de cambios a esta especificación que Alejo aprobó. Gana lo que está aquí sobre el texto de arriba.

- **1 de octubre de 2026 · Días hábiles:** sábado y domingo no son hábiles. Los festivos oficiales de Colombia tampoco. Para Laura, que trabaja desde Costa Rica, cuentan solo los festivos de Costa Rica. El admin puede agregar o quitar días no hábiles propios de Forte. El festivo del 13 de julio (Ley 2578 de 2026) se mantiene.
- **1 de octubre de 2026 · Zona horaria por persona:** reemplaza "Zona horaria fija: America/Bogota". Cada usuario tiene su zona horaria (por defecto America/Bogota). Laura usa America/Costa_Rica: su reporte abre a las 7:00 y cierra a las 11:30 en su hora, y "hoy" y "ayer" se calculan con su hora.
- **1 de octubre de 2026 · Días antes del lanzamiento:** los días entre el 30 de septiembre y el lanzamiento no se marcan como no hábiles. El daily sigue en Slack y esos días se importan con un archivo actualizado antes de lanzar.
- **1 de octubre de 2026 · Promedio del equipo:** se oculta en las semanas con menos de 3 personas con datos.
