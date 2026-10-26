import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "../api";
import type { EgpAtualizadoRow } from "../types";
import { pathFor, spaLinkClick } from "../routes";
import { SEG } from "../pipeline";

// Comparação de uma versão recebida com o antecessor: deltas antigo×novo, impactos da
// troca, inputs novos, outputs removidos com consumidor externo, histórico de versões,
// autor e data do último save. Fonte: as 5 tabelas sas_egp_atualizados*, carregadas pelo
// script local publish_egps_atualizados.py (ADR 0001 — o app nunca escreve nelas).
//
// Vivia na aba "EGPs Atualizados", aposentada em 2026-09 (spec §5): é o que ela tinha de
// ÚNICO, e virou seção do detalhe do EGP (EgpDetailPanel → "Versão atualizada"). O resto
// da aba — lista, cards, chips de Situação, CSV próprio e o funil editável por versão —
// saiu: o sucessor é linha da aba EGPs e usa sas_egp_pipeline.

const SITUACAO_LABEL: Record<string, string> = {
  disponivel: "Disponível (na carga)",
  a_ingerir: "Requer ingestão",
  arquivo: "Arquivo",
  script: "Script",
};

// Os dois valores da antiga taxonomia "Situação" que NÃO são tipo de vínculo: dizem que a
// comparação não pôde ser feita. Ficam como PENDÊNCIA — sem branch própria, "Falha na
// extração" caía no default e aparecia como "atualizado", implicando seguro trocar quando
// a comparação nunca rodou. Mesmo par de PENDENCIA_POR_QUADRANTE (backend).
const PENDENCIA: Record<string, string> = {
  "Par não resolvido": "pareamento não resolvido — indique o antecessor na carga (--antigo)",
  "Falha na extração": "falha na extração — um dos lados não pôde ser lido; a comparação não rodou, sem score",
};

function fmtData(iso: string | null): string {
  if (!iso) return "—";
  const [y, m, d] = iso.split("-");
  return y && m && d ? `${d}/${m}/${y}` : iso;
}

const RECORTE_LABEL: Record<string, { label: string; cls: string }> = {
  indi: { label: "escopo Indicium", cls: "ms-badge scope" },
  dep: { label: "dependência", cls: "ms-badge dep" },
  ex: { label: "ex-dependência", cls: "ms-badge exdep" },
  fora: { label: "fora do recorte", cls: "mf-flag mf-warn" },
};

// Callout de recorte do antecessor, no topo: fica EVIDENTE quando o EGP antigo não está no
// escopo nem é dependência (a troca não mexe nos indicadores atuais) — e, quando está,
// mostra onde ele se encaixa.
function RecorteAntecessor({ ants, inedito }: {
  ants: EgpAtualizadoRow["antecessores"] | undefined; inedito: boolean;
}) {
  if (inedito || !ants?.length || ants.every((a) => a.recorte == null)) return null;
  const dentro = ants.filter((a) => a.recorte && a.recorte !== "fora");
  const nome = (p: string) => (p.includes("__") ? p.split("__").slice(1).join("__") : p);
  if (dentro.length === 0) {
    return (
      <div className="lin-hint" style={{ fontSize: 13 }}>
        🚫 <b>Antecessor fora do recorte</b>: o EGP anterior não está no escopo Indicium
        nem entra como dependência — a troca desta versão <b>não altera os indicadores
        atuais</b> (adotar = decisão de incluir no escopo).
      </div>
    );
  }
  return (
    <div className="lin-hint" style={{ fontSize: 13 }}>
      ✅ <b>Antecessor no recorte</b>:{" "}
      {ants.map((a, i) => {
        const r = RECORTE_LABEL[a.recorte ?? "fora"];
        return (
          <span key={a.projeto}>
            {i > 0 && " · "}
            {nome(a.projeto)} <span className={r.cls}>{r.label}</span>
          </span>
        );
      })}
    </div>
  );
}

