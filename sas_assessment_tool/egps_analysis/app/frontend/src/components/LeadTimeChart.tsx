import type { LeadTimeStats } from "../types";

// Tempo total (dias) da 1ª transição de etapa até "Migrado" — só EGPs que já chegaram lá
// (cohort fechado). Barras horizontais por mês de chegada, pra ver a tendência do funil
// acelerando/desacelerando — mesmo padrão CSS do TempoEtapaChart, sem lib de chart.
export function LeadTimeChart({ title, data, nounPlural = "EGPs", nounSingular = "EGP", terminal = "Migrado" }: {
  title: string; data: LeadTimeStats; nounPlural?: string; nounSingular?: string; terminal?: string;
}) {
  const max = Math.max(1, ...data.por_mes.map((m) => m.media_dias));

  return (
    <div className="funnel">
      <div className="funnel-head">
        <h3>{title}</h3>
        <div className="funnel-prog" title={`${data.n} ${nounPlural} que já chegaram em ${terminal}`}>
          <span className="fp-num">
            {data.media_dias != null ? `média ${data.media_dias}d · mediana ${data.mediana_dias}d` : "sem dados"}
          </span>
          <span className="fp-pct">n={data.n}</span>
        </div>
      </div>

      {data.por_mes.length === 0 ? (
        <div className="funnel-empty">Nenhum {nounSingular} chegou em "{terminal}" ainda neste recorte.</div>
      ) : (
        <div className="te-rows">
          {data.por_mes.map((m) => {
            const w = Math.max(2, (m.media_dias / max) * 100);
            return (
              <div className="te-row" key={m.mes}>
                <div className="te-label" title={m.mes}>{m.mes}</div>
                <div className="te-track">
                  <div className="te-bar te-bar-conosco" style={{ width: `${w}%` }}
                    title={`${m.mes} · média ${m.media_dias}d (n=${m.n})`} />
                </div>
                <div className="te-value">{m.media_dias.toLocaleString("pt-BR")}d <span className="te-n">(n={m.n})</span></div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
