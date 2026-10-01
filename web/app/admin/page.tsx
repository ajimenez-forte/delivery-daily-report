import { requireAdmin } from "@/lib/auth";
import { createClient } from "@/lib/supabase/server";
import { aprobarImportacion } from "./actions";

type Resumen = {
  dias: { total: number; libre: number; marcas: number; desde: string | null; hasta: string | null };
  personas: { persona: string; libre: number; marcas: number; total: number; ayer_en_la_app: number }[];
  marcas: { ayer_hecho: number; ayer_pendiente: number; ayer_no_tocado: number; extras_marcados: number; corregidos_a_mano: number };
  hoy: { total: number; sin_link: number; tercer_dia_o_mas: number };
  revision: { total: number; pendientes: number; resueltas: number; descartadas: number };
  ultima_corrida: { id: number; estado: string; terminada: string | null; avisos: string[] } | null;
};

export default async function Importacion() {
  await requireAdmin();
  const supabase = await createClient();
  const [{ data: r, error }, { data: estado }] = await Promise.all([
    supabase.rpc("resumen_importacion"), supabase.rpc("estado_aprobacion"),
  ]);
  if (error) throw new Error(error.message);
  const s = r as Resumen;
  const a = estado?.[0];

  return (
    <>
      <h1>Resumen de importación</h1>
      {a?.aprobado ? <p className="ok">Aprobado el {a.aprobado_en}</p> : (
        <div className="card">
          <p className="warn">Pendiente de aprobación. La app no se lanza hasta aprobar la última importación.</p>
          <form action={aprobarImportacion}><button className="primary">Aprobar importación y permitir lanzamiento</button></form>
        </div>
      )}
      <h2>Días importados: {s.dias.total}</h2>
      <p>{s.dias.desde} a {s.dias.hasta} · texto libre {s.dias.libre} · con marcas {s.dias.marcas}</p>
      <h2>Reportes por persona</h2>
      <div className="scroll"><table>
        <thead><tr><th>Persona</th><th className="n">Texto libre</th><th className="n">Con marcas</th><th className="n">Total</th><th className="n">&quot;Ayer&quot; el primer día</th></tr></thead>
        <tbody>{s.personas.map((p) => (
          <tr key={p.persona}><td>{p.persona}</td><td className="n">{p.libre}</td><td className="n">{p.marcas}</td><td className="n">{p.total}</td><td className="n">{p.ayer_en_la_app}</td></tr>
        ))}</tbody>
      </table></div>
      <h2>Compromisos con marca</h2>
      <p>Ayer: ✅ {s.marcas.ayer_hecho} · 🔄 {s.marcas.ayer_pendiente} · ⬜ {s.marcas.ayer_no_tocado} · extras marcados {s.marcas.extras_marcados} · corregidos a mano {s.marcas.corregidos_a_mano}</p>
      <h2>Compromisos de Hoy: {s.hoy.total}</h2>
      <p>Sin link: {s.hoy.sin_link} · en tercer día o más: {s.hoy.tercer_dia_o_mas}</p>
      <h2>Revisión</h2>
      <p>{s.revision.total} líneas · pendientes <b>{s.revision.pendientes}</b> · resueltas {s.revision.resueltas} · descartadas {s.revision.descartadas}</p>
      {s.ultima_corrida?.avisos?.length ? (<><h2>Avisos</h2><ul>{s.ultima_corrida.avisos.map((w, i) => <li key={i}>{w}</li>)}</ul></>) : null}
    </>
  );
}
