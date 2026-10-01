import { createServerClient } from "@supabase/ssr";
import { generateKeyPair, importJWK, SignJWT } from "jose";
import { beforeAll, describe, expect, inject, it } from "vitest";
import { APP_URL, KID, PUBLISHABLE_KEY, SUPABASE_URL } from "./harness";

const { db, privateJwk } = inject("e2e");
const ADMIN = "jefe.prueba@forteglobal.com";
const OTRO_ADMIN = "otro.admin@forteglobal.com";
const LAURA = "laura.prueba@forteglobal.com";
const GMAIL = "intruso@gmail.com";
const NO_LISTADO = "no.listado@forteglobal.com";
const RANGO = "desde=2026-08-27&hasta=2026-09-29";

async function token(email: string, opts: { sub?: string; otherKey?: boolean } = {}) {
  const key = opts.otherKey ? (await generateKeyPair("ES256")).privateKey : await importJWK(privateJwk, "ES256");
  return new SignJWT({ email, role: "authenticated", aud: "authenticated", session_id: crypto.randomUUID(), is_anonymous: false })
    .setProtectedHeader({ alg: "ES256", kid: KID, typ: "JWT" })
    .setSubject(opts.sub ?? db.users[email])
    .setIssuedAt().setExpirationTime("1h").sign(key);
}

/** Cookie de sesión tal como la escribe @supabase/ssr después de iniciar sesión. */
async function cookieFor(accessToken: string) {
  const jar = new Map<string, string>();
  const sb = createServerClient(SUPABASE_URL, PUBLISHABLE_KEY, {
    cookies: {
      getAll: () => [...jar].map(([name, value]) => ({ name, value })),
      setAll: (list) => list.forEach((c) => (c.value ? jar.set(c.name, c.value) : jar.delete(c.name))),
    },
  });
  const { error } = await sb.auth.setSession({ access_token: accessToken, refresh_token: "r-" + crypto.randomUUID() });
  if (error) throw error;
  return [...jar].map(([n, v]) => `${n}=${v}`).join("; ");
}

/** Igual que cookieFor, pero sin pasar por Supabase: sirve para tokens falsos. */
function forgedCookie(accessToken: string, email: string, sub: string) {
  const session = { access_token: accessToken, refresh_token: "r", token_type: "bearer", expires_in: 3600,
    expires_at: Math.floor(Date.now() / 1000) + 3600, user: { id: sub, email, aud: "authenticated", role: "authenticated" } };
  const host = new URL(SUPABASE_URL).hostname.split(".")[0];
  return `sb-${host}-auth-token=base64-${Buffer.from(JSON.stringify(session)).toString("base64url")}`;
}

async function get(path: string, cookie?: string, headers: Record<string, string> = {}) {
  return fetch(APP_URL + path, { redirect: "manual", headers: { ...(cookie ? { cookie } : {}), ...headers } });
}

const ADMIN_PATHS = () => [
  "/admin", `/admin/carga?${RANGO}`, `/admin/carga/csv?${RANGO}`, `/admin/persona/${db.people.LT}?${RANGO}`,
  "/admin/revision", "/admin/usuarios", "/admin/boletin?dia=2026-09-29",
];

let cookies: Record<string, string>;
beforeAll(async () => {
  cookies = {};
  for (const e of [ADMIN, OTRO_ADMIN, LAURA, GMAIL, NO_LISTADO]) cookies[e] = await cookieFor(await token(e));
});

describe("acceso a la sección de administrador (era AdminServerTest.test_access)", () => {
  it("el admin entra a todas las pantallas", async () => {
    for (const p of ADMIN_PATHS()) {
      const r = await get(p, cookies[ADMIN]);
      expect(r.status, p).toBe(200);
    }
    const carga = await (await get(`/admin/carga?${RANGO}`, cookies[ADMIN])).text();
    expect(carga).toContain("Ricardo Vergara");
    expect(carga).toContain("Todo es autorreportado.");
    const csv = await get(`/admin/carga/csv?${RANGO}`, cookies[ADMIN]);
    expect(csv.headers.get("content-type")).toContain("text/csv");
  });

  it("member, correo fuera de la lista y otro dominio listado como admin reciben 403", async () => {
    for (const who of [LAURA, NO_LISTADO, GMAIL]) {
      for (const p of ADMIN_PATHS()) {
        const r = await get(p, cookies[who]);
        expect(r.status, `${who} ${p}`).toBe(403);
        expect(await r.text(), `${who} ${p}`).not.toContain("Ricardo Vergara");
      }
    }
  });

  it("sin sesión, todo manda al login y no muestra datos", async () => {
    for (const p of ADMIN_PATHS()) {
      const r = await get(p);
      expect([302, 303, 307], p).toContain(r.status);
      expect(r.headers.get("location"), p).toContain("/login");
    }
  });
});

