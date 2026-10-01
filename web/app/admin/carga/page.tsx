import Link from "next/link";
import { requireAdmin } from "@/lib/auth";
import { COLUMNS, DISCLAIMER, fmtCountPct, fmtDays, fmtNum, fmtRatio, libreNote, parseRange, parseSort, sortRows } from "@/lib/carga";
import { loadCarga } from "@/lib/data/carga";

type Q = { desde?: string; hasta?: string; orden?: string; dir?: string };

export default async function Carga({ searchParams }: { searchParams: Promise<Q> }) {
  await requireAdmin();
  const q = await searchParams;
  const [desde, hasta] = parseRange(q);
  const { sort, desc } = parseSort(q);
  const { rows, days } = await loadCarga(desde, hasta);
  const filas = sortRows(rows, sort, desc);
  const note = libreNote(days);
  const qs = (extra: Record<string, string>) => new URLSearchParams({ desde, hasta, ...extra }).toString();

  return (
    <>
      <h1>Carga y cumplimiento por persona</h1>
      <form className="row" method="get">
        <label>Desde <input type="date" name="desde" defaultValue={desde} /></label>
        <label>Hasta <input type="date" name="hasta" defaultValue={hasta} /></label>
        <input type="hidden" name="orden" value={sort} />
        <input type="hidden" name="dir" value={desc ? "desc" : "asc"} />
        <button>Aplicar</button>
      </form>
      <p className="muted">
        {days.length} días de Daily entre {desde} y {hasta}. Las columnas 2 a 6 usan solo días con formato de marcas.
      </p>
      {note ? <p className="warn">{note}</p> : null}
      <div className="scroll">
        <table>
          <thead>
            <tr>
              {COLUMNS.map(([key, label]) => {
                const next = sort === key && desc ? "asc" : "desc";
                const arrow = sort === key ? (desc ? " ↓" : " ↑") : "";
                return (
                  <th key={key} className={key === "persona" ? "" : "n"}>
                    <Link href={`/admin/carga?${qs({ orden: key, dir: next })}`}>{label}{arrow}</Link>
                  </th>
                );
              })}
            </tr>
          </thead>
          <tbody>
            {filas.map((r) => (
              <tr key={r.person_id}>
                <td><Link href={`/admin/persona/${r.person_id}?${qs({})}`}>{r.persona}</Link></td>
                <td className="n">
                  {fmtDays({ ...r, dias_pto: 0 })}
                  {r.dias_pto ? <div className="muted small">{r.dias_pto} {r.dias_pto === 1 ? "día" : "días"} de PTO</div> : null}
                </td>
                <td className="n">{fmtNum(r.compromisos_por_dia)}</td>
                <td className="n">{fmtRatio(r.hechos, r.marcados, r.pct_hechos)}</td>
                <td className="n">{fmtCountPct(r.sin_tocar, r.pct_sin_tocar)}</td>
                <td className="n">{r.alertas_tercer_dia}</td>
                <td className="n">{r.sin_marca}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="muted">{DISCLAIMER}</p>
      <p><a className="button" href={`/admin/carga/csv?${qs({ orden: sort, dir: desc ? "desc" : "asc" })}`}>Exportar a CSV</a></p>
    </>
  );
}
