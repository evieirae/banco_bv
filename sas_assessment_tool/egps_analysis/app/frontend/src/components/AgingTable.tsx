import type { AgingRow } from "../types";

const LIMIT = 20;

// EGPs AINDA em curso (etapa != Migrado), ordenados do mais parado pro mais recente —
// quem precisa de atenção AGORA (diferente do resto das análises, que só fecham a conta
// depois que o EGP termina). `nomeDe` resolve email -> nome (ver TempoEtapasView).
//
// `dias` total é repartido em trabalho (até o status virar "Concluído" nesta etapa) e
// espera (depois disso) — pedido 2026-09-30: um EGP concluído há 60d não está "travado
// precisando de atenção" do mesmo jeito que um ainda em andamento há 60d, mesmo contando
// o mesmo total. O total NÃO muda (aging continua somando os dois); só ficou visível qual
// parte é espera.
export function AgingTable({ title, rows, nomeDe, nounSingular = "EGP", nounPlural = "EGPs", colLabel = "EGP" }: {
  title: string; rows: AgingRow[]; nomeDe: (email: string) => string;
  nounSingular?: string; nounPlural?: string; colLabel?: string;
}) {
  const shown = rows.slice(0, LIMIT);

  return (
    <div className="funnel">
      <div className="funnel-head">
        <h3>{title}</h3>
        <div className="funnel-prog" title={`${nounPlural} com etapa viva == última transição auditada`}>
          <span className="fp-num">{rows.length} {rows.length === 1 ? nounSingular : nounPlural} em curso</span>
        </div>
      </div>

      {shown.length === 0 ? (
        <div className="funnel-empty">Nenhum {nounSingular} em curso com transição de etapa auditada neste recorte.</div>
      ) : (
        <div className="hist-table">
          <div className="aging-thead">
            <div>{colLabel}</div><div>Etapa</div><div>Dias</div><div>Responsável</div>
          </div>
          <div className="hist-tbody">
            {shown.map((r) => (
              <div className="aging-trow" key={r.projeto}>
                <div className="c-art" title={r.projeto}>{r.projeto}</div>
                <div title={r.etapa}>{r.etapa}</div>
                <div className="aging-dias"
                  title={r.dias_espera > 0
                    ? `${r.dias_trabalho}d de trabalho até Concluído + ${r.dias_espera}d de espera depois`
                    : "sem status Concluído registrado nesta etapa — tudo trabalho"}>
                  {r.dias}d
                  {r.dias_espera > 0 && <span className="aging-espera"> ({r.dias_espera}d espera)</span>}
                </div>
                <div title={r.responsavel ?? ""}>{r.responsavel ? nomeDe(r.responsavel) : "—"}</div>
              </div>
            ))}
          </div>
        </div>
      )}
      {rows.length > LIMIT && (
        <p className="muted" style={{ marginTop: 8 }}>mostrando os {LIMIT} mais parados de {rows.length}</p>
      )}
    </div>
  );
}
