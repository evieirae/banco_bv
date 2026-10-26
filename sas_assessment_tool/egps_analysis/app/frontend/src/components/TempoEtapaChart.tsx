import type { TempoEtapaRow } from "../types";

// Tempo médio (dias) que os EGPs passaram em cada etapa do funil de migração, repartido
// entre "Conosco" (trabalho nosso) e "Com BV" (bloqueado esperando a área/banco) — barras
// horizontais empilhadas em CSS puro (mesmo padrão sem-lib do FunnelChart). Comprimento
// proporcional à média total; etapa sem amostra (n=0) mostra "sem dados" em vez de barra vazia.
export function TempoEtapaChart({ title, rows, nounPlural = "EGPs" }: {
  title: string; rows: TempoEtapaRow[]; nounPlural?: string;
}) {
  const max = Math.max(1, ...rows.map((r) => r.media_dias ?? 0));
  const comAmostra = rows.filter((r) => r.n > 0);
  const totalN = comAmostra.reduce((s, r) => s + r.n, 0);

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
            {rows.map((r) => {
              const wConosco = r.media_dias_conosco != null ? (r.media_dias_conosco / max) * 100 : 0;
              const wComBv = r.media_dias_com_bv != null ? (r.media_dias_com_bv / max) * 100 : 0;
              return (
                <div className="te-row" key={r.etapa}>
                  <div className="te-label" title={r.etapa}>{r.etapa}</div>
                  <div className="te-track">
                    {r.media_dias != null ? (
                      <>
                        {wConosco > 0 && (
                          <div className="te-bar te-bar-conosco" style={{ width: `${wConosco}%` }}
                            title={`${r.etapa} · Conosco: ${r.media_dias_conosco}d (média)`} />
                        )}
                        {wComBv > 0 && (
                          <div className="te-bar te-bar-combv" style={{ width: `${wComBv}%` }}
                            title={`${r.etapa} · Com BV: ${r.media_dias_com_bv}d (média)`} />
                        )}
                      </>
                    ) : null}
                  </div>
                  <div className="te-value">
                    {r.media_dias != null
                      ? <>{r.media_dias.toLocaleString("pt-BR")}d <span className="te-n">(n={r.n})</span></>
                      : <span className="te-n">sem dados</span>}
                  </div>
                </div>
              );
            })}
          </div>
          <div className="funnel-legend">
            <span className="leg"><i className="te-leg-conosco" />Conosco</span>
            <span className="leg"><i className="te-leg-combv" />Com BV</span>
          </div>
        </>
      )}
    </div>
  );
}
