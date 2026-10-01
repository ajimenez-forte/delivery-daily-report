# Pendientes por etapa

## Etapa 2 (Next.js, login, administrador)

- **Prueba del 403 del administrador.** Era `AdminServerTest.test_access`, retirada en la etapa 0 junto con el servidor de Python. Debe volver contra las rutas de Next.js:
  - admin recibe 200 en Carga y cumplimiento, en el CSV, en el dashboard individual, en Revisión y en Resumen;
  - un member, un correo que no está en la lista y alguien sin sesión reciben 403 en todas;
  - un POST de notas sin el mismo origen recibe 403.
- **Prueba de suplantación con tokens reales** (Supabase local con `supabase start` en GitHub Actions). Todos estos intentos deben fallar:
  1. `?email=` o `?user=` con el correo del admin;
  2. los encabezados `X-Forwarded-Email` y `X-User`;
  3. una cookie de sesión editada a mano;
  4. un JWT con el correo del admin firmado con otra llave;
  5. un correo de otro dominio que sí está en `users` como admin.

  El caso 5, y los de token con correo que no coincide, ya se prueban en la base desde la etapa 1 (`tests/test_acceso.py`).
- **Prueba con token real** de que un miembro solo ve sus filas (paso 5 de `docs/SUPABASE.md`).
- **Sección Usuarios:** agregar o desactivar correos, rol, Slack user ID, país, PTO y días no hábiles de Forte.

## Decisiones abiertas

- **Feriados de Costa Rica de pago no obligatorio** (2 de agosto, 31 de agosto, 1 de diciembre). No se cargan como no hábiles. Si Forte se los da libres a Laura, se agregan como días no hábiles de Forte. Ojo: esos días hoy aplican a todo el equipo. Si debe aplicar solo a Laura, hace falta decidirlo antes de la etapa 2.
- **Días entre el 30 de septiembre y el lanzamiento.** Cuentan como hábiles sin reporte. Si la app sale después, conviene marcarlos como días no hábiles de Forte o arrancar el rango en la fecha de lanzamiento.
