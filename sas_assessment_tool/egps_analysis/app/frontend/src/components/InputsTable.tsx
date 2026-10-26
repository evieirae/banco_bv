import { useEffect, useRef, useState } from "react";
import { useVirtualizer } from "@tanstack/react-virtual";
import type { InputRow, Analista, PreworkingRow } from "../types";
import type { GestaoRow } from "../gestaoApi";
import { isDynamicRef, DYNAMIC_REF_TITLE, fmtAreas, effEtapa, effStatusInput, preworkingPercentual, chavesDoInput, confirmEscritaFamilia, travaDerivada } from "../inputs";
import { PIPELINE_INPUT, STATUS_INPUT, SEG } from "../pipeline";
import { InputDetailPanel } from "./InputDetailPanel";
import { confirmStatusTerminal } from "../pipeline";
import { DetailModal } from "./DetailModal";
import { pathFor, spaLinkClick } from "../routes";
import { usePodeEscrever } from "../usePodeEscrever";

export type InputSortKey =
  | "artifact" | "categoria" | "origem" | "areas" | "source_types" | "qtd_projetos"
  | "n_proj_ativos" | "modernizada_auto" | "responsavel" | "observacao";

interface Props {
  rows: InputRow[];
  loading: boolean;
  onPatch: (chave: string, patch: Partial<InputRow>) => void;
  onBodyScroll?: (e: React.UIEvent<HTMLElement>) => void;  // auto-recolher do cabeçalho
  onClearFilters?: () => void;   // botão do estado vazio (mantém só o escopo)
  onSort: (k: InputSortKey) => void;
  indicator: (k: InputSortKey) => string;
  onOpenEgp: (projeto: string) => void;
  analistas: Analista[];
  // artifact(UPPER) -> { n: EGPs bloqueados (transitivo), sole: EGPs cuja única causa é esta tabela }
  blockStats?: Map<string, { n: number; sole: number }>;
  gestaoById?: Map<string, GestaoRow>;   // chave_canonica → linha de gestão (p/ o "Último status")
  preworkingById?: Map<string, PreworkingRow>;   // chave_canonica → checklist de pré-working
  abrir?: string | null;                  // deep-link: chave a abrir quando ela existir em `rows`
  onAbriu?: () => void;                   // avisa o App p/ limpar o estado do deep-link
  onOpenChange?: (chave: string | null) => void;   // espelha o drawer aberto na URL
}

const ROW_H = 40;

export function isDivergent(r: InputRow): boolean {
  // Família não tem "divergência humano × automático": `etapa` dela é um roll-up das
  // safras, não uma edição humana, e `modernizada_auto` só é Disponível quando TODAS as
  // safras estão — comparar os dois acenderia o ⚠ em família mista (47 sanitizadas +
  // 11 modernizadas), que não é contradição nenhuma.
  if (r.is_familia) return false;
  if (!r.etapa) return false;
  const humanModern = r.etapa === "Modernizado" || r.status === "Sanitizado" || r.status === "Autoprodutor";
  const autoModern = r.modernizada_auto === "Disponível";
  return humanModern !== autoModern;
}

// A API (Statement Execution) devolve booleano como string ("true"/"false"); "false"
// é truthy em JS. Por isso comparamos explicitamente para a tag só aparecer em órfãos reais.
function isOrfao(r: InputRow): boolean {
  const v = r.orfao as unknown;
  return v === true || v === "true";
}

