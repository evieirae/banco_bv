import { Fragment, useEffect, useMemo, useRef, useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "../api";
import type { AppConfig, ReadinessRow, ReadinessPayload } from "../types";
import { EgpDetailPanel } from "./EgpDetailPanel";
import { RespBvInput } from "./RespBvInput";
import { pathFor, spaLinkClick } from "../routes";
import { useHeaderCollapse } from "../useHeaderCollapse";
import { useTabState } from "../tabState";
import { InfoTip } from "./InfoTip";
import { DetailModal } from "./DetailModal";
import { STATUS_PROJETO, opcoesStatusEgp, SEG, STATUS_HELP, PIPELINE_PROJETO, PHANTOM_ETAPAS_MIGRACAO,
  confirmStatusTerminal, contaNoTotalEgp, TIPO_VINCULO_LABEL, TIPO_VINCULO_HELP } from "../pipeline";
import { JiraIdInput } from "./JiraIdInput";
import { usePodeEscrever } from "../usePodeEscrever";
import { MultiSelect } from "./MultiSelect";
import { RangeFilter } from "./RangeFilter";
import {
  pctCard, pctCardPrdShare, pctPassaFiltro, PCT_CATEGORIAS, PCT_CATEGORIA_LABEL, Gauge,
  pctGaugeTitulo, type PctCategoria,
} from "./GestaoKanban";
import { csvDownload, csvFromColumns, csvBool, csvDate, egpShort, type CsvColumn } from "../csv";
import { RECORTES, recorteApi, passaNoRecorte, passaNoPapel, PAPEIS_VINCULO,
  papeisDoVinculo, type RecorteEgp } from "../vinculo";
import { VinculoPapeis } from "./ExtraTipoIcon";

import { mesTag, useMesPlan } from "../mesPlan";
import { useSubareas } from "../useSubareas";
import { SEM_SUBAREA, subareaDe, ordenarSubareas } from "../subareas";

const shortName = (id: string) => (id.includes("__") ? id.split("__").slice(1).join("__") : id);

// Pendência de uma versão recebida: a comparação com o antecessor não pôde ser feita
// (pareamento não resolvido ou falha na extração). Entrar no corpus não a resolve — sem
// este aviso, um arquivo cuja extração falhou parece normal.
const PENDENCIA_HELP = "a comparação com o antecessor não rodou: recarregue a versão "
  + "indicando o antecessor (--antigo) ou corrija a extração antes de tratar como troca.";

type Bucket = "pronto" | "quase" | "parcial" | "bloqueado" | "ciclo";
function bucketOf(r: ReadinessRow): Bucket {
  if (r.ciclo_id > 0) return "ciclo";
  if (r.pct >= 100) return "pronto";
  if (r.pct >= 70) return "quase";
  if (r.pct >= 30) return "parcial";
  return "bloqueado";
}
const BUCKET: Record<Bucket, { label: string; tone: string }> = {
  pronto: { label: "Habilitado p/ migrar", tone: "ok" },
  quase: { label: "Quase pronto", tone: "wip" },
  parcial: { label: "Parcial", tone: "wip" },
  bloqueado: { label: "Bloqueado", tone: "todo" },
  ciclo: { label: "Em ciclo", tone: "cyc" },
};

type SortKey = "pct" | "projeto" | "area" | "n_inputs" | "n_faltam" | "n_deps" | "prontidao" | "loc";
// O recorte da aba (5 valores desde o ticket 21, 29/09/2026). Os dois novos são vistas
// do `indi_deps` — a lista dos recortes e o mapeamento p/ o backend vivem em vinculo.ts,
// testáveis fora do React.
type Scope = RecorteEgp;

// Responsável BV: texto livre (pessoa do lado BV), save-on-blur/Enter — mesmo contrato
// do JiraIdInput ("" limpa; campo não enviado preserva), sem validação de formato.

interface Props {
  cfg: AppConfig | null;
  egpToOpen: string | null;
  onEgpOpened: () => void;
  onOpenInput?: (chave: string) => void;   // cross-nav p/ a aba Inputs (deep-link do input)
}

// rótulos do filtro "Tipo" (valor interno de r.tipo -> rótulo exibido)
const TIPO_LABEL: Record<string, string> = {
  escopo: "escopo",
  dependencia: "dependência",
  ex_dependencia: "ex-dependência",
  // 4º valor: o EGP que tem VÍNCULO DE ATUALIZAÇÃO com outro — sucessor (de QUALQUER
  // tipo de vínculo, inclusive Substituído) ou casca — e está fora da linha de base.
  // Listado e filtrável, fora do total, com contador próprio ao lado (spec §3.1.2).
  // É um valor só: a distinção sucessor × casca vive no DETALHE do EGP, não no filtro.
  extra: "extra",
  // 5º valor (07/10/2026): no corpus e fora do recorte Indicium inteiro — nem escopo, nem
  // dependência, nem ex-dependência. Só aparece no recorte "todos", que é o único que os
  // lista; antes vinham rotulados "escopo", o que fazia o filtro ter um valor útil só.
  fora_do_recorte: "fora do recorte",
};

// Rótulo do "porquê" do extra — só no detalhe/tooltip, nunca no filtro.
const EXTRA_MOTIVO_LABEL: Record<string, string> = {
  sucessor: "versão nova de um EGP do corpus",
  casca: "casca: antecessor absorvido por um unificador, sem inventário próprio",
  novo: "novo no escopo: entrou depois do congelamento e não substitui nenhum EGP",
  dependencia: "dependência nova: o grafo a puxou depois do congelamento",
};

// Tipo EXIBIDO da linha: o extra tem tipo próprio, senão vale o que o backend
// classificou (escopo / dependência / ex-dependência).
const tipoDe = (r: ReadinessRow) =>
  r.e_extra ? TIPO_LABEL.extra : (TIPO_LABEL[r.tipo] ?? r.tipo);

const extraTitle = (r: ReadinessRow) =>
  `Extra: chegou depois do congelamento e está fora da linha de base${
    r.extra_motivo ? ` — ${EXTRA_MOTIVO_LABEL[r.extra_motivo] ?? r.extra_motivo}` : ""
  }. Conta no contador próprio ao lado do total, nunca dentro dele.`;


export function ReadinessView({ cfg, egpToOpen, onEgpOpened, onOpenInput }: Props) {
  const qc = useQueryClient();
  const pode = usePodeEscrever();
  const pipeMut = useMutation({
    mutationFn: (v: { projeto: string; etapa?: string; status?: string; responsavel?: string; responsavel_bv?: string | null; jira_id?: string | null; preworking?: boolean; preworking_data?: string | null }) => api.egpPipeline(v),
    onMutate: async (v) => {
      const key = ["egp-readiness", recorteApi(scope)] as const;
      await qc.cancelQueries({ queryKey: key });
      const prev = qc.getQueryData<ReadinessPayload>(key);
      qc.setQueryData<ReadinessPayload>(key, (old) =>
        old ? { ...old, rows: old.rows.map((r) => (r.projeto === v.projeto
          ? { ...r,
              ...(v.status !== undefined ? { status: v.status } : {}),
              ...(v.etapa !== undefined ? { etapa: v.etapa } : {}),
              ...(v.responsavel !== undefined ? { responsavel: v.responsavel } : {}),
              ...(v.responsavel_bv !== undefined ? { responsavel_bv: v.responsavel_bv } : {}),
              ...(v.jira_id !== undefined ? { jira_id: v.jira_id } : {}),
              ...(v.preworking !== undefined ? { preworking: v.preworking } : {}),
              ...(v.preworking_data !== undefined ? { preworking_data: v.preworking_data } : {}) }
          : r)) } : old,
      );
      return { prev, key };
    },
    onError: (_e, _v, ctx) => { if (ctx?.prev) qc.setQueryData(ctx.key, ctx.prev); },
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["egp-readiness"] }); qc.invalidateQueries({ queryKey: ["funis"] }); },
  });
  // PONTE TEMPORÁRIA (ticket 17) — classifica o tipo de vínculo da TROCA em
  // sas_egp_atualizados_pipeline (grão egp_key). A aba EGPs Atualizados foi aposentada e
  // este endpoint foi junto; voltou porque o merge chegou em prod ANTES do publish que leva
  // os sucessores ao corpus, e sem eles o vínculo unificado é impossível de criar (o PATCH
  // /api/egp-pipeline recusa com 404). O backend aceita SÓ tipo_vinculo.
  //
  // Apagar — daqui e do backend — quando egp_vinculo_tipo tiver os 3 registros em prod.
  // Optimistic update (achado do usuário, 2026-09): sem isso o select "não parecia fazer
  // nada" entre o clique e o refetch, e a tabela reordena depois — a linha some de onde
  // estava e passa a impressão de que não salvou. Atualiza TODAS as linhas com o mesmo
  // atualizado_link_key (agrupamento = N:1, o tipo é da TROCA).
  const vinculoMut = useMutation({
    mutationFn: (v: { egp_key: string; tipo_vinculo: string }) => api.egpAtualizadoPipeline(v),
    onMutate: async (v) => {
      const key = ["egp-readiness", scope] as const;
      await qc.cancelQueries({ queryKey: key });
      const prev = qc.getQueryData<ReadinessPayload>(key);
      qc.setQueryData<ReadinessPayload>(key, (old) =>
        old ? { ...old, rows: old.rows.map((r) => (r.atualizado_link_key === v.egp_key
          ? { ...r, atualizado_link_tipo_vinculo: v.tipo_vinculo as ReadinessRow["atualizado_link_tipo_vinculo"] }
          : r)) } : old);
      return { prev, key };
    },
    onError: (_e, _v, ctx) => { if (ctx?.prev) qc.setQueryData(ctx.key, ctx.prev); },
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["egp-readiness"] }); },
  });
  // "Ainda é dependência" muda o GRAFO, não uma célula: o recorte inteiro se move (o
  // produtor volta ao frontier e traz as dependências dele). Por isso nada de update
  // otimista — ao contrário do vinculoMut acima, aqui não dá para prever o resultado no
  // cliente: invalida tudo que deriva da linhagem e deixa o servidor recomputar.
  const depMut = useMutation({
    mutationFn: (v: { produtor: string; mantida: boolean }) =>
      api.setDepMantida(v.produtor, v.mantida),
    onSuccess: (r) => {
      for (const k of ["egp-readiness", "funis", "priorizacao", "landing", "inputs"])
        qc.invalidateQueries({ queryKey: [k] });
      if (r.mantida)
        window.alert(`Dependência reaberta: ${r.produtor}\n\n`
          + `${r.fan_out.alteracoes} par(es) marcado(s), consumidor(es): `
          + `${r.fan_out.consumidores.join(", ")}.\n\n`
          + `O input segue Modernizado no funil de ingestão — o que foi declarado aqui é `
          + `que aquela ingestão não cobre o que este consumidor lê.`);
    },
    onError: (e) => window.alert(`Não foi possível alterar: ${String(e)}`),
  });
  const [scope, setScope] = useTabState<Scope>("egps.scope", "indi_deps");
  const [q, setQ] = useTabState("egps.q", "");
  const [areaSel, setAreaSel] = useTabState<Set<string>>("egps.area", new Set());
  const toggleArea = (s: string) =>
    setAreaSel((cur) => { const n = new Set(cur); n.has(s) ? n.delete(s) : n.add(s); return n; });
  const [mesSel, setMesSel] = useTabState<Set<string>>("egps.mes", new Set());
  const toggleMes = (s: string) =>
    setMesSel((cur) => { const n = new Set(cur); n.has(s) ? n.delete(s) : n.add(s); return n; });
  // filtro por TIPO da linha (escopo / dependência / ex-dependência) — só faz sentido
  // no recorte indi_deps (nos demais tudo é "escopo"); rótulo exibido -> valor de r.tipo.
  const [tipoSel, setTipoSel] = useTabState<Set<string>>("egps.tipo", new Set());
  const toggleTipo = (s: string) =>
    setTipoSel((cur) => { const n = new Set(cur); n.has(s) ? n.delete(s) : n.add(s); return n; });
  // Filtro do TIPO do extra (29/09/2026). Separado do filtro "Tipo" de propósito: ali
  // "extra" continua valendo como um valor só — "me mostra tudo que chegou depois" é uma
  // pergunta, "me mostra os unificados" é outra, e obrigar a segunda a passar pela
  // primeira custaria dois cliques para a pergunta mais comum.
  const [tipoExtraSel, setTipoExtraSel] = useTabState<Set<string>>("egps.tipoExtra", new Set());
  const toggleTipoExtra = (s: string) =>
    setTipoExtraSel((cur) => { const n = new Set(cur); n.has(s) ? n.delete(s) : n.add(s); return n; });
  // "só os extras" virou RECORTE (ticket 21): o botão do card e o seletor de escopo
  // mexem no mesmo estado. Dois mecanismos para o mesmo filtro era como a tela dizia uma
  // coisa e o card, outra.
  const soExtra = scope === "extras";
  // Filtro do indicador de Prontidão (mesmo indicador/composto da aba Gestão — ver
  // GestaoKanban.pctCard/pctPassaFiltro): categorias consideradas (vazio = Completo, as 3)
  // + faixa [min,max]. Categorias 1+ = a faixa exige TODAS dentro dela (E lógico).
  const [pctCategoriasSel, setPctCategoriasSel] = useTabState<Set<PctCategoria>>("egps.pctcat", new Set());
  const togglePctCategoria = (v: string) =>
    setPctCategoriasSel((cur) => { const c = v as PctCategoria; const n = new Set(cur); n.has(c) ? n.delete(c) : n.add(c); return n; });
  const [pctRange, setPctRange] = useTabState<[number, number] | null>("egps.pctrange", null);
  const [bucket, setBucket] = useTabState<Bucket | "">("egps.bucket", "");
  const [quickWin, setQuickWin] = useTabState("egps.quickwin", false); // sem bloqueio pendente (não bloqueado por dependência)
  const [blockedOnly, setBlockedOnly] = useTabState("egps.blocked", false); // só EGPs bloqueados por dependência transitiva
  const [despOnly, setDespOnly] = useTabState("egps.desp", false); // só EGPs impactados por dependência despriorizada
  const [convOnly, setConvOnly] = useTabState("egps.conv", false); // só EGPs com Fim Conversão preenchido (sas_gestao_datas)
  // sem recolhimento automático por scroll (ver useHeaderCollapse): só o botão ▴/▾
  const hdr = useHeaderCollapse("hdr-egps", { auto: false });
  const [pendOnly, setPendOnly] = useTabState("egps.pend", false); // oculta Migrado + Despriorizado e Contabilizado ("o que falta fazer")
  const [soComResp, setSoComResp] = useTabState("egps.resp", false); // espelha o filtro da aba Gestão; default off p/ preservar o comportamento atual da aba
  const [noOutOnly, setNoOutOnly] = useTabState("egps.noout", false); // só EGPs que não produzem output algum no corpus (consumidores puros)
  const [brokenOnly, setBrokenOnly] = useTabState("egps.broken", false); // só EGPs com pelo menos 1 vínculo quebrado
  // Linha FORA da linha de base congelada (na prática, a ex-dependência que não entrou na
  // lista): não está no card de total, mas era listada — a tabela dizia 209 e o card 192.
  // Fica OCULTA por padrão, para a lista bater com o card; o chip reexibe. Não é "sumir":
  // a retenção existe para o esforço não desaparecer (2 das 17 em prod têm Pré-conversão
  // concluída, com responsável e JIRA).
  const [showExSemEtapa, setShowExSemEtapa] = useTabState("egps.exsemetapa", false);
  // só EGPs com alguma versão atualizada vinculada — CONFIRMADA ou só SUGERIDA (atualizado_link_key
  // é o resolvido: manual ?? automático, mesmo campo que já pinta a linha com rd-atu-confirmed/
  // -suggested — pedido 2026-09: achar rápido todos que têm troca em andamento, decidida ou não).
  const [vinculadoOnly, setVinculadoOnly] = useTabState("egps.vinculado", false);
  // só EGPs onde 100% do que falta já está na banda de uma remessa em trânsito
  // (PDI+GMUD/Ingestão PRD) — pedido cliente BV 2026-09: simular quantos EGPs ficam
  // prontos quando essa remessa completar (virar Modernizado). Ver desbloqueia_remessa.
  const [remessaOnly, setRemessaOnly] = useTabState("egps.remessa", false);
  const [statusSel, setStatusSel] = useTabState<Set<string>>("egps.status", new Set());
  const toggleStatus = (s: string) =>
    setStatusSel((cur) => { const n = new Set(cur); n.has(s) ? n.delete(s) : n.add(s); return n; });
  const [etapaSel, setEtapaSel] = useTabState<Set<string>>("egps.etapa", new Set());
  const toggleEtapa = (s: string) =>
    setEtapaSel((cur) => { const n = new Set(cur); n.has(s) ? n.delete(s) : n.add(s); return n; });
  // Filtro por Responsável BV (texto livre, coluna homônima da tabela) — opções = valores
  // distintos presentes nos dados (mesmo padrão de areasList), não um vocabulário fixo.
  // useTabState (não useState) pelo mesmo motivo dos filtros vizinhos: sobrevive ao
  // cross-nav (achado P1 do critique 2026-08-28, ver tabState.ts).
  const [respBvSel, setRespBvSel] = useTabState<Set<string>>("egps.respbv", new Set());
  const toggleRespBv = (s: string) =>
    setRespBvSel((cur) => { const n = new Set(cur); n.has(s) ? n.delete(s) : n.add(s); return n; });
  // Filtro por "Tipo de vínculo" (pedido 2026-09) — Atualizado/Descontinuado/Unificado,
  // rótulo derivado de tipo_vinculo (funil da troca, aba EGPs Atualizados) só quando o
  // vínculo está CONFIRMADO (egp_atualizado_key). Vazio/sem confirmação não casa com
  // nenhum rótulo — não vira um 4º valor de filtro, só some do resultado ao filtrar.
  const vinculoLabelOf = (r: ReadinessRow): string | null =>
    r.egp_atualizado_key && r.atualizado_link_tipo_vinculo
      ? (TIPO_VINCULO_LABEL[r.atualizado_link_tipo_vinculo] ?? null) : null;
  const [vinculoSel, setVinculoSel] = useTabState<Set<string>>("egps.vinculo", new Set());
  const toggleVinculo = (s: string) =>
    setVinculoSel((cur) => { const n = new Set(cur); n.has(s) ? n.delete(s) : n.add(s); return n; });
  // Sub-área BV = área interna do cliente, derivada do Responsável BV pelo cadastro da
  // Gestão (ver src/subareas.ts). useTabState pelo mesmo motivo dos filtros vizinhos:
  // sobrevive ao cross-nav — inclusive ao vindo da tabela do Resumo, que escreve nesta
  // mesma chave antes de navegar.
  const [subareaSel, setSubareaSel] = useTabState<Set<string>>("egps.subarea", new Set());
  const toggleSubarea = (s: string) =>
    setSubareaSel((cur) => { const n = new Set(cur); n.has(s) ? n.delete(s) : n.add(s); return n; });
  const [sort, setSort] = useTabState<SortKey>("egps.sort", "pct");
  const [asc, setAsc] = useTabState("egps.asc", true); // pendente primeiro (% asc) por padrão
  // Detalhe do EGP em MODAL centrado (um por vez) — substituiu o expand inline
  // (.rd-expand-detail): em notebook o inline virava uma janela de ~450px com scroll
  // aninhado dentro do scroll da tabela (pedido 2026-08-28).
  const [openEgp, setOpenEgp] = useState<string | null>(null);
  const toggle = (p: string) => setOpenEgp((cur) => (cur === p ? null : p));
  const [flash, setFlash] = useState<string | null>(null);        // EGP destacado ao vir do Escopo
  const rowRefs = useRef<Map<string, HTMLDivElement>>(new Map());  // âncora por EGP p/ scroll
  // cabeçalho segue o scroll horizontal do corpo (ver comentário na JSX do .rd-thead-wrap)
  const headWrapRef = useRef<HTMLDivElement>(null);
  const onBodyScroll = (e: React.UIEvent<HTMLDivElement>) => {
    if (headWrapRef.current) headWrapRef.current.scrollLeft = e.currentTarget.scrollLeft;
    hdr.onScroll(e);
  };
  const scrollBehavior = (): ScrollBehavior =>
    window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth";
  const [notFound, setNotFound] = useState<string | null>(null);  // deep-link p/ EGP inexistente

  // uma consulta por recorte de BACKEND: "só os extras" e "+ extras" reusam o payload do
  // indi_deps (recorteApi) e filtram na tela — duas consultas para o mesmo recorte é como
  // a tabela e o contador de extras voltariam a discordar.
  const scopeApi = recorteApi(scope);
  const rq = useQuery({ queryKey: ["egp-readiness", scopeApi], queryFn: () => api.egpReadiness(scopeApi) });
  const rows = useMemo(() => rq.data?.rows ?? [], [rq.data]);
  // pares (chave_canonica, projeto): alimenta o filtro "não produz outputs" aqui e é reusado
  // pelo EgpDetailPanel (cache compartilhado via React Query).
  const outPairsQ = useQuery({ queryKey: ["outputs-egps", "base"], queryFn: () => api.outputsEgps("base") });
  // Guarda da spec §5: entre a chegada do arquivo e a entrada no corpus o sucessor não
  // existe em superfície nenhuma. Contador DERIVADO (diferença de conjuntos no backend) —
  // zera sozinho depois de uma rodada do pipeline e some sozinho se a versão for
  // descartada. Schema sem publicação alguma = lista vazia; FALHA de leitura vira chip
  // com "?" — número ausente por erro é indistinguível de "não há nada aguardando", que
  // é justamente o silêncio que este contador existe para quebrar.
  const aguardandoQ = useQuery({ queryKey: ["egps-atualizados", "aguardando-corpus"],
    queryFn: () => api.egpsAtualizadosAguardandoCorpus() });
  const aguardando = aguardandoQ.data?.rows ?? [];
  // Pendências (pareamento não resolvido / falha na extração): a taxonomia "Situação" da
  // aba aposentada morreu, mas estes dois valores não são tipo de vínculo — dizem que a
  // comparação não pôde ser feita. Entram aqui para não sumirem junto com a aba: as que
  // ainda aguardam levam o selo na própria linha; as que já entraram no corpus vêm em
  // `pendencias` (o "aguardando" se resolve, a pendência não).
  const pendencias = aguardandoQ.data?.pendencias ?? [];
  const nPendencias = aguardandoQ.data?.n_pendencias ?? 0;
  const [showAguardando, setShowAguardando] = useState(false);
  // Ticket 23, contrapartida do chip acima: ENTROU no corpus e mesmo assim não tem linha
  // em tela nenhuma. Não é só invisibilidade — sem vínculo o app não sabe que o EGP é
  // versão nova de alguém, trata-o como produtor qualquer e os inputs dele vão parar no
  // card de dependências da gestão (30/09: 3 EGPs, 26 inputs, deps marcando 88 × 61 de
  // prod). Mesmo tratamento de erro do aguardando: falha vira "?" e não silêncio.
  const semVinculoQ = useQuery({ queryKey: ["egps-sem-vinculo"], queryFn: () => api.egpsSemVinculo() });
  const semVinculo = semVinculoQ.data?.sem_vinculo ?? [];
  const orfaos = semVinculoQ.data?.orfaos ?? [];
  // Separados de propósito (01/10/2026): dos 4 órfãos medidos, 3 eram inertes — dois por
  // ex-dependência (um criado por decisão explícita da gestão) e um por antecessor
  // duplicado. Gritar nos 4 com a mesma força enterrava o único que pedia ação.
  const orfaosInvisiveis = orfaos.filter((o) => o.sucessor_em_tela === false);
  const orfaosInertes = orfaos.filter((o) => o.sucessor_em_tela !== false);
  const [showSemVinculo, setShowSemVinculo] = useState(false);
  const producersSet = useMemo(
    () => new Set((outPairsQ.data?.rows ?? []).map((p) => p.projeto)),
    [outPairsQ.data],
  );
  // Card de EGPs: linha de base CONGELADA — não reage a filtro nem a recorte, de propósito
  // (ver o title dele na JSX). Os cards de INPUT, sim: são contados em tela, sobre as
  // unidades dos EGPs visíveis (inputStats, abaixo de `view`).
  const d = rq.data;
  const cardTotal = d?.total ?? 0;
  const cardBase = d?.base_count ?? 0;
  const cardDeps = d?.dep_count ?? 0;
  const cardEx = d?.ex_count ?? 0;
  const cardExtra = d?.extra_count ?? 0;
  const nf = (n: number) => n.toLocaleString("pt-BR");
  // só os recortes com dependências distinguem escopo x dependência x ex-dependência
  // A coluna Tipo vale em TODO recorte (01/10/2026). Ela deixou de ser só
  // "escopo/dependência" quando passou a carregar o PAPEL NO VÍNCULO, e esse é o dado que
  // não depende do recorte: em "só Indicium" é justamente onde mora o antecessor
  // Desatualizado, e em "só os extras" é onde se separa quem entrou de quem saiu.
  //
  // O FILTRO de escopo/dependência, não: num recorte de um tipo só ele teria uma opção e
  // nenhum efeito. Fica onde o rótulo de fato varia.
  const misturaTipos = scope === "indi_deps" || scope === "indi_deps_extras" || scope === "base";
  // O filtro de tipo de extra só aparece quando há extra no recorte — num recorte sem
  // nenhum (prod hoje, 0) ele seria um controle que só sabe esvaziar a tela.
  // O papel no vínculo não é exclusivo do extra — o antecessor Desatualizado costuma
  // estar no escopo. O filtro aparece quando ALGUÉM em tela tem papel.
  const temExtraEmTela = useMemo(() => rows.some((r) => papeisDoVinculo(r).length > 0), [rows]);
  const { mesOf, meses } = useMesPlan();
  const { mapa: mapaSub, pronto: cadastroPronto } = useSubareas();
  // EGP sem responsável ou com responsável fora do cadastro cai em "Sem sub-área" — bucket
  // visível, nunca linha escondida.
  const subOf = useMemo(
    () => (r: ReadinessRow) => subareaDe(r.responsavel_bv, mapaSub) ?? SEM_SUBAREA,
    [mapaSub]);
  // Opções do filtro/chips: saem de TODAS as linhas do recorte (não do subconjunto
  // filtrado), senão a opção desaparece assim que você filtra por ela.
  const subareaList = useMemo(() => ordenarSubareas(rows.map(subOf)), [rows, subOf]);
  const analistasQ = useQuery({ queryKey: ["analistas"], queryFn: () => api.analistas() });
  const analistas = analistasQ.data?.rows ?? [];
  const analistaEmails = useMemo(() => new Set(analistas.map((a) => a.email)), [analistas]);
  // A coluna "Último status" saiu da tabela (2026-09): custava 140px de scroll horizontal e
  // o mesmo texto já aparece no drawer do EGP, com o histórico completo. Com ela foi embora
  // a única leitura de gestaoApi.listRows aqui — a aba Gestão segue dona desse dado.
  const busy = rq.isFetching;
  const err = rq.error ? String(rq.error) : null;

  const areasList = useMemo(() => [...new Set(rows.map((r) => r.area))].sort(), [rows]);
  const mesesList = useMemo(() => meses.map((n) => `M${n}`), [meses]);
  const respBvList = useMemo(
    () => [...new Set(rows.map((r) => r.responsavel_bv).filter((v): v is string => !!v))].sort(),
    [rows]);
  // Conjunto após os filtros de DIMENSÃO (área/onda/status/etapa/busca). Os chips de
  // bucket e quick win são toggles aplicados em cima (em `view`); por isso os
  // indicadores abaixo contam sobre baseDims e reagem aos filtros de dimensão.
  //
  // Dois memos: `baseSemSubarea` é tudo MENOS o filtro de sub-área, e é sobre ele que os
  // chips de sub-área contam. Se contassem sobre baseDims, selecionar uma sub-área zeraria
  // todas as outras e nenhuma daria para clicar de novo.
  const baseSemSubarea = useMemo(() => {
    let v = rows;
    // eixo EXTRA: decidido pelo recorte (vinculo.passaNoRecorte). "Indicium +
    // dependências" é o recorte dos 193 e não mostra extra; os dois recortes novos
    // mostram só os extras / os dois juntos.
    v = v.filter((r) => passaNoRecorte(scope, r));
    // eixo CONTAGEM: o chip reexibe quem está FORA da linha de base congelada (as
    // ex-dependências retidas). O extra fica fora do total mas segue listado por regra
    // (§3.1.2) nos recortes que o incluem — por isso a exceção `r.e_extra`.
    if (!showExSemEtapa) v = v.filter((r) => r.e_extra || contaNoTotalEgp(r));
    if (soComResp) v = v.filter((r) => !!r.responsavel);
    if (areaSel.size) v = v.filter((r) => areaSel.has(r.area));
    if (mesSel.size) v = v.filter((r) => mesSel.has(mesTag(mesOf.get(r.projeto))));
    if (statusSel.size) v = v.filter((r) => statusSel.has(r.status));
    if (etapaSel.size) v = v.filter((r) => etapaSel.has(r.etapa));
    if (respBvSel.size) v = v.filter((r) => !!r.responsavel_bv && respBvSel.has(r.responsavel_bv));
    if (misturaTipos && tipoSel.size) v = v.filter((r) => tipoSel.has(tipoDe(r)));
    if (tipoExtraSel.size) v = v.filter((r) => passaNoPapel(tipoExtraSel, r));
    if (vinculoSel.size) v = v.filter((r) => { const l = vinculoLabelOf(r); return !!l && vinculoSel.has(l); });
    if (q) {
      const ql = q.toLowerCase();
      v = v.filter((r) => r.projeto.toLowerCase().includes(ql)
        || (r.jira_id?.toLowerCase().includes(ql) ?? false));
    }
    return v;
  }, [rows, scope, showExSemEtapa, soComResp, areaSel, mesSel, mesOf, statusSel, etapaSel, respBvSel,
      tipoSel, tipoExtraSel, misturaTipos, vinculoSel, q]);
  const baseDims = useMemo(
    () => (subareaSel.size ? baseSemSubarea.filter((r) => subareaSel.has(subOf(r))) : baseSemSubarea),
    [baseSemSubarea, subareaSel, subOf]);
  // Contagem por sub-área para os chips (ignora o próprio filtro de sub-área, ver acima).
  const subareaCounts = useMemo(() => {
    const m = new Map<string, number>();
    for (const r of baseSemSubarea) m.set(subOf(r), (m.get(subOf(r)) ?? 0) + 1);
    return m;
  }, [baseSemSubarea, subOf]);
  const counts = useMemo(() => {
    const c: Record<Bucket, number> = { pronto: 0, quase: 0, parcial: 0, bloqueado: 0, ciclo: 0 };
    baseDims.forEach((r) => { c[bucketOf(r)]++; });
    return c;
  }, [baseDims]);
  const qwCount = useMemo(() => baseDims.filter((r) => !r.bloqueado_dep).length, [baseDims]);
  const blkCount = useMemo(() => baseDims.filter((r) => r.bloqueado_dep).length, [baseDims]);
  const despCount = useMemo(() => baseDims.filter((r) => (r.deps_despriorizadas?.length ?? 0) > 0).length, [baseDims]);
  const convCount = useMemo(() => baseDims.filter((r) => !!r.fim_conversao).length, [baseDims]);
  const pendCount = useMemo(() => baseDims.filter(
    (r) => r.status !== "Migrado" && r.status !== "Despriorizado e Contabilizado"
      && !r.ex_dependencia).length, [baseDims]);
  const noOutCount = useMemo(() => baseDims.filter((r) => !producersSet.has(r.projeto)).length, [baseDims, producersSet]);
  const brokenCount = useMemo(() => baseDims.filter((r) => (r.n_links_broken ?? 0) > 0).length, [baseDims]);
  // Sobre `rows` (recorte inteiro), não sobre baseDims: quando estão ocultas elas não estão em
  // baseDims, e o chip mostraria 0 — ficando impossível reexibi-las.
  // (o rótulo do chip fala em "fora da linha de base": é o mesmo conjunto, dito pela régua
  // que passou a decidir — ver contaNoTotalEgp)
  const exSemEtapaCount = useMemo(
    () => rows.filter((r) => !r.e_extra && !contaNoTotalEgp(r)).length, [rows]);
  const vinculadoCount = useMemo(() => baseDims.filter((r) => !!r.atualizado_link_key).length, [baseDims]);
  const remessaCount = useMemo(() => baseDims.filter((r) => r.desbloqueia_remessa).length, [baseDims]);

  const view = useMemo(() => {
    let v = baseDims;
    if (bucket) v = v.filter((r) => bucketOf(r) === bucket);
    if (quickWin) v = v.filter((r) => !r.bloqueado_dep);
    if (blockedOnly) v = v.filter((r) => r.bloqueado_dep);
    if (despOnly) v = v.filter((r) => (r.deps_despriorizadas?.length ?? 0) > 0);
    if (convOnly) v = v.filter((r) => !!r.fim_conversao);
    if (pendOnly) v = v.filter((r) => r.status !== "Migrado" && r.status !== "Despriorizado e Contabilizado" && !r.ex_dependencia);
    if (noOutOnly) v = v.filter((r) => !producersSet.has(r.projeto));
    if (brokenOnly) v = v.filter((r) => (r.n_links_broken ?? 0) > 0);
    if (vinculadoOnly) v = v.filter((r) => !!r.atualizado_link_key);
    if (remessaOnly) v = v.filter((r) => r.desbloqueia_remessa);
    if (pctRange) v = v.filter((r) => pctPassaFiltro(r, pctCategoriasSel, pctRange));
    const dir = asc ? 1 : -1;
    return [...v].sort((a, b) => {
      // "prontidao" não é campo bruto de ReadinessRow — é derivado (mesma conta da coluna,
      // reagindo à categoria selecionada no filtro) — por isso não cabe no a[sort] genérico.
      if (sort === "prontidao") return (pctCard(a, pctCategoriasSel) - pctCard(b, pctCategoriasSel)) * dir;
      const x = a[sort], y = b[sort];
      if (typeof x === "number" && typeof y === "number") return (x - y) * dir;
      return String(x).localeCompare(String(y)) * dir;
    });
  }, [baseDims, bucket, quickWin, blockedOnly, despOnly, convOnly, pendOnly, noOutOnly, brokenOnly,
    vinculadoOnly, remessaOnly, pctRange, pctCategoriasSel, producersSet, sort, asc]);

  // Cards de INPUT contados sobre os EGPs EM TELA (`view`, já com recorte + filtros +
  // chips). O universo e o estado de cada unidade vêm de /api/egp-input-units, que é o
  // MESMO dataset que a Visão geral e a aba Inputs contam — por isso, sem filtro ligado,
  // estes três números são exatamente os da Visão geral para o recorte escolhido
  // (05/10/2026, prod: só Indicium 1.161 / 311; + dependências 1.303 / 377).
  //
  // Antes vinham do header de /api/egp-readiness, que agrega por SQL e EXCLUI o
  // Sanitizado do universo: o card dizia 711 inputs onde o Resumo dizia 1.303, e nenhum
  // filtro da aba mexia nele.
  //
  // Dedup por unidade: dois EGPs que leem a mesma tabela contam uma vez (é um Set de
  // índices), que é a razão de a soma não ser Σ n_inputs das linhas.
  const unitsQ = useQuery({ queryKey: ["egp-input-units", scopeApi],
    queryFn: () => api.egpInputUnits(scopeApi) });
  const inputStats = useMemo(() => {
    const u = unitsQ.data;
    if (!u) return null;
    const sel = new Set<number>();
    for (const r of view) {
      const idx = u.por_egp[r.projeto];
      if (idx) for (const i of idx) sel.add(i);
    }
    let dist = 0, faltam = 0, semFonte = 0;
    for (const i of sel) {
      const un = u.unidades[i];
      if (!un) continue;
      dist++;
      if (un.a) faltam++;
      if (un.sf) semFonte++;
    }
    return { dist, faltam, semFonte };
  }, [unitsQ.data, view]);
  // "—" enquanto carrega: mostrar o número do recorte inteiro sob um filtro ligado seria
  // uma resposta errada para a pergunta na tela, e ela não se anuncia como provisória.
  const nfIn = (n: number | undefined) => (n === undefined ? "—" : nf(n));
  const inputsDist = inputStats?.dist;
  const inputsFaltam = inputStats?.faltam;
  const inputsSemFonte = inputStats?.semFonte;
  const semFontePct = inputStats && inputStats.dist
    ? Math.round((inputStats.semFonte / inputStats.dist) * 1000) / 10 : null;
  const filtrosAtivos = view.length !== rows.length;

  // cross-nav (vindo do drawer de input): garante o EGP visível e expande quando aparecer.
  useEffect(() => {
    if (!egpToOpen) return;
    setAreaSel(new Set()); setMesSel(new Set()); setBucket(""); setQ(""); setQuickWin(false); setBlockedOnly(false); setDespOnly(false); setConvOnly(false); setSoComResp(false); setNoOutOnly(false); setBrokenOnly(false); setStatusSel(new Set()); setEtapaSel(new Set()); setRespBvSel(new Set()); setPctCategoriasSel(new Set()); setPctRange(null);
    // troca p/ escopo "todos" (base) se o EGP não está no recorte atual. Usa o estado
    // da query (settled) e não rows.length, senão um escopo Indicium legitimamente
    // vazio nunca dispararia o flip (EGP base-only ficaria preso, sem abrir/erro).
    if (scope !== "base" && rq.isSuccess && !rq.isFetching && !rows.some((r) => r.projeto === egpToOpen)) setScope("base");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [egpToOpen, rows, rq.isSuccess, rq.isFetching]);
  useEffect(() => {
    if (!egpToOpen) return;
    if (view.some((r) => r.projeto === egpToOpen)) {
      const target = egpToOpen;
      setOpenEgp(target);
      setFlash(target);
      // espera o React montar a linha (já expandida) antes de rolar até ela
      requestAnimationFrame(() =>
        requestAnimationFrame(() =>
          rowRefs.current.get(target)?.scrollIntoView({ behavior: scrollBehavior(), block: "center" })));
      onEgpOpened();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [egpToOpen, view]);
  // limpa o destaque depois de ~2s
  useEffect(() => {
    if (!flash) return;
    const t = setTimeout(() => setFlash(null), 2200);
    return () => clearTimeout(t);
  }, [flash]);
  // deep-link p/ um EGP que não existe (link desatualizado): só conclui depois de
  // já estar no escopo "todos" e com os dados carregados — senão dá falso negativo.
  useEffect(() => {
    if (!egpToOpen || busy || !rq.isSuccess) return;
    if (scope === "base" && !rows.some((r) => r.projeto === egpToOpen)) {
      setNotFound(egpToOpen);
      onEgpOpened();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [egpToOpen, rows, scope, busy, rq.isSuccess]);

  const th = (k: SortKey, label: string, title?: string) => {
    const act = () => (k === sort ? setAsc(!asc) : (setSort(k), setAsc(false)));
    return (
      <div className="rd-th" title={title} role="button" tabIndex={0}
        aria-sort={sort === k ? (asc ? "ascending" : "descending") : undefined}
        onClick={act}
        onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); act(); } }}>
        {label}{sort === k ? (asc ? " ▲" : " ▼") : ""}
      </div>
    );
  };

  // Exporta as linhas EXIBIDAS (filtros + ordenação) como CSV — nome do EGP sem o prefixo `area__`.
  const exportCsv = () => {
    const cols: CsvColumn<ReadinessRow>[] = [
      { header: "EGP", get: (r) => egpShort(r.projeto) },
      { header: "Tipo", get: (r) => r.tipo },
      { header: "Nível dep", get: (r) => r.dep_nivel },
      { header: "Área", get: (r) => r.area },
      { header: "Mês", get: (r) => mesTag(mesOf.get(r.projeto)) },
      { header: "Escopo Indicium", get: (r) => csvBool(r.escopo_indi) },
      { header: "Ciclo", get: (r) => r.ciclo_id || "" },
      { header: "Inputs", get: (r) => r.n_inputs },
      { header: "LOC", get: (r) => r.loc },
      { header: "Disponíveis", get: (r) => r.n_disp },
      { header: "Faltam", get: (r) => r.n_faltam },
      { header: "Em PRD (desbloqueado)", get: (r) => r.n_prd },
      { header: "Em PDI+GMUD/PRD (remessa)", get: (r) => r.n_remessa },
      { header: "Desbloqueia c/ remessa", get: (r) => csvBool(r.desbloqueia_remessa) },
      { header: "% modernizado", get: (r) => r.pct },
      { header: "Prontidão %", get: (r) => pctCard(r, pctCategoriasSel) },
      { header: "Depende de", get: (r) => r.n_deps },
      { header: "Deps no escopo", get: (r) => r.n_deps_indi },
      { header: "Deps externas", get: (r) => r.n_deps_ext },
      { header: "Sem fonte", get: (r) => r.n_sem_fonte },
      { header: "Vínculos quebrados", get: (r) => r.n_links_broken ?? 0 },
      { header: "Etapa", get: (r) => r.etapa },
      { header: "Status", get: (r) => r.status },
      { header: "Tipo de vínculo", get: (r) => vinculoLabelOf(r) ?? "" },
      { header: "Responsável", get: (r) => r.responsavel ?? "" },
      { header: "Responsável BV", get: (r) => r.responsavel_bv ?? "" },
      { header: "Sub-área BV", get: (r) => subOf(r) },
      { header: "Pré-working", get: (r) => csvBool(r.preworking) },
      { header: "Pré-working data", get: (r) => r.preworking_data ?? "" },
      { header: "Bloqueado por dep.", get: (r) => csvBool(r.bloqueado_dep) },
      { header: "Dep. despriorizada", get: (r) => (r.deps_despriorizadas ?? []).map(shortName).join(" | ") },
    ];
    csvDownload(`egps_${scope}_${csvDate()}.csv`, csvFromColumns(view, cols));
  };

  return (
    <div className="readiness">
      {cfg?.familias_safra && (
        <p className="muted">
          <b>A unidade de input é a família de safras.</b> Safras datadas da mesma tabela
          contam como um input só — a ingestão de uma família cria UMA tabela particionada no
          destino. Por isso a prontidão de vários EGPs subiu sem ninguém ter ingerido nada: o
          que mudou foi a unidade, não o trabalho. A lista de tabelas bloqueadoras de cada EGP
          também vem por família.
        </p>
      )}
      <div className="filters">
        <select value={scope} onChange={(e) => setScope(e.target.value as Scope)}>
          {RECORTES.map((r) => <option key={r.id} value={r.id}>{r.label}</option>)}
        </select>
        <MultiSelect label="Área" options={areasList} sel={areaSel}
          onToggle={toggleArea} onClear={() => setAreaSel(new Set())} />
        <MultiSelect label="Mês" options={mesesList} sel={mesSel}
          onToggle={toggleMes} onClear={() => setMesSel(new Set())} />
        <MultiSelect label="Status" options={STATUS_PROJETO} colors={SEG} sel={statusSel} onToggle={toggleStatus} onClear={() => setStatusSel(new Set())} />
        <MultiSelect label="Etapa" options={[...PIPELINE_PROJETO.migracao, ...PHANTOM_ETAPAS_MIGRACAO]} sel={etapaSel} onToggle={toggleEtapa} onClear={() => setEtapaSel(new Set())} />
        <MultiSelect label="Responsável BV" options={respBvList} sel={respBvSel}
          title="Responsável do lado BV atribuído ao EGP (coluna 'Responsável BV' da tabela)."
          onToggle={toggleRespBv} onClear={() => setRespBvSel(new Set())} />
        <MultiSelect label="Tipo de vínculo" options={Object.values(TIPO_VINCULO_LABEL)} sel={vinculoSel}
          title={`Motivo do vínculo com uma versão atualizada (aba EGPs Atualizados), quando confirmado — coluna "Vínculo" da tabela. ${TIPO_VINCULO_HELP}`}
          onToggle={toggleVinculo} onClear={() => setVinculoSel(new Set())} />
        <MultiSelect label="Sub-área BV" options={subareaList} sel={subareaSel}
          title="Área interna do BV do responsável (Digital, MIS, Operações, Estratégia…). Vem do cadastro em Gestão → Responsáveis BV; quem não está lá aparece como 'Sem sub-área'."
          onToggle={toggleSubarea} onClear={() => setSubareaSel(new Set())} />
        {misturaTipos && (
          <MultiSelect label="Tipo" options={Object.values(TIPO_LABEL)} sel={tipoSel}
            onToggle={toggleTipo} onClear={() => setTipoSel(new Set())} />
        )}
        {temExtraEmTela && (
          <MultiSelect label="Papel no vínculo" options={[...PAPEIS_VINCULO]} sel={tipoExtraSel}
            title="De que lado do vínculo o EGP está: Desatualizado/Atualizado, Unificado/Unificador, Substituído/Substituto — o primeiro de cada par é quem saiu, o segundo é quem entrou. A casca — antecessor absorvido, sem inventário próprio — conta como Unificado, que é o que ela é. Mais novo, para quem entrou no escopo e não substitui ninguém. Um EGP pode ter MAIS DE UM: o meio de uma cadeia é as duas pontas ao mesmo tempo, e um sucessor pode ter antecessores de tipos diferentes."
            onToggle={toggleTipoExtra} onClear={() => setTipoExtraSel(new Set())} />
        )}
        <MultiSelect label="Categoria de prontidão" options={PCT_CATEGORIAS} sel={pctCategoriasSel}
          labels={PCT_CATEGORIA_LABEL}
          title="Em qual(is) pedaço(s) da prontidão olhar (mesmo indicador da aba Gestão). Nenhuma selecionada = Completo (média de inputs/outputs/pré-working). Selecionando 1+, a faixa ao lado só deixa passar quem tem TODAS elas dentro do intervalo — e a coluna Prontidão passa a mostrar a média entre as categorias escolhidas."
          onToggle={togglePctCategoria} onClear={() => setPctCategoriasSel(new Set())} />
        <RangeFilter
          label={pctCategoriasSel.size === 0 ? "Prontidão" : `Prontidão (${Array.from(pctCategoriasSel).map((c) => PCT_CATEGORIA_LABEL[c]).join(" + ")})`}
          min={0} max={100} value={pctRange} onChange={setPctRange}
          title={pctCategoriasSel.size === 0
            ? "Faixa do indicador de prontidão geral (média de inputs/outputs/pré-working)."
            : pctCategoriasSel.size === 1
              ? `Faixa do indicador de prontidão, olhando só a categoria ${PCT_CATEGORIA_LABEL[Array.from(pctCategoriasSel)[0]]}.`
              : `Faixa do indicador de prontidão — só passa quem tem TODAS as categorias selecionadas (${Array.from(pctCategoriasSel).map((c) => PCT_CATEGORIA_LABEL[c]).join(", ")}) dentro dela.`} />
        <input type="search" placeholder="filtrar EGP / JIRA…" title="Busca substring no nome do EGP OU no JIRA ID (fuzzy match)."
          value={q} onChange={(e) => setQ(e.target.value)} />
        <label style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 12, cursor: "pointer" }}
          title="Ligado: mostra só EGPs com responsável atribuído. Desligue para ver tudo.">
          <input type="checkbox" checked={soComResp}
            onChange={(e) => setSoComResp(e.target.checked)} />
          só com responsável
        </label>
        {aguardandoQ.error && (
          <span className="chip todo"
            title={`Falha ao ler as versões recebidas: ${String(aguardandoQ.error)}. O alerta está CEGO — a ausência de número aqui NÃO quer dizer que não há versão aguardando entrada no corpus.`}>
            📥 Aguardando corpus: ?
          </span>
        )}
        {(aguardando.length > 0 || pendencias.length > 0) && (
          <button className="chip todo" onClick={() => setShowAguardando(true)}
            title="Versões recebidas do cliente que ainda NÃO viraram projeto do corpus: já foram comparadas e publicadas, mas o pipeline (extrator → orquestrador → publish) ainda não rodou. Até rodar, elas não aparecem em nenhuma linha desta tabela. Clique para ver quais.">
            📥 Aguardando corpus: {aguardando.length}
            {nPendencias > 0 && (
              <span title={`${nPendencias} versão(ões) com pendência: pareamento não resolvido ou falha na extração — a comparação com o antecessor não rodou.`}>
                {" "}· ⚠ {nPendencias} pendência(s)
              </span>
            )}
          </button>
        )}
        {semVinculoQ.error && (
          <span className="chip todo"
            title={`Falha ao ler os EGPs sem vínculo: ${String(semVinculoQ.error)}. O alerta está CEGO — a ausência de número aqui NÃO quer dizer que não há EGP no corpus sem vínculo.`}>
            🔗 Sem vínculo: ?
          </span>
        )}
        {(semVinculo.length > 0 || orfaos.length > 0) && (
          <button className="chip todo" onClick={() => setShowSemVinculo(true)}
            title="EGPs que JÁ entraram no corpus e não aparecem em nenhuma linha desta tabela: fora da linha de base, fora do recorte e sem vínculo com antecessor nem sucessor. Além de invisíveis, eles são contados como dependência e empurram os próprios inputs para o card de dependências da gestão. Clique para ver quais.">
            🔗 Sem vínculo: {semVinculo.length}
            {orfaosInvisiveis.length > 0 && (
              <span title={`${orfaosInvisiveis.length} EGP(s) com vínculo declarado que NÃO aparecem em nenhuma tela: nem o antecessor nem o sucessor estão no recorte. Este alerta é a única coisa no app que os menciona — a lista "sem vínculo" não os pega, justamente porque eles TÊM vínculo.`}>
                {" "}· ⚠ {orfaosInvisiveis.length} invisível(is)
              </span>
            )}
          </button>
        )}
        <div className="rd-count-box">
          <span className="count">{busy ? "carregando…" : `${view.length} de ${rows.length} EGPs`}</span>
          {!busy && <span className="chip ok rd-recebidos" title="EGPs recebidos e analisados no recorte atual">🟢 Recebidos: {rows.length}</span>}
        </div>
        <button className="ghost csv-btn" onClick={exportCsv} disabled={busy || !view.length}
          title="Baixar CSV com as linhas exibidas (filtros + ordenação aplicados)">⬇ Exportar CSV</button>
        <button className="hdr-toggle" onClick={hdr.toggle}
          aria-label={hdr.collapsed ? "Expandir o cabeçalho" : "Recolher o cabeçalho"}
          title={hdr.collapsed
            ? "Expandir o cabeçalho (métricas e chips)"
            : "Recolher o cabeçalho — mais tabela na tela (persistente)"}>
          {hdr.collapsed ? "▾" : "▴"}
        </button>
      </div>

      {!hdr.collapsed && <>
      <section className="metrics compact">
        <InfoTip text="Os três cards de input contam as tabelas distintas lidas pelos EGPs QUE ESTÃO NA TABELA abaixo — recorte, filtros e chips inclusive. Sem filtro ligado eles são os mesmos números da Visão geral para aquele recorte. O card de EGPs é a exceção: ele é a linha de base congelada e não reage a filtro." />
        <div className="card" title="Total CONGELADO (linha de base de 29/09/2026): é o tamanho de uma lista versionada, não uma conta sobre o recorte. Não sobe quando chega versão nova, casca ou dependência inédita, e não cai quando um EGP sai do escopo. A decomposição (escopo / deps / ex) vem da classe gravada nessa lista. O que é vivo é a TABELA abaixo e o andamento de cada EGP.">
          <div className="card-value">
            {nf(cardTotal)}
            {cardExtra > 0 && (
              <button className={`card-extra ${soExtra ? "on" : ""}`}
                onClick={() => setScope(soExtra ? "indi_deps" : "extras")}
                title={soExtra
                  ? "Mostrando só os extras — clique para voltar a Indicium + dependências."
                  : "Extras: EGPs com vínculo de atualização com outro EGP (versão nova ou casca) que estão FORA da linha de base congelada. Contador próprio, fora do total ao lado. Clique para ver QUAIS na tabela."}>
                +{nf(cardExtra)} extra
              </button>
            )}
          </div>
          <div className="card-label">EGPs{cardDeps > 0 || cardEx > 0 ? ` (${nf(cardBase)} escopo + ${nf(cardDeps)} deps${cardEx > 0 ? ` + ${nf(cardEx)} ex` : ""})` : ""}</div>
        </div>
        <div className="card" title="Tabelas/inputs distintos lidos pelos EGPs em tela, sem dupla contagem (dois EGPs que leem a mesma tabela contam uma vez). Mesmo universo e mesma unidade da Visão geral e da aba Inputs — com os filtros desta aba aplicados.">
          <div className="card-value">{nfIn(inputsDist)}</div>
          <div className="card-label">Inputs distintos{filtrosAtivos ? " (filtrado)" : ""}</div>
        </div>
        <div className="card danger" title="Inputs distintos ainda pendentes de ingestão entre os EGPs em tela. Mesma régua da Visão geral: Modernizado, Sanitizado e Autoprodutor contam como resolvidos.">
          <div className="card-value">{nfIn(inputsFaltam)}</div>
          <div className="card-label">A ingerir{filtrosAtivos ? " (filtrado)" : ""}</div>
        </div>
        <div className="card danger" title="Inputs SAS/Local (externo) sem fonte mapeada: sem produtor no corpus e sem fonte externa reconhecida — entre os EGPs em tela.">
          <div className="card-value">{nfIn(inputsSemFonte)}</div>
          <div className="card-label">Sem fonte (SAS/Local){semFontePct !== null ? ` · ${semFontePct.toLocaleString("pt-BR")}%` : ""}</div>
        </div>
      </section>
      <div className="rd-chips">
        <button className={`chip ok ${bucket === "pronto" ? "on" : ""}`} onClick={() => setBucket(bucket === "pronto" ? "" : "pronto")}>🟢 Habilitados: {counts.pronto}</button>
        <button className={`chip wip ${bucket === "quase" ? "on" : ""}`} onClick={() => setBucket(bucket === "quase" ? "" : "quase")}>🟡 Quase: {counts.quase}</button>
        <button className={`chip wip ${bucket === "parcial" ? "on" : ""}`} onClick={() => setBucket(bucket === "parcial" ? "" : "parcial")}>🟠 Parcial: {counts.parcial}</button>
        <button className={`chip todo ${bucket === "bloqueado" ? "on" : ""}`} onClick={() => setBucket(bucket === "bloqueado" ? "" : "bloqueado")}>🔴 Bloqueado: {counts.bloqueado}</button>
        <button className={`chip cyc ${bucket === "ciclo" ? "on" : ""}`} onClick={() => setBucket(bucket === "ciclo" ? "" : "ciclo")}>⟳ Em ciclo: {counts.ciclo}</button>
        <span className="sep" />
        <button className={`chip ok ${quickWin ? "on" : ""}`} title="EGPs sem bloqueio pendente — nenhuma dependência (direta/transitiva) de tabela SAS sem produtor mapeado; migráveis agora"
          onClick={() => setQuickWin((v) => !v)}>⚡ Quick win (sem bloqueio): {qwCount}</button>
        <button className={`chip todo ${blockedOnly ? "on" : ""}`} title="EGPs bloqueados: dependem (direta/transitivamente) de tabelas SAS sem produtor (EGP) mapeado"
          onClick={() => setBlockedOnly((v) => !v)}>🔒 Bloqueio dependência: {blkCount}</button>
        <button className={`chip cyc ${despOnly ? "on" : ""}`} title="EGPs impactados por dependência despriorizada — dependem (direta/transitivamente) de EGP fora do backlog; o output que consomem não será produzido pelo plano"
          onClick={() => setDespOnly((v) => !v)}>⏸ Dep. despriorizada: {despCount}</button>
        <button className={`chip wip ${pendOnly ? "on" : ""}`} title="Só o que falta fazer: oculta EGPs com status Migrado, Despriorizado e Contabilizado e ex-dependências"
          onClick={() => setPendOnly((v) => !v)}>◻ Só pendentes: {pendCount}</button>
        <button className={`chip ok ${convOnly ? "on" : ""}`} title="EGPs com Fim Conversão preenchido em sas_gestao_datas — presença = já convertido (pré ou pós funil)"
          onClick={() => setConvOnly((v) => !v)}>✔ Convertidos: {convCount}</button>
        <button className={`chip todo ${noOutOnly ? "on" : ""}`} title="EGPs sem nenhum output no corpus (consumidores puros) — candidatos a revisão de escopo/objetivo"
          onClick={() => setNoOutOnly((v) => !v)}>⊘ Sem outputs: {noOutCount}</button>
        <button className={`chip todo ${brokenOnly ? "on" : ""}`} title="EGPs com pelo menos 1 vínculo quebrado — declararam não depender de algum input compartilhado"
          onClick={() => setBrokenOnly((v) => !v)}>⛓️‍💥 Vínculos quebrados: {brokenCount}</button>
        {exSemEtapaCount > 0 && (
          <button className={`chip cyc ${showExSemEtapa ? "on" : ""}`}
            title="EGPs FORA da linha de base congelada (na prática, ex-dependências que não entraram na lista de 29/09/2026): não contam no card de total, por isso estão ocultos por padrão — assim a lista bate com o card. Ligue para revê-los (alguns têm pré-conversão concluída, com responsável e JIRA). Os EXTRAS também ficam fora do total, mas têm contador e recorte próprios."
            onClick={() => setShowExSemEtapa((v) => !v)}>👁 Fora da linha de base: {exSemEtapaCount}</button>
        )}
        <button className={`chip wip ${vinculadoOnly ? "on" : ""}`}
          title="EGPs com alguma versão atualizada vinculada (aba EGPs Atualizados) — confirmada (🔗) OU só sugerida pelo pareamento automático (❔), ainda sem o humano confirmar"
          onClick={() => setVinculadoOnly((v) => !v)}>🔗 Atualização vinculada: {vinculadoCount}</button>
        <button className={`chip ok ${remessaOnly ? "on" : ""}`}
          title="EGPs onde 100% do que falta já está em PDI+GMUD ou Ingestão PRD — ficariam prontos (n_faltam=0) se essa remessa em trânsito completasse (virasse Modernizado)"
          onClick={() => setRemessaOnly((v) => !v)}>🚚 Desbloqueia c/ remessa PDI+GMUD/PRD: {remessaCount}</button>
        <InfoTip text="Cada chip é um filtro liga/desliga; o número é a contagem no recorte + filtros de cima (não considera os outros chips). 🟢 habilitado · 🟡/🟠 quase/parcial · 🔴 bloqueado · ⟳ em ciclo · ⚡ sem bloqueio pendente · 🔒 bloqueado por dependência · ⏸ impactado por despriorizada · ◻ pendente (falta fazer) · ✔ convertido · ⊘ não produz outputs · ⛓️‍💥 com vínculo quebrado · 👁 fora da linha de base congelada (oculto por padrão; fora do card de total) · 🔗 com atualização vinculada · 🚚 100% do que falta já em PDI+GMUD/Ingestão PRD." />
      </div>
      {/* só depois do cadastro chegar: antes, TODOS os EGPs cairiam num único chip
          "Sem sub-área" e a linha inteira piscaria */}
      {cadastroPronto && <div className="rd-chips">
        <span className="rd-chips-lbl">Sub-área BV</span>
        {subareaList.map((s) => (
          <button key={s} className={`chip ${s === SEM_SUBAREA ? "todo" : "wip"} ${subareaSel.has(s) ? "on" : ""}`}
            title={s === SEM_SUBAREA
              ? "EGPs sem Responsável BV, ou com um responsável que não está no cadastro da Gestão"
              : `EGPs cujo Responsável BV é da sub-área ${s}`}
            onClick={() => toggleSubarea(s)}>{s}: {subareaCounts.get(s) ?? 0}</button>
        ))}
        <InfoTip text="Área interna do BV a que pertence o Responsável BV do EGP. É atributo da PESSOA: cadastre em Gestão → Responsáveis BV e todos os EGPs dela mudam junto. Cada chip é o mesmo filtro do seletor 'Sub-área BV' acima; a contagem ignora o próprio filtro de sub-área (por isso selecionar uma não zera as outras)." />
      </div>}
      </>}
      {hdr.collapsed && (
        <div className="hdr-slim" role="button" tabIndex={0} onClick={hdr.toggle}
          onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); hdr.toggle(); } }}
          title="Cabeçalho recolhido — clique para expandir">
          <b>{nf(cardTotal)}</b> EGPs · <b className="danger">{nfIn(inputsFaltam)}</b> a ingerir
          · 🟢 {counts.pronto} · 🔴 {counts.bloqueado} · ⚡ {qwCount} quick win · ◻ {pendCount} pendentes
        </div>
      )}
      {err && <div className="error">{err}</div>}
      {notFound && (
        <div className="error rd-notfound">
          <span>EGP <b>{shortName(notFound)}</b> não encontrado — o link pode estar desatualizado.</span>
          <button className="row-x" onClick={() => setNotFound(null)} title="fechar">✕</button>
        </div>
      )}

      <div className="rd-table rd-egps">
        {/* O scroll horizontal vive no .rd-tbody (para as colunas # e EGP poderem ser
            sticky — sticky se ancora no container de scroll mais próximo). O cabeçalho
            fica num wrapper recortado e acompanha por scrollLeft no onScroll do corpo. */}
        <div className="rd-thead-wrap" ref={headWrapRef}>
        <div className="rd-thead with-tipo">
          <div className="rd-idx">#</div>{th("projeto", "EGP")}
          <div>JIRA</div>
          <div>Tipo</div>
          {th("area", "Área")}
          <div>Mês</div>{th("n_inputs", "Inputs")}
          {th("loc", "LOC", "Linhas de código do EGP (soma de LINES_OF_CODE do header extraído) — ordene para achar os menores/maiores primeiro")}
          {th("pct", "% modernizado", "Inputs do EGP já disponíveis no BigQuery/lake, + inputs em Ingestão PRD/Aplicação de Grant (desbloqueados, contam com o mesmo peso — sinalizados com ⚑, nunca fecham 100% sozinhos). 100% sem ⚑ + fora de ciclo = realmente pronto pra migrar. Clique na linha para abrir o detalhe.")}
          {th("prontidao", "Prontidão", "Indicador composto de prontidão (mesmo da aba Gestão): inputs + outputs + pré-working — reage à Categoria de prontidão selecionada no filtro")}
          {th("n_faltam", "Faltam")}{th("n_deps", "Depende de")}<div>Etapa</div><div>Status</div>
          <div title={TIPO_VINCULO_HELP}>Vínculo</div>
          <div>Responsável</div><div>Responsável BV</div><div>Sub-área BV</div>
        </div>
        </div>
        <div className="rd-tbody" onScroll={onBodyScroll}>
          {view.map((r, idx) => {
            const b = bucketOf(r);
            const isOpen = openEgp === r.projeto;
            return (
              <Fragment key={r.projeto}>
                <div
                  ref={(el) => { if (el) rowRefs.current.set(r.projeto, el); else rowRefs.current.delete(r.projeto); }}
                  className={`rd-trow clickable with-tipo ${isOpen ? "sel" : ""} ${flash === r.projeto ? "flash" : ""} ${r.atualizado_link_key ? (r.egp_atualizado_key ? "rd-atu-confirmed" : "rd-atu-suggested") : ""}`}
                  onClick={() => toggle(r.projeto)}>
                  <div className="rd-idx">{idx + 1}</div>
                  <div className="c-art">
                    {/* link real p/ o deep-link: botão do meio/ctrl+clique/"abrir em nova guia"
                        funcionam nativamente; clique normal segue abrindo o modal. */}
                    <a className="rd-egp-link" href={pathFor("readiness", r.projeto)}
                      title={`${r.projeto} — clique: detalhe · botão do meio/ctrl+clique: nova guia`}
                      onClick={(e) => spaLinkClick(e, () => toggle(r.projeto), { stop: true })}>
                      <span className="dep-caret">{isOpen ? "▾" : "▸"}</span> {shortName(r.projeto)}
                    </a>
                    {r.bloqueado_dep && <span style={{ marginLeft: 4 }} role="img" aria-label="bloqueado por dependência" title="Bloqueado: depende de tabelas SAS sem produtor (EGP) mapeado">🔒</span>}
                    {r.dep_ausente && <span style={{ marginLeft: 4 }} role="img" aria-label="input sem fonte" title={`${r.n_sem_fonte} input(s) SAS/Local sem fonte`}>⚠</span>}
                    {(r.deps_despriorizadas?.length ?? 0) > 0 && <span style={{ marginLeft: 4 }} role="img" aria-label="impactado por dependência despriorizada" title={`Impactado por dependência despriorizada: ${(r.deps_despriorizadas ?? []).map(shortName).join(", ")}`}>⏸</span>}
                    {(r.n_links_broken ?? 0) > 0 && <span className="rd-badge rd-vinc" style={{ marginLeft: 4 }} title={`${r.n_links_broken} vínculo(s) quebrado(s) — este EGP declarou não depender de ${r.n_links_broken} input(s)`}>⛓️‍💥 {r.n_links_broken}</span>}
                    {r.desbloqueia_remessa && <span style={{ marginLeft: 4 }} role="img" aria-label="desbloqueia com a remessa" title={`Ficaria pronto (${r.n_faltam} de ${r.n_faltam} pendências) se a remessa em trânsito (PDI+GMUD/Ingestão PRD) completasse`}>🚚</span>}
                    {r.atualizado_link_key && (
                      <span className={`rd-badge ${r.egp_atualizado_key ? "rd-atu-badge-confirm" : "rd-atu-badge-auto"}`}
                        style={{ marginLeft: 4 }}
                        title={r.egp_atualizado_key
                          ? `Vínculo confirmado com versão atualizada: "${r.atualizado_link_nome}" — ver seção "Versão atualizada" no detalhe`
                          : `Sugestão automática de versão atualizada (não confirmada): "${r.atualizado_link_nome}" — confirme no detalhe do EGP`}>
                        🔄
                      </span>
                    )}
                  </div>
                  <div className="rd-jira" onClick={(e) => e.stopPropagation()}>
                    <JiraIdInput value={r.jira_id ?? null} className=""
                      onSave={(v) => pipeMut.mutate({ projeto: r.projeto, jira_id: v })} />
                  </div>
                  <div onClick={(e) => e.stopPropagation()}>
                      {r.e_extra
                        ? <span className="ms-badge extra" title={extraTitle(r)}>extra</span>
                        : r.tipo === "ex_dependencia"
                        ? <span className="ms-badge exdep" title={`Já foi dependência do recorte e saiu (${r.ex_motivo ?? "motivo não determinado"}). Retido no painel para o esforço não desaparecer — fora dos contadores de inputs.`}>ex-dependência</span>
                        : r.tipo === "dependencia"
                          ? <span className="ms-badge dep" title={`dependência (nível ${r.dep_nivel})`}>dependência ·{r.dep_nivel}</span>
                          : <span className="ms-badge scope">escopo</span>}
                      {/* O papel no vínculo vale para QUALQUER linha, não só para extra:
                          o antecessor costuma estar no escopo e é ele quem fica
                          Desatualizado. Por isso fica fora do ternário acima. */}
                      <VinculoPapeis linha={r} />
                      {/* Escape hatch da detecção automática: a via foi dada como resolvida
                          (tabela no lake), mas o consumidor ainda precisa do PRODUTOR — caso
                          da ingestão que não cobre o que ele lê. Reabre a aresta; o EGP volta
                          a ser dependência viva. Só onde faz sentido oferecer: ex-dep
                          "resolvida por ingestão", ou uma já mantida (para desfazer). */}
                      {(r.ex_motivo === "resolvida por ingestão" || r.dep_mantida) && pode && (
                        <button className={`dep-keep-btn${r.dep_mantida ? " on" : ""}`}
                          disabled={depMut.isPending}
                          title={r.dep_mantida
                            ? "Dependência mantida à mão: a via está resolvida, mas alguém declarou que este produtor ainda é necessário. Clique para voltar ao automático."
                            : "A via deste produtor entrou no lake e a dependência caiu. Se ele ainda é necessário (ingestão não cobre o que o consumidor lê), clique para reabrir a dependência."}
                          onClick={() => depMut.mutate({ produtor: r.projeto, mantida: !r.dep_mantida })}>
                          {r.dep_mantida ? "↩ mantida à mão" : "ainda é dependência"}
                        </button>
                      )}
                  </div>
                  <div className="c-src">{r.area}</div>
                  <div className={r.ciclo_id > 0 ? "cyc-txt" : ""}>{mesTag(mesOf.get(r.projeto))}{r.ciclo_id > 0 ? " ⟳" : ""}</div>
                  <div className="c-num">{r.n_inputs}</div>
                  <div className="c-num">{r.loc}</div>
                  <div className="rd-pct" title={r.n_prd
                    ? `${r.n_prd} input(s) já em Ingestão PRD/Aplicação de Grant — desbloqueado, ainda não Modernizado`
                    : undefined}>
                    <div className="rd-bar">
                      <div className={`rd-fill ${BUCKET[b].tone}`} style={{ width: `${r.pct}%` }}>
                        {!!r.n_prd && r.n_inputs > 0 && r.pct > 0 && (
                          <div className="rd-fill-prd"
                            style={{ width: `${Math.min(100, (100 * r.n_prd / r.n_inputs) / (r.pct / 100))}%` }} />
                        )}
                      </div>
                    </div>
                    <span>{r.pct}%{!!r.n_prd && <span className="kanban-gauge-flag">⚑</span>}</span>
                  </div>
                  <div className="rd-prontidao">
                    {(() => {
                      const pv = pctCard(r, pctCategoriasSel);
                      return <Gauge pct={pv} secondaryPct={pctCardPrdShare(r, pctCategoriasSel)}
                        title={pctGaugeTitulo(pv, pctCategoriasSel)} size="sm" />;
                    })()}
                  </div>
                  <div className="c-num">
                    {r.n_faltam || ""}
                    {!!r.n_prd && <span className="rd-prd-note" title="dos quais já em Ingestão PRD/Aplicação de Grant">{` (${r.n_prd} em PRD)`}</span>}
                  </div>
                  <div className={`rd-deps ${r.n_deps ? "has" : ""}`}>
                    {r.n_deps ? (
                      <>
                        <span className="dep-tot">{r.n_deps}</span>
                        <span className="dep-bd">
                          {r.n_deps_indi > 0 && <span className="dep-b indi">{r.n_deps_indi}i</span>}
                          {r.n_deps_ext > 0 && <span className="dep-b ext">{r.n_deps_ext}e</span>}
                        </span>
                      </>
                    ) : ""}
                  </div>
                  <div className="rd-etapa" onClick={(e) => e.stopPropagation()}>
                    <select value={r.etapa} disabled={r.etapa_editavel === false || !pode}
                      title={r.etapa_editavel === false
                        ? `Etapa espelhada de "${r.sucessor}" — edite no EGP sucessor`
                        : undefined}
                      onChange={(e) => pipeMut.mutate({ projeto: r.projeto, etapa: e.target.value })}>
                      <option value="">— etapa —</option>
                      {PIPELINE_PROJETO.migracao.map((s) => <option key={s} value={s}>{s}</option>)}
                      <optgroup label="Fora do funil">
                        {PHANTOM_ETAPAS_MIGRACAO.map((s) => <option key={s} value={s}>{s}</option>)}
                      </optgroup>
                    </select>
                  </div>
                  <div className="rd-status" onClick={(e) => e.stopPropagation()}>
                    <select value={r.status} title={STATUS_HELP} disabled={!pode}
                      style={{ background: SEG[r.status]?.bg, color: SEG[r.status]?.fg }}
                      onChange={(e) => { const v = e.target.value;
                        if (!confirmStatusTerminal(v, shortName(r.projeto))) return;
                        pipeMut.mutate({ projeto: r.projeto, status: v }); }}>
                      {opcoesStatusEgp(r.status).map((o) => <option key={o.value} value={o.value} disabled={o.disabled}>{o.label}</option>)}
                    </select>
                  </div>
                  {/* Tipo de vínculo (pedido 2026-09): coluna própria, editável direto daqui —
                      grava em sas_egp_atualizados_pipeline via egp_atualizado_key (a mesma
                      tabela/campo que o "Pipeline da troca" em EgpsAtualizadosView.tsx),
                      não em sas_egp_pipeline. Só edita quando o vínculo já foi CONFIRMADO
                      (egp_atualizado_key) — sem isso não há pra qual troca gravar o tipo;
                      confirme primeiro no painel de detalhe (seção "Versão atualizada"). */}
                  <div className="rd-vinculo" onClick={(e) => e.stopPropagation()}
                    title={!r.egp_atualizado_key
                      ? "Confirme o vínculo com uma versão atualizada no detalhe do EGP (seção \"Versão atualizada\") antes de classificar o tipo"
                      : TIPO_VINCULO_HELP}>
                    {r.egp_atualizado_key ? (
                      <select value={r.atualizado_link_tipo_vinculo ?? ""} disabled={!pode}
                        onChange={(e) => {
                          const projeto = r.projeto;
                          // destaca + rola até a linha: a tabela reordena no refetch e sem
                          // isto o EGP "some" de onde estava (achado do usuário, 2026-09).
                          vinculoMut.mutate({ egp_key: r.egp_atualizado_key!, tipo_vinculo: e.target.value }, {
                            onSuccess: () => {
                              setFlash(projeto);
                              requestAnimationFrame(() => requestAnimationFrame(() =>
                                rowRefs.current.get(projeto)?.scrollIntoView({ behavior: scrollBehavior(), block: "center" })));
                            },
                          });
                        }}>
                        <option value="">— tipo —</option>
                        {Object.entries(TIPO_VINCULO_LABEL).map(([k, label]) =>
                          <option key={k} value={k}>{label}</option>)}
                      </select>
                    ) : <span className="de-meta">—</span>}
                  </div>
                  <div className="rd-resp" onClick={(e) => e.stopPropagation()}>
                    <select value={r.responsavel ?? ""} title="Responsável pela migração deste EGP" disabled={!pode}
                      onChange={(e) => pipeMut.mutate({ projeto: r.projeto, responsavel: e.target.value })}>
                      <option value="">—</option>
                      {r.responsavel && !analistaEmails.has(r.responsavel) && (
                        <option value={r.responsavel}>{r.responsavel}</option>
                      )}
                      {analistas.map((a) => <option key={a.email} value={a.email}>{a.nome || a.email}</option>)}
                    </select>
                  </div>
                  <div className="rd-respbv" onClick={(e) => e.stopPropagation()}>
                    <RespBvInput value={r.responsavel_bv ?? null}
                      onSave={(v) => pipeMut.mutate({ projeto: r.projeto, responsavel_bv: v ?? "" })} />
                  </div>
                  <div className="rd-subarea"
                    title="Sub-área BV — derivada do Responsável BV (cadastro em Gestão → Responsáveis BV); não se edita por EGP">
                    {subOf(r)}
                  </div>
                </div>
              </Fragment>
            );
          })}
        </div>
      </div>

      {showAguardando && (
        <DetailModal onClose={() => setShowAguardando(false)}
          title={`${aguardando.length} versão(ões) recebida(s) aguardando entrada no corpus`
            + (nPendencias ? ` · ${nPendencias} com pendência` : "")}>
          <div className="muted" style={{ marginBottom: 8 }}>
            Chegaram do cliente e já foram comparadas, mas ainda não são projeto do corpus:
            só entram depois de uma rodada do pipeline (extrator → orquestrador → publish),
            com a chave <b>Área__nome__ATU&lt;data de recebimento&gt;</b>. Até lá não aparecem
            em nenhuma linha desta tabela. A lista é derivada — some sozinha quando o pipeline
            roda, ou quando a versão é descartada da aba.
          </div>
          <div className="egp-panel" style={{ maxHeight: "60vh" }}>
            {aguardando.map((v) => (
              <div key={v.versao_id} className="dep">
                <span className="dep-proj" title={v.versao_id}>{v.nome}</span>
                <span className="dep-meta">{v.area} · recebida em {v.data_recebimento}</span>
                <span className="dep-via"
                  title={`Antecessor: ${v.egp_original ?? "nenhum (EGP inédito)"} — chave prevista no corpus: ${v.chave_prevista}`}>
                  {v.pendencia && <span className="mf-flag mf-warn" title={PENDENCIA_HELP}>⚠ {v.pendencia}</span>}
                  {v.pendencia ? " · " : ""}
                  antecessor: {v.egp_original ? shortName(v.egp_original) : "— inédito"} · vira {v.chave_prevista}
                </span>
              </div>
            ))}
          </div>
          {pendencias.length > 0 && (
            <>
              <div className="muted" style={{ margin: "12px 0 8px" }}>
                <b>Já entraram no corpus, mas seguem com pendência</b> — {PENDENCIA_HELP}
              </div>
              <div className="egp-panel" style={{ maxHeight: "30vh" }}>
                {pendencias.map((v) => (
                  <div key={v.versao_id} className="dep">
                    <span className="dep-proj" title={v.versao_id}>{v.nome}</span>
                    <span className="dep-meta">{v.area} · recebida em {v.data_recebimento}</span>
                    <span className="dep-via">
                      <span className="mf-flag mf-warn">⚠ {v.pendencia}</span>
                    </span>
                  </div>
                ))}
              </div>
            </>
          )}
        </DetailModal>
      )}

      {showSemVinculo && (
        <DetailModal onClose={() => setShowSemVinculo(false)}
          title={`${semVinculo.length} EGP(s) no corpus sem vínculo`
            + (orfaos.length ? ` · ${orfaos.length} vínculo(s) órfão(s)` : "")}>
          <div className="muted" style={{ marginBottom: 8 }}>
            Já são projeto do corpus, mas não têm linha em tela nenhuma: estão fora da linha
            de base congelada, fora do recorte e sem vínculo em nenhuma das duas direções —
            não são antecessor de ninguém nem sucessor de ninguém. <b>O custo não é só ficar
            escondido:</b> sem vínculo o app não sabe que o EGP é versão nova de alguém,
            então ele entra no grafo como produtor qualquer e os inputs dele caem no card de
            dependências da gestão. Medido em 30/09/2026: 3 EGPs nessa condição moveram 26
            inputs e o card de dependências marcava <b>88</b> contra os <b>61</b> de
            produção. Criar o vínculo (no detalhe do antecessor) tira o EGP desta lista.
          </div>
          <div className="egp-panel" style={{ maxHeight: "60vh" }}>
            {semVinculo.map((v) => (
              <div key={v.projeto} className="dep">
                <span className="dep-proj">
                  {/* mesmo link da tabela: clique abre o detalhe, ctrl/meio abre em nova
                      guia. O EGP está fora do recorte, então não há linha para expandir —
                      o modal do detalhe é a única porta que ele tem. */}
                  <a className="rd-egp-link" href={pathFor("readiness", v.projeto)}
                    title={`${v.projeto} — clique: abre o EGP · botão do meio/ctrl+clique: nova guia`}
                    onClick={(e) => spaLinkClick(e, () => { setShowSemVinculo(false); setOpenEgp(v.projeto); })}>
                    {shortName(v.projeto)}
                  </a>
                </span>
                <span className="dep-meta">{v.projeto}</span>
                <span className="dep-via"
                  title={v.antecessor_sugerido
                    ? `Antecessor sugerido pelo pareamento medido (hash de tasks) em sas_egp_atualizados — confira antes de vincular: ${v.antecessor_sugerido}`
                    : "Nenhum candidato a antecessor no pareamento medido. Pode ser EGP inédito (entrou no escopo sem substituir ninguém) — sugerir por semelhança de nome custaria um vínculo errado."}>
                  antecessor sugerido: {v.antecessor_sugerido
                    ? shortName(v.antecessor_sugerido)
                    : "— nenhum candidato"}
                </span>
              </div>
            ))}
          </div>
          {orfaosInvisiveis.length > 0 && (
            <>
              <div className="muted" style={{ margin: "12px 0 8px" }}>
                <b>Vínculo órfão — EGP invisível</b>: o vínculo foi declarado, mas nem o
                antecessor nem o sucessor estão no recorte. O EGP foi publicado e não existe
                em nenhuma tela de trabalho. Este bloco é a única coisa que o menciona: a
                lista acima não o pega, justamente porque ele <b>tem</b> vínculo.
              </div>
              <div className="egp-panel" style={{ maxHeight: "30vh" }}>
                {orfaosInvisiveis.map((o) => (
                  <div key={`${o.antecessor}→${o.sucessor}`} className="dep">
                    <span className="dep-proj" title={o.antecessor}>{shortName(o.antecessor)}</span>
                    <span className="dep-meta">→ {shortName(o.sucessor)}</span>
                    <span className="dep-via" title={`Sucessor: ${o.sucessor}`}>
                      <span className="mf-flag mf-warn">⚠ invisível no app</span>
                      {o.tipo ? ` · ${o.tipo}` : ""}
                    </span>
                  </div>
                ))}
              </div>
            </>
          )}
          {orfaosInertes.length > 0 && (
            <>
              <div className="muted" style={{ margin: "12px 0 8px" }}>
                <b>Vínculo inerte</b> — o antecessor está fora do recorte, então o vínculo
                não exibe “Desatualizado”, não espelha etapa e não puxa nada. Mas o
                <b> sucessor aparece assim mesmo</b>, por outro antecessor ou com badge de
                ex-dependência. Fica aqui como registro, não como pendência: na medição de
                01/10/2026 eram 3 de 4, e dois deles vieram de decisões deliberadas da
                gestão.
              </div>
              <div className="egp-panel" style={{ maxHeight: "24vh" }}>
                {orfaosInertes.map((o) => (
                  <div key={`${o.antecessor}→${o.sucessor}`} className="dep">
                    <span className="dep-proj" title={o.antecessor}>{shortName(o.antecessor)}</span>
                    <span className="dep-meta">→ {shortName(o.sucessor)}</span>
                    <span className="dep-via" title={`Sucessor: ${o.sucessor} — aparece na tabela por outro caminho`}>
                      antecessor fora do recorte{o.tipo ? ` · ${o.tipo}` : ""}
                    </span>
                  </div>
                ))}
              </div>
            </>
          )}
        </DetailModal>
      )}

      {openEgp && (
        <DetailModal onClose={() => setOpenEgp(null)}>
          <EgpDetailPanel projeto={openEgp} row={rows.find((x) => x.projeto === openEgp)}
            onOpenInput={onOpenInput}
            onOpenEgp={(p) => {
              if (scope !== "base" && !rows.some((x) => x.projeto === p)) setScope("base");
              setOpenEgp(p);
              requestAnimationFrame(() => requestAnimationFrame(() =>
                rowRefs.current.get(p)?.scrollIntoView({ behavior: scrollBehavior(), block: "center" })));
            }} />
        </DetailModal>
      )}

    </div>
  );
}
