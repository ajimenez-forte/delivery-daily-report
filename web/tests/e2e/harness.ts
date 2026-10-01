// Arma un "Supabase" local para probar la app de punta a punta, sin Docker:
//   - Postgres con las migraciones reales y la historia importada (tests/e2e_db.py).
//   - PostgREST, el mismo componente que Supabase usa para la API: verifica la firma
//     del token con la llave pública y aplica RLS con el rol `authenticated`.
//   - Un servidor que imita los endpoints de Auth que usa la app (llaves públicas y /user).
//   - La app de Next.js compilada y corriendo con `next start`.
import { spawn, spawnSync, type ChildProcess } from "node:child_process";
import http from "node:http";
import path from "node:path";
import { exportJWK, generateKeyPair, jwtVerify, type JWK } from "jose";

export const AUTH_PORT = 54399;
export const APP_PORT = 54398;
export const REST_PORT = 54397;
export const SUPABASE_URL = `http://127.0.0.1:${AUTH_PORT}`;
export const APP_URL = `http://127.0.0.1:${APP_PORT}`;
export const PUBLISHABLE_KEY = "sb_publishable_prueba";
export const KID = "llave-de-prueba";

const ROOT = path.resolve(__dirname, "../../..");
const WEB = path.resolve(__dirname, "../..");

export type DbInfo = { name: string; url: string; users: Record<string, string>; people: Record<string, number> };

function python(args: string[]) {
  const r = spawnSync("python3", ["-m", ...args], { cwd: ROOT, encoding: "utf8", env: process.env });
  if (r.status !== 0) throw new Error(`python ${args.join(" ")} falló:\n${r.stderr}`);
  return r.stdout;
}

function waitFor(url: string, ms = 60000) {
  const until = Date.now() + ms;
  return new Promise<void>((resolve, reject) => {
    const tick = () => {
      http.get(url, (res) => { res.resume(); resolve(); }).on("error", () => {
        if (Date.now() > until) reject(new Error(`No respondió ${url}`));
        else setTimeout(tick, 300);
      });
    };
    tick();
  });
}

function pgrstUri(dbUrl: string) {
  // Mismo destino que la base de prueba, con el usuario authenticator (como en Supabase).
  const pw = process.env.E2E_AUTHENTICATOR_PASSWORD;
  return dbUrl.replace(/^(postgres(?:ql)?:\/\/)[^@/]*@/, `$1authenticator${pw ? ":" + encodeURIComponent(pw) : ""}@`);
}

function portFree(port: number) {
  return new Promise<boolean>((resolve) => {
    const s = http.createServer().once("error", () => resolve(false))
      .once("listening", () => s.close(() => resolve(true))).listen(port, "127.0.0.1");
  });
}

