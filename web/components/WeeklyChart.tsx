// Una serie semanal en porcentaje (0 a 100). Las semanas sin datos quedan como hueco.
// Un gráfico por métrica (small multiples), sin leyenda: el título nombra la serie.
export type Punto = { semana: string; valor: number | null; detalle: string };

export function WeeklyChart({ title, points }: { title: string; points: Punto[] }) {
  const w = 340, h = 170, l = 36, r = 22, t = 12, b = 26;
  const pw = w - l - r, ph = h - t - b, n = points.length;
  const x = (i: number) => l + (n === 1 ? pw / 2 : (pw * i) / (n - 1));
  const y = (v: number) => t + ph * (1 - v / 100);

  const segments: string[][] = [];
  let seg: string[] = [];
  points.forEach((p, i) => {
    if (p.valor === null) {
      if (seg.length) segments.push(seg);
      seg = [];
    } else seg.push(`${x(i).toFixed(1)},${y(p.valor).toFixed(1)}`);
  });
  if (seg.length) segments.push(seg);
  const step = Math.max(1, Math.floor(n / 6));

  return (
    <figure className="chart">
      <figcaption>{title}</figcaption>
      <svg viewBox={`0 0 ${w} ${h}`} role="img" aria-label={title}>
        {[0, 50, 100].map((v) => (
          <g key={v}>
            <line className="grid" x1={l} x2={w - r} y1={y(v)} y2={y(v)} />
            <text className="axis" x={l - 6} y={y(v) + 4} textAnchor="end">{v}%</text>
          </g>
        ))}
        {segments.filter((s) => s.length > 1).map((s, i) => <polyline key={i} className="line" points={s.join(" ")} />)}
        {points.map((p, i) => (
          <g key={p.semana}>
            {i % step === 0 || i === n - 1 ? (
              <text className="axis" x={x(i)} y={h - 8} textAnchor={i === n - 1 && n > 1 ? "end" : "middle"}>
                {p.semana.slice(5)}
              </text>
            ) : null}
            {p.valor !== null ? (
              <>
                <circle className="hit" cx={x(i)} cy={y(p.valor)} r={12}>
                  <title>{`Semana del ${p.semana}: ${p.valor.toFixed(1)}% (${p.detalle})`}</title>
                </circle>
                <circle className="dot" cx={x(i)} cy={y(p.valor)} r={4}>
                  <title>{`Semana del ${p.semana}: ${p.valor.toFixed(1)}% (${p.detalle})`}</title>
                </circle>
              </>
            ) : null}
          </g>
        ))}
      </svg>
    </figure>
  );
}
