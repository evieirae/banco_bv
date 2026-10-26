import type {
  AppConfig, Filters, InputRow, InputsResponse, Metrics, BlockingPayload,
  LineageNode, LineagePayload, EgpDetail, WaveRow, AuditRow, ReadinessPayload, EgpInputUnits, ResumoPayload,
  InputDetail, IndiciumPayload, LandingMetrics,
  FunisPayload, TempoEtapasPayload, TempoAnalisesPayload, TempoFiltro, TempoFiltroInput,
  FunilIngestaoMes, FunilMesExtras, ScopeEgps, AnalistasPayload, PriorizacaoPayload,
  OutputsResponse, OutputDetail, PreworkingRow, OutputPipelineRow,
  EgpsAtualizadosResponse, EgpAtualizadoDetail, ResponsaveisBvPayload, SanFragilidade,
  AguardandoCorpusPayload, EgpsSemVinculoPayload, EgpsExtras, EgpsNovosPayload,
} from "./types";
import type { MeResposta } from "./escrita";
import { destinoDoLogin } from "./login";

// `status` vai junto no Error (mensagem inalterada) p/ o retry global do React Query
// distinguir 4xx (definitivo, não repete) de falha transitória — ver App.tsx.
async function json<T>(r: Response): Promise<T> {
  if (!r.ok) {
    const texto = await r.text();
    const login = destinoDoLogin(r.status, texto, window.location.pathname, window.location.search);
    if (login) window.location.assign(login);
    throw Object.assign(new Error(`${r.status} ${texto}`), { status: r.status });
  }
  return r.json() as Promise<T>;
}

function tempoFiltroParams(f: TempoFiltro): URLSearchParams {
  const p = new URLSearchParams();
  (f.responsavel ?? []).forEach((r) => p.append("responsavel", r));
  (f.responsavel_bv ?? []).forEach((r) => p.append("responsavel_bv", r));
  (f.projeto ?? []).forEach((pr) => p.append("projeto", pr));
  (f.status ?? []).forEach((s) => p.append("status", s));
  (f.com_bv ?? []).forEach((c) => p.append("com_bv", c));
  return p;
}

function tempoFiltroInputParams(f: TempoFiltroInput): URLSearchParams {
  const p = new URLSearchParams();
  (f.responsavel ?? []).forEach((r) => p.append("responsavel", r));
  (f.categoria ?? []).forEach((c) => p.append("categoria", c));
  (f.origem ?? []).forEach((o) => p.append("origem", o));
  (f.chave ?? []).forEach((c) => p.append("chave", c));
  (f.status ?? []).forEach((s) => p.append("status", s));
  (f.com_bv ?? []).forEach((c) => p.append("com_bv", c));
  return p;
}