export async function startAll() {
  for (const port of [AUTH_PORT, APP_PORT, REST_PORT]) {
    if (!(await portFree(port))) throw new Error(`El puerto ${port} está ocupado (¿quedó una prueba anterior corriendo?).`);
  }
  if (!process.env.DAILY_TEST_DATABASE_URL) throw new Error("Falta DAILY_TEST_DATABASE_URL (ver docs/IMPORTACION.md).");
  const db: DbInfo = JSON.parse(python(["tests.e2e_db", "create"]));
  const procs: ChildProcess[] = [];
  let auth: http.Server | undefined;
  const cleanup = async () => {
    // Cada proceso arranca en su propio grupo: así se cierra también lo que lanza (npx -> next-server).
    for (const p of procs) {
      try { if (p.pid) process.kill(-p.pid, "SIGTERM"); } catch { /* ya terminó */ }
    }
    if (auth) await new Promise<void>((r) => auth!.close(() => r()));
    python(["tests.e2e_db", "drop", db.name]);
  };
  try {
  const { publicKey, privateKey } = await generateKeyPair("ES256", { extractable: true });
  const publicJwk: JWK = { ...(await exportJWK(publicKey)), kid: KID, alg: "ES256", use: "sig" };
  const privateJwk: JWK = { ...(await exportJWK(privateKey)), kid: KID, alg: "ES256" };

  // PostgREST: solo acepta tokens firmados con la llave pública de prueba.
  const pgrst = spawn(process.env.POSTGREST_BIN || "/opt/pgrst/postgrest", [], {
    env: {
      ...process.env,
      PGRST_DB_URI: pgrstUri(db.url),
      PGRST_DB_SCHEMAS: "public",
      PGRST_DB_ANON_ROLE: "anon",
      PGRST_JWT_SECRET: JSON.stringify({ keys: [publicJwk] }),
      PGRST_SERVER_PORT: String(REST_PORT),
      PGRST_SERVER_HOST: "127.0.0.1",
      PGRST_DB_CHANNEL_ENABLED: "false",
      PGRST_LOG_LEVEL: "crit",
    },
    stdio: "ignore",
    detached: true,
  });
  procs.push(pgrst);

  // Imitación de los endpoints de Supabase que usa la app.
  auth = http.createServer(async (req, res) => {
    const url = new URL(req.url!, SUPABASE_URL);
    const send = (code: number, body: unknown) => {
      res.writeHead(code, { "content-type": "application/json" });
      res.end(JSON.stringify(body));
    };
    if (url.pathname === "/auth/v1/.well-known/jwks.json") return send(200, { keys: [publicJwk] });
    if (url.pathname === "/auth/v1/user") {
      try {
        const token = (req.headers.authorization || "").replace(/^Bearer /, "");
        const { payload } = await jwtVerify(token, publicKey);
        return send(200, { id: payload.sub, aud: "authenticated", role: "authenticated", email: payload.email,
          email_confirmed_at: "2026-10-01T12:00:00Z", app_metadata: { provider: "google" }, user_metadata: {} });
      } catch {
        return send(401, { code: 401, error_code: "bad_jwt", msg: "invalid JWT" });
      }
    }
    if (url.pathname === "/auth/v1/token") return send(400, { error: "invalid_grant" });
    if (url.pathname === "/auth/v1/logout") { res.writeHead(204); return res.end(); }
    if (url.pathname.startsWith("/rest/v1/")) {
      const headers: http.OutgoingHttpHeaders = { ...req.headers, host: `127.0.0.1:${REST_PORT}` };
      // Como el gateway de Supabase: la llave pública sola equivale a no tener sesión (anon).
      if (headers.authorization === `Bearer ${PUBLISHABLE_KEY}`) delete headers.authorization;
      const fwd = http.request({ host: "127.0.0.1", port: REST_PORT, method: req.method,
        path: url.pathname.replace("/rest/v1", "") + url.search, headers }, (r) => {
        res.writeHead(r.statusCode || 502, r.headers);
        r.pipe(res);
      });
      fwd.on("error", () => send(502, { msg: "PostgREST no responde" }));
      return req.pipe(fwd);
    }
    send(404, { msg: "no existe" });
  });
  await new Promise<void>((r) => auth!.listen(AUTH_PORT, "127.0.0.1", () => r()));

  // La app, compilada con la URL de este Supabase local.
  const env = { ...process.env, NEXT_PUBLIC_SUPABASE_URL: SUPABASE_URL, NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY: PUBLISHABLE_KEY,
    NEXT_TELEMETRY_DISABLED: "1" };
  const build = spawnSync("npx", ["next", "build"], { cwd: WEB, env, encoding: "utf8" });
  if (build.status !== 0) throw new Error("next build falló:\n" + build.stdout + build.stderr);
  const app = spawn("npx", ["next", "start", "-p", String(APP_PORT), "-H", "127.0.0.1"], { cwd: WEB, env, stdio: "ignore", detached: true });
  procs.push(app);

  await waitFor(`http://127.0.0.1:${REST_PORT}/`);
  await waitFor(`${APP_URL}/login`);

  return { db, privateJwk, publicJwk, stop: cleanup };
  } catch (e) {
    await cleanup();
    throw e;
  }
}
