# Supabase: configuración y prueba de RLS

Proyecto en la cuenta de Forte, región São Paulo (sa-east-1). Este archivo es para quien lo configura y no necesita ser desarrollador.

**Regla de oro:** las llaves y contraseñas nunca se pegan en un chat, un issue ni un commit. Van en `.env.local` en tu computador y en las variables de entorno de Vercel.

## 1. Variables

Copia `.env.example` como `.env.local`, en la carpeta del repo, y llénalo. `.env.local` está en `.gitignore`, así que git no lo sube.

| Variable | Dónde se saca en Supabase | `.env.local` | Vercel | Para qué |
|---|---|---|---|---|
| `NEXT_PUBLIC_SUPABASE_URL` | Project Settings > Data API > Project URL | sí | sí (etapa 2) | la app |
| `NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY` | Project Settings > API Keys > Publishable key | sí | sí (etapa 2) | la app. Es pública por diseño: RLS protege los datos |
| `DATABASE_URL` | botón **Connect** > **Session pooler** > URI, con la contraseña de la base | sí | **no** | solo el script de importación |

La llave `service_role` (o "secret key") no hace falta por ahora. La app no la usa. Si una etapa futura la necesita, va solo en el servidor (Vercel) y nunca en una variable `NEXT_PUBLIC_`.

Uso la conexión "Session pooler" porque la conexión directa de Supabase solo funciona con IPv6, y muchas redes de oficina no lo tienen.

Más adelante:
- **Credenciales de Google (etapa 2):** el Client ID y el Client Secret van en el panel de Supabase (Authentication > Providers > Google), no en `.env.local` ni en Vercel.
- **Slack (etapa 4):** suma `SLACK_WEBHOOK_URL`, `SLACK_BOT_TOKEN`, `SLACK_ENABLED` y `NOTIFICATIONS_ENABLED`.

## 2. Crear las tablas y las políticas

Opción sin instalar nada:
1. En Supabase, abre **SQL Editor**.
2. Abre cada archivo de `supabase/migrations/` en orden (por el número del nombre), copia todo y dale **Run**:
   1. `20261001000000_esquema.sql`
   2. `20261001000100_acceso.sql`
   3. `20261001000200_festivos.sql`
   4. `20261001000300_calculo.sql`
   5. `20261002000000_zona_horaria.sql`
   6. `20261002000100_admin.sql`

Se pueden volver a correr sin dañar nada.

Opción con la terminal: con `DATABASE_URL` en `.env.local`, `python -m daily_report.import_json` aplica las migraciones antes de importar.

## 3. Activar el filtro de registro

En **Authentication > Hooks**, agrega **Before User Created**, tipo **Postgres**, esquema `public`, función `hook_before_user_created`.

Con eso, Supabase rechaza la creación de cualquier cuenta que no sea `@forteglobal.com` o que no esté en la lista de usuarios. La base vuelve a revisar lo mismo en cada consulta, así que el filtro no depende solo del hook.

## 4. Importar la historia y registrar usuarios

En una terminal, en la carpeta del repo:

```bash
pip install -r requirements.txt
python -m daily_report.import_json
python -m daily_report.users add ajimenez@forteglobal.com admin
python -m daily_report.users add persona@forteglobal.com member --persona LT
python -m daily_report.users list
```

Para desactivar a alguien: `python -m daily_report.users deactivate correo@forteglobal.com`. En la etapa 2 esto pasa a la sección Usuarios de la app.

El país de cada persona define sus festivos. Laura (`LT`) queda en Costa Rica por `config/paises.json`. Ese archivo solo se usa al crear la persona.

La zona horaria va en el usuario. Si no se indica, sale del país: Costa Rica toma `America/Costa_Rica` y el resto `America/Bogota`. Para fijarla a mano: `users add ... --zona America/Costa_Rica`.

## 5. Probar que un miembro solo ve sus filas

**Ahora (etapa 1), en el SQL Editor:**
1. Registra al miembro con `users add ... member --persona XX` (paso 4).
2. Crea su cuenta en **Authentication > Users > Add user > Create new user**, con ese correo y **Auto Confirm User** marcado. El hook la deja pasar porque está en la lista.
3. Abre `supabase/pruebas/rls_miembro.sql`, cambia el correo en las dos líneas marcadas y dale **Run**.

Lo que tiene que salir:

| Consulta | Resultado esperado |
|---|---|
| 1 | el correo, `es_usuario = true`, `es_admin = false` |
| 2 | `personas = 1`, `personas_en_reportes = 1`, `revision = 0`, `notas = 0`, `usuarios = 1` |
| 3 | una sola fila, la de esa persona |

