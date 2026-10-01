-- Daily Delivery · días hábiles y cálculo de cumplimiento (etapa 1)
--
-- Las reglas viven aquí para que la app (Next.js) y las pruebas (Python)
-- usen exactamente el mismo cálculo. Las funciones son SECURITY INVOKER:
-- RLS decide qué filas ve quien llama. La única excepción es el promedio del
-- equipo, que solo devuelve agregados.
--
-- Día hábil para una persona: lunes a viernes, que no sea festivo del país de
-- la persona (people.country) ni día no hábil de Forte. Día disponible: día
-- hábil sin PTO, desde el primer Daily registrado y ya cerrado (el reporte
-- cierra a las 11:30 am, hora de Bogotá).

CREATE OR REPLACE FUNCTION public.is_business_day(p_person integer, p_day date) RETURNS boolean
    LANGUAGE sql STABLE SET search_path = '' AS
$$
    SELECT extract(isodow FROM p_day) < 6
       AND NOT EXISTS (SELECT 1 FROM public.forte_non_working_days f WHERE f.day = p_day)
       AND NOT EXISTS (SELECT 1 FROM public.holidays h JOIN public.people p ON p.country = h.country
                       WHERE p.id = p_person AND h.day = p_day)
$$;

-- Día hábil anterior. Si hoy es lunes, "ayer" es el viernes (o antes, si hubo festivo).
CREATE OR REPLACE FUNCTION public.previous_business_day(p_person integer, p_day date) RETURNS date
    LANGUAGE sql STABLE SET search_path = '' AS
$$
    SELECT max(d)::date FROM generate_series(p_day - 30, p_day - 1, interval '1 day') AS g(d)
    WHERE public.is_business_day(p_person, d::date)
$$;

-- Último día cuyo reporte ya cerró: hoy si ya pasaron las 11:30 en Bogotá, si no ayer.
CREATE OR REPLACE FUNCTION public.last_closed_day(p_now timestamptz DEFAULT now()) RETURNS date
    LANGUAGE sql STABLE SET search_path = '' AS
$$
    SELECT CASE WHEN (p_now AT TIME ZONE 'America/Bogota')::time >= time '11:30'
                THEN (p_now AT TIME ZONE 'America/Bogota')::date
                ELSE (p_now AT TIME ZONE 'America/Bogota')::date - 1 END
$$;

-- Días hábiles de la persona en el rango, con marca de PTO.
CREATE OR REPLACE FUNCTION public.business_days(p_person integer, p_from date, p_to date,
                                                p_now timestamptz DEFAULT now())
    RETURNS TABLE (day date, is_pto boolean)
    LANGUAGE sql STABLE SET search_path = '' AS
$$
    WITH bounds AS (
        SELECT greatest(p_from, (SELECT min(d.day)::date FROM public.days d)) AS a,
               least(p_to, public.last_closed_day(p_now)) AS b
    )
    SELECT g::date,
           EXISTS (SELECT 1 FROM public.pto t WHERE t.person_id = p_person AND t.day = g::date::text)
    FROM bounds, generate_series(bounds.a, bounds.b, interval '1 day') AS g
    WHERE bounds.a IS NOT NULL AND public.is_business_day(p_person, g::date)
$$;

-- Carga y cumplimiento por persona. Columnas de la especificación:
--   1 días con reporte / disponibles (todos los formatos)
--   2 compromisos por día, 3 hechos / marcados, 4 sin tocar, 5 alertas de tercer día,
--   6 líneas sin marca (solo días con formato de marcas)
CREATE OR REPLACE FUNCTION public.carga_cumplimiento(p_desde date, p_hasta date, p_now timestamptz DEFAULT now())
    RETURNS TABLE (
        person_id integer, persona text,
        dias_reporte integer, dias_disponibles integer, dias_pto integer, tasa_reporte double precision,
        dias_marcas_reportados integer, compromisos integer, compromisos_por_dia double precision,
        hechos integer, pendientes integer, marcados integer, pct_hechos double precision,
        sin_tocar integer, pct_sin_tocar double precision, cumplimiento double precision,
        alertas_tercer_dia integer, sin_marca integer)
    LANGUAGE sql STABLE SET search_path = '' AS
