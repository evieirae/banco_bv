import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "../api";
import { fmtTsBR } from "../diasUteis";
import type { AuditRow } from "../types";
import { pathFor, spaLinkClick } from "../routes";

const CAMPO_LABEL: Record<string, string> = {
  status_humano: "Status",
  responsavel: "Responsável",
  observacao: "Observação",
  etapa: "Etapa",
  status: "Status",
  escopo: "Escopo",
  ComBV: "Validação BV",
};
const artifactOf = (chave: string) => (chave.includes("::") ? chave.split("::").slice(1).join("::") : chave);
const shortName = (id: string) => (id.includes("__") ? id.split("__").slice(1).join("__") : id);
// nome de exibição do artefato conforme a aba: Monitoramento usa a chave do input; EGPs/Escopo/Vínculos usam o nome curto do EGP.
const artefatoLabel = (r: AuditRow) => (r.fonte === "Monitoramento" ? artifactOf(r.chave_canonica) : shortName(r.chave_canonica));
// Fan-out de família: o backend colapsa as N safras de UMA edição numa linha só
// (sem isso um clique virava 20 linhas e comia o limite do feed). Quando colapsou,
// o rótulo é o nome da família — `chave_canonica` é só a safra representante.
const nCargas = (r: AuditRow) => (r.fonte === "Monitoramento" && (r.n_safras ?? 1) > 1 ? r.n_safras! : 0);
const artefatoDisplay = (r: AuditRow) => (nCargas(r) && r.familia ? r.familia : artefatoLabel(r));
// Quais linhas viram link para o EGP. Só as fontes em que `chave_canonica` é comprovadamente
// um `projeto` (T_PIPE_AUD.projeto e T_LINK_AUD.projeto no /api/audit). "Escopo" fica de fora
// porque o backend cai em `projeto OR egp_dor1` — num EGP ainda não recebido a chave é o
// rótulo do DOR1, que não é rota e daria link morto.
const ehEgp = (r: AuditRow) => r.fonte === "EGPs" || r.fonte === "Vínculos";
// "Monitoramento" é input. A auditoria é gravada no grão SAFRA e a aba Inputs lista FAMÍLIA,
// então o link vai em `chave_familia` quando o backend resolveu uma (senão, a própria chave).
// Note que NÃO é o mesmo teste do rótulo: `familia`/`n_safras` descrevem o colapso desta
// consulta; `chave_familia` responde "que linha existe na aba Inputs".
const ehInput = (r: AuditRow) => r.fonte === "Monitoramento";
const chaveInput = (r: AuditRow) => r.chave_familia || r.chave_canonica;
const tituloArtefato = (r: AuditRow) =>
  (nCargas(r) ? `${r.chave_canonica} e outras ${nCargas(r) - 1} cargas` : r.chave_canonica);
const fonteCls = (f: string) => (
  f === "Monitoramento" ? "f-mon" :
  f === "EGPs" ? "f-egp" :
  f === "Vínculos" ? "f-vinc" : "f-esc"
);
// Vínculo (EGP↔Input): o campo vem como `link_broken@<chave_canonica>` do backend (não
// há coluna livre no /api/audit shape); parseia o sufixo para exibir qual input.
const campoLabel = (campo: string) => {
  if (campo.startsWith("link_broken@")) {
    const chave = campo.slice("link_broken@".length);
    return `Vínculo (EGP↔Input): ${artifactOf(chave)}`;
  }
  return CAMPO_LABEL[campo] ?? campo;
};
// Vínculos: valores vêm serializados como "True"/"False" — render mais amigável.
const valorVinculoLabel = (v: string | null | undefined) => {
  if (v === "True" || v === "true") return "Quebrado";
  if (v === "False" || v === "false") return "Linkado";
  return v || "—";
};
const EMPTY: AuditRow[] = [];   // referência estável p/ o fallback (evita re-render à toa)

