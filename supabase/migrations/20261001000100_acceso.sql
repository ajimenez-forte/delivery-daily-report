-- Daily Delivery · identidad, RLS y hook de registro (etapa 1)
--
-- La identidad sale solo del token firmado por Supabase Auth: auth.uid() y
-- auth.jwt(). Además, el correo tiene que:
--   - coincidir con el de auth.users para ese uid,
--   - estar verificado (email_confirmed_at),
--   - ser exactamente @forteglobal.com,
--   - estar en public.users y activo.
-- Si algo falla, app_user_email() devuelve NULL y las políticas no dejan ver nada.

-- ---------------------------------------------------------------- identidad

CREATE OR REPLACE FUNCTION public.app_user_email() RETURNS text
    LANGUAGE sql STABLE SECURITY DEFINER SET search_path = '' AS
$$
    SELECT lower(u.email)
    FROM auth.users u
    WHERE u.id = auth.uid()
      AND u.email_confirmed_at IS NOT NULL
      AND lower(u.email) = lower(auth.jwt() ->> 'email')
      AND lower(u.email) ~ '^[^@\s]+@forteglobal\.com$'
$$;

CREATE OR REPLACE FUNCTION public.app_is_user() RETURNS boolean
    LANGUAGE sql STABLE SECURITY DEFINER SET search_path = '' AS
$$ SELECT EXISTS (SELECT 1 FROM public.users WHERE email = public.app_user_email() AND active) $$;

CREATE OR REPLACE FUNCTION public.app_is_admin() RETURNS boolean
    LANGUAGE sql STABLE SECURITY DEFINER SET search_path = '' AS
$$ SELECT EXISTS (SELECT 1 FROM public.users WHERE email = public.app_user_email() AND active AND role = 'admin') $$;

CREATE OR REPLACE FUNCTION public.app_person_id() RETURNS integer
    LANGUAGE sql STABLE SECURITY DEFINER SET search_path = '' AS
$$ SELECT person_id FROM public.users WHERE email = public.app_user_email() AND active $$;

-- ---------------------------------------------------------------- RLS

DO $$
DECLARE
    t text;
BEGIN
    -- Todas las tablas con RLS y una política de admin para todo.
    FOREACH t IN ARRAY ARRAY['people', 'users', 'days', 'pto', 'reports', 'report_messages', 'commitments',
                             'operation_items', 'blockers', 'review_items', 'import_runs', 'launch_approvals',
                             'holidays', 'forte_non_working_days'] LOOP
        EXECUTE format('ALTER TABLE public.%I ENABLE ROW LEVEL SECURITY', t);
        EXECUTE format('DROP POLICY IF EXISTS admin_all ON public.%I', t);
        EXECUTE format('CREATE POLICY admin_all ON public.%I FOR ALL TO authenticated '
                       'USING ((SELECT public.app_is_admin())) WITH CHECK ((SELECT public.app_is_admin()))', t);
    END LOOP;

    -- Filas de la propia persona.
    FOREACH t IN ARRAY ARRAY['reports', 'pto'] LOOP
        EXECUTE format('DROP POLICY IF EXISTS own_rows ON public.%I', t);
        EXECUTE format('CREATE POLICY own_rows ON public.%I FOR ALL TO authenticated '
                       'USING (person_id = (SELECT public.app_person_id())) '
                       'WITH CHECK (person_id = (SELECT public.app_person_id()))', t);
    END LOOP;

    -- Hijas de un reporte de la propia persona.
    FOREACH t IN ARRAY ARRAY['report_messages', 'commitments', 'operation_items', 'blockers'] LOOP
        EXECUTE format('DROP POLICY IF EXISTS own_rows ON public.%I', t);
        EXECUTE format('CREATE POLICY own_rows ON public.%I FOR ALL TO authenticated '
                       'USING (report_id IN (SELECT id FROM public.reports WHERE person_id = (SELECT public.app_person_id()))) '
                       'WITH CHECK (report_id IN (SELECT id FROM public.reports WHERE person_id = (SELECT public.app_person_id())))', t);
    END LOOP;

    -- Lectura para cualquier usuario permitido (no tienen datos de personas).
    FOREACH t IN ARRAY ARRAY['days', 'holidays', 'forte_non_working_days'] LOOP
        EXECUTE format('DROP POLICY IF EXISTS read_users ON public.%I', t);
        EXECUTE format('CREATE POLICY read_users ON public.%I FOR SELECT TO authenticated '
                       'USING ((SELECT public.app_is_user()))', t);
    END LOOP;
END $$;

DROP POLICY IF EXISTS own_row ON public.people;
CREATE POLICY own_row ON public.people FOR SELECT TO authenticated USING (id = (SELECT public.app_person_id()));

DROP POLICY IF EXISTS own_row ON public.users;
CREATE POLICY own_row ON public.users FOR SELECT TO authenticated USING (email = (SELECT public.app_user_email()) AND active);

-- Notas privadas: solo el admin que las escribió. Otro admin tampoco las ve.
ALTER TABLE public.admin_notes ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS author_only ON public.admin_notes;
CREATE POLICY author_only ON public.admin_notes FOR ALL TO authenticated
    USING (author_email = (SELECT public.app_user_email()) AND (SELECT public.app_is_admin()))
    WITH CHECK (author_email = (SELECT public.app_user_email()) AND (SELECT public.app_is_admin()));

-- ---------------------------------------------------------------- permisos

-- anon (sin sesión) no toca nada. authenticated pasa siempre por RLS.
REVOKE ALL ON ALL TABLES IN SCHEMA public FROM anon;
REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM anon;
REVOKE EXECUTE ON ALL FUNCTIONS IN SCHEMA public FROM anon, public;
GRANT USAGE ON SCHEMA public TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO authenticated;
GRANT USAGE ON ALL SEQUENCES IN SCHEMA public TO authenticated;
GRANT EXECUTE ON FUNCTION public.app_user_email(), public.app_is_user(), public.app_is_admin(),
    public.app_person_id() TO authenticated;

-- ---------------------------------------------------------------- hook de registro
-- Se activa en el panel de Supabase: Authentication > Hooks > Before User Created,
-- tipo Postgres, función public.hook_before_user_created.

CREATE OR REPLACE FUNCTION public.hook_before_user_created(event jsonb) RETURNS jsonb
    LANGUAGE plpgsql STABLE SET search_path = '' AS
$$
DECLARE
    v_email text := lower(coalesce(event -> 'user' ->> 'email', ''));
BEGIN
    IF v_email !~ '^[^@\s]+@forteglobal\.com$' THEN
        RETURN jsonb_build_object('error', jsonb_build_object(
            'http_code', 403, 'message', 'Solo se permiten cuentas @forteglobal.com.'));
    END IF;
    IF NOT EXISTS (SELECT 1 FROM public.users WHERE email = v_email AND active) THEN
        RETURN jsonb_build_object('error', jsonb_build_object(
            'http_code', 403, 'message', 'Tu correo no está en la lista de acceso. Pídele acceso a Alejo.'));
    END IF;
    RETURN '{}'::jsonb;
END
$$;

GRANT USAGE ON SCHEMA public TO supabase_auth_admin;
GRANT EXECUTE ON FUNCTION public.hook_before_user_created(jsonb) TO supabase_auth_admin;
REVOKE EXECUTE ON FUNCTION public.hook_before_user_created(jsonb) FROM authenticated, anon, public;
GRANT SELECT ON public.users TO supabase_auth_admin;
DROP POLICY IF EXISTS auth_admin_read ON public.users;
CREATE POLICY auth_admin_read ON public.users FOR SELECT TO supabase_auth_admin USING (true);