$$
    WITH ppl AS (SELECT p.id, p.name FROM public.people p),
    bd AS (
        SELECT p.id AS person_id, b.day, b.is_pto
        FROM ppl p CROSS JOIN LATERAL public.business_days(p.id, p_desde, p_hasta, p_now) b
    ),
    avail AS (
        SELECT person_id, count(*) FILTER (WHERE NOT is_pto) AS disponibles,
               count(*) FILTER (WHERE is_pto) AS pto
        FROM bd GROUP BY person_id
    ),
    rep AS (
        SELECT r.person_id,
               count(*) FILTER (WHERE EXISTS (SELECT 1 FROM bd WHERE bd.person_id = r.person_id
                                              AND bd.day = d.day::date AND NOT bd.is_pto)) AS con_reporte,
               count(*) FILTER (WHERE d.format <> 'libre') AS estructurados
        FROM public.reports r JOIN public.days d ON d.id = r.day_id
        WHERE d.day::date BETWEEN p_desde AND p_hasta
        GROUP BY r.person_id
    ),
    hoy AS (
        SELECT r.person_id, count(*) AS n, count(*) FILTER (WHERE c.streak_days = 3) AS tercer_dia
        FROM public.commitments c JOIN public.reports r ON r.id = c.report_id JOIN public.days d ON d.id = r.day_id
        WHERE d.day::date BETWEEN p_desde AND p_hasta AND d.format <> 'libre' AND c.section = 'hoy'
        GROUP BY r.person_id
    ),
    ayer AS (
        SELECT r.person_id,
               count(*) FILTER (WHERE c.mark IS NOT NULL) AS marcados,
               count(*) FILTER (WHERE c.mark = 'hecho') AS hechos,
               count(*) FILTER (WHERE c.mark = 'pendiente') AS pendientes,
               count(*) FILTER (WHERE c.mark = 'no_tocado') AS sin_tocar,
               count(*) FILTER (WHERE c.mark IS NULL) AS sin_marca
        FROM public.commitments c JOIN public.reports r ON r.id = c.report_id JOIN public.days d ON d.id = r.day_id
        WHERE d.day::date BETWEEN p_desde AND p_hasta AND d.format <> 'libre'
          AND c.section = 'ayer' AND c.is_extra = 0
        GROUP BY r.person_id
    ),
    rev AS (
        SELECT ri.person_id, count(*) AS n
        FROM public.review_items ri JOIN public.days d ON d.day = ri.day
        WHERE d.day::date BETWEEN p_desde AND p_hasta AND d.format <> 'libre' AND ri.kind = 'linea'
          AND ri.status = 'pendiente' AND ri.section IN ('ayer', 'extra')
        GROUP BY ri.person_id
    )
    SELECT p.id, p.name,
           coalesce(rep.con_reporte, 0)::int,
           coalesce(avail.disponibles, 0)::int,
           coalesce(avail.pto, 0)::int,
           CASE WHEN coalesce(avail.disponibles, 0) > 0
                THEN round(100.0 * coalesce(rep.con_reporte, 0) / avail.disponibles, 1)::float8 END,
           coalesce(rep.estructurados, 0)::int,
           coalesce(hoy.n, 0)::int,
           CASE WHEN coalesce(rep.estructurados, 0) > 0
                THEN round(coalesce(hoy.n, 0)::numeric / rep.estructurados, 1)::float8 END,
           coalesce(ayer.hechos, 0)::int,
           coalesce(ayer.pendientes, 0)::int,
           coalesce(ayer.marcados, 0)::int,
           CASE WHEN coalesce(ayer.marcados, 0) > 0
                THEN round(100.0 * ayer.hechos / ayer.marcados, 1)::float8 END,
           coalesce(ayer.sin_tocar, 0)::int,
           CASE WHEN coalesce(ayer.marcados, 0) > 0
                THEN round(100.0 * ayer.sin_tocar / ayer.marcados, 1)::float8 END,
           -- Cumplimiento del miembro: Hecho 1, Pendiente 0,5, No lo toqué 0, sobre el total marcado.
           CASE WHEN coalesce(ayer.marcados, 0) > 0
                THEN round(100.0 * (ayer.hechos + 0.5 * ayer.pendientes) / ayer.marcados, 1)::float8 END,
           coalesce(hoy.tercer_dia, 0)::int,
           (coalesce(ayer.sin_marca, 0) + coalesce(rev.n, 0))::int
    FROM ppl p
    LEFT JOIN avail ON avail.person_id = p.id
    LEFT JOIN rep ON rep.person_id = p.id
    LEFT JOIN hoy ON hoy.person_id = p.id
    LEFT JOIN ayer ON ayer.person_id = p.id
    LEFT JOIN rev ON rev.person_id = p.id