export function HistoryView({ onOpenEgp, onOpenInput }: {
  onOpenEgp?: (projeto: string) => void;
  onOpenInput?: (chave: string) => void;
}) {
  const [q, setQ] = useState("");
  // useQuery p/ participar do cache compartilhado (staleTime global de 5 min): trocar de aba
  // não rebusca. Antes usava fetch em useEffect → rebuscava a cada mount. "Atualizar" e o ⟳
  // do topo forçam refetch.
  const auditQ = useQuery({ queryKey: ["audit", "all"], queryFn: () => api.audit("", 1000) });
  const rows = auditQ.data?.rows ?? EMPTY;
  const busy = auditQ.isFetching;
  const err = auditQ.error ? String(auditQ.error) : null;

  const filtered = q
    ? rows.filter((r) => (r.fonte + " " + r.chave_canonica + " " + (r.updated_by ?? "") + " " + (r.valor_novo ?? "")).toLowerCase().includes(q.toLowerCase()))
    : rows;

  return (
    <div className="history">
      <div className="filters">
        <input type="search" placeholder="filtrar por artefato, usuário ou valor…" value={q} onChange={(e) => setQ(e.target.value)} />
        <button className="ghost" onClick={() => auditQ.refetch()} disabled={busy}>Atualizar</button>
        <span className="count">{busy ? "carregando…" : `${filtered.length} edições`}</span>
      </div>
      <div className="lin-hint">
        Auditoria de <b>todas as abas</b>: edições de input (Monitoramento), etapa/status de EGP (EGPs), add/remove de escopo (Escopo) e quebra/restauração de vínculo per-(EGP, Input) (Vínculos) — cada uma com autor, horário e a <b>aba</b> de origem.
      </div>
      {err && <div className="error">{err}</div>}
      {!busy && filtered.length === 0 && <div className="empty">Nenhuma edição registrada ainda.</div>}
      {filtered.length > 0 && (
        <div className="hist-table">
          <div className="hist-thead">
            <div>Quando</div><div>Quem</div><div>Aba</div><div>Artefato</div><div>Campo</div><div>De</div><div>Para</div>
          </div>
          <div className="hist-tbody">
            {filtered.map((r, i) => (
              <div key={i} className="hist-trow">
                <div className="c-src" title={r.updated_at ?? undefined}>{fmtTsBR(r.updated_at, false)}</div>
                <div className="c-src">{r.updated_by ?? "—"}</div>
                <div><span className={`hist-fonte ${fonteCls(r.fonte)}`}>{r.fonte}</span></div>
                <div className="c-art" title={ehEgp(r) || ehInput(r) ? undefined : tituloArtefato(r)}>
                  {ehEgp(r) ? (
                    <a className="rd-egp-link" href={pathFor("readiness", r.chave_canonica)}
                      title={`${r.chave_canonica} — clique: abre o EGP · botão do meio/ctrl+clique: nova guia`}
                      onClick={(ev) => { if (onOpenEgp) spaLinkClick(ev, () => onOpenEgp(r.chave_canonica)); }}>
                      {artefatoDisplay(r)}
                    </a>
                  ) : ehInput(r) ? (
                    <a className="rd-egp-link" href={pathFor("monitor", chaveInput(r))}
                      title={`${tituloArtefato(r)}${r.chave_familia ? " — abre a família desta safra" : ""}`
                        + " · botão do meio/ctrl+clique: nova guia"}
                      onClick={(ev) => { if (onOpenInput) spaLinkClick(ev, () => onOpenInput(chaveInput(r))); }}>
                      {artefatoDisplay(r)}
                    </a>
                  ) : artefatoDisplay(r)}
                  {/* a contagem de cargas fica FORA do link: é metadado da linha de
                      auditoria, não parte do nome do artefato. */}
                  {nCargas(r) > 0 && <span className="c-src"> · {nCargas(r)} cargas</span>}
                </div>
                <div>{campoLabel(r.campo)}</div>
                <div className="c-old">{r.fonte === "Vínculos" ? valorVinculoLabel(r.valor_antigo) : (r.valor_antigo || "—")}</div>
                <div className="c-new">{r.fonte === "Vínculos" ? valorVinculoLabel(r.valor_novo) : (r.valor_novo || "—")}</div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
