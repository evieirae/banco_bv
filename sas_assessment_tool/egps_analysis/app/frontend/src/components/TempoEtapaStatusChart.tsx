import type { TempoEtapaRow } from "../types";
import { SEG, SEG_ORDER } from "../pipeline";

// Mesmo dado do TempoEtapaChart (tempo médio por etapa), mas repartido por STATUS_PROJETO
// em vez de Com BV/Conosco — corte ORTOGONAL, não um refinamento do outro. Reaproveita a
// paleta SEG do FunnelChart pra ficar visualmente consistente com o funil acima.
export function TempoEtapaStatusChart({ title, rows, nounPlural = "EGPs" }: {
  title: string; rows: TempoEtapaRow[]; nounPlural?: string;
}) {
  const max = Math.max(1, ...rows.map((r) => r.media_dias ?? 0));
  const comAmostra = rows.filter((r) => r.n > 0);
  const totalN = comAmostra.reduce((s, r) => s + r.n, 0);
  const segsPresentes = SEG_ORDER.filter((s) => rows.some((r) => r.por_status.some((p) => p.status === s)));

  return (
    <div className="funnel tempo-etapa">
      <div className="funnel-head">
        <h3>{title}</h3>
        <div className="funnel-prog" title={`${nounPlural} com pelo menos 1 transição de etapa auditada`}>
          <span className="fp-num">{totalN} amostra{totalN === 1 ? "" : "s"}</span>
        </div>
      </div>

      {comAmostra.length === 0 ? (
        <div className="funnel-empty">
          Sem transições de etapa auditadas ainda — o histórico começa a partir da 1ª mudança de etapa feita no app.
        </div>
      ) : (
        <>
          <div className="te-rows">
            {rows.map((r) => (
              <div className="te-row" key={r.etapa}>
                <div className="te-label" title={r.etapa}>{r.etapa}</div>
                <div className="te-track">
                  {SEG_ORDER.filter((s) => r.por_status.some((p) => p.status === s)).map((s) => {
                    const p = r.por_status.find((p) => p.status === s)!;
                    const w = (p.media_dias / max) * 100;
                    return (
                      <div key={s} className="te-bar" style={{ width: `${w}%`, background: SEG[s].bg }}
                        title={`${r.etapa} · ${s}: ${p.media_dias}d (média)`} />
                    );
                  })}
                </div>
                <div className="te-value">
                  {r.media_dias != null
                    ? <>{r.media_dias.toLocaleString("pt-BR")}d <span className="te-n">(n={r.n})</span></>
                    : <span className="te-n">sem dados</span>}
                </div>
              </div>
            ))}
          </div>
          <div className="funnel-legend">
            {segsPresentes.map((s) => (
              <span key={s} className="leg"><i style={{ background: SEG[s].bg }} />{s}</span>
            ))}
          </div>
        </>
      )}
    </div>
  );
}
