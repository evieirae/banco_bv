import type { RetrabalhoStats } from "../types";

// Quantas vezes um EGP voltou pra uma etapa ANTERIOR na ordem do funil — sinal de
// retrabalho/qualidade que o resto das análises (sempre "pra frente") não captura.
export function RetrabalhoPanel({ title, data, nounSingular = "EGP", nounPlural = "EGPs" }: {
  title: string; data: RetrabalhoStats; nounSingular?: string; nounPlural?: string;
}) {
  return (
    <div className="funnel">
      <div className="funnel-head">
        <h3>{title}</h3>
        <div className="funnel-prog" title={`${nounPlural} cuja etapa regrediu ao menos 1 vez, e quantas transições de regressão ao todo`}>
          <span className="fp-num">{data.n_egps} {data.n_egps === 1 ? nounSingular : nounPlural}</span>
          <span className="fp-pct">{data.n_eventos} evento{data.n_eventos === 1 ? "" : "s"}</span>
        </div>
      </div>

      {data.pares.length === 0 ? (
        <div className="funnel-empty">Nenhuma regressão de etapa registrada neste recorte.</div>
      ) : (
        <ul className="retrab-list">
          {data.pares.map((p) => (
            <li key={`${p.de}→${p.para}`}>
              <span className="retrab-de" title={p.de}>{p.de}</span>
              <span className="retrab-arrow">→</span>
              <span className="retrab-para" title={p.para}>{p.para}</span>
              <span className="retrab-n">×{p.n}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