export function InputsTable({ rows, loading, onPatch, onSort, indicator, onOpenEgp, analistas, blockStats, gestaoById, preworkingById, onBodyScroll, onClearFilters, abrir, onAbriu, onOpenChange }: Props) {
  const parentRef = useRef<HTMLDivElement>(null);
  const pode = usePodeEscrever();
  const analistaEmails = new Set(analistas.map((a) => a.email));
  // Detalhe do input em MODAL centrado (um por vez) — substituiu o expand inline
  // (.rd-expand-detail): em notebook o inline virava scroll aninhado (pedido 2026-08-28).
  // measureElement/getItemKey ficam: a medição dinâmica é inócua com linhas de altura fixa.
  const [openChave, setOpenChave] = useState<string | null>(null);
  const toggle = (chave: string) => setOpenChave((cur) => {
    const next = cur === chave ? null : chave;
    onOpenChange?.(next);
    return next;
  });
  // deep-link: a linha pode só aparecer depois que o recorte/filtro assentar lá em cima.
  useEffect(() => {
    if (!abrir || !rows.some((r) => r.chave_canonica === abrir)) return;
    setOpenChave(abrir);
    onAbriu?.();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [abrir, rows]);
  // filtro pode remover a linha aberta -> modal fecha sozinho (openRow vira undefined)
  const openRow = openChave ? rows.find((r) => r.chave_canonica === openChave) : undefined;
  const virt = useVirtualizer({
    count: rows.length,
    getScrollElement: () => parentRef.current,
    estimateSize: () => ROW_H,
    overscan: 12,
    getItemKey: (index) => rows[index].chave_canonica,
  });

  const H = (k: InputSortKey, label: string, cls: string) => (
    <div className={`${cls} sort-th`} role="button" tabIndex={0} title="ordenar"
      onClick={() => onSort(k)}
      onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onSort(k); } }}>
      {label}{indicator(k)}
    </div>
  );

  return (
    <div className="table-wrap">
      <div className="thead">
        <div className="c-idx">#</div>
        {H("artifact", "Input", "c-art")}
        {H("categoria", "Cat.", "c-cat")}
        {H("origem", "Origem", "c-orig")}
        {H("areas", "Área(s) [Principal]|Demais", "c-area")}
        {H("source_types", "Fontes", "c-src")}
        {H("qtd_projetos", "#proj", "c-num")}
        {H("n_proj_ativos", "#ativos", "c-num")}
        {H("modernizada_auto", "Auto", "c-auto")}
        <div className="c-etapa">Etapa</div>
        <div className="c-status">Status</div>
        {H("responsavel", "Responsável", "c-resp")}
        {H("observacao", "Tbl. Corresp.", "c-obs")}
        <div className="c-lstat" title="Último status registrado na aba Gestão para este input — clique para abrir o detalhe">Último status</div>
        <div className="c-pwk" title="Checklist de pré-working (preenchido manualmente): dados para configurar a ingestão — clique na linha para expandir">Pré-Working</div>
      </div>

      <div className="tbody" ref={parentRef} onScroll={onBodyScroll}>
        <div style={{ height: virt.getTotalSize(), position: "relative" }}>
          {virt.getVirtualItems().map((vi) => {
            const r = rows[vi.index];
            const div = isDivergent(r);
            const bs = blockStats?.get(r.artifact.toUpperCase());
            // Badge longo demais p/ a linha do nome (nowrap + ellipsis no .art-name): inline ele
            // comia a coluna inteira e o input sumia da tela. Vai na 2ª linha (.art-tags), junto
            // das pílulas de bloqueio — e DEPOIS delas, que são o sinal mais acionável.
            const autoprodCand = !!r.autoprodutor_candidato && r.status !== "Autoprodutor";
            const isOpen = openChave === r.chave_canonica;
            return (
              <div
                key={vi.key}
                data-index={vi.index}
                ref={virt.measureElement}
                style={{ position: "absolute", top: 0, left: 0, right: 0, transform: `translateY(${vi.start}px)` }}
              >
                <div
                  className={`trow ${div ? "diverge" : ""} ${isOpen ? "sel" : ""} ${r.ex_dependencia ? "exdep" : ""}`}
                  style={{ height: ROW_H }}
                >
                  <div className="c-idx">{vi.index + 1}</div>
                  {/* <a> no deep-link do próprio input: botão do meio/ctrl+clique/"abrir em
                      nova guia" funcionam nativamente; o clique simples segue abrindo e
                      fechando o modal aqui. `role="button"`/`tabIndex` saíram porque a âncora
                      já é focável e ativa com Enter (que dispara o onClick); o onKeyDown fica
                      só para o ESPAÇO, que num link rolaria a página em vez de abrir. */}
                  <a className="c-art clickable" aria-haspopup="dialog"
                    href={pathFor("monitor", r.chave_canonica)}
                    title={`${r.nome_exibicao ?? r.artifact}${r.nome_exibicao ? ` — {SAFRA} marca onde a data entra no nome; chave: ${r.artifact}` : ""}`
                      + ` — clique para ${isOpen ? "fechar" : "abrir"} o detalhe · botão do meio/ctrl+clique: nova guia`}
                    onClick={(ev) => spaLinkClick(ev, () => toggle(r.chave_canonica))}
                    onKeyDown={(e) => { if (e.key === " ") { e.preventDefault(); toggle(r.chave_canonica); } }}>
                    <div className="art-name">
                      <span className="dep-caret">{isOpen ? "▾" : "▸"}</span>{" "}
                      {isOrfao(r) && <span className="tag orphan" title="órfão: sumiu do último refresh">órfão</span>}
                      {r.ex_dependencia && (
                        <span className="tag exdep" title="Consumido apenas por ex-dependências (EGPs que saíram do recorte Indicium + deps) — fora de todos os cards e indicadores; visível só com o chip 'mostrar ex-dependências'.">
                          input de ex-dependência
                        </span>
                      )}
                      {r.vinculo_ativo === false && (
                        <span className="tag nolink" title="Todos os vínculos deste input com EGPs do recorte foram marcados como quebrados — fora das contagens (cards e Resumo); visível aqui para gestão do vínculo.">
                          sem vínculo ativo
                        </span>
                      )}
                      {div && <span className="tag warn" title="etapa/status humanos divergem da detecção automática">⚠</span>}
                      {r.nome_exibicao ?? r.artifact}
                      {r.is_familia && (
                        <span className="pill familia"
                          title={`Família de safras: ${r.n_safras} tabelas datadas da mesma tabela lógica`
                            + `${r.safra_min ? ` (${r.safra_min}–${r.safra_max})` : ""}`
                            + `${r.safras_sem_mes ? ` + ${r.safras_sem_mes} com ano solto` : ""}`
                            + `. A ingestão dela é UMA tabela particionada no destino, então conta como 1 input.`
                            + `${(r.n_safras_no_recorte ?? r.n_safras) !== r.n_safras ? ` ${r.n_safras_no_recorte} delas estão neste recorte.` : ""}`
                            + `${r.n_safras_pendentes !== (r.n_safras_no_recorte ?? r.n_safras) ? ` ${r.n_safras_pendentes} pendente(s) aqui; as resolvidas não seguram a família.` : ""}`}>
                          {r.n_safras} safras
                        </span>
                      )}
                      {r.is_familia && r.estado_misto && (
                        <span className="pill misto" title="As safras desta família estão em etapas/status diferentes entre si. A linha mostra o estado da safra pendente menos avançada; editar a família alinha todas.">
                          estado misto
                        </span>
                      )}
                    </div>
                    {((bs && (bs.n > 0 || bs.sole > 0)) || autoprodCand || !!r.sanitizado_derivado) && (
                      <div className="art-tags">
                        {bs && bs.n > 0 && (
                          <span className="tag blocker" title="EGPs bloqueados (direta ou transitivamente) por esta tabela SAS/Local sem produtor e não modernizada. Um EGP pode ter várias causas, então este total sobrepõe entre pílulas.">
                            bloqueia {bs.n} EGP{bs.n > 1 ? "s" : ""}
                          </span>
                        )}
                        {bs && bs.sole > 0 && (
                          <span className="tag sole" title="EGPs cuja ÚNICA causa-raiz de bloqueio é esta tabela (transitivo): resolvê-la destrava exatamente estes.">
                            único bloqueador de {bs.sole} EGP{bs.sole > 1 ? "s" : ""}
                          </span>
                        )}
                        {autoprodCand && (
                          <span className="tag autoprod" title={`EGP "${r.autoprodutor_egp}" cria E consome esta tabela — candidato a dispensar pré-working. Confirme marcando o status como "Autoprodutor".`}>
                            🔁 candidato a autoprodutor
                          </span>
                        )}
                        {r.sanitizado_derivado && (
                          <span className="tag sanderiv" title={`Fora da fila de ingestão por derivação — nenhum status foi gravado. O status no banco continua "${r.status_real ?? "—"}" e volta sozinho se a condição deixar de valer — um consumidor repriorizado, ou o vínculo com a versão nova desfeito.`}>
                            sanitizado: {r.sanitizado_motivo}
                          </span>
                        )}
                      </div>
                    )}
                  </a>
                  <div className="c-cat">{r.categoria}</div>
                  <div className="c-orig" title={r.origem}>{r.origem}</div>
                  <div className="c-area" title={r.areas}>{fmtAreas(r.areas, r.area_principal)}</div>
                  <div className="c-src" title={r.source_types}>
                    {r.source_types}
                    {isDynamicRef(r) && (
                      <span className="pill dinamica" title={DYNAMIC_REF_TITLE}>ref. dinâmica</span>
                    )}
                    {r.paths_fisicos && (
                      <div className="src-path" title={r.paths_fisicos}>
                        {Number(r.n_paths_fisicos) > 1 && (
                          <span className="pill homonimo" title={r.categoria === "tabela"
                            ? "mesmo nome SAS/Local = N tabelas físicas distintas (linhagem por path)"
                            : "mesmo nome de arquivo em N pastas diferentes — a chave deste input é o basename, então as N viraram uma linha"}>
                            homônimo ×{r.n_paths_fisicos}
                          </span>
                        )}{" "}
                        {r.paths_fisicos}
                      </div>
                    )}
                  </div>
                  <div className="c-num">{r.qtd_projetos}</div>
                  <div className="c-num" title="EGPs consumidores dentro do recorte Indicium + deps, sem despriorização e sem vínculo quebrado">{r.n_proj_ativos ?? ""}</div>
                  <div className="c-auto">
                    <span className={r.modernizada_auto === "Disponível" ? "pill ok" : "pill todo"}>
                      {r.modernizada_auto === "Disponível" ? "BQ" : "ingerir"}
                    </span>
                  </div>
                  <div className="c-etapa">
                    <select
                      value={effEtapa(r.etapa, r.modernizada_auto)}
                      disabled={!pode || !!travaDerivada(r)} title={travaDerivada(r)}
                      onChange={(e) => { const v = e.target.value;
                        if (!confirmEscritaFamilia(r, "etapa")) return;
                        onPatch(r.chave_canonica, { etapa: v }); }}
                    >
                      {PIPELINE_INPUT.map((s) => (
                        <option key={s} value={s}>{s}</option>
                      ))}
                    </select>
                  </div>
                  <div className="c-status">
                    {(() => {
                      const effSt = effStatusInput(r.status, r.etapa, r.modernizada_auto);
                      return (
                        <select
                          value={effSt}
                          style={{ background: SEG[effSt]?.bg, color: SEG[effSt]?.fg }}
                          disabled={!pode || !!travaDerivada(r)} title={travaDerivada(r)}
                          onChange={(e) => { const v = e.target.value;
                            if (!confirmStatusTerminal(v, r.artifact)) return;
                            if (!confirmEscritaFamilia(r, `status "${v}"`)) return;
                            onPatch(r.chave_canonica, { status: v }); }}
                        >
                          {STATUS_INPUT.map((s) => (
                            <option key={s} value={s}>{s}</option>
                          ))}
                        </select>
                      );
                    })()}
                  </div>
                  <div className="c-resp">
                    <select
                      value={r.responsavel ?? ""} disabled={!pode}
                      onChange={(e) => onPatch(r.chave_canonica, { responsavel: e.target.value })}
                      title="Responsável pela ingestão deste input"
                    >
                      <option value="">—</option>
                      {r.responsavel && !analistaEmails.has(r.responsavel) && (
                        <option value={r.responsavel}>{r.responsavel}</option>
                      )}
                      {analistas.map((a) => (
                        <option key={a.email} value={a.email}>{a.nome || a.email}</option>
                      ))}
                    </select>
                  </div>
                  <div className="c-obs">
                    <input
                      defaultValue={r.observacao ?? ""}
                      placeholder="—" disabled={!pode}
                      onBlur={(e) => {
                        const v = e.target.value.trim();
                        if (v !== (r.observacao ?? "")) onPatch(r.chave_canonica, { observacao: v });
                      }}
                    />
                  </div>
                  {(() => {
                    // Gestão e pré-working seguem chaveados por SAFRA; para uma família,
                    // vale o último status entre as safras (mais recente) — não o da chave
                    // da família, que não existe naquelas tabelas.
                    const gr = r.is_familia
                      ? chavesDoInput(r).map((c) => gestaoById?.get(c)).filter(Boolean)
                          .sort((a, b) => (b!.resumoStatusData ?? "").localeCompare(a!.resumoStatusData ?? ""))[0]
                      : gestaoById?.get(r.chave_canonica);
                    if (!gr) return <div className="c-lstat muted">fora de escopo</div>;
                    const txt = gr.resumoStatus;
                    return (
                      <div className="c-lstat muted" style={{ cursor: "pointer", color: txt ? "inherit" : undefined }}
                        title={txt ?? "sem status — clique para adicionar"}
                        onClick={(e) => { e.stopPropagation(); setOpenChave(r.chave_canonica); }}>
                        {txt ?? "sem status"}
                      </div>
                    );
                  })()}
                  {(() => {
                    // Sempre a PRÓPRIA chave da linha, família inclusive. O checklist é
                    // config de ingestão — uma por família, não uma por carga — e o backend
                    // garante que a chave `familia::...` tem linha: a dela, ou a herdada da
                    // safra mais recente (`_pwk_herdadas`).
                    //
                    // Era `Math.max` sobre família + safras, o que discordava do drawer:
                    // família com safra antiga a 100% e a mais recente a 40% herda 40, mas o
                    // MAX pintava 100. Média sobre os membros também não serve — contaria a
                    // linha herdada junto das originais, dobrando a mesma informação.
                    const pct = preworkingPercentual(preworkingById?.get(r.chave_canonica));
                    const estado = pct === 100 ? "completo" : pct > 0 ? "parcial" : "vazio";
                    const title = pct === 100
                      ? "Checklist de pré-working 100% — liberado para Ingestão UAT"
                      : pct > 0
                        ? `Checklist de pré-working ${pct}% preenchido — clique na linha para completar`
                        : "Checklist de pré-working ainda não preenchido — clique na linha para preencher";
                    return (
                      <div className={`c-pwk pwk-${estado}`} title={title}>{pct}%</div>
                    );
                  })()}
                </div>
              </div>
            );
          })}
        </div>
        {!loading && rows.length === 0 && (
          <div className="empty">
            Nenhuma linha para os filtros atuais.
            {onClearFilters && (
              <button className="ghost" style={{ marginLeft: 10 }} onClick={onClearFilters}>
                limpar filtros
              </button>
            )}
          </div>
        )}
      </div>

      {openRow && (
        <DetailModal title={openRow.nome_exibicao ?? openRow.artifact}
          onClose={() => { setOpenChave(null); onOpenChange?.(null); }}>
          <InputDetailPanel row={openRow} onOpenEgp={onOpenEgp} onPatch={pode ? onPatch : undefined} analistas={analistas} />
        </DetailModal>
      )}
    </div>
  );
}
