import type { PorResponsavelRow } from "../types";

// Lead time médio (1ª etapa -> Migrado, só cohort fechado) por responsável ATUAL — mesmo
// padrão CSS do TempoEtapaChart. `nomeDe` resolve email -> nome (ver TempoEtapasView).
export function PorResponsavelChart({ title, rows, nomeDe, nounPlural = "EGPs", nounSingular = "EGP", terminal = "migrado" }: {
  title: string; rows: PorResponsavelRow[]; nomeDe: (email: string) => string;
  nounPlural?: string; nounSingular?: string; terminal?: string;
}) {
  const max = Math.max(1, ...rows.map((r) => r.media_dias));
  const totalN = rows.reduce((s, r) => s + r.n, 0);

  return (
    <div className="funnel">
      <div className="funnel-head">
        <h3>{title}</h3>
        <div className="funnel-prog" title={`${nounPlural} já ${terminal}s, agrupados pelo responsável de hoje`}>
          <span className="fp-num">{totalN} {nounPlural} {terminal}s</span>
        </div>
      </div>

      {rows.length === 0 ? (
        <div className="funnel-empty">Nenhum {nounSingular} {terminal} com responsável atribuído neste recorte.</div>
      ) : (
        <div className="te-rows">
          {rows.map((r) => {
            const w = Math.max(2, (r.media_dias / max) * 100);
            const label = r.responsavel === "Sem responsável" ? r.responsavel : nomeDe(r.responsavel);
            return (
              <div className="te-row" key={r.responsavel}>
                <div className="te-label" title={r.responsavel}>{label}</div>
                <div className="te-track">
                  <div className="te-bar te-bar-conosco" style={{ width: `${w}%` }}
                    title={`${label} · média ${r.media_dias}d (n=${r.n})`} />
                </div>
                <div className="te-value">{r.media_dias.toLocaleString("pt-BR")}d <span className="te-n">(n={r.n})</span></div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