$$;

-- Semanas de lunes a domingo, recortadas al rango.
CREATE OR REPLACE FUNCTION public.weeks_in_range(p_desde date, p_hasta date)
    RETURNS TABLE (semana date, desde date, hasta date)
    LANGUAGE sql IMMUTABLE AS
$$
    SELECT w::date, greatest(w::date, p_desde), least(w::date + 6, p_hasta)
    FROM generate_series(date_trunc('week', p_desde::timestamp), p_hasta::timestamp, interval '7 days') AS w
$$;

CREATE OR REPLACE FUNCTION public.evolucion_semanal(p_person integer, p_desde date, p_hasta date,
                                                    p_now timestamptz DEFAULT now())
    RETURNS TABLE (semana date, desde date, hasta date, dias_libre integer,
                   dias_reporte integer, dias_disponibles integer, dias_pto integer, tasa_reporte double precision,
                   hechos integer, marcados integer, pct_hechos double precision,
                   sin_tocar integer, pct_sin_tocar double precision, cumplimiento double precision)
    LANGUAGE sql STABLE SET search_path = '' AS
$$
    SELECT w.semana, w.desde, w.hasta,
           (SELECT count(*) FROM public.days d WHERE d.day::date BETWEEN w.desde AND w.hasta
                                               AND d.format = 'libre')::int,
           c.dias_reporte, c.dias_disponibles, c.dias_pto, c.tasa_reporte,
           c.hechos, c.marcados, c.pct_hechos, c.sin_tocar, c.pct_sin_tocar, c.cumplimiento
    FROM public.weeks_in_range(p_desde, p_hasta) w
    CROSS JOIN LATERAL public.carga_cumplimiento(w.desde, w.hasta, p_now) c
    WHERE c.person_id = p_person
      AND EXISTS (SELECT 1 FROM public.days d WHERE d.day::date BETWEEN w.desde AND w.hasta)
    ORDER BY w.semana
$$;

-- Promedio semanal del equipo para la vista del miembro. Corre con permisos del
-- dueño para poder agregar a todos, pero solo devuelve promedios. Si una semana
-- tiene menos de 3 personas con datos, no devuelve el promedio, para que nadie
-- pueda deducir el número de otra persona.
CREATE OR REPLACE FUNCTION public.promedio_equipo_semanal(p_desde date, p_hasta date, p_now timestamptz DEFAULT now())
    RETURNS TABLE (semana date, tasa_reporte double precision, cumplimiento double precision)
    LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path = '' AS
$$
BEGIN
    IF NOT public.app_is_user() THEN
        RETURN;
    END IF;
    RETURN QUERY
    SELECT w.semana,
           CASE WHEN count(c.tasa_reporte) >= 3 THEN round(avg(c.tasa_reporte)::numeric, 1)::float8 END,
           CASE WHEN count(c.cumplimiento) >= 3 THEN round(avg(c.cumplimiento)::numeric, 1)::float8 END
    FROM public.weeks_in_range(p_desde, p_hasta) w
    CROSS JOIN LATERAL public.carga_cumplimiento(w.desde, w.hasta, p_now) c
    JOIN public.users u ON u.person_id = c.person_id AND u.active AND u.role = 'member'
    GROUP BY w.semana
    ORDER BY w.semana;
END
$$;

REVOKE EXECUTE ON FUNCTION public.promedio_equipo_semanal(date, date, timestamptz) FROM anon, public;
GRANT EXECUTE ON FUNCTION
    public.is_business_day(integer, date), public.previous_business_day(integer, date),
    public.last_closed_day(timestamptz), public.business_days(integer, date, date, timestamptz),
    public.carga_cumplimiento(date, date, timestamptz), public.weeks_in_range(date, date),
    public.evolucion_semanal(integer, date, date, timestamptz),
    public.promedio_equipo_semanal(date, date, timestamptz)
    TO authenticated;