export const api = {
  me: () => fetch("api/me").then(json<MeResposta>),
  config: () => fetch("api/config").then(json<AppConfig>),
  metrics: (scope: string, area: string[] = []) => {
    const p = new URLSearchParams();
    p.set("scope", scope);
    area.forEach((a) => p.append("area", a));
    return fetch(`api/metrics?${p}`).then(json<Metrics>);
  },

  inputs: (f: Filters) => {
    const p = new URLSearchParams();
    p.set("scope", f.scope);
    f.categoria.forEach((c) => p.append("categoria", c));
    f.origem.forEach((o) => p.append("origem", o));
    f.etapa.forEach((e) => p.append("etapa", e));
    f.status.forEach((s) => p.append("status", s));
    f.area.forEach((a) => p.append("area", a));
    if (f.q) p.set("q", f.q);
    p.set("divergence", String(f.divergence));
    return fetch(`api/inputs?${p}`).then(json<InputsResponse>);
  },

  // profundidade necessária de um par (EGP, família); tipo:"" volta ao derivado. Gestão.
  familiaPeriodo: (b: { projeto: string; categoria: string; familia: string; tipo: string; valor?: string | null }) =>
    fetch("api/familia-periodo", {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(b),
    }).then(json<{ ok: boolean; tipo: string | null; valor: string | null; origem: string }>),

  // profundidade INGERIDA de uma família (fato consumado; qualquer analista logado).
  // desde:"" apaga o registro.
  familiaIngestao: (b: { categoria: string; familia: string; desde?: string | null; ingerida_em?: string | null }) =>
    fetch("api/familia-ingestao", {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(b),
    }).then(json<{ ok: boolean; desde: string | null }>),

  inputDetail: (chave: string) =>
    fetch(`api/input?chave=${encodeURIComponent(chave)}`).then(json<InputDetail>),

  // Checklist de pré-working (sas_inputs_preworking): tabela pequena, carregada inteira
  // uma vez — badge de completude na tabela de Inputs + seção no InputDetailPanel usam a
  // mesma queryKey ["preworking"] (cache compartilhado, mesmo padrão de gestaoApi.listRows).
  preworkingRows: () => fetch("api/inputs/preworking").then(json<{ rows: PreworkingRow[] }>),
  preworkingPatch: (body: Partial<PreworkingRow> & { chave_canonica: string }) =>
    fetch("api/inputs/preworking", {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }).then(json<PreworkingRow>),

  // Fragilidade da sanitização derivada — aviso permanente da aba Inputs. Derivado e
  // cacheado por geração no backend; sem parâmetro porque o recorte é único (o mais
  // largo), o mesmo do conjunto derivado.
  fragilidade: () => fetch("api/inputs/fragilidade").then(json<SanFragilidade>),

  // mapeamento input->EGP(s) do recorte, p/ o export "uma linha por (input x EGP)".
  inputsEgps: (scope: string, area: string[] = []) => {
    const p = new URLSearchParams();
    p.set("scope", scope);
    area.forEach((a) => p.append("area", a));
    return fetch(`api/inputs-egps?${p}`).then(json<{ rows: { chave_canonica: string; projeto: string }[] }>);
  },

  scopeEgps: (scope: string, area: string[] = []) => {
    const p = new URLSearchParams();
    p.set("scope", scope);
    area.forEach((a) => p.append("area", a));
    return fetch(`api/scope-egps?${p}`).then(json<ScopeEgps>);
  },

  // Os extras por extenso: o "(+N extra)" diz quantos, isto diz QUAIS.
  egpsExtras: () => fetch("api/egps-extras").then(json<EgpsExtras>),

  indicium: () => fetch("api/indicium").then(json<IndiciumPayload>),

  landing: () => fetch("api/landing").then(json<LandingMetrics>),

  funis: () => fetch("api/funis").then(json<FunisPayload>),

  tempoEtapas: (f: TempoFiltro = {}) => {
    const p = tempoFiltroParams(f);
    return fetch(`api/tempo-etapas?${p}`).then(json<TempoEtapasPayload>);
  },

  tempoAnalises: (f: TempoFiltro = {}) => {
    const p = tempoFiltroParams(f);
    return fetch(`api/tempo-analises?${p}`).then(json<TempoAnalisesPayload>);
  },

  // Irmãos dos 2 acima, pro funil de ingestão (ver _tempo_etapas_input/_analises_tempo_input).
  tempoEtapasInput: (f: TempoFiltroInput = {}) => {
    const p = tempoFiltroInputParams(f);
    return fetch(`api/tempo-etapas-input?${p}`).then(json<TempoEtapasPayload>);
  },
  tempoAnalisesInput: (f: TempoFiltroInput = {}) => {
    const p = tempoFiltroInputParams(f);
    return fetch(`api/tempo-analises-input?${p}`).then(json<TempoAnalisesPayload>);
  },

  // Funil de ingestão cruzado com o mês do plano. Universo = frontier vivo (mesmo dos
  // cards da Visão geral), NÃO o do plano congelado — ver docstring do endpoint.
  funilIngestaoMes: () => fetch("api/funil-ingestao-mes").then(json<FunilIngestaoMes>),
  // irmãos dos dois acima, só p/ os extras: mesmo shape, mês vindo do ANTECESSOR
  funilMesExtras: () => fetch("api/funil-mes-extras").then(json<FunilMesExtras>),
  funilIngestaoMesExtras: () =>
    fetch("api/funil-ingestao-mes-extras").then(json<FunilIngestaoMes>),

  egpPipeline: (body: { projeto: string; etapa?: string | null; status?: string | null; responsavel?: string | null; responsavel_bv?: string | null; jira_id?: string | null; preworking?: boolean; preworking_data?: string | null; egp_atualizado_key?: string | null;
    // Vínculo antecessor -> sucessor (spec §1). Aponta para o PROJETO do corpus, não
    // para a chave da aba de recebimentos (egp_atualizado_key acima). "" desfaz o vínculo.
    egp_vinculo_tipo?: string | null; egp_sucessor?: string | null }) =>
    fetch("api/egp-pipeline", {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ funil: "migracao", ...body }),
    }).then(json<{ ok: boolean; etapa: string | null; status: string | null; responsavel: string | null; jira_id: string | null; preworking: boolean; preworking_data: string | null }>),

  analistas: (incluirInativos = false) =>
    fetch(`api/analistas${incluirInativos ? "?incluir_inativos=true" : ""}`).then(json<AnalistasPayload>),
  analistaUpsert: (body: { email: string; nome?: string; ativo?: boolean; organograma?: boolean; papel?: string }) =>
    fetch("api/analistas", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }).then(json<{ ok: boolean; email: string; nome: string }>),
  analistaDelete: (email: string) =>
    fetch(`api/analistas/${encodeURIComponent(email)}`, { method: "DELETE" }).then(json<{ ok: boolean }>),

  responsaveisBv: (incluirInativos = false) =>
    fetch(`api/responsaveis-bv${incluirInativos ? "?incluir_inativos=true" : ""}`).then(json<ResponsaveisBvPayload>),
  responsavelBvUpsert: (body: { nome: string; subarea?: string; ativo?: boolean }) =>
    fetch("api/responsaveis-bv", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }).then(json<{ ok: boolean; nome_key: string; nome: string }>),

  // EGPs declarados NOVOS (ticket 24). O PATCH recusa alto (404 fora do corpus, 409 na
  // linha de base / já extra por vínculo) — a view mostra o detail cru da recusa.
  // PONTE (ticket 17): classifica só o tipo_vinculo da troca. O funil próprio da aba
  // aposentada não aceita mais etapa/status/responsável — o backend recusa com 400.
  // Apagar quando egp_vinculo_tipo tiver os 3 registros em prod.
  egpAtualizadoPipeline: (body: { egp_key: string; tipo_vinculo: string }) =>
    fetch("api/egp-atualizado-pipeline", {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }).then(json<{ ok: boolean; egp_key: string; tipo_vinculo: string | null }>),

  egpsNovos: () => fetch("api/egps-novos").then(json<EgpsNovosPayload>),
  egpNovoPatch: (body: { projeto: string; acao: "declarar" | "remover" }) =>
    fetch("api/egps-novos", {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }).then(json<{ ok: boolean; acao: string; projeto: string; declarados: string[] }>),

  escopoAdd: (body: { egp_dor1: string; area?: string; projeto?: string }) =>
    fetch("api/escopo", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }).then(json<{ ok: boolean; id: string }>),
  // DELETE = desativa (soft) por padrão; hard=true remove de vez.
  escopoDel: (id: string, hard = false) =>
    fetch(`api/escopo/${encodeURIComponent(id)}${hard ? "?hard=true" : ""}`, { method: "DELETE" }).then(json<{ ok: boolean }>),
  escopoReactivate: (id: string) =>
    fetch(`api/escopo/${encodeURIComponent(id)}/ativar`, { method: "POST" }).then(json<{ ok: boolean }>),

  patch: (body: Partial<InputRow> & { chave_canonica: string }) =>
    fetch("api/inputs", {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }).then(json<InputRow>),

  lineageAreas: () =>
    fetch("api/lineage/areas").then(json<{ rows: { area: string; n: number; n_indi: number }[] }>),

  lineageSearch: (q: string, scope: string, area = "", limit = 100) =>
    fetch(`api/lineage/search?q=${encodeURIComponent(q)}&scope=${scope}`
      + `&area=${encodeURIComponent(area)}&limit=${limit}`)
      .then(json<{ rows: LineageNode[] }>),

  lineageNeighbors: (node: string, dir: string) =>
    fetch(`api/lineage/neighbors?node=${encodeURIComponent(node)}&dir=${dir}`)
      .then(json<LineagePayload>),

  // Bloqueio por dependência (_blocking): tabelas SAS/Local sem produtor e não modernizadas.
  blocking: () => fetch("api/lineage/graph").then(json<BlockingPayload>),

  lineageGraph: (p: { area?: string; scope?: string; mode?: string; deps?: boolean }) => {
    const qs = new URLSearchParams({
      area: p.area ?? "", scope: p.scope ?? "", mode: p.mode ?? "",
      deps: String(p.deps ?? true),
    });
    return fetch(`api/lineage/graph?${qs}`).then(json<LineagePayload>);
  },

  egp: (projeto: string) =>
    fetch(`api/egp?projeto=${encodeURIComponent(projeto)}`).then(json<EgpDetail>),

  waves: (scope: string) =>
    fetch(`api/waves?scope=${scope}`).then(json<{ rows: WaveRow[] }>),

  // Recorte FIXO da aba Priorização: Indicium + dependências, todas as áreas. A capacidade
  // vem da config persistida no servidor (default 400); gestão edita via setCapacidade.
  priorizacao: () =>
    fetch("api/priorizacao?scope=indi&deps=transitive").then(json<PriorizacaoPayload>),
  // Recalcular ao vivo (não salva) com edições locais (pins/capacidade); e salvar (admin).
  priorizacaoPreview: (edits: { pins: Record<string, number | null>; capacidade: number | null }) =>
    fetch("api/priorizacao/preview", {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(edits),
    }).then(json<PriorizacaoPayload>),
  priorizacaoSaveSnapshot: (edits: { pins: Record<string, number | null>; capacidade: number | null }) =>
    fetch("api/priorizacao/snapshot", {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(edits),
    }).then(json<PriorizacaoPayload>),
  priorizacaoSetCapacidade: (capacidade: number) =>
    fetch("api/priorizacao/capacidade", {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ capacidade }),
    }).then(json<{ ok: boolean; capacidade: number }>),
  priorizacaoSetMes: (body: { projeto: string; mes: number | null }) =>
    fetch("api/priorizacao/mes", {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }).then(json<{ ok: boolean; projeto: string; mes: number | null }>),

  // Quebra (broken=true) ou restaura (false) o vínculo per-(EGP, Input). Gestão-only
  // no backend (403 fora de bv_users); UI decide se mostra clicável ou só ícone.
  setEgpInputLink: (projeto: string, chave: string, broken: boolean) =>
    fetch("api/egp-input-link", {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ projeto, chave_canonica: chave, link_broken: broken }),
    }).then(json<{ ok: boolean; projeto: string; chave_canonica: string; link_broken: boolean }>),

  // "Ainda é dependência": reabre a aresta de um PRODUTOR cuja via foi dada como
  // resolvida. Age no produtor, grava por par (consumidor, input) — o fan-out vem na
  // resposta. Gestão-only no backend. NÃO mexe no status do input: a tabela segue
  // Modernizada; o que se declara aqui é que aquela ingestão não cobre este consumidor.
  setDepMantida: (produtor: string, mantida: boolean, motivo?: string | null) =>
    fetch("api/egp-dep-mantida", {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ produtor, mantida, motivo: motivo ?? null }),
    }).then(json<{ ok: boolean; produtor: string; mantida: boolean;
      fan_out: { pares: number; alteracoes: number; consumidores: string[] } }>),

  egpReadiness: (scope: string) =>
    fetch(`api/egp-readiness?scope=${scope}`).then(json<ReadinessPayload>),

  egpInputUnits: (scope: string) =>
    fetch(`api/egp-input-units?scope=${scope}`).then(json<EgpInputUnits>),

  audit: (chave = "", limit = 200) =>
    fetch(`api/audit?chave=${encodeURIComponent(chave)}&limit=${limit}`)
      .then(json<{ rows: AuditRow[] }>),

  resumo: () => fetch("api/resumo").then(json<ResumoPayload>),

  outputs: (scope: string, onlyMulti = false) =>
    fetch(`api/outputs?scope=${scope}${onlyMulti ? "&only_multi=true" : ""}`).then(json<OutputsResponse>),
  setOutputProducer: (chave_canonica: string, projeto_escolhido: string) =>
    fetch("api/output-producer", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ chave_canonica, projeto_escolhido }),
    }).then(json<{ ok: boolean; projeto_escolhido: string }>),
  clearOutputProducer: (chave_canonica: string) =>
    fetch(`api/output-producer?chave=${encodeURIComponent(chave_canonica)}`, { method: "DELETE" }).then(json<{ ok: boolean }>),
  outputDetail: (chave: string) =>
    fetch(`api/output?chave=${encodeURIComponent(chave)}`).then(json<OutputDetail>),
  outputsEgps: (scope: string) =>
    fetch(`api/outputs-egps?scope=${scope}`).then(json<{ rows: { chave_canonica: string; projeto: string }[] }>),

  // Versões recebidas (read-only; a mais recente por egp_key) — catálogo da busca do
  // AtualizadoLinkButton, no detalhe do EGP. A aba própria foi aposentada (spec §5).
  egpsAtualizados: () => fetch("api/egps-atualizados").then(json<EgpsAtualizadosResponse>),
  // Guarda da aba EGPs: versões recebidas que ainda não viraram projeto do corpus.
  egpsAtualizadosAguardandoCorpus: () =>
    fetch("api/egps-atualizados/aguardando-corpus").then(json<AguardandoCorpusPayload>),
  // Sentido inverso do anterior: entrou no corpus e não tem porta em tela nenhuma.
  egpsSemVinculo: () => fetch("api/egps-sem-vinculo").then(json<EgpsSemVinculoPayload>),
  egpAtualizadoDetalhe: (versaoId: string) =>
    fetch(`api/egp-atualizado?versao_id=${encodeURIComponent(versaoId)}`).then(json<EgpAtualizadoDetail>),

  // Recebimento manual por output (sas_outputs_pipeline): tabela pequena, carregada inteira
  // 1x (mesmo padrão de preworkingRows/-Patch) — hidrata o Map usado no GestaoStatusPanel.
  outputsPipeline: () => fetch("api/outputs-pipeline").then(json<{ rows: OutputPipelineRow[] }>),
  outputPipelinePatch: (body: { chave_canonica: string; recebido?: boolean; recebido_data?: string | null; carga_fria?: boolean;
    cf_etapa?: string; cf_status?: string; cf_responsavel?: string;
    cf_inicio?: string; cf_fim?: string; cf_caminho?: string; cf_tabela?: string }) =>
    fetch("api/output-pipeline", {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }).then(json<{ ok: boolean; chave_canonica: string; recebido: boolean; recebido_data: string | null; carga_fria: boolean }>),
};
