import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useQuery, useMutation, useQueryClient, keepPreviousData } from "@tanstack/react-query";
import { api } from "../api";
import type { AppConfig, Filters, InputRow, InputsResponse, Metrics, SanFragilidade } from "../types";
import { MetricsBar } from "./MetricsBar";
import { useHeaderCollapse } from "../useHeaderCollapse";
import { useTabState } from "../tabState";
import { FilterBar } from "./FilterBar";
import { InputsTable, isDivergent, type InputSortKey } from "./InputsTable";
import { gestaoApi, type GestaoRow } from "../gestaoApi";
import { useTableSort } from "../useTableSort";
import { chavesDoInput, effEtapa, effStatusInput, fmtAreas } from "../inputs";
import { avisoFragilidade } from "../fragilidade";
import { csvEscape, csvDownload, csvDate, egpShort } from "../csv";
import { pathFor, spaLinkClick } from "../routes";
import { useMesPlan, mesTag } from "../mesPlan";
import { mesesPorChave, mesesDoInput } from "../mesInput";

const DEFAULT_FILTERS: Filters = {
  scope: "indi_deps",
  categoria: [],
  origem: [],
  etapa: [],
  status: [],
  area: [],
  responsavel: [],
  mes: [],
  q: "",
  divergence: false,
  bloqueador: false,
  exDeps: false,
  semExtras: false,
  extra: false,
  pendentes: false,
  safra: false,
};

const EMPTY: InputRow[] = [];
const SEM_RESPONSAVEL = "__sem_responsavel__";

const inputAccessor = (r: InputRow, k: InputSortKey): string | number | null | undefined => {
  switch (k) {
    case "qtd_projetos": return r.qtd_projetos;
    case "n_proj_ativos": return r.n_proj_ativos ?? -1;   // null vira -1 pra ficar no fim asc
    case "artifact": return r.artifact;
    case "categoria": return r.categoria;
    case "origem": return r.origem;
    case "areas": return fmtAreas(r.areas, r.area_principal);
    case "source_types": return r.source_types;
    case "modernizada_auto": return r.modernizada_auto;
    case "responsavel": return r.responsavel;
    case "observacao": return r.observacao;
    default: return undefined;
  }
};

// etapa/status EFETIVOS: helpers compartilhados em ../inputs (effEtapa/effStatusInput),
// espelho de _eff_etapa()/_eff_status_input() do backend.

// haystack da busca: mesmas colunas que o backend cobre (exclui responsável/observação).
function haystack(r: InputRow): string {
  return [r.artifact, r.categoria, r.origem, r.areas, r.source_types, r.paths_fisicos, r.etapa, r.status,
    // Linha de FAMÍLIA: as chaves das safras entram no haystack para que buscar por
    // "CARGA_MASSIFICADOS_202506" (ou só "202506") continue achando a família que a
    // contém — senão a unificação tornaria invisível justamente o nome que o analista
    // tem anotado na planilha.
    r.membros?.join(" "),
    // e o nome exibido (`..._{SAFRA}`), para quem digita o marcador achar as famílias
    r.nome_exibicao]
    .filter(Boolean).join(" ").toLowerCase();
}

// `areas` do input é multivalorado ("Cobrança|Crédito"): pertinência = bate QUALQUER uma.
const areasDo = (r: InputRow) => (r.areas || "").split(/\s*[|,]\s*/).map((a) => a.trim()).filter(Boolean);

/** Aviso PERMANENTE da fragilidade (spec §3.4.16/17): a sanitização derivada mede
 * exclusividade contra o ESCOPO ATIVO, não contra o corpus — então uma chave pode estar
 * fora da fila só porque os outros consumidores dela estão fora do escopo, e volta
 * sozinha se qualquer um deles entrar. A decisão da gestão foi consciente; o aviso
 * existe para o preço dela não ficar implícito.
 *
 * O rollup é INVERSO (EGP fora -> chaves que voltariam) porque é essa a pergunta
 * acionável: quem é o EGP que, se entrar, me devolve 40 chaves. Dá para ver QUAIS, não
 * só o número — por isso o `details` com a lista, e as chaves no title de cada linha. */