describe("suplantación: un member con sesión válida intenta pasar por admin", () => {
  it("1. parámetro ?email= o ?user= con el correo del admin", async () => {
    for (const q of [`email=${ADMIN}`, `user=${ADMIN}`, `correo=${ADMIN}`]) {
      expect((await get(`/admin/carga?${q}`, cookies[LAURA])).status).toBe(403);
    }
  });

  it("2. encabezados X-Forwarded-Email / X-User con el correo del admin", async () => {
    for (const h of ["X-Forwarded-Email", "X-User", "X-Auth-Request-Email", "X-Forwarded-User"]) {
      expect((await get("/admin/carga", cookies[LAURA], { [h]: ADMIN })).status, h).toBe(403);
    }
  });

  it("3. cookie de sesión editada a mano", async () => {
    const real = await token(LAURA);
    const [h, , s] = real.split(".");
    const payload = Buffer.from(JSON.stringify({ email: ADMIN, sub: db.users[ADMIN], role: "authenticated",
      aud: "authenticated", exp: Math.floor(Date.now() / 1000) + 3600 })).toString("base64url");
    const edited = forgedCookie(`${h}.${payload}.${s}`, ADMIN, db.users[ADMIN]);
    const r = await get("/admin/carga", edited);
    expect(r.status === 403 || (r.headers.get("location") ?? "").includes("/login")).toBe(true);
    expect(await r.text()).not.toContain("Ricardo Vergara");
  });

  it("4. JWT con el correo y el id del admin firmado con otra llave", async () => {
    const fake = await token(ADMIN, { otherKey: true });
    const r = await get("/admin/carga", forgedCookie(fake, ADMIN, db.users[ADMIN]));
    expect(r.status === 403 || (r.headers.get("location") ?? "").includes("/login")).toBe(true);
    // Y directo contra la API de Supabase: PostgREST rechaza la firma.
    const api = await fetch(`${SUPABASE_URL}/rest/v1/people?select=name`, {
      headers: { apikey: PUBLISHABLE_KEY, Authorization: `Bearer ${fake}` } });
    expect(api.status).toBe(401);
  });

  it("5. correo de otro dominio que sí está en users como admin", async () => {
    expect((await get("/admin/carga", cookies[GMAIL])).status).toBe(403);
    const api = await fetch(`${SUPABASE_URL}/rest/v1/people?select=name`, {
      headers: { apikey: PUBLISHABLE_KEY, Authorization: `Bearer ${await token(GMAIL)}` } });
    expect(await api.json()).toEqual([]);
  });
});

describe("RLS con el token real de Supabase (paso 5 de docs/SUPABASE.md)", () => {
  const rest = async (t: string, q: string) => fetch(`${SUPABASE_URL}/rest/v1/${q}`, {
    headers: { apikey: PUBLISHABLE_KEY, Authorization: `Bearer ${t}` } });

  it("un member solo ve sus filas", async () => {
    const rows = (await (await rest(await token(LAURA), "reports?select=person_id")).json()) as { person_id: number }[];
    expect(rows.length).toBeGreaterThan(0);
    expect(new Set(rows.map((r) => r.person_id))).toEqual(new Set([db.people.LT]));
    const review = await (await rest(await token(LAURA), "review_items?select=id")).json();
    expect(review).toEqual([]);
  });

  it("el admin ve a las 6 personas", async () => {
    const rows = (await (await rest(await token(ADMIN), "reports?select=person_id")).json()) as { person_id: number }[];
    expect(new Set(rows.map((r) => r.person_id)).size).toBe(6);
  });

  it("sin token (solo la llave pública) no ve nada", async () => {
    const r = await fetch(`${SUPABASE_URL}/rest/v1/people?select=name`, { headers: { apikey: PUBLISHABLE_KEY, Authorization: `Bearer ${PUBLISHABLE_KEY}` } });
    expect([401, 403]).toContain(r.status);
  });
});

describe("notas privadas por la app", () => {
  async function notesForm(cookie: string) {
    const html = await (await get(`/admin/persona/${db.people.NG}?${RANGO}`, cookie)).text();
    const form = html.slice(html.lastIndexOf("<form", html.indexOf('name="body"')), html.indexOf("</form>", html.indexOf('name="body"')));
    const fields = [...form.matchAll(/<input type="hidden" name="([^"]+)"(?: value="([^"]*)")?/g)].map((m) => [m[1], m[2] ?? ""]);
    return fields;
  }
  async function submit(cookie: string, body: string, origin: string) {
    const fd = new FormData();
    for (const [k, v] of await notesForm(cookie)) fd.append(k, v.replace(/&quot;/g, '"').replace(/&amp;/g, "&"));
    fd.append("body", body);
    return fetch(`${APP_URL}/admin/persona/${db.people.NG}?${RANGO}`, { method: "POST", body: fd, redirect: "manual",
      headers: { cookie, origin } });
  }
  const readNote = async (email: string) => {
    const r = await fetch(`${SUPABASE_URL}/rest/v1/admin_notes?select=body&person_id=eq.${db.people.NG}`, {
      headers: { apikey: PUBLISHABLE_KEY, Authorization: `Bearer ${await token(email)}` } });
    return ((await r.json()) as { body: string }[])[0]?.body;
  };

  it("el admin guarda su nota y otro admin no la ve", async () => {
    const r = await submit(cookies[ADMIN], "nota solo para mí", APP_URL);
    expect(r.status).toBeLessThan(400);
    expect(await readNote(ADMIN)).toBe("nota solo para mí");
    expect(await readNote(OTRO_ADMIN)).toBeUndefined();
    const html = await (await get(`/admin/persona/${db.people.NG}?${RANGO}`, cookies[OTRO_ADMIN])).text();
    expect(html).not.toContain("nota solo para mí");
  });

  it("un envío desde otro origen no cambia nada", async () => {
    await submit(cookies[ADMIN], "desde otro sitio", "https://evil.example");
    expect(await readNote(ADMIN)).toBe("nota solo para mí");
  });
});
