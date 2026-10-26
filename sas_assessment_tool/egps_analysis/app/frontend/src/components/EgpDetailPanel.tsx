import { useEffect, useMemo, useState } from "react";
import { JiraIdInput } from "./JiraIdInput";
import { AtualizadoLinkButton } from "./AtualizadoLinkButton";
import { EgpAtualizadoDetail } from "./EgpAtualizadoDetail";
import { VinculoSucessorPanel } from "./VinculoSucessorPanel";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "../api";
import type { EgpDetail, EgpInput, OutputPipelineRow, OutputRow, ReadinessRow } from "../types";
import { RespBvInput } from "./RespBvInput";
import { usePodeEscrever } from "../usePodeEscrever";
import { PIPELINE_PROJETO, PHANTOM_ETAPAS_MIGRACAO, opcoesStatusEgp, STATUS_HELP, SEG,
  PIPELINE_INPUT, STATUS_INPUT, confirmStatusTerminal, statusTrocaLabel } from "../pipeline";
import { sugereFecharAntecessor, STATUS_FECHAMENTO } from "../vinculo";
import { egpShareUrl, pathFor, spaLinkClick } from "../routes";
import { isDynamicRef, DYNAMIC_REF_TITLE, effEtapa, effStatusInput, travaDerivada } from "../inputs";
import { mesTag, useMesPlan } from "../mesPlan";
import { OutputsDrawer } from "./OutputsDrawer";
import { DetailModal } from "./DetailModal";
import { GestaoStatusHistory } from "./GestaoStatusHistory";
import { STATUS_DESPRIORIZADO } from "./GestaoKanban";
import { gestaoApi, type GestaoRow } from "../gestaoApi";
import { useSubareas } from "../useSubareas";
import { SEM_SUBAREA, subareaDe } from "../subareas";

const EMPTY_PIPE = { migracao: { etapa: null, status: null, jira_id: null,
  responsavel: null, responsavel_bv: null } };

const shortName = (id: string) => (id.includes("__") ? id.split("__").slice(1).join("__") : id);
const indiOf = (n: { escopo_indi: string | boolean }) => n.escopo_indi === true || n.escopo_indi === "true";
const isTruthy = (v: boolean | string | null | undefined) => v === true || v === "true";

// Autoridade sobre um output do ponto de vista deste EGP:
// green  = produtor único OU escolhido como canônico
// red    = há escolhido e é OUTRO EGP (perdeu para outro produtor)
// yellow = multi-produtor sem escolha ainda ("a definir", precisa de input do negócio)
type Authority = "green" | "yellow" | "red";
const authOf = (projeto: string, r: OutputRow): Authority => {
  if (Number(r.qtd_produtores) <= 1) return "green";
  if (r.produtor_escolhido === projeto) return "green";
  if (r.produtor_escolhido) return "red";
  return "yellow";
};
const AUTH_ORDER: Record<Authority, number> = { yellow: 0, green: 1, red: 2 };
const AUTH_DOT: Record<Authority, string> = { yellow: "🟡", green: "🟢", red: "🔴" };
const AUTH_TITLE: Record<Authority, string> = {
  green: "EGP autoritativo — produtor único ou escolhido como canônico",
  yellow: "A definir — múltiplos produtores, nenhum escolhido ainda",
  red: "Outro EGP foi escolhido como produtor canônico deste output",
};
// n_paths_fisicos>1 => HOMÔNIMO (1 nome de input SAS/Local = N tabelas físicas distintas)
const nPaths = (i: EgpInput) => Number(i.n_paths_fisicos ?? 0);
const isHomonimo = (i: EgpInput) => nPaths(i) > 1;

// Nome de outro EGP citado no detalhe (depende de / alimenta / bloqueadores / despriorizadas).
// Antes era texto morto; vira link para o deep-link do EGP — clique abre no próprio modal
// (onOpenEgp) e botão do meio/ctrl+clique abrem em nova guia. Sem onOpenEgp o <a> navega
// sozinho, que continua sendo o destino certo.
function EgpRef({ projeto, onOpen }: { projeto: string; onOpen?: (p: string) => void }) {
  return (
    <a className="rd-egp-link" href={pathFor("readiness", projeto)}
      title={`${projeto} — clique: abre o EGP · botão do meio/ctrl+clique: nova guia`}
      onClick={(ev) => { if (onOpen) spaLinkClick(ev, () => onOpen(projeto)); }}>
      {shortName(projeto)}
    </a>
  );
}