4. Repite con tu correo de admin. Deben aparecer las 6 personas y `revision` con las líneas pendientes.
5. Repite con un correo que no esté en la lista. El correo aparece en la consulta 1, pero `es_usuario` y `es_admin` salen falsos y todo lo demás en 0.

El script hace exactamente lo que Supabase hace con un token ya verificado: pasa al rol `authenticated` y carga los datos del token. Lo que no prueba es la verificación de la firma. Eso se prueba en la etapa 2 con un token real del login.

**En la etapa 2, con el token real del login:** inicia sesión en la app como el miembro, copia el token de acceso (el paso a paso va en la etapa 2) y corre:

```bash
curl "$NEXT_PUBLIC_SUPABASE_URL/rest/v1/reports?select=person_id" \
  -H "apikey: $NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY" \
  -H "Authorization: Bearer EL_TOKEN"
```

Todas las filas que devuelva deben tener el mismo `person_id`. Con un token alterado, Supabase responde 401.

## 6. Festivos

- Colombia y Costa Rica 2026–2027 salen de `scripts/generar_festivos.py` (librería `holidays`, que cita las leyes de cada país). Para Costa Rica solo se cargan los feriados de pago obligatorio.
- Para otro año: `python scripts/generar_festivos.py 2028` y luego aplicar la migración que genera.
- Los días no hábiles propios de Forte se guardan en `forte_non_working_days`. En la etapa 2 los manejas desde la sección Usuarios.

## 7. Login con Google (etapa 2)

1. **Google Cloud Console**, con la cuenta de Forte:
   1. En *APIs & Services > OAuth consent screen*, elige el tipo **Internal**. Así Google solo deja entrar cuentas de Forte, y es una capa más además de la base.
   2. En *Credentials > Create credentials > OAuth client ID*, elige el tipo *Web application*.
   3. En *Authorized redirect URIs*, pon `https://TU-PROYECTO.supabase.co/auth/v1/callback` (la URL de tu proyecto sale de Project Settings > Data API).
   4. Copia el Client ID y el Client Secret.
2. **Supabase > Authentication > Sign In / Providers > Google**: actívalo, pega el Client ID y el Client Secret, y guarda. Estos dos valores quedan en Supabase, no en `.env.local` ni en Vercel.
3. **Supabase > Authentication > Sign In / Providers > Email**: desactívalo. La app solo usa Google.
4. **Supabase > Authentication > URL Configuration**:
   - *Site URL*: la dirección de producción en Vercel (por ejemplo `https://daily-delivery.vercel.app`).
   - *Redirect URLs*: `https://daily-delivery.vercel.app/auth/callback` y, para las versiones de prueba de Vercel, `https://*-forte.vercel.app/auth/callback`. Cambia `forte` por el nombre del equipo de Vercel.
5. **Supabase > Project Settings > JWT Keys**: lo ideal es que diga *ECC (P-256)*. Así la app verifica la firma de cada sesión sin llamar a Supabase. Con la llave antigua (HS256) también funciona, pero cada verificación hace una llamada.

## 8. Vercel (etapa 2)

1. Con la cuenta de Forte: *Add New > Project* e importa el repo `delivery-daily-report`.
2. **Root Directory**: `web`. El framework lo detecta solo (Next.js).
3. **Environment Variables**: `NEXT_PUBLIC_SUPABASE_URL` y `NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY`. Nada más. `DATABASE_URL` no va en Vercel.
4. Mientras no haya merge a `main`, usa la versión de prueba (*Preview*) que Vercel arma para la rama `claude/clever-bohr-j2erqs`.

## 9. Aplicar en Supabase sin terminal (GitHub Actions)

Desde el entorno de Claude no hay salida de red hacia Supabase. Por eso las migraciones y la importación corren en GitHub, con un flujo que solo se ejecuta cuando le das clic:

1. En GitHub, ve al repo > *Settings > Environments > New environment* y créalo con el nombre `supabase-forte`. Marca *Required reviewers* y ponte tú, así cada corrida espera tu aprobación.
2. En ese environment, en *Environment secrets > Add secret*: nombre `DATABASE_URL`, valor la URI del Session pooler (paso 1).
3. En *Settings > Secrets and variables > Actions > Variables*, crea `SUPABASE_APLICAR_ACTIVO` con valor `true`. Ese es el interruptor: si lo pones en `false`, el flujo no hace nada.
4. Ve a *Actions > Aplicar en Supabase > Run workflow* y apruébalo cuando lo pida. El resumen de la importación queda en el registro de la corrida.

GitHub solo muestra el botón *Run workflow* si el archivo del flujo está en la rama principal. Por eso este paso necesita que apruebes pasar solo `.github/workflows/supabase-aplicar.yml` a `main`.
