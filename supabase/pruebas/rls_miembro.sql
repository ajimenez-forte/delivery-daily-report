-- Prueba de RLS como un miembro, en el SQL Editor de Supabase.
--
-- Hace lo mismo que Supabase hace con cada petición después de verificar la
-- firma del token: cambia al rol `authenticated` y carga los datos del token
-- (sub y email) en request.jwt.claims. Todo va dentro de una transacción que
-- termina en ROLLBACK, así que no cambia nada.
--
-- Antes de correrla, reemplaza el correo en la línea de abajo (las 2 veces).

BEGIN;

SELECT set_config('request.jwt.claims', json_build_object(
    'sub',   (SELECT id FROM auth.users WHERE lower(email) = 'persona@forteglobal.com'),
    'email', 'persona@forteglobal.com',
    'role',  'authenticated')::text, true);
SET LOCAL ROLE authenticated;

-- 1. ¿Quién soy para la base? Debe salir el correo, app_is_user = true y app_is_admin = false.
SELECT app_user_email() AS correo, app_is_user() AS es_usuario, app_is_admin() AS es_admin;

-- 2. Lo que ve. Personas = 1, personas en reportes = 1, revisión = 0, notas = 0.
SELECT (SELECT count(*) FROM people)                       AS personas,
       (SELECT count(DISTINCT person_id) FROM reports)     AS personas_en_reportes,
       (SELECT count(*) FROM review_items)                 AS revision,
       (SELECT count(*) FROM admin_notes)                  AS notas,
       (SELECT count(*) FROM users)                        AS usuarios;

-- 3. El cálculo de cumplimiento solo le devuelve su propia fila.
SELECT persona, dias_reporte, dias_disponibles, hechos, marcados
FROM carga_cumplimiento(current_date - 29, current_date);

ROLLBACK;