export function EgpAtualizadoDetail({ versaoId, onOpenInput }: {
  // versão recebida a exibir; o histórico navega entre as versões da mesma egp_key SEM
  // sair do detalhe do EGP (a aba tinha deep-link próprio, /egps-atualizados/<versao_id>,
  // que saiu junto com ela).
  versaoId: string;
  onOpenInput?: (chave: string) => void;
}) {
  const [vid, setVid] = useState(versaoId);
  useEffect(() => { setVid(versaoId); }, [versaoId]);
  const dQ = useQuery({
    queryKey: ["egp-atualizado", vid],
    queryFn: () => api.egpAtualizadoDetalhe(vid),
  });

  const d = dQ.data;
  const v = d?.versao;
  const inputs = d?.inputs ?? [];
  const outputs = d?.outputs ?? [];
  const historico = d?.historico ?? [];
  const removidos = outputs.filter((o) => o.removido);
  const inedito = !!v && !v.egp_original;
  const pendencia = v ? PENDENCIA[v.quadrante ?? ""] : undefined;

  if (dQ.isFetching && !d) return <div className="empty">carregando detalhe…</div>;
  if (dQ.error) return <div className="error">{String(dQ.error)}</div>;
  if (!v) return null;

  return (
    <div className="input-detail">
      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <strong style={{ fontSize: 13 }}>{v.nome}</strong>
        <span className="de-meta">{v.versao_id}</span>
      </div>

      {pendencia && (
        <div className="lin-hint">
          🛑 <b>Pendência</b>: {pendencia}. Não interprete a ausência de impactos como
          seguro trocar.
        </div>
      )}

      {d && !d.mais_recente && (
        <div className="lin-hint">
          ⚠ Esta <b>não</b> é a versão recebida mais recente deste EGP — veja o histórico
          abaixo. Os dados exibidos são os desta carga.
        </div>
      )}

      <RecorteAntecessor ants={v.antecessores} inedito={inedito} />

      <div className="egpa-detail-cols">
        <div>
          <h4>Versão recebida</h4>
          <div className="drawer-meta">
            <div><span className="k">Área</span><span>{v.area}</span></div>
            <div><span className="k">Antecessor</span>
              <span>{v.egp_original ?? "— (EGP inédito, sem antecessor no corpus)"}</span></div>
            <div><span className="k">Autor (último save)</span>
              <span>{v.autor_ultimo_save ?? "?"}{v.login_autor ? ` (${v.login_autor})` : ""}</span></div>
            <div><span className="k">Último save</span><span>{fmtData(v.data_ultimo_save)}</span></div>
            <div><span className="k">Criado em</span><span>{fmtData(v.data_criacao)}</span></div>
            <div><span className="k">Recebido em</span><span>{fmtData(v.data_recebimento)}</span></div>
            <div><span className="k">Origem</span><span>{v.origem ?? "—"}</span></div>
            <div><span className="k">Arquivo</span>
              <span>{v.arquivo} · <code>{v.arquivo_hash.slice(0, 8)}</code></span></div>
            <div><span className="k">Status da troca</span><span>{v.status_troca}</span></div>
            <div><span className="k">Prontidão</span>
              {/* Mesmo guard de sempre (n_inputs > 0): sem inventário não há prontidão.
                  Mostrar "100%" quando n_inputs = 0 — que é o que sai quando a extração
                  do .egp falhou — pintava de verde justamente o caso em que nada pôde
                  ser lido. */}
              {v.n_inputs > 0
                ? <span>{v.pct}% ({v.n_disp}/{v.n_inputs} inputs resolvidos)</span>
                : <span className="de-meta">— (sem inventário de inputs para esta versão)</span>}</div>
          </div>
        </div>

        {!inedito && (
          <div>
            <h4>Comparação com o antecessor</h4>
            <div className="drawer-meta">
              <div><span className="k">Resultado</span>
                <span>{pendencia ? pendencia
                  : v.quadrante === "Sem mudança (descartar)" ? "sem mudança (descartar o envio)"
                  : v.n_vetos > 0 ? `com impacto — ${v.n_vetos} ponto(s) a conferir na troca` : "atualizado"}</span></div>
              {(v.antecessores ?? []).length > 0 && (
                <div><span className="k">Funil do antecessor</span>
                  <span>
                    {v.antecessores.map((a) => (
                      <span key={a.projeto} style={{ display: "block" }}>
                        {a.projeto.includes("__") ? a.projeto.split("__").slice(1).join("__") : a.projeto}
                        {a.recorte && (
                          <span className={RECORTE_LABEL[a.recorte].cls} style={{ marginLeft: 4 }}>
                            {RECORTE_LABEL[a.recorte].label}
                          </span>
                        )}:{" "}
                        {a.etapa ?? "fora do funil"}
                        {a.status && (
                          <span className="pill" style={SEG[a.status] ? { background: SEG[a.status].bg, color: SEG[a.status].fg, marginLeft: 4 } : { marginLeft: 4 }}>
                            {a.status}
                          </span>
                        )}
                      </span>
                    ))}
                  </span></div>
              )}
              <div><span className="k">Pareamento</span>
                <span>{v.confianca_par}
                  {v.overlap_tasks != null ? ` (overlap ${Math.round(v.overlap_tasks * 100)}%)` : ""}
                  {v.n_antecessores > 1 ? ` · ${v.n_antecessores} antecessores` : ""}</span></div>
              {v.loc_novo != null && (
                <div><span className="k">Código</span>
                  <span>{v.loc_antigo} → {v.loc_novo} LOC (+{v.linhas_add}/−{v.linhas_rem},{" "}
                    {v.tasks_novas} tasks novas)</span></div>
              )}
              {v.outputs_novo != null && (
                <div><span className="k">Outputs (bruto)</span>
                  <span title="Contagem do inventário bruto do compare (inclui temporárias WORK e nomes com macro); a lista abaixo mostra só os artefatos concretos, como na aba Outputs.">
                    {v.outputs_antigo} → {v.outputs_novo}
                    {removidos.length ? ` (${removidos.length} removidos concretos)` : ""}</span></div>
              )}
              {v.alcance_total != null && (
                <div><span className="k">Alcance do antigo</span>
                  <span>{v.alcance_total} EGP(s) downstream</span></div>
              )}
            </div>
            {v.vetos && (
              <>
                <h4>Impactos da troca (importante conferir)</h4>
                {v.vetos.split(" | ").map((x, i) => <div key={i} className="lin-hint">⚠ {x}</div>)}
              </>
            )}
            {v.alertas && (
              <>
                <h4>Alertas (pedem confirmação humana)</h4>
                {v.alertas.split(" | ").map((x, i) => <div key={i} className="lin-hint">⚠ {x}</div>)}
              </>
            )}
          </div>
        )}

        {historico.length > 1 && (
          <div>
            <h4>Histórico de versões ({historico.length})</h4>
            <div className="drawer-egps">
              {historico.map((h, i) => {
                const atual = h.versao_id === vid;
                const conteudo = (
                  <>
                    <span>
                      {fmtData(h.data_recebimento)}
                      {i === 0 && <span className="mf-flag"> mais recente</span>}
                      {atual && <span className="mf-flag"> aberta</span>}
                    </span>
                    <span className="de-meta">{h.status_troca}</span>
                  </>
                );
                const hint = `hash ${h.arquivo_hash.slice(0, 8)} · publicado em ${h.publicado_em ?? "?"}`;
                // troca a versão exibida aqui mesmo — a versão recebida não tem mais URL
                // própria (a aba dedicada, e com ela o deep-link, foram aposentadas).
                return (
                  <button key={h.versao_id} className="drawer-egp" disabled={atual}
                          style={atual ? { borderColor: "var(--accent)" } : undefined}
                          title={hint} onClick={() => setVid(h.versao_id)}>{conteudo}</button>
                );
              })}
            </div>
          </div>
        )}
      </div>

      <div className="egpa-detail-cols">
        <div style={{ flex: 1.4 }}>
          <h4>Inputs ({inputs.length})</h4>
          <div className="drawer-egps" style={{ maxHeight: "48vh" }}>
            {inputs.map((r) => (
              <div key={r.chave_canonica} className="drawer-egp" style={{ cursor: "default" }}
                   title={r.artefato}>
                <span style={{ wordBreak: "break-all" }}>
                  <span className="de-meta">{r.categoria} · </span>
                  {/* só quem existe no corpus vira link: input inédito não tem linha na aba
                      Inputs, e link que cai em "não encontrado" se lê como "sumiu do corpus",
                      que é justamente a conclusão errada aqui. */}
                  {r.no_corpus ? (
                    <a className="rd-egp-link" href={pathFor("monitor", r.chave_familia || r.chave_canonica)}
                      title={`${r.artefato}${r.chave_familia ? " — abre a família desta safra" : ""} · botão do meio/ctrl+clique: nova guia`}
                      onClick={(ev) => { if (onOpenInput) spaLinkClick(ev, () => onOpenInput(r.chave_familia || r.chave_canonica)); }}>
                      {r.categoria === "tabela" ? r.artefato
                        : r.artefato.replace(/\\/g, "/").split("/").pop()}
                    </a>
                  ) : (r.categoria === "tabela" ? r.artefato
                    : r.artefato.replace(/\\/g, "/").split("/").pop())}
                  {r.novo === true && <span className="mf-flag mf-warn"> novo</span>}
                </span>
                <span className="de-meta">
                  {r.no_corpus ? (
                    <>
                      {r.etapa_corpus || "A Receber"} / {r.status_corpus || "A Iniciar"}
                      {r.qtd_projetos != null && ` · ${r.qtd_projetos} EGP(s)`}{" "}
                      <span className={`pill ${r.disponivel_vivo ? "ok" : "todo"}`}>
                        {r.disponivel_vivo ? "resolvido" : "pendente"}
                      </span>
                    </>
                  ) : (
                    <span className="pill todo"
                          title={`fora do corpus atual — congelado na carga: ${SITUACAO_LABEL[r.situacao_no_recebimento] ?? r.situacao_no_recebimento}`}>
                      fora do corpus{r.situacao_no_recebimento === "disponivel" ? " · disp." : ""}
                    </span>
                  )}
                </span>
              </div>
            ))}
            {inputs.length === 0 && <div className="empty">sem inputs externos.</div>}
          </div>
        </div>

        <div style={{ flex: 1 }}>
          <h4>Outputs ({outputs.length}{removidos.length ? ` · ${removidos.length} removido(s)` : ""})</h4>
          <div className="drawer-egps" style={{ maxHeight: "48vh" }}>
            {outputs.map((o) => (
              <div key={`${o.situacao}:${o.chave_canonica}`} className="drawer-egp"
                   style={{ cursor: "default", opacity: o.removido ? 0.75 : 1 }} title={o.artefato}>
                <span style={{ wordBreak: "break-all" }}>
                  {o.categoria === "arquivo" && <span className="de-meta">arquivo · </span>}
                  {o.categoria === "arquivo"
                    ? o.artefato.replace(/\\/g, "/").split("/").pop()
                    : o.artefato}
                </span>
                <span className="de-meta">
                  {o.padrao && (
                    <span className="mf-flag" style={{ marginRight: 4 }}
                          title="Nome parametrizado por macro: o EGP escreve uma tabela REAL por execução (ex. safrada); o corpus não a monitora por chave, mas é output de verdade.">
                      padrão &amp;macro
                    </span>
                  )}
                  {o.removido
                    ? <span className="mf-flag mf-warn">
                        removido{o.n_consumidores_externos ? ` · ${o.n_consumidores_externos} consumidor(es)` : ""}
                      </span>
                    : o.novo === true
                      ? <span className="mf-flag">novo</span>
                      : <span>{o.situacao}</span>}
                </span>
              </div>
            ))}
            {outputs.length === 0 && <div className="empty">sem outputs permanentes.</div>}
          </div>
        </div>
      </div>
    </div>
  );
}