function FragilidadeAviso({ frag, onOpenEgp }: { frag?: SanFragilidade; onOpenEgp: (p: string) => void }) {
  const texto = avisoFragilidade(frag);
  if (!texto || !frag) return null;
  return (
    <details className="san-fragil">
      <summary>⚠ {texto}</summary>
      <div className="san-fragil-lista">
        {frag.por_egp.map((e) => (
          <a key={e.projeto} className="san-fragil-linha" href={pathFor("readiness", e.projeto)}
            title={`${e.projeto}\n\nchaves que voltariam:\n${e.chaves.join("\n")}`}
            onClick={(ev) => spaLinkClick(ev, () => onOpenEgp(e.projeto))}>
            <span className="de-name">{egpShort(e.projeto)}</span>
            <span className="muted">devolveria {e.n_chaves} {e.n_chaves === 1 ? "chave" : "chaves"}</span>
          </a>
        ))}
      </div>
    </details>
  );
}

interface MonitorProps {
  cfg: AppConfig | null;
  onOpenEgp: (projeto: string) => void;
  // deep-link "/monitoramento/<chave_canonica>" — mesmo contrato do egpToOpen da aba EGPs:
  // o App manda a chave, a view abre o drawer e devolve onInputOpened p/ limpar o estado.
  inputToOpen?: string | null;
  onInputOpened?: () => void;
  onInputRoute?: (chave: string | null) => void;   // espelha o drawer aberto na URL
}

