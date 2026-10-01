-- Daily Delivery · zona horaria por persona (cambio aprobado por Alejo el 1 de octubre de 2026)
--
-- Laura trabaja desde Costa Rica: su reporte abre a las 7:00 y cierra a las
-- 11:30 en su hora (America/Costa_Rica), y "hoy" y "ayer" se calculan con su
-- hora. El resto del equipo sigue en America/Bogota, que es el valor por defecto.

ALTER TABLE public.users ADD COLUMN IF NOT EXISTS timezone text NOT NULL DEFAULT 'America/Bogota';
ALTER TABLE public.users DROP CONSTRAINT IF EXISTS users_timezone_check;
ALTER TABLE public.users ADD CONSTRAINT users_timezone_check
    CHECK (timezone IN ('America/Bogota', 'America/Costa_Rica'));

-- Zona horaria de una persona: la de su usuario activo, o Bogotá si no tiene.
-- SECURITY DEFINER porque un miembro no puede leer la fila de otros usuarios,
-- pero el cálculo del admin y el promedio del equipo la necesitan. Solo
-- devuelve el nombre de la zona horaria.
CREATE OR REPLACE FUNCTION public.person_timezone(p_person integer) RETURNS text
    LANGUAGE sql STABLE SECURITY DEFINER SET search_path = '' AS
$$
    SELECT coalesce((SELECT u.timezone FROM public.users u
                     WHERE u.person_id = p_person AND u.active ORDER BY u.email LIMIT 1),
                    'America/Bogota')
$$;

-- "Hoy" en la hora de la persona.
CREATE OR REPLACE FUNCTION public.person_today(p_person integer, p_now timestamptz DEFAULT now()) RETURNS date
    LANGUAGE sql STABLE SET search_path = '' AS
$$ SELECT (p_now AT TIME ZONE public.person_timezone(p_person))::date $$;

-- Último día cuyo reporte ya cerró (11:30 am en la zona horaria dada).
CREATE OR REPLACE FUNCTION public.last_closed_day(p_now timestamptz, p_tz text) RETURNS date
    LANGUAGE sql STABLE SET search_path = '' AS
$$
    SELECT CASE WHEN (p_now AT TIME ZONE p_tz)::time >= time '11:30'
                THEN (p_now AT TIME ZONE p_tz)::date
                ELSE (p_now AT TIME ZONE p_tz)::date - 1 END
$$;

CREATE OR REPLACE FUNCTION public.last_closed_day(p_now timestamptz DEFAULT now()) RETURNS date
    LANGUAGE sql STABLE SET search_path = '' AS
$$ SELECT public.last_closed_day(p_now, 'America/Bogota') $$;

-- "Ayer" de la persona en su hora: el día hábil anterior a su hoy.
CREATE OR REPLACE FUNCTION public.person_yesterday(p_person integer, p_now timestamptz DEFAULT now()) RETURNS date
    LANGUAGE sql STABLE SET search_path = '' AS
$$ SELECT public.previous_business_day(p_person, public.person_today(p_person, p_now)) $$;

-- Días hábiles: igual que antes, pero el cierre usa la hora de la persona.
CREATE OR REPLACE FUNCTION public.business_days(p_person integer, p_from date, p_to date,
                                                p_now timestamptz DEFAULT now())
    RETURNS TABLE (day date, is_pto boolean)
    LANGUAGE sql STABLE SET search_path = '' AS
$$
    WITH bounds AS (
        SELECT greatest(p_from, (SELECT min(d.day)::date FROM public.days d)) AS a,
               least(p_to, public.last_closed_day(p_now, public.person_timezone(p_person))) AS b
    )
    SELECT g::date,
           EXISTS (SELECT 1 FROM public.pto t WHERE t.person_id = p_person AND t.day = g::date::text)
    FROM bounds, generate_series(bounds.a, bounds.b, interval '1 day') AS g
    WHERE bounds.a IS NOT NULL AND public.is_business_day(p_person, g::date)
$$;

REVOKE EXECUTE ON FUNCTION public.person_timezone(integer) FROM anon, public;
GRANT EXECUTE ON FUNCTION public.person_timezone(integer), public.person_today(integer, timestamptz),
    public.last_closed_day(timestamptz, text), public.person_yesterday(integer, timestamptz)
    TO authenticated;