export function EgpDetailPanel({ projeto, onOpenEgp, onOpenInput, row }:
  { projeto: string; onOpenEgp?: (projeto: string) => void;
    onOpenInput?: (chave: string) => void;
    // linha da tabela da aba EGPs (quando aberto por ela): alimenta as pills de
    // tipo/% modernizado/faltam do cabeçalho sem repetir o cálculo do backend.
    row?: ReadinessRow }) {
  const qc = useQueryClient();
  const { mesOf } = useMesPlan();
  const { mapa: mapaSub } = useSubareas();
  const [copied, setCopied] = useState(false);
  useEffect(() => {
    if (!copied) return;
    const t = setTimeout(() => setCopied(false), 1600);
    return () => clearTimeout(t);
  }, [copied]);
  const copyLink = async () => {
    const url = egpShareUrl(projeto);
    try {
      if (!navigator.clipboard) throw new Error("clipboard indisponível");
      await navigator.clipboard.writeText(url);
      setCopied(true);
    } catch {
      // contexto sem clipboard (http/webview) ou permissão negada: mostra o link
      // selecionável para cópia manual, em vez de falhar em silêncio.
      window.prompt("Copie o link deste EGP:", url);
    }
  };
  const egpKey = ["egp", projeto] as const;
  const egpQ = useQuery({ queryKey: egpKey, queryFn: () => api.egp(projeto), enabled: !!projeto });
  const det = egpQ.data ?? null;
  const cfgQ = useQuery({ queryKey: ["config"], queryFn: () => api.config() });
  const isGestao = !!cfgQ.data?.is_gestao;
  const pode = usePodeEscrever();

  // Outputs produzidos por este EGP — reusa duas queries já cacheadas na aba Outputs (base scope):
  //   outputs        → OutputRow[] com produtor_escolhido/qtd_produtores/terminal/…
  //   outputs-egps   → pares (chave_canonica, projeto) de todos os produtores
  // React Query dedupa: se a aba Outputs já rodou, aqui é cache hit.
  const outputsQ = useQuery({ queryKey: ["outputs", "base"], queryFn: () => api.outputs("base") });
  const pairsQ = useQuery({ queryKey: ["outputs-egps", "base"], queryFn: () => api.outputsEgps("base") });
  const producedOutputs = useMemo(() => {
    const mine = new Set(
      (pairsQ.data?.rows ?? []).filter((p) => p.projeto === projeto).map((p) => p.chave_canonica),
    );
    const rows = (outputsQ.data?.rows ?? []).filter((r) => mine.has(r.chave_canonica));
    return rows
      .map((r) => ({ row: r, auth: authOf(projeto, r) }))
      .sort((a, b) => (AUTH_ORDER[a.auth] - AUTH_ORDER[b.auth]) || a.row.artifact.localeCompare(b.row.artifact));
  }, [outputsQ.data, pairsQ.data, projeto]);
  const nOut = producedOutputs.length;
  const nOutRed = producedOutputs.filter((o) => o.auth === "red").length;
  const nOutYellow = producedOutputs.filter((o) => o.auth === "yellow").length;
  const [selOutput, setSelOutput] = useState<OutputRow | null>(null);

  // Pré-working do EGP: mesmo campo (sas_egp_pipeline) e mesma queryKey do drawer
  // GestaoStatusPanel (cache compartilhado) — editável direto na aba EGPs, junto com
  // Inputs/Outputs, sem precisar abrir o drawer de status (pedido 2026-08).
  // A linha vem da tabela da aba EGPs (`row`) quando aberto por ela: mesma função de
  // hidratação no backend (_egp_readiness_rows("base") + anexa_vinculo) em qualquer recorte,
  // então traz os mesmos campos lidos aqui (preworking*, atualizado_*, vinculo_tipo/sucessor/
  // antecessores, status). Buscar o recorte "base" inteiro só p/ ler esta linha custava o
  // endpoint mais caro do app a cada EGP aberto — fica só como fallback sem `row`.
  const readinessQ = useQuery({ queryKey: ["egp-readiness", "base"], queryFn: () => api.egpReadiness("base"),
    enabled: !row });
  const pipeRow = row ?? readinessQ.data?.rows.find((r) => r.projeto === projeto);
  const preworkingVal = pipeRow?.preworking ?? false;
  const [pwDataInput, setPwDataInput] = useState(pipeRow?.preworking_data ?? "");
  useEffect(() => { setPwDataInput(pipeRow?.preworking_data ?? ""); }, [pipeRow?.preworking_data]);
  const pwMut = useMutation({
    mutationFn: (v: { preworking?: boolean; preworking_data?: string | null }) =>
      api.egpPipeline({ projeto, ...v }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["egp-readiness"] });
      qc.invalidateQueries({ queryKey: ["gestao", "egp"] });
      qc.invalidateQueries({ queryKey: ["funis"] });
    },
  });

  // Vínculo com "EGP atualizado" (pedido 2026-09): mesma readinessQ/pipeRow acima já traz
  // egp_atualizado_key (manual) + atualizado_link_key/nome (resolvido: manual vence, senão
  // o melhor candidato automático por hash de tasks — ver _egp_readiness_rows em main.py).
  // Lista de opções da busca = mesma queryKey da aba EGPs Atualizados (cache compartilhado).
  const atualizadosQ = useQuery({ queryKey: ["egps-atualizados"], queryFn: () => api.egpsAtualizados() });
  const atualizadosOptions = atualizadosQ.data?.rows ?? [];
  const atuMut = useMutation({
    // Confirmar o vínculo (egp_atualizado_key != null) é "este EGP foi substituído por
    // essa versão" — pedido 2026-09: já sai do funil ativo na hora, sem precisar de um
    // segundo clique em "Marcar como substituído" (EgpsAtualizadosView.tsx). Reaproveita
    // o status "Despriorizado e Contabilizado" (mesmo raciocínio de lá: já exclui do
    // funil por mês/plano/priorização em todo lugar) — o rótulo mostrado (Atualizado/
    // Descontinuado/Unificado) vem do tipo_vinculo da versão, não de um status novo.
    // DESvincular (null) não reverte o status sozinho — decisão deliberada: eram 2
    // clientes que já tinham status manual antes do vínculo; reverter senão perde
    // informação sem o usuário pedir.
    mutationFn: (egpAtualizadoKey: string | null) =>
      api.egpPipeline({ projeto, egp_atualizado_key: egpAtualizadoKey ?? "",
        ...(egpAtualizadoKey ? { status: STATUS_DESPRIORIZADO } : {}) }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["egp-readiness"] });
      qc.invalidateQueries({ queryKey: ["gestao", "egp"] });
      qc.invalidateQueries({ queryKey: ["funis"] });
    },
  });

  // Recebimento manual por output (sas_outputs_pipeline) — mesma queryKey/mutação do
  // GestaoStatusPanel (cache react-query compartilhado); aqui editável direto na aba EGPs,
  // sem precisar abrir o drawer de status.
  const outPipeQ = useQuery({ queryKey: ["outputs-pipeline"], queryFn: () => api.outputsPipeline() });
  const outPipeMap = useMemo(
    () => new Map((outPipeQ.data?.rows ?? []).map((r) => [r.chave_canonica, r])), [outPipeQ.data]);
  const outPipeMut = useMutation({
    mutationFn: (v: { chave_canonica: string; recebido?: boolean; recebido_data?: string | null; carga_fria?: boolean }) =>
      api.outputPipelinePatch(v),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["outputs-pipeline"] });
      qc.invalidateQueries({ queryKey: ["egp-readiness"] });
      qc.invalidateQueries({ queryKey: ["gestao", "egp"] });
      qc.invalidateQueries({ queryKey: ["gestao", "input"] });
      qc.invalidateQueries({ queryKey: ["funis"] });
    },
  });

  // "Último status" do EGP (aba Gestão, entity=egp) + analistas p/ o select de responsável —
  // mesmas query keys da aba EGPs/Gestão, cache compartilhado (react-query dedupa).
  const gestaoEgpQ = useQuery({ queryKey: ["gestao", "egp"], queryFn: () => gestaoApi.listRows("egp") });
  const gestaoEgp = (gestaoEgpQ.data ?? []).find((g) => g.id === projeto);
  const analistasQ = useQuery({ queryKey: ["analistas"], queryFn: () => api.analistas() });
  const analistas = analistasQ.data?.rows ?? [];
  // "Último status" (aba Gestão, entity=input) — mesma query key da aba Gestão/Inputs, cache compartilhado.
  const gestaoRowsQ = useQuery({ queryKey: ["gestao", "input"], queryFn: () => gestaoApi.listRows("input") });
  const gestaoRows: GestaoRow[] = gestaoRowsQ.data ?? [];
  const gestaoById = useMemo(() => new Map(gestaoRows.map((r) => [r.id, r])), [gestaoRows]);
  const [panelChave, setPanelChave] = useState<string | null>(null);
  const panelRow = panelChave ? gestaoById.get(panelChave) ?? null : null;

  const setDet = (fn: (d: EgpDetail) => EgpDetail) =>
    qc.setQueryData<EgpDetail>(egpKey, (d) => (d ? fn(d) : d));

  const patchMut = useMutation({
    mutationFn: (v: { chave: string; patch: Partial<EgpInput> }) =>
      api.patch({ chave_canonica: v.chave, ...v.patch }),
    onMutate: async ({ chave, patch }) => {
      await qc.cancelQueries({ queryKey: egpKey });
      const prev = qc.getQueryData<EgpDetail>(egpKey);
      setDet((d) => ({ ...d, inputs: d.inputs.map((i) => (i.chave_canonica === chave ? { ...i, ...patch } : i)) }));
      return { prev };
    },
    onError: (_e, _v, ctx) => {
      if (ctx?.prev) qc.setQueryData(egpKey, ctx.prev);
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["metrics"] });
      qc.invalidateQueries({ queryKey: ["resumo"] });
      qc.invalidateQueries({ queryKey: ["landing"] });
      qc.invalidateQueries({ queryKey: ["egp-readiness"] });
      qc.invalidateQueries({ queryKey: ["funis"] }); // status de input alimenta o funil de ingestão
    },
  });
  const onPatch = (chave: string, patch: Partial<EgpInput>) => patchMut.mutate({ chave, patch });

  const linkMut = useMutation({
    mutationFn: (v: { chave: string; broken: boolean }) =>
      api.setEgpInputLink(projeto, v.chave, v.broken),
    onMutate: async ({ chave, broken }) => {
      await qc.cancelQueries({ queryKey: egpKey });
      const prev = qc.getQueryData<EgpDetail>(egpKey);
      setDet((d) => ({ ...d, inputs: d.inputs.map((i) =>
        i.chave_canonica === chave ? { ...i, link_broken: broken } : i) }));
      return { prev };
    },
    onError: (_e, _v, ctx) => { if (ctx?.prev) qc.setQueryData(egpKey, ctx.prev); },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["metrics"] });
      qc.invalidateQueries({ queryKey: ["resumo"] });
      qc.invalidateQueries({ queryKey: ["landing"] });
      qc.invalidateQueries({ queryKey: ["egp-readiness"] });
      qc.invalidateQueries({ queryKey: ["funis"] });
      qc.invalidateQueries({ queryKey: ["priorizacao"] });
      qc.invalidateQueries({ queryKey: ["waves"] });
      qc.invalidateQueries({ queryKey: ["input"] });    // drawer counts
      qc.invalidateQueries({ queryKey: ["output"] });
      qc.invalidateQueries({ queryKey: ["audit"] });
    },
  });
  const toggleLink = (i: EgpInput) =>
    linkMut.mutate({ chave: i.chave_canonica, broken: !i.link_broken });

  // etapa+status+jira_id do EGP no funil migração (otimista + invalida ['funis'])
  const pipeMut = useMutation({
    mutationFn: (v: { etapa?: string; status?: string; jira_id?: string | null;
                      responsavel?: string; responsavel_bv?: string }) =>
      api.egpPipeline({ projeto, ...v }),
    onMutate: async (v) => {
      await qc.cancelQueries({ queryKey: egpKey });
      const prev = qc.getQueryData<EgpDetail>(egpKey);
      setDet((d) => {
        const pl = d.pipeline ?? EMPTY_PIPE;
        const cur = pl.migracao;
        return { ...d, pipeline: { ...pl, migracao: {
          etapa: v.etapa !== undefined ? v.etapa : cur.etapa,
          status: v.status !== undefined ? v.status : cur.status,
          jira_id: v.jira_id !== undefined ? v.jira_id : cur.jira_id ?? null,
          responsavel: v.responsavel !== undefined ? v.responsavel : cur.responsavel ?? null,
          responsavel_bv: v.responsavel_bv !== undefined ? v.responsavel_bv : cur.responsavel_bv ?? null,
        } } };
      });
      return { prev };
    },
    onError: (_e, _v, ctx) => { if (ctx?.prev) qc.setQueryData(egpKey, ctx.prev); },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: egpKey });   // reconcilia com o valor normalizado do servidor
      qc.invalidateQueries({ queryKey: ["funis"] });
      qc.invalidateQueries({ queryKey: ["priorizacao"] }); // status→Migrado muda o resumo do plano
      qc.invalidateQueries({ queryKey: ["egp-readiness"] }); // responsável/status aparecem na tabela
    },
  });

  if (egpQ.isFetching && !det) return <div className="empty">carregando detalhe…</div>;
  if (egpQ.error) return <div className="error">{String(egpQ.error)}</div>;
  if (!det) return null;

  const nProdAusente = det.inputs.filter((i) => i.origem === "SAS/Local (externo)").length;
  const nHomonimo = det.inputs.filter(isHomonimo).length;
  const nLinksBroken = det.inputs.filter((i) => i.link_broken).length;
  // linkados primeiro (broken vai pro fim); dentro do mesmo grupo, mantém a ordem
  // vinda do servidor (por categoria/artefato).
  const sortedInputs = [...det.inputs].sort((a, b) =>
    Number(!!a.link_broken) - Number(!!b.link_broken));

  return (
    <div className="egp-body">
      <div className="egp-head">
        <h2>{shortName(det.node.projeto)}</h2>
        <span className="pill">{det.node.area}</span>
        <span className="pill">{mesTag(mesOf.get(det.node.projeto))}</span>
        {Number(det.node.ciclo_id) > 0 && <span className="pill cyc">⟳ em ciclo #{det.node.ciclo_id}</span>}
        {indiOf(det.node) && <span className="pill ind">◆ Indicium</span>}
        {isTruthy(det.node.flag_output_100pct_egp) ? (
          <span className="pill" title="Todos os outputs avaliados deste EGP são lidos por outro EGP do corpus (mesma régua da aba Outputs) — candidato a modelo intermediário, não a fato/dimensão terminal.">
            100% p/ outro EGP
          </span>
        ) : isTruthy(det.node.flag_algum_output_egp) && (
          <span className="pill" title="Pelo menos 1 output deste EGP é lido por outro EGP do corpus.">
            parte p/ outro EGP
          </span>
        )}
        {isTruthy(det.node.flag_hub_multiplos_consumidores) && (
          <span className="pill" title={`${det.node.n_egps_consumidores ?? "?"} EGPs distintos leem algum output deste EGP.`}>
            🔀 hub · {det.node.n_egps_consumidores}
          </span>
        )}
        {isTruthy(det.node.flag_output_unico) && (
          <span className="pill" title="Este EGP só tem 1 output avaliado — mais simples de revisar manualmente.">
            output único
          </span>
        )}
        {isTruthy(det.node.flag_sem_export_arquivo) && (
          <span className="pill" title="Não exporta nenhum arquivo (CSV/XLSX) — não confirma consumo terminal via BI/planilha. Pode ainda ser lido direto por BI fora do corpus.">
            sem export
          </span>
        )}
        <span className="muted">
          {det.node.n_inputs} inputs · {det.node.n_outputs} outputs · {det.node.loc ?? "—"} linhas de código
          {Number(det.node.n_outputs_avaliados ?? 0) > 0 &&
            ` · ${det.node.n_outputs_consumidos_por_outro_egp}/${det.node.n_outputs_avaliados} outputs p/ outro EGP (${det.node.pct_outputs_consumidos_por_outro_egp}%)`}
        </span>
        <button className="link-btn" onClick={copyLink} title="Copiar link compartilhável deste EGP">
          {copied ? "✓ copiado" : "🔗 link"}
        </button>
      </div>

      {/* espelho das colunas da tabela da aba EGPs (pedido 2026-08-28): strip de stats
          segmentado (rótulo + valor) p/ dar visibilidade a tipo/progresso/último status.
          Os editáveis (etapa/status/responsáveis) seguem na seção Pipeline abaixo. */}
      {(row || gestaoEgp) && (
        <div className="egp-stats">
          {row && (
            <div className="egp-stat">
              <span className="egp-stat-k">Tipo</span>
              <span className="egp-stat-v">
                {row.e_extra ? (
                  /* O filtro tem um valor só (`extra`); a distinção sucessor x casca
                     continua visível AQUI, no detalhe (spec §3.1.2). */
                  <span className="ms-badge extra"
                    title="Entrou no corpus depois da linha de base: fica no recorte e traz os inputs dele, mas conta no contador de extras, nunca no total.">
                    extra{row.extra_motivo ? ` · ${row.extra_motivo}` : ""}
                  </span>
                ) : row.tipo === "escopo" ? <span className="ms-badge scope">escopo</span>
                  : row.tipo === "ex_dependencia" ? <span className="ms-badge exdep">ex-dependência</span>
                  : row.tipo === "fora_do_recorte" ? (
                    <span className="ms-badge fora"
                      title="Está no corpus mas fora do recorte Indicium: não é escopo, não é dependência (direta ou transitiva) de ninguém do escopo, e não é ex-dependência. Aparece só no recorte 'escopo: todos'.">
                      fora do recorte
                    </span>
                  ) : <span className="ms-badge dep">dependência{row.dep_nivel ? ` ·${row.dep_nivel}` : ""}</span>}
              </span>
            </div>
          )}
          {row && (
            <div className="egp-stat egp-stat-pct">
              <span className="egp-stat-k">% modernizado</span>
              <span className="egp-stat-v">
                <span className="rd-bar"><span
                  className={`rd-fill ${row.pct >= 100 ? "ok" : row.pct > 0 ? "wip" : "todo"}`}
                  style={{ width: `${row.pct}%` }} /></span>
                {row.pct}%
              </span>
            </div>
          )}
          {row && (
            <div className="egp-stat">
              <span className="egp-stat-k">Faltam</span>
              <span className="egp-stat-v"><b>{row.n_faltam}</b>&nbsp;de {row.n_inputs} inputs</span>
            </div>
          )}
          {row && (
            <div className="egp-stat">
              <span className="egp-stat-k">Depende de</span>
              <span className="egp-stat-v"><b>{row.n_deps}</b></span>
            </div>
          )}
          {gestaoEgp?.resumoStatus && (
            <div className="egp-stat egp-stat-lstat">
              <span className="egp-stat-k">Último status</span>
              <span className="egp-stat-v egp-lstat" title={gestaoEgp.resumoStatus}>
                “{gestaoEgp.resumoStatus}”
              </span>
            </div>
          )}
        </div>
      )}

      {det.em_ciclo_com.length > 0 && (
        <div className="cyc-warn">
          ⚠ Este EGP está numa <b>dependência cíclica</b> com:{" "}
          {det.em_ciclo_com.map((c) => shortName(c.projeto)).join(", ")}. Ver detalhe na aba <b>Linhagem</b>.
        </div>
      )}

      <h3>Pipeline de migração</h3>
      <div className="egp-table egp-table-single">
        <div className="egp-thead egp-pipe-head">
          <div>Etapa</div><div>Status</div><div>JIRA</div><div>Responsável</div><div>Responsável BV</div>
        </div>
        <div className="egp-tbody">
          {(() => {
            const funil = "migracao" as const;
            const cur = (det.pipeline ?? EMPTY_PIPE)[funil];
            // `cur.etapa`/`cur.status` já vêm DERIVADOS do backend (etapa espelhada +
            // "Desatualizado"), iguais aos da linha da aba EGPs. Quem diz se a etapa é
            // editável é a linha do readiness — a do recorte aberto, ou a de "base".
            const vincRow = row ?? pipeRow;
            return (
              <div className="egp-trow egp-pipe-row" key={funil}>
                <div className="c-etapa">
                  {/* etapa espelhada do sucessor (§3.2.7): o backend já recusa a escrita;
                      aqui só não se oferece o que vai ser recusado, igual à aba EGPs. */}
                  <select value={cur.etapa ?? ""} disabled={vincRow?.etapa_editavel === false || !pode}
                    title={vincRow?.etapa_editavel === false
                      ? `Etapa espelhada de "${vincRow.sucessor}" — edite no EGP sucessor`
                      : undefined}
                    onChange={(e) => pipeMut.mutate({ etapa: e.target.value })}>
                    <option value="">— etapa —</option>
                    {PIPELINE_PROJETO[funil].map((s) => <option key={s} value={s}>{s}</option>)}
                    <optgroup label="Fora do funil">
                      {PHANTOM_ETAPAS_MIGRACAO.map((s) => <option key={s} value={s}>{s}</option>)}
                    </optgroup>
                  </select>
                </div>
                <div className="c-status">
                  <select value={cur.status ?? ""} disabled={!cur.etapa || !pode} title={STATUS_HELP}
                    style={cur.status ? { background: SEG[cur.status]?.bg, color: SEG[cur.status]?.fg } : undefined}
                    onChange={(e) => { const v = e.target.value;
                      if (!confirmStatusTerminal(v, shortName(projeto))) return;
                      pipeMut.mutate({ status: v }); }}>
                    <option value="">— status —</option>
                    {opcoesStatusEgp(cur.status).map((o) => <option key={o.value} value={o.value} disabled={o.disabled}>{o.label}</option>)}
                  </select>
                  {/* Mesmo selo da tabela compacta (ReadinessView.tsx) — aqui no painel
                      expandido, que é onde "Versão atualizada"/AtualizadoLinkButton vivem,
                      então é onde faz mais sentido ver o resultado logo depois de confirmar. */}
                  {cur.status === STATUS_DESPRIORIZADO && pipeRow?.egp_atualizado_key && (
                    <span className="mf-flag" style={{ marginLeft: 4 }}
                      title={`${statusTrocaLabel(pipeRow.atualizado_link_tipo_vinculo)} pela versão atualizada "${pipeRow.atualizado_link_nome ?? pipeRow.egp_atualizado_key}"`}>
                      {statusTrocaLabel(pipeRow.atualizado_link_tipo_vinculo).toLowerCase()}
                    </span>
                  )}
                </div>
                <div>
                  <JiraIdInput value={cur.jira_id ?? null}
                    onSave={(v) => pipeMut.mutate({ jira_id: v })} />
                </div>
                <div>
                  <select value={cur.responsavel ?? ""} title="Responsável pela migração deste EGP" disabled={!pode}
                    onChange={(e) => pipeMut.mutate({ responsavel: e.target.value })}>
                    <option value="">—</option>
                    {cur.responsavel && !analistas.some((a) => a.email === cur.responsavel) && (
                      <option value={cur.responsavel}>{cur.responsavel}</option>
                    )}
                    {analistas.map((a) => <option key={a.email} value={a.email}>{a.nome || a.email}</option>)}
                  </select>
                </div>
                <div>
                  <RespBvInput value={cur.responsavel_bv ?? null}
                    onSave={(v) => pipeMut.mutate({ responsavel_bv: v ?? "" })} />
                  {/* derivada do nome acima pelo cadastro (Gestão → Responsáveis BV); muda
                      sozinha quando o responsável muda, por isso não é editável aqui */}
                  <div className="muted" style={{ fontSize: 11, marginTop: 2 }}
                    title="Área interna do BV — vem do cadastro em Gestão → Responsáveis BV">
                    {subareaDe(cur.responsavel_bv, mapaSub) ?? SEM_SUBAREA}
                  </div>
                </div>
              </div>
            );
          })()}
        </div>
      </div>

      {/* Duas coisas diferentes, e confundi-las era o ticket 20:
          1) o VÍNCULO (egp_vinculo_tipo + egp_sucessor) — aponta para o projeto do corpus
             e é o que deriva Desatualizado/etapa espelhada/sanitização;
          2) a COMPARAÇÃO (egp_atualizado_key) — aponta para a versão recebida na aba de
             recebimentos e só serve para ver o diff antigo x novo.
          Ficam na mesma seção, nesta ordem, cada uma dizendo o que é. */}
      <h3>Versão atualizada</h3>
      <VinculoSucessorPanel projeto={projeto} row={pipeRow} isGestao={isGestao && pode} onOpenEgp={onOpenEgp} />

      {/* Substituído: o app SUGERE fechar o antecessor e a gestão aplica com 1 clique.
          Classificar nunca muda status sozinho (spec §3.5.21) — o backend só grava o
          status pelo caminho normal de edição, depois do clique. */}
      {sugereFecharAntecessor(pipeRow) && (
        <div className="vinc-sugestao">
          <span>
            Substituído por <b>{shortName(pipeRow!.sucessor!)}</b> — etapa, mês, JIRA e
            responsável já foram copiados para lá. Fechar este EGP é decisão da gestão.
          </span>
          {pode && (
            <button className="link-btn" onClick={() => {
              if (!confirmStatusTerminal(STATUS_FECHAMENTO, shortName(projeto))) return;
              pipeMut.mutate({ status: STATUS_FECHAMENTO });
            }}>
              Fechar como “{STATUS_FECHAMENTO}”
            </button>
          )}
        </div>
      )}

      {/* A aba "EGPs Atualizados" foi aposentada (spec §5): a comparação com o antecessor
          — o que ela tinha de único — mora AQUI, logo abaixo do vínculo. É OUTRA coluna
          (egp_atualizado_key, chave da aba de recebimentos): apontar aqui abre o diff e
          sugere o sucessor acima, mas NÃO cria vínculo nem muda status/etapa/contagem. */}
      <div className="vinc-explica">
        <b>Comparação com a versão recebida</b> — aponta para o arquivo que o BV enviou, na
        carga de recebimentos, para ver o diff antigo × novo. Não cria vínculo: quando essa
        versão já tiver entrado no corpus, ela vira a sugestão de sucessor no bloco acima.
      </div>
      <div className="egp-atu-section">
        {pipeRow ? (pode ? (
          <AtualizadoLinkButton row={pipeRow} options={atualizadosOptions}
            onLink={(v) => atuMut.mutate(v)} />
        ) : <span>{pipeRow.atualizado_link_nome ?? "—"}</span>) : <span className="muted">carregando…</span>}
        {atuMut.isError && <span className="error">Falha ao salvar: {String(atuMut.error)}</span>}
      </div>
      {pipeRow?.atualizado_link_versao_id && (
        <EgpAtualizadoDetail versaoId={pipeRow.atualizado_link_versao_id}
          onOpenInput={onOpenInput} />
      )}

      {/* histórico de status da Gestão embutido (pedido 2026-08-28): visível direto ao
          abrir o EGP, sem o clique extra no "último status" da tabela. */}
      <h3>Último status &amp; histórico (Gestão)</h3>
      <GestaoStatusHistory entity="egp" id={projeto} />

      <div className="egp-cols">
        <div className="egp-panel">
          <h3>Depende de ({det.depende_de.length})</h3>
          {nProdAusente > 0 && (
            <div className="dep dep-missing-note" title="Tabelas SAS/Local lidas por este EGP que nenhum EGP do corpus produz — dependência de um produtor (EGP) ausente.">
              ⚠ +{nProdAusente} de <b>produtor ausente</b> (SAS/Local sem EGP no corpus) — ver Inputs
            </div>
          )}
          {det.depende_de.length === 0 && <div className="muted">— nenhuma dependência upstream</div>}
          {det.depende_de.map((d) => (
            <div key={d.projeto} className="dep">
              <span className="dep-proj"><EgpRef projeto={d.projeto} onOpen={onOpenEgp} /><StatusSelo status={d.status} /></span>
              <span className="dep-meta">{d.area ?? "?"} · {mesTag(mesOf.get(d.projeto))} {Number(d.ciclo_id) > 0 ? "· ⟳" : ""}</span>
              <span className="dep-via" title={d.via_tabelas ?? ""}>via {d.via_tabelas ?? "—"}</span>
            </div>
          ))}
        </div>
        <div className="egp-panel">
          <h3>Alimenta ({det.alimenta.length})</h3>
          {det.alimenta.length === 0 && <div className="muted">— não alimenta outros EGPs</div>}
          {det.alimenta.map((d) => (
            <div key={d.projeto} className="dep">
              <span className="dep-proj"><EgpRef projeto={d.projeto} onOpen={onOpenEgp} /><StatusSelo status={d.status} /></span>
              <span className="dep-meta">{d.area ?? "?"} · {mesTag(mesOf.get(d.projeto))} {Number(d.ciclo_id) > 0 ? "· ⟳" : ""}</span>
              <span className="dep-via" title={d.via_tabelas ?? ""}>via {d.via_tabelas ?? "—"}</span>
            </div>
          ))}
        </div>
      </div>

      {det.bloqueio && det.bloqueio.deps_bloqueadoras.length > 0 && (
        <div className="egp-panel egp-block">
          <h3>🔒 Bloqueado por dependência ({det.bloqueio.deps_bloqueadoras.length})</h3>
          <div className="muted">Depende (direta ou transitivamente) de EGPs que leem tabelas SAS sem produtor mapeado — bloqueado até essas tabelas serem ingeridas.</div>
          {det.bloqueio.deps_bloqueadoras.map((d) => (
            <div key={d.projeto} className="dep">
              <span className="dep-proj"><EgpRef projeto={d.projeto} onOpen={onOpenEgp} /></span>
              <span className="dep-via" title={d.tabelas.join(", ")}>{d.tabelas.length} tabela{d.tabelas.length > 1 ? "s" : ""} SAS sem produtor: {d.tabelas.slice(0, 6).join(", ")}{d.tabelas.length > 6 ? "…" : ""}</span>
            </div>
          ))}
        </div>
      )}

      {det.impacto_despriorizado?.impactado && (
        <div className="egp-panel egp-block egp-block-desp">
          <h3>⏸ Dependência despriorizada impactando ({det.impacto_despriorizado.deps.length})</h3>
          <div className="muted">Este EGP depende (direta ou transitivamente) de EGPs fora do backlog (“Despriorizado e Contabilizado”) — o output que ele consome não será produzido pelo plano de migração.</div>
          {det.impacto_despriorizado.deps.map((p) => (
            <div key={p} className="dep">
              <span className="dep-proj"><EgpRef projeto={p} onOpen={onOpenEgp} /><StatusSelo status="Despriorizado e Contabilizado" /></span>
            </div>
          ))}
        </div>
      )}

      <h3>Inputs / necessidades ({det.inputs.length - nLinksBroken}){nProdAusente > 0 && <span className="muted"> · {nProdAusente} dep. produtor ausente</span>}{nHomonimo > 0 && <span className="muted"> · {nHomonimo} homônimo{nHomonimo > 1 ? "s" : ""}</span>}{nLinksBroken > 0 && <span className="muted"> · <span title="Vínculos quebrados: este EGP declarou que não depende destes inputs (equivalem a Sanitizado só para este EGP)">⛓️‍💥 {nLinksBroken} vínculo{nLinksBroken > 1 ? "s" : ""} quebrado{nLinksBroken > 1 ? "s" : ""}</span></span>}</h3>
      <div className="egp-table">
        <div className="egp-thead">
          <div>Artefato</div><div>Cat.</div><div title="EGPs consumidores dentro do escopo Indicium + dependências que NÃO estão despriorizados (0 = candidato a despriorizar/remover)">#Proj Ativos Dentro do Escopo</div><div>Origem</div><div>Auto</div><div>Etapa</div><div>Status</div><div>Responsável</div><div>Tbl. Corresp.</div><div title="Último status registrado na aba Gestão para este input — clique para abrir o painel">Último status</div>
        </div>
        <div className="egp-tbody">
          {sortedInputs.map((i) => {
            const broken = !!i.link_broken;
            // Broken row: só o toggle de vínculo é interativo — status/responsável/observação/último
            // status ficam trancados p/ evitar que esta view mute algo que este EGP declarou não usar.
            const glyphTitle = broken
              ? (isGestao && pode
                ? "Vínculo quebrado — não conta para modernização deste EGP. Clique para restaurar."
                : "Vínculo quebrado (só gestão pode alterar)")
              : (isGestao && pode
                ? "Vínculo ativo. Clique para quebrar (este EGP declara não depender deste input)."
                : "Vínculo ativo");
            const glyph = isGestao && pode ? (
              <button className="rd-vinc-btn" onClick={() => toggleLink(i)}
                disabled={linkMut.isPending} title={glyphTitle}>
                {broken ? "⛓️‍💥" : "🔗"}
              </button>
            ) : (
              <span className="rd-vinc-span" title={glyphTitle}>{broken ? "⛓️‍💥" : "🔗"}</span>
            );
            return (
              <div key={i.chave_canonica} className={`egp-trow${broken ? " egp-trow-broken" : ""}`}>
                <div className="c-art" title={i.is_familia ? `${i.artifact} — ${i.n_safras_no_recorte} carga(s) lida(s) por este EGP` : i.artifact}>
                  {/* link real p/ o deep-link do input ("/monitoramento/<chave>"): clique
                      abre na aba Inputs, botão do meio/ctrl+clique abrem em nova guia. */}
                  <span className="c-art-vinc">{glyph}</span>
                  <a className="rd-egp-link" href={pathFor("monitor", i.chave_canonica)}
                    title={`${i.is_familia ? `${i.artifact} — ${i.n_safras_no_recorte} carga(s) lida(s) por este EGP` : i.artifact} · botão do meio/ctrl+clique: nova guia`}
                    onClick={(ev) => { if (onOpenInput) spaLinkClick(ev, () => onOpenInput(i.chave_canonica)); }}>
                    {i.nome_exibicao || i.artifact}
                  </a>
                  {i.is_familia && <span className="muted"> · {i.n_safras_no_recorte} cargas</span>}
                </div>
                <div>{i.categoria}</div>
                <div>{i.n_proj_ativos}</div>
                <div className="c-src" title={i.source_types}>
                  {i.origem === "SAS/Local (externo)"
                    ? <span className="pill dep-missing" title="SAS/Local sem EGP produtor no corpus — dependência de produtor ausente">dep. produtor ausente</span>
                    : (i.origem || i.source_types || "—")}
                  {i.paths_fisicos && (
                    <div className="src-path" title={i.paths_fisicos}>{i.paths_fisicos}</div>
                  )}
                  {isHomonimo(i) && (
                    <span className="pill homonimo"
                      title={`Homônimo: 1 nome de input mapeia para ${nPaths(i)} ${i.categoria === "tabela" ? "tabelas físicas distintas" : "arquivos em pastas diferentes"} (${i.paths_fisicos})`}>
                      homônimo: {nPaths(i)} {i.categoria === "tabela" ? "tab. físicas" : "pastas"}
                    </span>
                  )}
                  {isDynamicRef(i) && (
                    <span className="pill dinamica" title={DYNAMIC_REF_TITLE}>ref. dinâmica</span>
                  )}
                </div>
                <div><span className={`pill ${i.modernizada_auto === "Disponível" ? "ok" : "todo"}`}>{i.modernizada_auto}</span></div>
                <div className="c-etapa">
                  <select value={effEtapa(i.etapa, i.modernizada_auto)} disabled={broken || !!travaDerivada(i) || !pode}
                    title={broken ? "Vínculo quebrado — restaure para editar (não deveria mexer na etapa por aqui)" : travaDerivada(i)}
                    onChange={(e) => onPatch(i.chave_canonica, { etapa: e.target.value })}>
                    {PIPELINE_INPUT.map((s) => <option key={s} value={s}>{s}</option>)}
                  </select>
                </div>
                <div className="c-status">
                  {(() => {
                    const effSt = effStatusInput(i.status, i.etapa, i.modernizada_auto);
                    return (
                      <select value={effSt} disabled={broken || !!travaDerivada(i) || !pode}
                        style={{ background: SEG[effSt]?.bg, color: SEG[effSt]?.fg }}
                        title={broken ? "Vínculo quebrado — restaure para editar (não deveria mexer no status por aqui)" : travaDerivada(i)}
                        onChange={(e) => onPatch(i.chave_canonica, { status: e.target.value })}>
                        {STATUS_INPUT.map((s) => <option key={s} value={s}>{s}</option>)}
                      </select>
                    );
                  })()}
                </div>
                <div><input defaultValue={i.responsavel ?? ""} placeholder="—" disabled={broken || !pode}
                  title={broken ? "Vínculo quebrado — restaure para editar" : undefined}
                  onBlur={(e) => { const v = e.target.value; if (v !== (i.responsavel ?? "")) onPatch(i.chave_canonica, { responsavel: v }); }} /></div>
                <div><input defaultValue={i.observacao ?? ""} placeholder="—" disabled={broken || !pode}
                  title={broken ? "Vínculo quebrado — restaure para editar" : undefined}
                  onBlur={(e) => { const v = e.target.value; if (v !== (i.observacao ?? "")) onPatch(i.chave_canonica, { observacao: v }); }} /></div>
                {(() => {
                  const gr = gestaoById.get(i.chave_canonica);
                  if (!gr) return <div className="c-lstat muted">fora de escopo</div>;
                  const txt = gr.resumoStatus;
                  return (
                    <div className={`c-lstat muted${broken ? " c-lstat-locked" : ""}`}
                      style={{ cursor: broken ? "not-allowed" : "pointer", color: txt ? "inherit" : undefined }}
                      title={broken ? "Vínculo quebrado — restaure para abrir o painel de status" : (txt ?? "sem status — clique para adicionar")}
                      onClick={() => { if (!broken) setPanelChave(i.chave_canonica); }}>
                      {txt ?? "sem status"}
                    </div>
                  );
                })()}
              </div>
            );
          })}
        </div>
      </div>

      <h3>Pré-working</h3>
      <div className="egp-table egp-table-single">
        <div className="egp-thead egp-pw-head">
          <div title="Questionário de pré-working específico do EGP (não é o checklist do input)">Preenchido</div>
          <div title="Data de referência do pré-working — 100% manual">Data</div>
        </div>
        <div className="egp-tbody">
          <div className="egp-trow egp-pw-row">
            <div>
              <button type="button" className={`gm-toggle-btn gm-toggle-btn-sm${preworkingVal ? " on" : ""}`}
                disabled={pwMut.isPending || !pode} title="Questionário de pré-working específico do EGP — clique para alternar"
                onClick={() => pwMut.mutate({ preworking: !preworkingVal })}>
                {preworkingVal ? "✓ Preenchido" : "○ Não preenchido"}
              </button>
            </div>
            <div>
              <input type="date" className="gm-out-date" value={pwDataInput} disabled={pwMut.isPending || !pode}
                title="Data de referência do pré-working — 100% manual"
                onChange={(e) => setPwDataInput(e.target.value)}
                onBlur={() => {
                  if (pwDataInput !== (pipeRow?.preworking_data ?? ""))
                    pwMut.mutate({ preworking_data: pwDataInput || null });
                }} />
            </div>
          </div>
        </div>
      </div>

      <h3>
        Outputs produzidos ({nOut})
        {nOutRed > 0 && <span className="muted"> · 🔴 {nOutRed} não-autoritativo{nOutRed > 1 ? "s" : ""}</span>}
        {nOutYellow > 0 && <span className="muted"> · 🟡 {nOutYellow} a definir</span>}
      </h3>
      {(outputsQ.isLoading || pairsQ.isLoading) && nOut === 0
        ? <div className="muted">carregando outputs…</div>
        : nOut === 0
          ? <div className="muted">— não produz outputs no corpus</div>
          : (
            <div className="egp-table">
              <div className="egp-thead egp-out-head">
                <div title="Autoridade sobre o output: verde = único/escolhido, amarelo = a definir, vermelho = outro EGP foi escolhido">Aut.</div>
                <div>Artefato</div><div>Categoria</div>
                <div title="Quantos EGPs consomem este output">#Cons.</div>
                <div title="Output terminal (sem downstream no corpus)">Terminal</div>
                <div title="Recebimento manual deste output (sas_outputs_pipeline) — conta para a prontidão">Recebido</div>
                <div title="Data de referência do recebimento — 100% manual">Data</div>
                <div title="Output que precisa de carga fria (histórico) além da carga incremental">Carga fria</div>
              </div>
              <div className="egp-tbody">
                {producedOutputs.map(({ row, auth }) => (
                  <div key={row.chave_canonica} className="egp-trow egp-out-row" style={{ cursor: "pointer" }}
                    onClick={() => setSelOutput(row)}
                    title="clique p/ ver produtores/consumidores">
                    <div title={AUTH_TITLE[auth]}>{AUTH_DOT[auth]}</div>
                    <div className="c-art" title={row.artifact}>{row.artifact}</div>
                    <div>{row.categoria}</div>
                    <div className="c-num">{row.qtd_consumidores}</div>
                    <div>
                      <span className={`pill ${isTruthy(row.terminal) ? "ok" : "todo"}`}>
                        {isTruthy(row.terminal) ? "Terminal" : "Intermediário"}
                      </span>
                    </div>
                    <OutputManualCell manual={outPipeMap.get(row.chave_canonica)} disabled={outPipeMut.isPending || !pode}
                      onToggle={(recebido) => outPipeMut.mutate({ chave_canonica: row.chave_canonica, recebido })}
                      onDataBlur={(recebido_data) => outPipeMut.mutate({ chave_canonica: row.chave_canonica, recebido_data })}
                      onCargaFria={(carga_fria) => outPipeMut.mutate({ chave_canonica: row.chave_canonica, carga_fria })} />
                  </div>
                ))}
              </div>
            </div>
          )}

      {selOutput && (
        <OutputsDrawer row={selOutput} onClose={() => setSelOutput(null)}
          onOpenEgp={(p) => { setSelOutput(null); onOpenEgp?.(p); }} />
      )}
      {panelRow && (
        <DetailModal title={panelRow.nome} narrow onClose={() => setPanelChave(null)}>
          <div className="muted" style={{ fontSize: 12 }}>
            {panelRow.area ?? "—"} · etapa atual: <b>{panelRow.etapa ?? "—"}</b>
          </div>
          <GestaoStatusHistory entity="input" id={panelRow.id} />
        </DetailModal>
      )}
    </div>
  );
}