export function MonitorView({ cfg, onOpenEgp, inputToOpen, onInputOpened, onInputRoute }: MonitorProps) {
  const qc = useQueryClient();
  const [filters, setFilters] = useTabState<Filters>("inputs.filters", DEFAULT_FILTERS);
  // "Último status" (aba Gestão, entity=input) — mesma query key da aba Gestão, cache compartilhado.
  const hdr = useHeaderCollapse("hdr-inputs", { auto: false });
  const gestaoRowsQ = useQuery({ queryKey: ["gestao", "input"], queryFn: () => gestaoApi.listRows("input") });
  const gestaoRows: GestaoRow[] = gestaoRowsQ.data ?? [];
  const gestaoById = useMemo(() => new Map(gestaoRows.map((r) => [r.id, r])), [gestaoRows]);

  // Checklist de pré-working (badge de completude na tabela) — mesma queryKey ["preworking"]
  // usada pelo InputDetailPanel, aberto em modal pela tabela (cache compartilhado, react-query dedupa).
  const preworkingQ = useQuery({ queryKey: ["preworking"], queryFn: () => api.preworkingRows() });
  const preworkingById = useMemo(
    () => new Map((preworkingQ.data?.rows ?? []).map((r) => [r.chave_canonica, r])),
    [preworkingQ.data],
  );

  // Carrega o dataset do escopo UMA vez (cacheado no backend + react-query). Busca, filtros
  // e ordenação rodam todos no cliente — instantâneos, sem ida ao warehouse por tecla.
  // A ÁREA é sempre filtro client-side de PERTINÊNCIA (input.areas): lista os inputs do escopo
  // relacionados à área — inclusive em "Indicium + Dependências", onde a área NÃO recorta a base
  // do fecho (senão áreas sem EGP no escopo, ex. Jurídico, zerariam a lista em vez de listar seus
  // 18 inputs). O backend serve o frontier COMPLETO com area=[]; o recorte por área é aqui.
  const inputsKey = ["inputs", filters.scope] as const;
  const inputsQ = useQuery({
    queryKey: inputsKey,
    queryFn: () => api.inputs({
      scope: filters.scope, categoria: [], origem: [], etapa: [], status: [], area: [], responsavel: [], mes: [], q: "", divergence: false, bloqueador: false, exDeps: false, semExtras: false, extra: false, pendentes: false, safra: false,
    }),
    placeholderData: keepPreviousData,
    staleTime: 5 * 60 * 1000,
  });

  // Indicador de EGPs do recorte (scope + área) — correlaciona inputs × EGPs. Área-aware nos 3 escopos.
  const egpsQ = useQuery({
    queryKey: ["scope-egps", filters.scope, filters.area],
    queryFn: () => api.scopeEgps(filters.scope, filters.area),
  });

  // Fragilidade da sanitização derivada (§3.4.16): quantas chaves estão fora da fila só
  // porque parte dos consumidores está FORA do escopo. Aviso permanente — a régua mede
  // exclusividade contra o escopo ativo, então a fila cresce sozinha quando um EGP entra.
  const fragilQ = useQuery({ queryKey: ["san-fragilidade"], queryFn: () => api.fragilidade() });

  // Analistas ativos p/ o dropdown de responsável (ingestão) na tabela de inputs.
  const analistasQ = useQuery({ queryKey: ["analistas"], queryFn: () => api.analistas() });

  // Bloqueio por dependência (inverso do contador "🔒 Bloqueio dependência" da aba Prontidão).
  // O contador é TRANSITIVO: EGPs do escopo Indicium (egp-readiness scope=indi) em estado
  // bloqueado_dep — os "133". Aqui viramos a chave: por tabela leaf-blocker, quantos DAQUELES
  // EGPs ela bloqueia, direta ou transitivamente.
  //   _blocking(): leaf_tables {projeto -> [tabelas leaf]} e dep_of {consumidor -> [produtores]}.
  //   universo: MESMO do contador (readiness/indi + bloqueado_dep); NÃO o plano de priorização,
  //   que inclui deps transitivas fora do escopo Indicium (contador maior).
  // Para cada EGP bloqueado, subimos suas dependências (fecho upstream via dep_of) e coletamos as
  // tabelas leaf que ele/seus ancestrais leem = suas causas-raiz; +1 em `n` de cada tabela.
  // Sobreposição é esperada (um EGP com 2 causas conta nas 2 pílulas), igual ao contador
  // transitivo — mas a UNIÃO distinta dos EGPs das pílulas == o contador (validado offline).
  // `sole` = EGPs cuja ÚNICA causa-raiz é esta tabela (roots == {T}): resolvê-la os destrava de
  // fato. Também é transitivo — uma cadeia que só depende de T tem roots={T} em cada elo.
  const blockingQ = useQuery({
    queryKey: ["blocking"], queryFn: () => api.blocking(), staleTime: 5 * 60 * 1000,
  });
  const readyQ = useQuery({
    queryKey: ["egp-readiness", "indi"], queryFn: () => api.egpReadiness("indi"), staleTime: 5 * 60 * 1000,
  });
  const blockStats = useMemo(() => {
    const leafTables = blockingQ.data?.leaf_tables ?? {};
    // tabela -> família (vem do backend; identidade quando a tabela não tem família). As
    // causas-raiz são agrupadas por FAMÍLIA antes de contar, senão 47 safras da mesma
    // tabela virariam 47 causas distintas do mesmo EGP — e a linha de família (chaveada
    // pelo nome da família) não acharia sua própria pílula de bloqueio.
    const famDe = blockingQ.data?.familia_de ?? {};
    const depOf = blockingQ.data?.dep_of ?? {};   // consumidor -> [produtores]
    const blockedSet = new Set<string>();
    for (const r of readyQ.data?.rows ?? []) if (r.bloqueado_dep) blockedSet.add(r.projeto);
    const m = new Map<string, { n: number; sole: number }>();
    for (const egp of blockedSet) {
      const seen = new Set<string>([egp]);
      const stack = [egp];
      const roots = new Set<string>();
      while (stack.length) {
        const p = stack.pop()!;
        for (const t of leafTables[p] ?? []) roots.add((famDe[t.toUpperCase()] ?? t).toUpperCase());
        for (const prod of depOf[p] ?? []) if (!seen.has(prod)) { seen.add(prod); stack.push(prod); }
      }
      const sole = roots.size === 1;
      for (const t of roots) {
        const e = m.get(t) ?? { n: 0, sole: 0 };
        e.n++; if (sole) e.sole++;
        m.set(t, e);
      }
    }
    return m;
  }, [blockingQ.data, readyQ.data]);

  // Filtro de mês: um input herda os meses dos EGPs a que se relaciona (n:n). Carregamos o
  // par input×EGP UMA vez por escopo (mesma query do export) e cruzamos com o plano (mesOf).
  // Join client-side barato — sem ida ao warehouse por tecla.
  const inputsEgpsQ = useQuery({
    queryKey: ["inputs-egps", filters.scope],
    queryFn: () => api.inputsEgps(filters.scope, []),
    staleTime: 5 * 60 * 1000,
  });
  const { mesOf, mesOfPlano, meses } = useMesPlan();
  // Mês do input = régua do funil de ingestão por mês do Resumo, em TODO recorte (ver
  // src/mesInput.ts): o compartilhado com a linha de base tem só o mês do plano; o mês do
  // extra vale só para o que SÓ extra lê. Antes "Indicium + dependências" já seguia o plano
  // (M1/Modernizado 155 x 150, 09/10/2026), mas "+ extras" dava ao compartilhado também o
  // mês do extra (M1+M2/A Receber 93 x 85, 13/10/2026).
  const mesByInputPlano = useMemo(
    () => mesesPorChave(inputsEgpsQ.data?.rows ?? [], mesOfPlano), [inputsEgpsQ.data, mesOfPlano]);
  const mesByInputExtras = useMemo(
    () => mesesPorChave(inputsEgpsQ.data?.rows ?? [], mesOf), [inputsEgpsQ.data, mesOf]);

  const all = inputsQ.data?.rows ?? EMPTY;
  // Único recorte: filtros do usuário (categoria/origem/status/área/mês/divergência/
  // bloqueador/q). Sanitizado é status TERMINAL mas continua no universo — sem filtro
  // de status, aparece na tabela e nos cards (contagem de escopo).
  // Em DUAS etapas de propósito: `semArea` (tudo menos o filtro de Área) alimenta as OPÇÕES
  // do filtro de Área — se derivássemos as opções do recorte já filtrado por área, escolher
  // uma área apagaria todas as outras da lista.
  const semArea = useMemo(() => {
    const cat = new Set(filters.categoria);
    const ori = new Set(filters.origem);
    const ets = new Set(filters.etapa);
    const sts = new Set(filters.status);
    const mes = new Set(filters.mes.map(Number));
    const resp = new Set(filters.responsavel ?? []);   // estado persistido antigo não tem o campo
    const terms = filters.q.toLowerCase().split(/\s+/).filter(Boolean);
    return all.filter((r) => {
      // Input de ex-dependência (consumido SÓ por EGPs que saíram do frontier): atrás
      // do chip "mostrar ex-dependências" (off por padrão) — tabela/export intactos p/
      // o fluxo de entrega; ligado, entra em cinza. NUNCA conta nos cards (abaixo).
      if (r.ex_dependencia && !filters.exDeps) return false;
      // Sem vínculo ativo no recorte (todos os pares quebrados) => o input não pertence
      // mais a nenhum EGP do escopo/deps: some da TABELA e do EXPORT nesses escopos
      // (o CSV explodia linha com EGP vazio). Continua visível na base completa (tag
      // "sem vínculo ativo") p/ gerir/reverter o vínculo.
      if (filters.scope !== "base" && r.vinculo_ativo === false) return false;
      const effEt = effEtapa(r.etapa, r.modernizada_auto);
      const effSt = effStatusInput(r.status, r.etapa, r.modernizada_auto);
      if (cat.size && !cat.has(r.categoria)) return false;
      if (ori.size && !ori.has(r.origem)) return false;
      if (ets.size && !ets.has(effEt)) return false;
      if (sts.size && !sts.has(effSt)) return false;
      if (resp.size && !resp.has(r.responsavel || SEM_RESPONSAVEL)) return false;
      if (mes.size) {
        // Os mapas são indexados pelas chaves de SAFRA (/api/inputs-egps vem de
        // sas_egp_inputs, grão de safra), mas a linha pode ser uma FAMÍLIA — cuja
        // chave `familia::…` não existe neles. Sem `chavesDoInput` o lookup errava
        // sempre e escolher qualquer mês esvaziava a tabela de toda família.
        const ms = mesesDoInput(chavesDoInput(r), r.so_de_extra, mesByInputPlano, mesByInputExtras);
        if (![...mes].some((x) => ms.has(x))) return false;
      }
      // "só pendentes": mesmo predicado isModern dos cards (modernizado OU sanitizado);
      // ex-dependência também sai (mesmo com o chip "mostrar ex-dependências" ligado)
      if (filters.pendentes && (effEt === "Modernizado" || effSt === "Sanitizado" || r.ex_dependencia)) return false;
      if (filters.divergence && !isDivergent(r)) return false;
      // "só safras": `de_safra` vem decidido pelo backend (corpus), nos dois estados da
      // flag — com família ligada a linha é a própria família; desligada, cada safra datada.
      if (filters.safra && !r.de_safra) return false;
      // "só inputs de extras": QUALQUER input lido por um EGP extra, inclusive os que a
      // linha de base também lê (162 das 190 medidas em 29/09) — a pergunta aqui é "o que
      // a versão nova consome". O card "Inputs dos extras" do Resumo conta outro conjunto,
      // o exclusivo (`so_de_extra`), porque lá as três parcelas têm de somar o total.
      // degrau "Indicium + Dependências": sai o que SÓ os extras leem. O compartilhado
      // fica, porque a linha de base também o lê — tirá-lo seria remover trabalho que
      // existe independentemente da versão nova.
      if (filters.semExtras && r.so_de_extra) return false;
      if (filters.extra && !r.de_extra) return false;
      if (filters.bloqueador && !blockStats.has(r.artifact.toUpperCase())) return false;
      if (terms.length) {
        const h = haystack(r);
        if (!terms.every((t) => h.includes(t))) return false;
      }
      return true;
    });
  }, [all, filters, mesByInputPlano, mesByInputExtras, blockStats]);

  // Opções do filtro de Área: só as áreas presentes no recorte atual (escopo + demais
  // filtros) — pedido 2026-09: dava pra marcar "Atacado" em Indicium + Dependências e não
  // havia um único input dessa área, virava um filtro que só zera a tela. Mantém a ordem
  // canônica de cfg.areas e NUNCA esconde uma área já selecionada (senão não dá pra
  // desmarcar quando outro filtro zera a contagem dela). Sem dados ainda -> lista cheia.
  const areaOptions = useMemo(() => {
    const presentes = new Set<string>();
    for (const r of semArea) for (const a of areasDo(r)) presentes.add(a);
    const sel = new Set(filters.area);
    const opts = (cfg?.areas ?? []).filter((a) => presentes.has(a) || sel.has(a));
    return opts.length ? opts : (cfg?.areas ?? []);
  }, [semArea, cfg, filters.area]);

  // Opções do filtro de Responsável: analistas ativos + quem já consta em alguma linha (um
  // responsável inativo continua filtrável) + "sem responsável". Sempre inclui o já selecionado.
  const { responsavelOptions, responsavelLabels } = useMemo(() => {
    const nomes: Record<string, string> = {};
    for (const a of analistasQ.data?.rows ?? []) nomes[a.email] = a.nome || a.email;
    const emails = new Set(Object.keys(nomes));
    for (const r of all) if (r.responsavel) emails.add(r.responsavel);
    for (const e of filters.responsavel ?? []) if (e !== SEM_RESPONSAVEL) emails.add(e);
    const ord = [...emails].sort((a, b) => (nomes[a] ?? a).localeCompare(nomes[b] ?? b, "pt-BR"));
    return {
      responsavelOptions: [SEM_RESPONSAVEL, ...ord],
      responsavelLabels: { [SEM_RESPONSAVEL]: "(sem responsável)", ...nomes },
    };
  }, [analistasQ.data, all, filters.responsavel]);

  const filtered = useMemo(() => {
    const ar = new Set(filters.area);
    if (!ar.size) return semArea;
    return semArea.filter((r) => areasDo(r).some((a) => ar.has(a)));
  }, [semArea, filters.area]);

  // Cards = métricas do universo filtrado (sem ir ao warehouse por tecla).
  const cardMetrics: Metrics = useMemo(() => {
    const m: Record<string, number> = {
      inputs_distintos: 0, inputs_a_ingerir: 0, total_saslocal: 0, total_transacional: 0,
      total_arquivos_scripts: 0, total_bigquery: 0, total_modernizadas: 0,
      total_saslocal_falta: 0, total_transacional_falta: 0, total_arquivos_scripts_falta: 0, total_bigquery_falta: 0,
    };
    for (const r of filtered) {
      // universo por vínculo (igual Resumo): todos os vínculos quebrados → fora dos
      // cards; inputs de ex-dependência NUNCA contam (mesmo com o chip ligado).
      if (r.vinculo_ativo === false || r.ex_dependencia) continue;
      const effEt = effEtapa(r.etapa, r.modernizada_auto);
      const effSt = effStatusInput(r.status, r.etapa, r.modernizada_auto);
      const isModern = effEt === "Modernizado" || effSt === "Sanitizado" || effSt === "Autoprodutor";
      m.inputs_distintos++;
      if (isModern) m.total_modernizadas++;
      else m.inputs_a_ingerir++;
      const o = r.origem;
      const falta = !isModern;  // ainda não modernizada
      if (o === "SAS/Local (externo)" || o === "SAS/Local (dependência)") {
        m.total_saslocal++; if (falta) m.total_saslocal_falta++;
      }
      else if (o === "Transacional") { m.total_transacional++; if (falta) m.total_transacional_falta++; }
      else if (o === "Arquivo" || o === "Script") { m.total_arquivos_scripts++; if (falta) m.total_arquivos_scripts_falta++; }
      else if (o === "BigQuery") { m.total_bigquery++; if (falta) m.total_bigquery_falta++; }
    }
    m.pct_modernizado = m.inputs_distintos ? Math.round((1000 * m.total_modernizadas) / m.inputs_distintos) / 10 : 0;
    return m;
  }, [filtered]);

  // Ordem inicial por #ativos, não por #proj (2026-09): #proj conta TODO consumidor do corpus,
  // inclusive despriorizado, fora do recorte ou com vínculo quebrado — inflava o topo da lista
  // com inputs que já não travam ninguém. #ativos é o que ainda pesa. Continua clicável para
  // reordenar por qualquer coluna; null (fora do recorte) vira -1 no accessor e fica no fim.
  const { sorted, onSort, indicator } = useTableSort<InputRow, InputSortKey>(
    filtered,
    inputAccessor,
    { key: "n_proj_ativos", dir: "desc" },
  );

  // ---- deep-link de input ---------------------------------------------------------
  // O drawer só abre se a linha estiver na lista EXIBIDA, então um link pode chegar em um
  // recorte/filtro que a esconde. Uma tentativa por chave (ref): limpa os filtros e, se o
  // input nem estiver no recorte carregado, alarga p/ a base completa. Se depois disso ele
  // não existir, avisa — link velho não pode virar "cliquei e nada aconteceu".
  const [notFound, setNotFound] = useState<string | null>(null);
  const alargou = useRef<string | null>(null);
  useEffect(() => {
    if (!inputToOpen) { alargou.current = null; return; }
    if (!inputsQ.isSuccess || inputsQ.isFetching) return;   // espera o recorte assentar
    if (sorted.some((r) => r.chave_canonica === inputToOpen)) return;   // já visível
    const noRecorte = all.some((r) => r.chave_canonica === inputToOpen);
    if (alargou.current === inputToOpen) {
      if (!noRecorte) { setNotFound(inputToOpen); onInputOpened?.(); }
      return;
    }
    alargou.current = inputToOpen;
    setFilters((f) => ({ ...DEFAULT_FILTERS, scope: noRecorte ? f.scope : "base" }));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [inputToOpen, sorted, all, inputsQ.isSuccess, inputsQ.isFetching]);

  const patchMut = useMutation({
    mutationFn: (v: { chave: string; patch: Partial<InputRow> }) =>
      api.patch({ chave_canonica: v.chave, ...v.patch }),
    onMutate: async ({ chave, patch }) => {
      await qc.cancelQueries({ queryKey: inputsKey });
      const prev = qc.getQueryData<InputsResponse>(inputsKey);
      qc.setQueryData<InputsResponse>(inputsKey, (old) =>
        old ? { ...old, rows: old.rows.map((r) => (r.chave_canonica === chave ? { ...r, ...patch } : r)) } : old,
      );
      return { prev };
    },
    onError: (_e, _v, ctx) => {
      if (ctx?.prev) qc.setQueryData(inputsKey, ctx.prev);
    },
    onSuccess: (updated, { chave }) => {
      // MERGE (não substitui): o PATCH pode não devolver TODAS as colunas derivadas
      // (ex.: paths_fisicos) — preservamos as existentes p/ o path não sumir da linha.
      qc.setQueryData<InputsResponse>(inputsKey, (old) =>
        old ? { ...old, rows: old.rows.map((r) => (r.chave_canonica === chave ? { ...r, ...updated } : r)) } : old,
      );
      qc.invalidateQueries({ queryKey: ["metrics"] });
      qc.invalidateQueries({ queryKey: ["resumo"] });
      qc.invalidateQueries({ queryKey: ["landing"] });
      qc.invalidateQueries({ queryKey: ["egp"] });
      qc.invalidateQueries({ queryKey: ["egp-readiness"] });
      qc.invalidateQueries({ queryKey: ["funis"] }); // status de input → funil de ingestão
    },
  });

  const onPatch = useCallback(
    (chave: string, patch: Partial<InputRow>) => patchMut.mutate({ chave, patch }),
    [patchMut],
  );

  const loading = inputsQ.isFetching;
  // FilterBar mostra a contagem das linhas exibidas (já filtradas no cliente).
  const result: InputsResponse = {
    total: filtered.length, returned: filtered.length,
    capped: inputsQ.data?.capped ?? false, rows: EMPTY,
  };
  const error = inputsQ.error
    ? String(inputsQ.error)
    : patchMut.error
      ? `Falha ao salvar: ${patchMut.error}`
      : null;

  // Exporta as linhas EXIBIDAS (filtros + busca + ordenação aplicados) como CSV — tudo no
  // cliente, sem ida ao warehouse. ';' + BOM UTF-8 p/ abrir com acento certo no Excel pt-BR.
  const exportCsv = useCallback(() => {
    const cols: { header: string; get: (r: InputRow) => string | number }[] = [
      { header: "Artefato", get: (r) => r.artifact },
      { header: "Categoria", get: (r) => r.categoria },
      { header: "Origem", get: (r) => r.origem },
      { header: "Áreas", get: (r) => r.areas },
      { header: "Tipos de fonte", get: (r) => r.source_types },
      { header: "Qtd projetos", get: (r) => r.qtd_projetos },
      { header: "Etapa efetiva", get: (r) => effEtapa(r.etapa, r.modernizada_auto) },
      { header: "Etapa (humana)", get: (r) => r.etapa ?? "" },
      { header: "Status efetivo", get: (r) => effStatusInput(r.status, r.etapa, r.modernizada_auto) },
      { header: "Status (humano)", get: (r) => r.status ?? "" },
      { header: "Modernizada (auto)", get: (r) => r.modernizada_auto },
      { header: "Responsável", get: (r) => r.responsavel ?? "" },
      { header: "Tbl. Corresp.", get: (r) => r.observacao ?? "" },
      { header: "Nº paths físicos", get: (r) => r.n_paths_fisicos },
      { header: "Paths físicos", get: (r) => r.paths_fisicos },
      { header: "Chave canônica", get: (r) => r.chave_canonica },
      { header: "Input de ex-dependência", get: (r) => (r.ex_dependencia ? "sim" : "") },
      { header: "Lido por EGP extra", get: (r) => (r.de_extra ? "sim" : "") },
      { header: "Só de EGP extra", get: (r) => (r.so_de_extra ? "sim" : "") },
    ];
    const esc = csvEscape;
    // mapeamento input -> EGP(s) do recorte, p/ explodir "uma linha por (input x EGP)".
    // Reusa a query já carregada (inputsEgpsQ); sem mapa => exporta com EGP vazio.
    const egpMap = new Map<string, string[]>();
    for (const p of inputsEgpsQ.data?.rows ?? []) {
      const arr = egpMap.get(p.chave_canonica);
      if (arr) arr.push(p.projeto); else egpMap.set(p.chave_canonica, [p.projeto]);
    }
    const header = ["EGP", ...cols.map((c) => c.header)];
    const lines = [header.join(";")];
    for (const r of sorted) {
      const base = cols.map((c) => esc(c.get(r)));
      // Mesma razão do filtro de mês: `egpMap` é por chave de SAFRA. Uma FAMÍLIA
      // consome os EGPs de todas as suas safras — dedup porque 47 safras lidas pelo
      // mesmo EGP são UMA linha, não 47. Sem isto o CSV saía com a coluna EGP vazia
      // para toda família (é o CSV levado às reuniões de ingestão do BV).
      const egps = [...new Set(chavesDoInput(r).flatMap((k) => egpMap.get(k) ?? []))];
      if (egps.length === 0) lines.push([esc(""), ...base].join(";"));
      else for (const eg of egps) lines.push([esc(egpShort(eg)), ...base].join(";"));
    }
    csvDownload(`monitoramento_inputs_${filters.scope}_por_egp_${csvDate()}.csv`, lines);
  }, [sorted, filters.scope, inputsEgpsQ.data]);

  return (
    <>
      {!hdr.collapsed && <MetricsBar metrics={cardMetrics} egps={egpsQ.data ?? null} />}
      {hdr.collapsed && (
        <div className="hdr-slim" role="button" tabIndex={0} onClick={hdr.toggle}
          onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); hdr.toggle(); } }}
          title="Cabeçalho recolhido — clique para expandir">
          <b className="danger">{(cardMetrics.inputs_a_ingerir ?? 0).toLocaleString("pt-BR")}</b> a ingerir
          de <b>{(cardMetrics.inputs_distintos ?? 0).toLocaleString("pt-BR")}</b> inputs
          · <b>{cardMetrics.pct_modernizado ?? 0}%</b> modernizado
        </div>
      )}
      <FilterBar
        cfg={cfg}
        filters={filters}
        onChange={(patch) => setFilters((f) => ({ ...f, ...patch }))}
        result={result}
        loading={loading}
        onExport={exportCsv}
        areaOptions={areaOptions}
        responsavelOptions={responsavelOptions}
        responsavelLabels={responsavelLabels}
        mesOptions={meses.map(String)}
        mesLabels={Object.fromEntries(meses.map((m) => [String(m), mesTag(m)]))}
        headerCollapsed={hdr.collapsed}
        onToggleHeader={hdr.toggle}
      />
      {error && <div className="error">{error}</div>}
      {notFound && (
        <div className="error rd-notfound">
          <span>Input <b>{notFound}</b> não encontrado — o link pode estar desatualizado.</span>
          <button className="row-x" onClick={() => setNotFound(null)} title="fechar">✕</button>
        </div>
      )}
      <FragilidadeAviso frag={fragilQ.data} onOpenEgp={onOpenEgp} />
      <InputsTable
        rows={sorted}
        abrir={inputToOpen ?? null}
        onAbriu={onInputOpened}
        onOpenChange={onInputRoute}
        loading={loading}
        onPatch={onPatch}
        onSort={onSort}
        indicator={indicator}
        onOpenEgp={onOpenEgp}
        analistas={analistasQ.data?.rows ?? []}
        blockStats={blockStats}
        gestaoById={gestaoById}
        onBodyScroll={hdr.onScroll}
        onClearFilters={() => setFilters((f) => ({ ...DEFAULT_FILTERS, scope: f.scope }))}
        preworkingById={preworkingById}
      />
    </>
  );
}
