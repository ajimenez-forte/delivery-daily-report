import { requireAdmin } from "@/lib/auth";
import { todayBogota } from "@/lib/carga";
import { createClient } from "@/lib/supabase/server";
import { agregarDiaForte, agregarPto, cambiarActivo, guardarPersona, guardarUsuario, quitarDiaForte, quitarPto } from "./actions";

type Person = { id: number; name: string; code: string | null; country: string; slack_user_id: string | null };

export default async function Usuarios() {
  await requireAdmin();
  const supabase = await createClient();
  const today = todayBogota();
  const year = today.slice(0, 4);
  const [{ data: users }, { data: people }, { data: pto }, { data: forte }, { data: holidays }] = await Promise.all([
    supabase.from("users").select("email, role, person_id, timezone, active").order("role").order("email"),
    supabase.from("people").select("id, name, code, country, slack_user_id").order("name"),
    supabase.from("pto").select("person_id, day").gte("day", today).order("day"),
    supabase.from("forte_non_working_days").select("day, name, created_by").order("day"),
    supabase.from("holidays").select("country, day, name").gte("day", `${year}-01-01`).lte("day", `${year}-12-31`).order("day"),
  ]);
  const ppl = (people ?? []) as Person[];
  const name = (id: number | null) => ppl.find((p) => p.id === id)?.name ?? "";

  return (
    <>
      <h1>Usuarios</h1>

      <h2>Acceso</h2>
      <p className="muted">Solo pueden entrar los correos @forteglobal.com de esta lista que estén activos.</p>
      <div className="scroll"><table>
        <thead><tr><th>Correo</th><th>Rol</th><th>Persona</th><th>Zona horaria</th><th>Estado</th><th></th></tr></thead>
        <tbody>
          {(users ?? []).map((u) => (
            <tr key={u.email}>
              <td>{u.email}</td><td>{u.role}</td><td>{name(u.person_id)}</td><td>{u.timezone}</td>
              <td>{u.active ? "activo" : <span className="muted">inactivo</span>}</td>
              <td><form action={cambiarActivo.bind(null, u.email, !u.active)}><button>{u.active ? "Desactivar" : "Activar"}</button></form></td>
            </tr>
          ))}
        </tbody>
      </table></div>
      <form action={guardarUsuario} className="card row">
        <input type="email" name="email" placeholder="correo@forteglobal.com" required style={{ flex: 2, minWidth: 220 }} />
        <select name="role" defaultValue="member"><option value="member">member</option><option value="admin">admin</option></select>
        <select name="person_id" defaultValue=""><option value="">(sin persona)</option>
          {ppl.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}</select>
        <select name="timezone" defaultValue=""><option value="">Zona: según el país</option>
          <option value="America/Bogota">America/Bogota</option><option value="America/Costa_Rica">America/Costa_Rica</option></select>
        <button className="primary">Agregar o actualizar</button>
      </form>

      <h2>Personas</h2>
      <p className="muted">El país define los festivos de cada persona.</p>
      {ppl.map((p) => (
        <form key={p.id} action={guardarPersona} className="row" style={{ marginBottom: 6 }}>
          <input type="hidden" name="id" value={p.id} />
          <strong style={{ width: 220 }}>{p.name}</strong>
          <select name="country" defaultValue={p.country}><option value="CO">Colombia</option><option value="CR">Costa Rica</option></select>
          <input type="text" name="slack_user_id" defaultValue={p.slack_user_id ?? ""} placeholder="Slack user ID" style={{ width: 160 }} />
          <button>Guardar</button>
        </form>
      ))}
      <form action={guardarPersona} className="card row">
        <input type="text" name="name" placeholder="Nombre de la persona nueva" required style={{ flex: 2, minWidth: 200 }} />
        <input type="text" name="code" placeholder="Código (opcional)" style={{ width: 140 }} />
        <select name="country" defaultValue="CO"><option value="CO">Colombia</option><option value="CR">Costa Rica</option></select>
        <input type="text" name="slack_user_id" placeholder="Slack user ID" style={{ width: 160 }} />
        <button className="primary">Agregar persona</button>
      </form>

      <h2>PTO (desde hoy)</h2>
      <ul>{(pto ?? []).map((t) => (
        <li key={`${t.person_id}-${t.day}`} className="row">{t.day} · {name(t.person_id)}
          <form action={quitarPto.bind(null, t.person_id, t.day)}><button>Quitar</button></form></li>
      ))}</ul>
      <form action={agregarPto} className="card row">
        <select name="person_id" required defaultValue=""><option value="" disabled>Persona…</option>
          {ppl.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}</select>
        <input type="date" name="day" required min={today} />
        <button className="primary">Agregar PTO</button>
      </form>

      <h2>Días no hábiles de Forte</h2>
      <p className="muted">Aplican a todo el equipo. Se suman a los festivos oficiales.</p>
      <ul>{(forte ?? []).map((d) => (
        <li key={d.day} className="row">{d.day} · {d.name} <span className="muted">{d.created_by}</span>
          <form action={quitarDiaForte.bind(null, d.day)}><button>Quitar</button></form></li>
      ))}</ul>
      <form action={agregarDiaForte} className="card row">
        <input type="date" name="day" required />
        <input type="text" name="name" placeholder="Motivo" required style={{ flex: 1, minWidth: 200 }} />
        <button className="primary">Agregar día</button>
      </form>

      <h2>Festivos oficiales {year}</h2>
      <div className="scroll"><table>
        <thead><tr><th>Fecha</th><th>País</th><th>Festivo</th></tr></thead>
        <tbody>{(holidays ?? []).map((h) => (
          <tr key={`${h.country}-${h.day}`}><td>{h.day}</td><td>{h.country === "CO" ? "Colombia" : "Costa Rica"}</td><td>{h.name}</td></tr>
        ))}</tbody>
      </table></div>
    </>
  );
}
