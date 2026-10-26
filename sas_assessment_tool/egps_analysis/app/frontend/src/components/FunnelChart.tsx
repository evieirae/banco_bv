import type { FunnelData } from "../types";
import { SEG, SEG_ORDER } from "../pipeline";

// Funil empilhado (CSS, sem dependência de chart lib). Cada barra = 1 etapa, normalizada
// ao coorte (todas as barras somam o coorte → altura 100%); segmentos = % por status.
export function FunnelChart({ title, data, unidade = "projetos" }: {
  title: string;
  data: FunnelData;
  unidade?: string;
}) {
  const total = data.coorte || 1;
  const pct = data.total ? Math.round((data.migrados / data.total) * 1000) / 10 : 0;
  const segsPresentes = SEG_ORDER.filter((s) => data.bars.some((b) => b.seg[s]));
  const TONE: Record<string, string> = { ok: "var(--ok)", mut: "var(--mut)", wip: "var(--warn)", danger: "var(--danger)" };

  return (
    <div className="funnel">
      <div className="funnel-head">
        <h3>{title}</h3>
        <div className="funnel-prog" title={`${data.migrados} de ${data.total} ${unidade}`}>
          <span className="fp-num">{data.migrados}/{data.total}</span>
          <div className="prog-track"><div className="prog-fill" style={{ transform: `scaleX(${pct / 100})` }} /></div>
          <span className="fp-pct">{pct.toLocaleString("pt-BR")}%</span>
        </div>
      </div>

      {data.top_stats && data.top_stats.length > 0 && (
        <div className="funnel-topstats">
          {data.top_stats.map((t) => (
            <span key={t.label} className="fts" title={`${t.label}: ${t.value} ${unidade}`}>
              <i style={{ background: TONE[t.tone ?? "mut"] }} />{t.label}: <b>{t.value.toLocaleString("pt-BR")}</b>
            </span>
          ))}
        </div>
      )}

      {data.coorte === 0 ? (
        <div className="funnel-empty">Sem itens neste funil ainda — defina etapa/status nos EGPs.</div>
      ) : (
        <div className="funnel-bars">
          {data.bars.map((b) => {
            const etapaLabel = b.etapa;
            return (
            <div className="fb-col" key={b.etapa}>
              <div className="fb-stack">
                {SEG_ORDER.filter((s) => b.seg[s]).map((s) => {
                  const h = (b.seg[s] / total) * 100;
                  return (
                    <div key={s} className="fb-seg" style={{ height: `${h}%`, background: SEG[s].bg, color: SEG[s].fg }}
                      title={`${etapaLabel} · ${s}: ${b.seg[s]}`}>
                      {h >= 7 ? b.seg[s] : ""}
                    </div>
                  );
                })}
              </div>
              <div className="fb-label" title={etapaLabel}>{etapaLabel}</div>
            </div>
            );
          })}
        </div>
      )}

      <div className="funnel-legend">
        {segsPresentes.map((s) => (
          <span key={s} className="leg"><i style={{ background: SEG[s].bg }} />{s}</span>
        ))}
      </div>
    </div>
  );
}