// Toggle + data de "Recebido" (sas_outputs_pipeline) de 1 output, como 2 células da grade —
// mesmo campo/mutação do GestaoStatusPanel (OutputManualRow), só em layout de tabela (linha
// única) em vez do bloco empilhado do drawer. stopPropagation em cada célula: a linha inteira
// tem onClick para abrir o OutputsDrawer (produtores/consumidores). Data em buffer local
// (mesmo motivo do drawer: o valor do servidor pode chegar/mudar depois do 1º render).
function OutputManualCell({ manual, disabled, onToggle, onDataBlur, onCargaFria }: {
  manual: OutputPipelineRow | undefined;
  disabled: boolean;
  onToggle: (recebido: boolean) => void;
  onDataBlur: (data: string | null) => void;
  onCargaFria: (v: boolean) => void;
}) {
  const recebidoVal = manual?.recebido === "true";
  const cargaFria = manual?.carga_fria === "true";
  const [dataInput, setDataInput] = useState(manual?.recebido_data ?? "");
  useEffect(() => { setDataInput(manual?.recebido_data ?? ""); }, [manual?.recebido_data]);
  return (
    <>
      <div onClick={(e) => e.stopPropagation()}>
        <button type="button" className={`gm-toggle-btn gm-toggle-btn-sm${recebidoVal ? " on" : ""}`}
          disabled={disabled} title="Recebimento manual deste output — conta para a prontidão"
          onClick={() => onToggle(!recebidoVal)}>
          {recebidoVal ? "✓ Recebido" : "○ Não recebido"}
        </button>
      </div>
      <div onClick={(e) => e.stopPropagation()}>
        <input type="date" className="gm-out-date" value={dataInput} disabled={disabled}
          title="Data de referência do recebimento — 100% manual"
          onChange={(e) => setDataInput(e.target.value)}
          onBlur={() => { if (dataInput !== (manual?.recebido_data ?? "")) onDataBlur(dataInput || null); }} />
      </div>
      <div onClick={(e) => e.stopPropagation()}>
        <button type="button" className={`gm-toggle-btn gm-toggle-btn-sm${cargaFria ? " on" : ""}`}
          disabled={disabled} title="Marca os outputs que precisam de carga fria (histórico)"
          onClick={() => onCargaFria(!cargaFria)}>
          {cargaFria ? "❄ Carga fria" : "○ Sem carga fria"}
        </button>
      </div>
    </>
  );
}

// Selo de status TERMINAL ao lado dos EGPs relacionados (Depende de / Alimenta):
// Migrado (verde) e Despriorizado e Contabilizado (azul, rótulo curto). Cores do SEG
// (tokens fixos do funil, iguais nos 2 temas). `status` vem do /api/egp (sas_egp_pipeline).
const SELO_LABEL: Record<string, string> = {
  "Migrado": "Migrado",
  "Despriorizado e Contabilizado": "Despriorizado",
};
function StatusSelo({ status }: { status?: string | null }) {
  if (!status || !SELO_LABEL[status]) return null;
  const seg = SEG[status];
  return (
    <span className="dep-selo" title={`status de migração: ${status}`}
      style={seg ? { background: seg.bg, color: seg.fg } : undefined}>
      {SELO_LABEL[status]}
    </span>
  );
}
