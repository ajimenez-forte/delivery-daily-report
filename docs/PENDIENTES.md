# Pendientes por etapa

## Etapa 2 (hecho)

- La prueba del 403 del administrador volvió contra las rutas de Next.js (`web/tests/e2e/acceso.test.ts`).
  - El admin recibe 200 en Importación, Carga y cumplimiento, el CSV, el dashboard individual, Revisión, Usuarios y Boletín.
  - Un member, un correo fuera de la lista y otro dominio listado como admin reciben 403 en todas.
  - Sin sesión, todas las rutas mandan al login y no muestran datos. Antes decía 403. Es un cambio: mandar al login es lo normal para quien no ha entrado.
  - Un envío de notas desde otro origen no cambia nada. Lo bloquea la protección de Next.js para Server Actions.
- La prueba de suplantación con tokens firmados de verdad la verifica PostgREST, el mismo componente de la API de Supabase. Los 5 intentos fallan.
- La prueba con token real de que un miembro solo ve sus filas está automatizada.
- Sección Usuarios: agregar o desactivar correos, rol, persona, zona horaria, país, Slack user ID, PTO y días no hábiles de Forte.

## Etapa 3

- Flujo del miembro (los 7 pasos), horarios en la zona horaria de cada persona y regla del tercer día al guardar.
- La racha de días seguidos de los compromisos nuevos se calcula hoy en Python (importación). Hay que pasarla a la app usando los mismos casos de prueba.

## Decisiones abiertas

- **Feriados de Costa Rica de pago no obligatorio** (2 de agosto, 31 de agosto, 1 de diciembre). No se cargan como no hábiles. Si Forte se los da libres a Laura, se agregan como días no hábiles de Forte. Ojo: esos días hoy aplican a todo el equipo. Si debe aplicar solo a Laura, hace falta decidirlo antes de la etapa 2.

## Antes de lanzar

- Importar el archivo de historia actualizado, con los días del 1 de octubre en adelante que siguieron en Slack. No se marcan como no hábiles.
