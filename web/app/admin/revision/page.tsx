import { requireAdmin } from "@/lib/auth";
import { createClient } from "@/lib/supabase/server";
import { marcarLinea } from "./actions";

type Item = {
  id: number; day: string; section: string | null; raw_text: string; reason: string; note: string | null;
  monday_url: string | null; slack_ts: string; stale: number; people: { name: string } | null;
};

export default async function Revision() {
  await requireAdmin();
  const supabase = await createClient();
  const { data, error } = await supabase
    .from("review_items")
    .select("id, day, section, raw_text, reason, note, monday_url, slack_ts, stale, people(name)")
    .eq("kind", "linea").eq("status", "pendiente").order("day").order("id");
  if (error) throw new Error(error.message);
  const items = (data ?? []) as unknown as Item[];

  return (
    <>
      <h1>Revisión ({items.length})</h1>
      <p className="muted">
        Líneas sin marca. No se les asignó marca automáticamente. Cuando les pones una, las de Ayer cuentan en el
        cumplimiento. Las de extras no cuentan, como todos los extras.
      </p>
      {items.map((it) => (
        <div className="card" key={it.id}>
          <div className="row muted">
            <span>{it.day}</span><span>·</span><span>{it.people?.name}</span><span>·</span>
            <span>{it.section === "extra" ? "Extra" : "Ayer"}</span>
            <span>·</span><span>Hilo de Slack: {it.slack_ts}</span>
          </div>
          <div className="raw">{it.raw_text}</div>
          <p className="muted">{it.note ? `Nota: ${it.note}` : it.reason}{it.monday_url ? ` · ${it.monday_url}` : ""}</p>
          <form action={marcarLinea.bind(null, it.id)} className="row">
            <select name="mark" defaultValue="" required>
              <option value="" disabled>Elige…</option>
              <option value="hecho">✅ Hecho</option>
              <option value="pendiente">🔄 Pendiente (avancé, no cerré)</option>
              <option value="no_tocado">⬜ No lo toqué</option>
              <option value="descartar">Descartar línea</option>
            </select>
            <input type="text" name="text" defaultValue={it.raw_text} aria-label="Texto" style={{ flex: 1, minWidth: 200 }} />
            <button className="primary">Guardar</button>
          </form>
        </div>
      ))}
    </>
  );
}
