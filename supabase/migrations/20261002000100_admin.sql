-- Daily Delivery · acciones del administrador (etapa 2)
--
-- Funciones SECURITY INVOKER: corren con los permisos de quien llama y RLS
-- aplica. Además revisan app_is_admin() para dar un error claro.

CREATE OR REPLACE FUNCTION public._utc_text(p timestamptz DEFAULT now()) RETURNS text
    LANGUAGE sql STABLE SET search_path = '' AS
$$ SELECT to_char(p AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"+00:00"') $$;

CREATE OR REPLACE FUNCTION public._require_admin() RETURNS void
    LANGUAGE plpgsql STABLE SET search_path = '' AS
$$
BEGIN
    IF NOT public.app_is_admin() THEN
        RAISE EXCEPTION 'Solo el rol admin puede hacer esto.' USING ERRCODE = '42501';
    END IF;
END
$$;

-- Revisión: asignar una marca a una línea sin marca. La línea pasa a contar en
-- el cumplimiento (si es de Ayer) y sale de "líneas sin marca".
CREATE OR REPLACE FUNCTION public.resolver_linea(p_item integer, p_mark text, p_text text DEFAULT NULL)
    RETURNS void LANGUAGE plpgsql SET search_path = '' AS
$$
DECLARE
    it public.review_items%ROWTYPE;
    v_report integer;
    v_text text;
BEGIN
    PERFORM public._require_admin();
    IF p_mark NOT IN ('hecho', 'pendiente', 'no_tocado') THEN
        RAISE EXCEPTION 'Marca no válida: %', p_mark;
    END IF;
    SELECT * INTO it FROM public.review_items WHERE id = p_item;
    IF NOT FOUND OR it.kind <> 'linea' OR it.section NOT IN ('ayer', 'extra') THEN
        RAISE EXCEPTION 'Esa línea no se puede marcar desde Revisión.';
    END IF;
    v_report := coalesce(it.report_id,
                         (SELECT report_id FROM public.report_messages WHERE slack_ts = it.slack_ts));
    IF v_report IS NULL THEN
        RAISE EXCEPTION 'La línea no está asociada a un reporte.';
    END IF;
    v_text := coalesce(nullif(btrim(p_text), ''), it.raw_text);

    DELETE FROM public.commitments
    WHERE slack_ts = it.slack_ts AND line_key = 'review:' || it.id AND manual = 1;
    INSERT INTO public.commitments (report_id, section, text, mark, mark_source, is_extra, monday_url,
                                    monday_key, link_status, note, origin, slack_ts, line_key, manual)
    VALUES (v_report, 'ayer', v_text, p_mark, 'manual', CASE WHEN it.section = 'extra' THEN 1 ELSE 0 END,
            it.monday_url,
            (SELECT CASE WHEN m[2] IS NULL THEN m[1] ELSE m[1] || ':' || m[2] END
             FROM regexp_match(coalesce(it.monday_url, ''), 'monday\.com/boards/(\d+)(?:/pulses/(\d+))?') AS m),
            CASE WHEN it.monday_url IS NULL THEN 'sin_link' ELSE 'con_link' END,
            it.note, 'slack', it.slack_ts, 'review:' || it.id, 1);

    UPDATE public.review_items
    SET status = 'resuelto', stale = 0, resolved_at = public._utc_text(),
        resolution = json_build_object('action', 'compromiso', 'section', it.section, 'mark', p_mark,
                                       'text', v_text, 'por', public.app_user_email())::text
    WHERE id = p_item;
END
$$;

CREATE OR REPLACE FUNCTION public.descartar_linea(p_item integer) RETURNS void
    LANGUAGE plpgsql SET search_path = '' AS
$$
DECLARE
    it public.review_items%ROWTYPE;
BEGIN
    PERFORM public._require_admin();
    SELECT * INTO it FROM public.review_items WHERE id = p_item;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'No existe esa línea.';
    END IF;
    DELETE FROM public.commitments
    WHERE slack_ts = it.slack_ts AND line_key = 'review:' || it.id AND manual = 1;
    UPDATE public.review_items
    SET status = 'descartado', stale = 0, resolved_at = public._utc_text(),
        resolution = json_build_object('action', 'descartar', 'por', public.app_user_email())::text
    WHERE id = p_item;
END
$$;

-- Aprobación de la importación antes de lanzar. Una nueva importación o una
-- corrección a mano después de aprobar obligan a aprobar de nuevo.
CREATE OR REPLACE FUNCTION public.estado_aprobacion()
    RETURNS TABLE (aprobado boolean, aprobado_en text, corrida_aprobada integer, ultima_corrida integer,
                   ultima_corrida_ok boolean)
    LANGUAGE sql STABLE SET search_path = '' AS
$$
    WITH run AS (SELECT id, status FROM public.import_runs ORDER BY id DESC LIMIT 1),
         appr AS (SELECT * FROM public.launch_approvals ORDER BY id DESC LIMIT 1)
    SELECT coalesce((SELECT appr.import_run_id = run.id AND run.status = 'ok'
                            AND NOT EXISTS (SELECT 1 FROM public.review_items r WHERE r.resolved_at > appr.approved_at)
                     FROM run, appr), false),
           (SELECT approved_at FROM appr), (SELECT import_run_id FROM appr),
           (SELECT id FROM run), (SELECT status = 'ok' FROM run)
$$;

CREATE OR REPLACE FUNCTION public.aprobar_importacion(p_resumen jsonb) RETURNS void
    LANGUAGE plpgsql SET search_path = '' AS
$$
DECLARE
    v_run integer;
BEGIN
    PERFORM public._require_admin();
    SELECT id INTO v_run FROM public.import_runs WHERE status = 'ok' AND id = (SELECT max(id) FROM public.import_runs);
    IF v_run IS NULL THEN
        RAISE EXCEPTION 'No hay una importación terminada sin errores para aprobar.';
    END IF;
    INSERT INTO public.launch_approvals (approved_at, import_run_id, summary_json)
    VALUES (public._utc_text(), v_run, p_resumen::text);
END
$$;

REVOKE EXECUTE ON FUNCTION public._utc_text(timestamptz), public._require_admin(), public.resolver_linea(integer, text, text),
    public.descartar_linea(integer), public.estado_aprobacion(), public.aprobar_importacion(jsonb) FROM anon, public;
GRANT EXECUTE ON FUNCTION public._utc_text(timestamptz), public._require_admin(), public.resolver_linea(integer, text, text),
    public.descartar_linea(integer), public.estado_aprobacion(), public.aprobar_importacion(jsonb) TO authenticated;

-- Quién soy para la base. La app la usa en el servidor para decidir 403; el
-- correo sale del token verificado, nunca de la petición.
CREATE OR REPLACE FUNCTION public.mi_acceso()
    RETURNS TABLE (correo text, es_usuario boolean, es_admin boolean, person_id integer)
    LANGUAGE sql STABLE SET search_path = '' AS
$$ SELECT public.app_user_email(), public.app_is_user(), public.app_is_admin(), public.app_person_id() $$;

-- Notas privadas: el autor lo pone la base con el correo del token.
CREATE OR REPLACE FUNCTION public.guardar_nota(p_person integer, p_body text) RETURNS void
    LANGUAGE plpgsql SET search_path = '' AS
$$
BEGIN
    PERFORM public._require_admin();
    INSERT INTO public.admin_notes (person_id, author_email, body, updated_at)
    VALUES (p_person, public.app_user_email(), coalesce(p_body, ''), public._utc_text())
    ON CONFLICT (person_id, author_email) DO UPDATE SET body = excluded.body, updated_at = excluded.updated_at;
END
$$;

-- Boletín: quién no reportó un día (sin contar PTO ni días no hábiles de la persona).
CREATE OR REPLACE FUNCTION public.boletin_sin_reporte(p_dia date)
    RETURNS TABLE (person_id integer, persona text)
    LANGUAGE sql STABLE SET search_path = '' AS
$$
    SELECT p.id, p.name
    FROM public.people p
    JOIN public.users u ON u.person_id = p.id AND u.active AND u.role = 'member'
    WHERE public.is_business_day(p.id, p_dia)
      AND NOT EXISTS (SELECT 1 FROM public.pto t WHERE t.person_id = p.id AND t.day = p_dia::text)
      AND NOT EXISTS (SELECT 1 FROM public.reports r JOIN public.days d ON d.id = r.day_id
                      WHERE r.person_id = p.id AND d.day = p_dia::text)
    GROUP BY p.id, p.name
    ORDER BY p.name
$$;

ALTER TABLE public.forte_non_working_days ALTER COLUMN created_by SET DEFAULT public.app_user_email();

REVOKE EXECUTE ON FUNCTION public.mi_acceso(), public.guardar_nota(integer, text), public.boletin_sin_reporte(date)
    FROM anon, public;
GRANT EXECUTE ON FUNCTION public.mi_acceso(), public.guardar_nota(integer, text), public.boletin_sin_reporte(date)
    TO authenticated;

-- Resumen de la importación para la pantalla del admin (los conteos se hacen en la base).
CREATE OR REPLACE FUNCTION public.resumen_importacion() RETURNS jsonb
    LANGUAGE sql STABLE SET search_path = '' AS
$$
    SELECT jsonb_build_object(
        'dias', (SELECT jsonb_build_object('total', count(*),
                    'libre', count(*) FILTER (WHERE format = 'libre'),
                    'marcas', count(*) FILTER (WHERE format = 'marcas'),
                    'desde', min(day), 'hasta', max(day)) FROM public.days WHERE origin = 'slack'),
        'personas', (SELECT coalesce(jsonb_agg(x ORDER BY x->>'persona'), '[]'::jsonb) FROM (
                    SELECT jsonb_build_object('persona', p.name,
                        'libre', count(r.id) FILTER (WHERE r.format = 'libre'),
                        'marcas', count(r.id) FILTER (WHERE r.format = 'marcas'),
                        'total', count(r.id),
                        'ayer_en_la_app', (SELECT count(*) FROM public.commitments c JOIN public.reports r2
                                           ON r2.id = c.report_id WHERE r2.person_id = p.id AND c.starting_point = 1)) AS x
                    FROM public.people p LEFT JOIN public.reports r ON r.person_id = p.id AND r.origin = 'slack'
                    GROUP BY p.id) s),
        'marcas', (SELECT jsonb_build_object(
                    'ayer_hecho', count(*) FILTER (WHERE is_extra = 0 AND mark = 'hecho'),
                    'ayer_pendiente', count(*) FILTER (WHERE is_extra = 0 AND mark = 'pendiente'),
                    'ayer_no_tocado', count(*) FILTER (WHERE is_extra = 0 AND mark = 'no_tocado'),
                    'extras_marcados', count(*) FILTER (WHERE is_extra = 1 AND mark IS NOT NULL),
                    'corregidos_a_mano', count(*) FILTER (WHERE manual = 1))
                   FROM public.commitments WHERE origin = 'slack' AND section = 'ayer'),
        'hoy', (SELECT jsonb_build_object('total', count(*),
                    'sin_link', count(*) FILTER (WHERE link_status = 'sin_link'),
                    'tercer_dia_o_mas', count(*) FILTER (WHERE streak_days >= 3))
                FROM public.commitments WHERE origin = 'slack' AND section = 'hoy'),
        'revision', (SELECT jsonb_build_object('total', count(*),
                    'pendientes', count(*) FILTER (WHERE status = 'pendiente'),
                    'resueltas', count(*) FILTER (WHERE status = 'resuelto'),
                    'descartadas', count(*) FILTER (WHERE status = 'descartado'))
                     FROM public.review_items WHERE kind = 'linea'),
        'ultima_corrida', (SELECT jsonb_build_object('id', id, 'estado', status, 'terminada', finished_at,
                                                     'avisos', coalesce((stats_json::jsonb) -> 'avisos', '[]'::jsonb))
                           FROM public.import_runs ORDER BY id DESC LIMIT 1)
    )
$$;
REVOKE EXECUTE ON FUNCTION public.resumen_importacion() FROM anon, public;
GRANT EXECUTE ON FUNCTION public.resumen_importacion() TO authenticated;
