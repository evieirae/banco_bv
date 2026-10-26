export interface InputRow {
  chave_canonica: string;
  artifact: string;
  categoria: string;
  source_types: string;
  origem: string;
  qtd_projetos: number;
  areas: string;
  area_principal: string | null;
  escopo_indi: boolean;
  modernizada_auto: string;
  etapa: string | null;
  status: string | null;
  responsavel: string | null;
  observacao: string | null;
  orfao: boolean;
  paths_fisicos: string;
  n_paths_fisicos: number | string;
  // EGPs consumidores dentro do escopo Indi ∪ deps, NÃO despriorizados E com vínculo
  // NÃO quebrado (mesma definição da coluna #Proj Ativos no EGP detail). `null` = não
  // pôde ser calculado (fallback silencioso).
  n_proj_ativos?: number | null;
  // false = TODOS os vínculos (EGP, input) do recorte estão quebrados → fora do universo
  // dos contadores (mesmo predicado do Resumo); a linha segue visível na tabela com
  // aviso, mas os cards a excluem. Bool JSON real (anotado em Python, não via SQL).
  vinculo_ativo?: boolean;
  // true = input consumido EXCLUSIVAMENTE por ex-dependências: linha cinza, atrás do
  // chip "mostrar ex-dependências" (off por padrão); NUNCA conta nos cards.
  ex_dependencia?: boolean;
  // Sanitização DERIVADA (§3.4.15 e §3.4.18 da spec da unificação): o backend SOBRESCREVEU
  // `status` por "Sanitizado" sem gravar nada — `sanitizado_derivado` traz o motivo em
  // código ("so_despriorizados" | "so_antecessor", as DUAS origens previstas),
  // `sanitizado_motivo` o rótulo legível e `status_real` o que está no banco. Ausência dos
  // três = regra não se aplica. Some sozinho quando a condição deixa de valer (um consumidor
  // é repriorizado, o vínculo é desfeito), sem ninguém rodar nada.
  // Desde 14/10/2026 a `etapa` também é sobrescrita (por "Modernizado"; a gravada vem em
  // `etapa_real`) e etapa/status ficam TRAVADOS: o backend recusa a edição com 409.
  sanitizado_derivado?: string;
  sanitizado_motivo?: string;
  status_real?: string | null;
  etapa_real?: string | null;
  // true = candidato a "Autoprodutor": algum EGP consumidor desta tabela também a CRIA
  // (criador único ou produtor canônico escolhido) — ver _autoprodutor_candidatos() no
  // backend. `autoprodutor_egp` nomeia esse EGP (null se não é candidato). Só um HINT —
  // a isenção real só vale quando `status === "Autoprodutor"` (confirmação humana via
  // o mesmo dropdown de status).
  autoprodutor_candidato?: boolean;
  autoprodutor_egp?: string | null;
  // Pertence a uma família de safras? Vem nos DOIS estados da flag (com ela desligada
  // marca cada safra datada; ligada, equivale a `is_familia`) — alimenta o filtro "só
  // safras". Decidido pelo corpus no backend (`_marca_safra`), nunca pelo recorte.
  de_safra?: boolean;
  // Vínculo do input com os EGPs `extra` do recorte (versões novas e cascas). DOIS campos
  // porque são duas perguntas: `de_extra` = algum extra lê (alimenta o filtro da aba);
  // `so_de_extra` = TODOS os consumidores no recorte são extras (é o que a Visão geral
  // conta no grupo próprio, sem dupla contagem). Decididos no backend (_marca_extra).
  de_extra?: boolean;
  so_de_extra?: boolean;
  // --- FAMÍLIA DE SAFRAS (docs/adr/0002; só com FAMILIAS_SAFRA ligada no backend) ---
  // A linha representa a FAMÍLIA, não uma safra: `artifact` é o nome da família
  // (`GRIMALDI.CARGA_MASSIFICADOS`) e `chave_canonica` tem o prefixo `familia::`. Ausência
  // de `is_familia` = linha física normal (safra sem irmã ou categoria que não colapsa).
  // A regra de família vive SÓ no backend — o front recebe pronto, nunca recalcula.
  is_familia?: boolean;
  familia?: string;
  // Nome para EXIBIÇÃO com a data marcada na posição original
  // (`GRIMALDI.CARGA_MASSIFICADOS_{SAFRA}`). Vem só na linha de família; `artifact`
  // segue sendo a CHAVE (sem o marcador) e é o que vai para export e ordenação.
  nome_exibicao?: string;
  n_safras?: number;                // tamanho da FAMÍLIA no corpus (o que o badge mostra)
  n_safras_no_recorte?: number;     // quantas dessas safras estão no recorte em tela
  n_safras_pendentes?: number;      // safras do recorte ainda a ingerir (as resolvidas não seguram)
  safra_min?: string | null;        // 'AAAAMM' da safra mais antiga (ano solto não entra)
  safra_max?: string | null;
  safras_sem_mes?: number;          // safras com ano solto no nome (fora do intervalo acima)
  estado_misto?: boolean;           // safras da família com etapa/status diferentes entre si
  membros?: string[];               // chaves canônicas das safras (p/ cruzar gestão/pré-working)
  origens?: string | null;          // preenchido só quando as safras têm origens diferentes
}

export interface InputsResponse {
  total: number;
  returned: number;
  capped: boolean;
  rows: InputRow[];
  // "familia" = linhas colapsadas por família de safras; "safra" = grão físico (flag
  // desligada, ou caminho filtrado do backend, que nunca agrega para não gerar
  // "família parcial"). Declarado pelo backend p/ nenhum consumidor ter que adivinhar.
  grao?: "familia" | "safra";
}

// Checklist de pré-working (sas_inputs_preworking): preenchido manualmente pelas áreas
// de negócio com o operacional necessário p/ configurar a ingestão de cada input.
export interface PreworkingRow {
  chave_canonica: string;
  origem_arquivo: string | null;
  frequencia: string | null;
  horario: string | null;
  tipo_carga: string | null;
  pos_processamento: string | null;
  dados_sensiveis: string | null;
  recebido: string | null;            // "true" | "false" (checkbox "Recebimento do Arquivo")
  data_recebimento: string | null;    // "YYYY-MM-DD"
  modernizado_bv: string | null;      // "true" | "false" (checkbox "Modernizado pelo BV")
  data_modernizado_bv: string | null; // "YYYY-MM-DD" — opcional, fora do % de completude
  updated_by: string | null;
  updated_at: string | null;
  iniciado_em: string | null;    // timestamp do 1º toque no checklist (setado 1x)
  concluido_em: string | null;   // timestamp da 1ª vez que o checklist bateu 100% (setado 1x)
  // Linha de FAMÍLIA que ainda não tem checklist próprio: herda o da safra (só leitura;
  // o 1º save grava na família e a herança para). Vem do backend em _pwk_herdadas.
  herdado_de?: string | null;
  // Presente só na resposta do PATCH: true = checklist bateu 100% e o input foi
  // avançado automaticamente p/ etapa "Ingestão UAT" / status "A Iniciar".
  auto_avancado?: boolean;
}

export type Metrics = Record<string, number>;

export interface AppConfig {
  status_options: string[];
  etapa_options: string[];
  categorias: string[];
  origens: string[];
  areas: string[];
  scope: string;
  is_gestao?: boolean;   // usuário pertence ao grupo bv_users (vê a aba Gestão)
  is_admin?: boolean;    // usuário pertence a bv_admins (correção retroativa da validação BV)
  // true = contagem de input por FAMÍLIA DE SAFRAS (docs/adr/0002): safras da mesma tabela
  // contam como 1 input em toda superfície. A UI usa isso para EXPLICAR a unidade — a fila
  // cai pela metade, e quem lembra do número antigo precisa saber por quê.
  familias_safra?: boolean;
  // URL de embed do Genie space (env GENIE_EMBED_URL); ausente = aba Perguntas escondida.
  genie_embed_url?: string | null;
  // App na AWS (ADR 0005): true = ninguém escreve (Fase 1); horário da última sincronização
  // boa com o Databricks (null fora da AWS).
  somente_leitura?: boolean;
  sincronizado_em?: string | null;
}

export interface Analista {
  email: string;
  nome: string;
  ativo: boolean | string;
  organograma?: boolean;   // aparece na aba Home (organograma)
  papel?: string | null;   // cargo; o grupo do organograma é derivado dele
}

export interface AnalistasPayload {
  rows: Analista[];
  is_gestao: boolean;
}

// Cadastro Responsável BV -> sub-área interna do cliente (tabela sas_responsaveis_bv,
// editada na aba Gestão). `ativo` vem como string em algumas respostas do SQL, igual Analista.
export interface ResponsavelBv {
  nome_key: string;
  nome: string;
  subarea?: string | null;
  ativo: boolean | string;
}

export interface ResponsaveisBvPayload {
  rows: ResponsavelBv[];
  is_gestao: boolean;
}

/** Um EGP DECLARADO como novo (ticket 24) — a 3ª perna do `extra`.
 *  `motivo_sem_declaracao` é o que sobraria se a declaração fosse removida agora: quando
 *  deixa de ser null, a declaração virou letra morta (o EGP ganhou vínculo). */
export interface EgpNovoRow {
  projeto: string;
  na_linha_base: boolean;
  no_corpus: boolean;
  motivo_sem_declaracao: string | null;
  redundante: boolean;
}

export interface EgpsNovosPayload {
  n: number;
  rows: EgpNovoRow[];
}

export interface Filters {
  scope: "indi" | "base" | "indi_deps";
  categoria: string[];
  origem: string[];
  etapa: string[];
  status: string[];
  area: string[];
  responsavel: string[];   // e-mails; SEM_RESPONSAVEL = linhas sem responsável. Vazio = todos
  mes: string[];   // meses do plano (via EGPs relacionados); vazio = todos
  q: string;
  divergence: boolean;
  bloqueador: boolean;  // só tabelas SAS/Local que bloqueiam dependência (leaf-blockers do _blocking)
  exDeps: boolean;      // chip "mostrar ex-dependências" (off por padrão) — só faz sentido em indi_deps
  // Degrau do meio do escopo: tira os inputs que SÓ os extras leem (`so_de_extra`), de
  // modo que os três botões formem uma escada cumulativa — Indicium ⊂ + dependências ⊂
  // + extras. O recorte servido pelo backend é o mesmo (`indi_deps` sempre trouxe os
  // extras); o que muda é o degrau exibido, então nada aqui mexe em contagem de card.
  // Off por padrão: o degrau mais largo é o que a aba sempre mostrou, e o do meio é que é
  // a novidade — trocar o padrão mudaria os números de quem já usa a tela.
  semExtras: boolean;
  extra: boolean;       // "só inputs de extras": QUALQUER input que um EGP extra leia (r.de_extra),
                        // inclusive os compartilhados com a linha de base — decisão de 29/09/2026.
                        // Não é o mesmo conjunto do card "Inputs dos extras" do Resumo, que conta
                        // só os exclusivos (so_de_extra) p/ não somar a mesma chave em dois grupos.
  pendentes: boolean;   // "só pendentes": oculta modernizados (etapa efetiva) e sanitizados
  safra: boolean;       // "só safras": linhas de família (flag ligada) ou safras datadas (desligada)
}

// /api/lineage/graph = _blocking() do backend: leaf_tables {projeto -> [tabelas bloqueadoras]}.
export interface BlockingPayload {
  leaf_tables: Record<string, string[]>;
  blocked: string[];
  dep_of: Record<string, string[]>;
  // TABELA (upper) -> nome da FAMÍLIA a que ela pertence (identidade quando não tem
  // família). Enviado só com a flag ligada; serve p/ agrupar as causas-raiz de bloqueio
  // por família sem duplicar a regra no cliente.
  familia_de?: Record<string, string>;
}

// GET /api/egps-extras: os EGPs do recorte que estão FORA da linha de base congelada —
// quantos E QUAIS. O contador sozinho diz que chegou trabalho novo mas não diz o quê.
export interface EgpExtra {
  projeto: string;
  area?: string | null;
  motivo?: string | null;   // 'sucessor' | 'casca' | 'novo' | 'dependencia' — só no detalhe
  tipos?: string[];         // idem `extra_tipos` da linha do readiness
}

export interface EgpsExtras {
  n: number;
  rows: EgpExtra[];
  projetos: string[];
}

export interface ScopeEgps {
  // CONGELADOS na linha de base (29/09/2026): n_egps é o tamanho da lista e n_base/
  // n_deps/n_ex são a decomposição pela CLASSE gravada no CSV, não pelo grafo vivo.
  n_egps: number;   // total de EGPs — igual ao Resumo/aba EGPs, e sempre o mesmo número
  n_base: number;   // classe `base` da linha de base
  n_deps: number;   // classe `dependencia` (0 fora de indi_deps)
  n_ex: number;     // classe `ex_dependencia` (0 fora de indi_deps)
  n_extra?: number; // VIVO: EGPs do recorte fora da lista — contador próprio, fora de n_egps
}

// Fragilidade da sanitização derivada (GET /api/inputs/fragilidade): quantas chaves
// estão fora da fila SÓ porque parte dos consumidores está fora do escopo — e o rollup
// inverso "EGP fora -> chaves que voltariam se ele entrar", já ordenado pelo backend.
export interface SanFragilidade {
  n_chaves: number;
  n_egps: number;
  chaves: string[];
  por_egp: { projeto: string; n_chaves: number; chaves: string[] }[];
}

export interface InputUsageEgp {
  projeto: string;
  area: string | null;
  onda: string | null;
  escopo_indi: string | boolean | null;
  ciclo_id: number | string | null;
  link_broken?: boolean;          // este consumidor (EGP) declarou vínculo quebrado com o input
  // Contexto p/ julgar "quem ainda depende disto" (backend _enrich_egp_contexto): recorte do
  // EGP ('indi' escopo direto | 'dep' dependência viva | 'ex' ex-dependência | 'fora' fora do
  // recorte) + etapa/status do funil de migração (sas_egp_pipeline; null = sem etapa definida).
  escopo?: "indi" | "dep" | "ex" | "fora";
  etapa?: string | null;
  status?: string | null;
  // quantas safras da família este EGP lê (só no detalhe de família); `link_broken` ali
  // só é true quando o vínculo foi quebrado em TODAS as safras que ele lê.
  n_safras?: number;
}

// Uma safra dentro do detalhe da família (read-only nesta fase: evidência, não unidade
// de trabalho — a edição é da família, ver ticket 03).
export interface InputSafra {
  chave_canonica: string;
  artifact: string;
  categoria: string;
  safra: string | null;            // token de data extraído do nome ('202506')
  etapa: string | null;            // valor HUMANO cru (null = nunca editado)
  status: string | null;
  etapa_efetiva: string;           // já resolvido (humano > derivado do auto)
  status_efetivo: string;
  resolvido: boolean;              // Modernizado | Sanitizado | Autoprodutor
  modernizada_auto: string;
  responsavel: string | null;
  observacao: string | null;
}

// Profundidade NECESSÁRIA de um par (EGP, família): "até que ponto do passado este EGP
// precisa desta família". `origem` diz se veio do corpus (derivado, recalculado sempre) ou
// de declaração humana (gravada, só gestão edita). Ver docs/adr/0002.
export interface PeriodoPar {
  projeto: string;
  tipo: "todas" | "desde" | "rolling";
  valor: string | null;            // 'AAAAMM' p/ desde; nº de meses p/ rolling; null p/ todas
  origem: "derivado" | "declarado";
  derivado_tipo?: string | null;   // o que o corpus diz, quando há declaração por cima
  derivado_valor?: string | null;
  n_safras_lidas?: number;
  safra_min_lida?: string | null;
  safra_max_lida?: string | null;
  span_meses?: number;
  esparso?: boolean;               // lê com buracos no intervalo (ex.: só dezembros)
  escopo?: "indi" | "dep" | "ex" | "fora";
  etapa?: string | null;
  status?: string | null;
}

// Profundidade INGERIDA: fato consumado, registrado por quem fez a carga (qualquer analista
// logado). Só a forma absoluta — "últimos N meses" descreve pedido, não o que está no disco.
export interface IngestaoFamilia {
  desde: string | null;            // 'AAAAMM' da safra mais antiga que existe no destino
  ingerida_em?: string | null;     // 'AAAA-MM-DD'
  updated_by?: string | null;
  updated_at?: string | null;
}

// Avisos da família — todos INFORMATIVOS. Nenhum bloqueia nada: campo manual esquecido não
// pode virar bloqueio (decisão Q13 do desenho).
export interface AvisosFamilia {
  // a carga não alcança o que algum consumidor vivo precisa (só existe com `ingerida`)
  rasa?: { n: number; de: number; projetos: string[]; precisa: string; mais_fundo: string };
  // faixa de profundidade pedida pelos consumidores vivos ("pedem de 8 a 103 meses")
  dispersao?: { min_meses: number; max_meses: number; n_consumidores: number; mais_fundo: string };
  // consumidores que leem safras com buracos no intervalo (ex.: só dezembros)
  esparsos?: string[];
}

export interface PeriodoFamilia {
  pares: PeriodoPar[];
  maximo: PeriodoPar | null;       // o mais fundo entre os consumidores VIVOS = a carga a pedir
  maximo_projeto: string | null;
  maximo_motivo?: string;          // por que não há máximo (ex.: nenhum consumidor vivo)
  n_esparsos: number;
  ingerida?: IngestaoFamilia | null;
  avisos?: AvisosFamilia;
}

export interface InputDetail {
  egps: InputUsageEgp[];
  produtores?: InputUsageEgp[];
  // presentes quando a chave pedida é (ou pertence a) uma FAMÍLIA — `egps` passa a ser a
  // união dos consumidores das safras, cada um com `n_safras` lidas.
  familia?: string;
  categoria?: string;
  n_safras?: number;
  safras?: InputSafra[];
  periodo?: PeriodoFamilia;
}

export interface IndiciumRow {
  id: string;
  egp_dor1: string;
  area: string;
  status_extracao: string;
  projeto: string;
  origem: string;
  node_projeto: string | null;
  onda: string | null;
  ciclo_id: number | string | null;
  recebido: boolean | string;
  ativo?: boolean | string;   // entrada do escopo ativa; false = desativada (preservada)
}

export interface IndiciumPayload {
  rows: IndiciumRow[];
}

export interface LandingMetrics {
  egps_escopo: number;
  egps_analisados: number;
  inputs_escopo: number;
  inputs_a_ingerir: number;
  deps: number;
  deps_ex: number;      // ex-dependências retidas (fora do frontier vivo) — exibido "(+N ex)"
  extras?: number;      // EGPs do recorte fora da linha de base congelada — "(+N extra)"
  inputs_deps: number;
  inputs_deps_a_ingerir: number;
  // Grupo PRÓPRIO dos extras (29/09/2026): os inputs que NENHUM EGP contável lê. Os três
  // grupos (escopo, dependências, extras) particionam `total_inputs` — o total não mudou
  // com a separação, a leitura mudou. Opcionais p/ o front tolerar backend anterior.
  inputs_extras?: number;
  inputs_extras_a_ingerir?: number;
  total_egps: number;
  total_inputs: number;
  total_nao_modernizados: number;
}

export interface FunnelBar {
  etapa: string;
  seg: Record<string, number>;
}

export interface FunnelTopStat {
  label: string;
  value: number;
  tone?: string; // ok | mut | wip — chave de cor no FunnelChart
}

export interface FunnelData {
  stages: string[];
  bars: FunnelBar[];
  coorte: number;
  migrados: number;
  total: number;
  top_stats?: FunnelTopStat[]; // contagens exibidas no topo (não nas barras), ex.: ingestão
}

export interface FunisPayload {
  migracao: FunnelData;
  ingestao: FunnelData;
  migracao_deps: FunnelData;   // escopo Indicium ∪ dependências transitivas (sem dupla contagem)
  ingestao_deps: FunnelData;
  migracao_extras: FunnelData; // extras: o que entrou no corpus depois da linha de base (§3.1.3)
  // Par de ingestão do funil acima: os inputs que NENHUM EGP contável lê (`so_de_extra`),
  // mesmo conjunto do card "Inputs dos extras". Opcional p/ tolerar backend anterior.
  ingestao_extras?: FunnelData;
}

// Tempo (dias) passado em cada etapa do funil de migração — ver /api/tempo-etapas.
// media_dias/mediana_dias vêm null quando n=0 (etapa sem transição auditada no escopo).
export interface TempoEtapaStatusRow {
  status: string;   // valor de STATUS_PROJETO (pipeline.ts)
  media_dias: number;
}

export interface TempoEtapaRow {
  etapa: string;
  media_dias: number | null;
  mediana_dias: number | null;
  n: number;
  // Repartição do media_dias entre "Com BV" (bloqueado esperando o banco) e "Conosco"
  // (trabalho nosso), via o switch de sas_gestao_bv. Somam media_dias por construção.
  media_dias_conosco: number | null;
  media_dias_com_bv: number | null;
  // Repartição ORTOGONAL (não um refinamento da de cima) do media_dias por STATUS_PROJETO
  // dentro da etapa — mesma paleta SEG do FunnelChart. Só status com dias > 0.
  por_status: TempoEtapaStatusRow[];
}

export interface TempoEtapasPayload {
  etapas: TempoEtapaRow[];
}

// Filtros compartilhados por /api/tempo-etapas e /api/tempo-analises (ver
// _tempo_base_filtrado no backend). `status` = status_migracao ATUAL (STATUS_PROJETO);
// `com_bv` = estado ATUAL do switch "Com BV" ("com_bv"/"conosco").
export interface TempoFiltro {
  responsavel?: string[];
  responsavel_bv?: string[];
  projeto?: string[];
  status?: string[];
  com_bv?: string[];
}

// Irmão de TempoFiltro pro lado dos INPUTS (/api/tempo-etapas-input, /api/tempo-analises-input)
// — ver _tempo_base_filtrado_input no backend. `chave` é o equivalente de `projeto` (busca
// de 1 input por chave_canonica); `categoria`/`origem` espelham os filtros da aba Inputs.
export interface TempoFiltroInput {
  responsavel?: string[];
  categoria?: string[];
  origem?: string[];
  chave?: string[];
  status?: string[];
  com_bv?: string[];
}

// 4 análises complementares de tempo — ver /api/tempo-analises e _analises_tempo (backend).
export interface LeadTimeMes {
  mes: string;          // "YYYY-MM" — mês em que o EGP entrou em "Migrado"
  media_dias: number;
  n: number;
}

export interface LeadTimeStats {
  media_dias: number | null;
  mediana_dias: number | null;
  n: number;             // só EGPs que JÁ chegaram em "Migrado" (cohort fechado)
  por_mes: LeadTimeMes[];
}

export interface AgingRow {
  projeto: string;
  etapa: string;
  dias: number;           // total na etapa (ainda em curso) — trabalho + espera
  // Repartição de `dias`: trabalho = até o status virar "Concluído" nesta etapa; espera =
  // depois disso (pronto, só não avançou de etapa ainda). Sem "Concluído" registrado,
  // espera=0 e trabalho=dias inteiro.
  dias_trabalho: number;
  dias_espera: number;
  responsavel: string | null;
}

export interface RetrabalhoPar {
  de: string;
  para: string;           // etapa ANTERIOR na ordem do funil (regressão real)
  n: number;
}

export interface RetrabalhoStats {
  n_egps: number;
  n_eventos: number;
  pares: RetrabalhoPar[];
}

export interface PorResponsavelRow {
  responsavel: string;    // email (login) — resolver nome no front, mesmo padrão de tempoEtapas
  media_dias: number;
  n: number;
}

export interface TempoAnalisesPayload {
  lead_time: LeadTimeStats;
  aging: AgingRow[];
  retrabalho: RetrabalhoStats;
  por_responsavel: PorResponsavelRow[];
}

export interface EgpPipelineState {
  migracao: { etapa: string | null; status: string | null; jira_id?: string | null;
    responsavel?: string | null; responsavel_bv?: string | null };
}

export interface LineageNode {
  projeto: string;
  area: string;
  onda: string;
  escopo_indi: string | boolean;
  n_inputs: number | string;
  n_outputs: number | string;
  ciclo_id?: number | string;
  // Indicadores de "modelo intermediário" (LOC + consumo por outro EGP) — cada um
  // independente, sem corte automático; o analista decide o que cruzar. Ver
  // publish_to_databricks.py § indicadores de "modelo intermediário" por EGP.
  loc?: number | string;
  code_tasks_count?: number | string;
  n_outputs_avaliados?: number | string;
  n_outputs_consumidos_por_outro_egp?: number | string;
  pct_outputs_consumidos_por_outro_egp?: number | string;
  n_egps_consumidores?: number | string;
  n_exports_arquivos?: number | string;
  flag_output_100pct_egp?: string | boolean;
  flag_algum_output_egp?: string | boolean;
  flag_sem_export_arquivo?: string | boolean;
  flag_output_unico?: string | boolean;
  flag_hub_multiplos_consumidores?: string | boolean;
}

export interface EgpInput {
  chave_canonica: string;
  artifact: string;
  categoria: string;
  source_types: string;
  origem: string;
  modernizada_auto: string;
  etapa: string | null;
  status: string | null;
  responsavel: string | null;
  observacao: string | null;
  paths_fisicos: string;
  n_paths_fisicos: number | string;
  n_proj_ativos: number | null;   // EGPs consumidores NÃO despriorizados (0 => candidato a remover)
  link_broken?: boolean;          // vínculo (EGP, Input) quebrado — conta como Sanitizado APENAS para este EGP
  // Com FAMILIAS_SAFRA ligada o painel lista FAMÍLIAS (mesma régua da aba Inputs):
  // `link_broken` só vem true quando TODAS as safras do EGP estão quebradas.
  is_familia?: boolean;
  nome_exibicao?: string;          // "LIB.TABELA_{SAFRA}" — o que se mostra no lugar do artifact
  n_safras_no_recorte?: number;    // cargas desta família que ESTE EGP lê
  // sanitização derivada — mesmos campos (e mesma trava) de InputRow
  sanitizado_derivado?: string;
  sanitizado_motivo?: string;
  status_real?: string | null;
  etapa_real?: string | null;
}

export interface EgpDep {
  projeto: string;
  via_tabelas: string | null;
  qtd_via: number | string;
  area: string | null;
  onda: string | null;
  ciclo_id: number | string | null;
  status?: string | null;  // status de migração do relacionado (selo Migrado/Despriorizado)
}

export interface EgpDetail {
  node: LineageNode;
  inputs: EgpInput[];
  depende_de: EgpDep[];
  alimenta: EgpDep[];
  em_ciclo_com: { projeto: string; area: string; onda: string }[];
  pipeline?: EgpPipelineState;
  bloqueio?: { bloqueado: boolean; proprias: string[]; deps_bloqueadoras: { projeto: string; tabelas: string[] }[] };
  impacto_despriorizado?: { impactado: boolean; deps: string[] };  // deps fora do backlog
}

export interface WaveRow {
  onda: string;
  onda_num: number;
  n_egps: number;
  n_inputs: number;
  n_ingeridos: number;
  n_andamento: number;
  pct: number;
  status: string;
  em_ciclo: boolean;
}

export interface PrioEgp {
  projeto: string;
  area: string | null;
  n_inputs_novos: number;          // CONGELADO no snapshot (contado na unidade da época)
  // marginal VIVO do EGP no mês, na unidade de hoje (família de safras quando a flag
  // está ligada). É o que a coluna "+Inputs" mostra; o congelado vai no title.
  n_inputs_novos_vivo?: number;
  responsavel: string | null;
  excede: boolean;
  bloqueado: boolean;
  fan_out: number;   // nº de EGPs do recorte que consomem o output deste (alavancagem)
  mes_pin: number | null;   // mês fixado manualmente (null = automático)
  ex_dependencia?: boolean; // retido no plano após sair do frontier (badge; 0 inputs)
  etapa: string | null;     // etapa no funil de migração (sas_egp_pipeline)
  status: string | null;    // status no funil de migração
}

export interface PrioResumo {
  migrados_mes: number;   // EGPs migrados NESTE mês de calendário (velocidade)
  bloqueados: number;
  habilitados: number;    // = total - bloqueados
  total: number;
}

export interface PrioMes {
  mes: number;
  n_inputs: number;          // CONGELADO no snapshot (pendentes na hora do plano) — não exibir
  n_egps: number;
  egps: PrioEgp[];
  // contagem VIVA (overlay a cada leitura): inputs distintos dos EGPs congelados do mês
  // (dedupe: input compartilhado conta no 1º mês). Ausente = live query falhou.
  n_inputs_total?: number;
  n_inputs_modernizados?: number;
}

// /api/funil-ingestao-mes — funil de ingestão (inputs) por mês do plano. Universo = inputs
// com vínculo ativo nos EGPs do frontier VIVO (mesmo dos cards da Visão geral e de
// funis.ingestao_deps), não o do plano congelado. `ingestao` é crosstab {etapa: {status: n}}
// (cada input numa única célula); Sanitizado fica fora e vira contador.
export interface FunilIngestaoBucket {
  ingestao: Record<string, Record<string, number>>;
  sanitizados: number;
  total: number;
}

// /api/funil-mes-extras — o funil de MIGRAÇÃO por mês SÓ dos extras. Mesmo `meses` do
// plano (por isso o mesmo componente o desenha), mas o mês vem do ANTECESSOR: o extra
// chegou depois do congelamento e não está no plano, e o trabalho dele é o do antecessor
// continuando noutro arquivo. `sem_mes` = extra sem antecessor no plano (casca, novo).
export interface FunilMesExtras {
  meses: { mes: number; egps: PrioEgp[] }[];
  n_egps: number;
  sem_mes: number;
  sem_mes_egps: PrioEgp[];        // os mesmos, para a linha "—" da tabela fechar com o card
}

export interface FunilIngestaoMes {
  meses: (FunilIngestaoBucket & { mes: number })[];
  sem_mes: FunilIngestaoBucket;   // inputs do frontier que nenhum EGP do plano consome
  total: number;
  sanitizados: number;
  n_egps: number;                 // tamanho do frontier que definiu o universo
}

export interface PriorizacaoPayload {
  meses: PrioMes[];
  n_meses: number;
  n_inputs: number;          // congelado (ver PrioMes.n_inputs)
  n_inputs_total?: number;         // vivo (soma dos meses)
  n_inputs_modernizados?: number;  // vivo (soma dos meses)
  n_egps: number;
  capacidade: number;   // vem da config persistida (sas_app_config); gestão pode mudar
  resumo: PrioResumo;
  snapshot?: { saved_by: string; saved_at: string } | null;  // meta do snapshot congelado; null = preview ao vivo
  // Mês dos EGPs EXTRA, herdado do Antecessor (backend `_extras_do_plano`). Fica FORA de
  // `meses[].egps` de propósito: extra não entra na contagem do plano, só ganha mês.
  // Casca e extra sem antecessor no plano não aparecem aqui — ficam sem mês.
  extras?: { projeto: string; mes: number }[];
}

export interface AuditRow {
  fonte: string;
  chave_canonica: string;
  // fonte "Monitoramento": a auditoria é gravada no grão SAFRA, mas a aba Inputs lista
  // FAMÍLIA — esta é a chave para onde o link deve ir (null = não é membro de família).
  chave_familia?: string | null;
  campo: string;
  valor_antigo: string | null;
  valor_novo: string | null;
  updated_by: string | null;
  updated_at: string | null;
  // Fan-out de família colapsado (só fonte "Monitoramento"): uma edição numa família
  // grava uma linha por safra, e o backend devolve UMA linha com a contagem. `familia` é
  // o nome sem o token de data — o rótulo certo quando n_safras > 1, porque
  // `chave_canonica` aí é só uma das safras, escolhida como representante.
  n_safras?: number | null;
  familia?: string | null;
}

export interface ReadinessDep {
  projeto: string;
  escopo_indi: boolean;
  area: string | null;
  ciclo_id: number;
}

export interface ReadinessRow {
  // Vínculo antecessor -> sucessor (spec 2026-09-24). Tudo derivado no backend.
  vinculo_tipo?: string | null;   // Atualizado | Substituído | Unificado
  sucessor?: string | null;       // projeto do corpus que substitui este
  // ESPELHAMENTO (decidido pelo tipo do vínculo): esta linha é o sucessor cuja etapa o
  // antecessor espelha. Eixo INDEPENDENTE da categoria abaixo — não unir os dois.
  e_sucessor?: boolean;
  // CATEGORIA `extra` (spec §3.1.2): o EGP tem VÍNCULO DE ATUALIZAÇÃO com outro — é
  // sucessor (inclusive de um Substituído) ou casca — e não está na linha de base.
  // ENUMERAÇÃO, não "todo o resto": ex-dependência nunca é extra, e quem nunca teve
  // vínculo também não (corrigido em 29/09/2026). Listado no recorte e com os inputs
  // contando, mas FORA do total base, em contador próprio.
  e_extra?: boolean;
  extra_motivo?: string | null;   // 'sucessor' | 'casca' | 'novo' | 'dependencia' — o "é extra?" com 1 rótulo
  // POR QUE é extra, no grão do FILTRO (29/09/2026): 'Atualizado' | 'Substituído' |
  // 'Unificado' | 'casca' | 'novo'. LISTA porque um sucessor pode ter antecessores de
  // tipos diferentes. Vazia (ou ausente) em quem não é extra.
  extra_tipos?: string[];
  // Quem este EGP substitui — o vínculo visto do lado do SUCESSOR. Lista porque um
  // unificador absorve vários; vem do mapa, então inclui antecessor fora do recorte.
  antecessores?: { projeto: string; tipo: string | null }[];
  // CONTAGEM: esta linha está na LISTA CONGELADA (linha de base de 29/09/2026)? Eixo
  // independente dos dois acima — ver contaNoTotalEgp, que a prefere à etapa viva.
  na_linha_base?: boolean;
  etapa_editavel?: boolean;       // false = etapa é espelho; o backend recusa a escrita
  // etapa GRAVADA (antes do espelho). `etapa` é a EXIBIDA; quem CONTA usa esta —
  // ver contaNoTotalEgp / _ex_deps_contab.
  etapa_real?: string | null;
  // status de CONTAGEM: igual a `status`, exceto no antecessor espelhado, onde `status`
  // diz `Desatualizado` (a relação) e este diz o terminal do fim da cadeia (o trabalho).
  // Quem soma migrados/despriorizados usa este — ver baldeEgp e vinculos.mapa_contagem.
  status_contagem?: string | null;
  projeto: string;
  area: string;
  onda: string;
  escopo_indi: string | boolean;
  ciclo_id: number;
  loc: number;                     // linhas de código do EGP (sas_lineage_nodes.loc)
  n_inputs: number;
  n_disp: number;
  n_faltam: number;
  n_prd: number;                   // subconjunto de n_faltam já em Ingestão PRD/Aplicação de
                                    // Grant (não Modernizado) — "desbloqueado", conta em `pct`
  n_remessa: number;               // subconjunto de n_faltam em PDI+GMUD/Ingestão PRD — banda
                                    // de uma remessa em trânsito (ver desbloqueia_remessa)
  desbloqueia_remessa: boolean;    // n_faltam > 0 e 100% do que falta já está na banda da
                                    // remessa (PDI+GMUD+Ingestão PRD) — EGP ficaria pronto
                                    // se essa remessa completasse (virasse Modernizado)
  n_links_broken?: number;         // qtos inputs deste EGP têm vínculo quebrado (informacional)
  pct: number;
  n_deps: number;
  n_deps_indi: number;
  n_deps_ext: number;
  deps: ReadinessDep[];
  status: string;
  etapa: string;
  bloqueado_dep?: boolean;
  responsavel?: string | null;
  responsavel_bv?: string | null;  // Responsável do lado BV (texto livre, editável na grid)
  // Classificação do EGP contra o recorte INDICIUM — propriedade do EGP, não do recorte
  // pedido. `fora_do_recorte` (07/10/2026) é o 4º valor: está no corpus e fora de tudo.
  // Antes esses saíam como "escopo" no recorte "todos", que é o único que os lista.
  tipo: "escopo" | "dependencia" | "ex_dependencia" | "fora_do_recorte";
  ex_dependencia?: boolean;        // saiu do frontier vivo mas fica retido (badge "ex-dependência")
  ex_motivo?: string | null;       // por que saiu: resolvida por ingestão (houve entrega) |
                                   // via descartada/desvinculada | cadeia despriorizada |
                                   // retida manualmente
  dep_mantida?: boolean;           // produtor mantido vivo à mão ("ainda é dependência")
  dep_nivel: number;               // distância do escopo (0 = escopo; 1 = dependência direta)
  n_sem_fonte: number;             // inputs SAS/Local (externo) deste EGP ainda sem fonte
  dep_ausente: boolean;            // tem >=1 dependência ausente (produtor fora do corpus)
  n_outputs: number;               // outputs distintos produzidos por este EGP (sas_egp_outputs)
  n_outputs_disp: number;          // desses, quantos "recebidos" — manual (sas_outputs_pipeline)
                                    // quando já tocado, senão cai no fallback modernizada_auto
  n_carga_fria?: number;           // outputs deste EGP marcados p/ carga fria (sas_outputs_pipeline.carga_fria)
  n_carga_fria_ok?: number;        // desses, quantos com carga fria finalizada (cf_etapa = Modernizado)
  preworking: boolean;             // questionário de pré-working do EGP preenchido (sas_egp_pipeline.preworking_preenchido)
  preworking_data?: string | null; // "YYYY-MM-DD" — data de referência 100% manual (sas_egp_pipeline.preworking_data)
  deps_despriorizadas?: string[];  // deps (transitivas) fora do backlog impactando este EGP
  fim_conversao?: string | null;   // sas_gestao_datas.fim_conversao — presença = "convertido"
  jira_id?: string | null;         // sas_egp_pipeline.jira_id (formato PROJ-123)
  egp_atualizado_key?: string | null;      // vínculo MANUAL confirmado (sas_egp_pipeline) — vence o automático
  atualizado_auto_key?: string | null;     // melhor candidato AUTOMÁTICO (pareamento por hash, egp_original)
  atualizado_auto_nome?: string | null;
  atualizado_auto_confianca?: string | null; // ok | alerta | forcado
  atualizado_link_key?: string | null;     // resolvido: manual ?? automático — o que a badge mostra
  atualizado_link_nome?: string | null;
  atualizado_link_versao_id?: string | null; // p/ deep-link em EGPs Atualizados (pathFor)
  // tipo_vinculo da versão vinculada (atualizacao|substituicao|agrupamento), decidido no
  // funil da troca (EgpsAtualizadosView.tsx) — null = ainda não decidido lá. Rotula o
  // status "Despriorizado e Contabilizado" como Atualizado/Descontinuado/Unificado no
  // lugar do genérico "substituído" (ver TIPO_VINCULO_LABEL em pipeline.ts).
  atualizado_link_tipo_vinculo?: "atualizacao" | "substituicao" | "agrupamento" | null;
}

export interface ReadinessPayload {
  rows: ReadinessRow[];
  base_count: number;
  dep_count: number;
  ex_count?: number;               // ex-dependências retidas (contam no total, não no header de inputs)
  extra_count?: number;            // extras do recorte (vivo) — AO LADO do total, nunca dentro
  total: number;
  inputs_distintos: number;        // inputs distintos no recorte, sem dupla contagem
  inputs_distintos_disp: number;   // distintos já modernizados/disponíveis
  inputs_distintos_faltam: number; // distintos a ingerir (nunca modernizados)
  inputs_distintos_base: number;   // distintos só do escopo (sem dependências)
  inputs_sem_fonte: number;        // distintos com origem SAS/Local (externo) — fonte não mapeada
}

/** Mapa EGP -> unidades de input, para os cards da aba EGPs contarem o MESMO dataset que
 * a Visão geral conta e reagirem aos filtros da tabela (`/api/egp-input-units`).
 *
 * `unidades` é o universo do recorte (uma linha por família de safras quando `grao` é
 * "familia"); `por_egp` dá, por EGP, os índices das unidades com vínculo não quebrado.
 * Somar os índices dos EGPs em tela e contar o conjunto é o que faz o card bater com o
 * Resumo quando nenhum filtro está ligado. */
export interface EgpInputUnits {
  grao: "familia" | "safra";
  unidades: {
    k: string;      // chave da unidade (física, ou `familia::categoria::nome`)
    a: boolean;     // a ingerir (pendente)
    sf: boolean;    // SAS/Local (externo) ainda pendente — "sem fonte mapeada"
  }[];
  por_egp: Record<string, number[]>;
}

export interface LineageEdge {
  from: string;
  to: string;
  via: string | null;
}

export interface LineagePayload {
  nodes: LineageNode[];
  edges: LineageEdge[];
  root?: string;
  capped?: boolean;
}

export interface AreaStat {
  area: string;
  n: number;
  n_indi: number;
}

export interface ResumoFunilRow {
  area: string;
  qtd_dor1: number;
  deps?: number;   // só na visão + dependências: quantos da linha são deps (fora do escopo)
  egps_enviados: number;
  egps_analisados: number;
  inputs_nao_modernizados: number;
  // linha dos extras na visão + dependências: os EGPs ficam FORA do total (como o
  // "(+N extra)" do card Total de EGPs), os inputs entram (o Total de Inputs os conta).
  a_parte?: boolean;
}

export interface ResumoOrigemRow {
  bucket: string;
  total: number;
  modernizado: number;
  nao_modernizado: number;
}

export interface ResumoFunil {
  rows: ResumoFunilRow[];
  total: { qtd_dor1: number; deps?: number; egps_enviados: number; egps_analisados: number; inputs_nao_modernizados: number };
}

export interface ResumoOrigem {
  rows: ResumoOrigemRow[];
  total: { total: number; modernizado: number; nao_modernizado: number };
  // unidades fora das 4 origens (o placeholder `casco::` dos unificados)
  fora_das_origens?: number;
}

export interface ResumoPayload {
  funil: ResumoFunil;
  origem: ResumoOrigem;
  funil_deps: ResumoFunil | null;    // visão Indicium + dependências (null se grafo ausente)
  origem_deps: ResumoOrigem | null;
  // 3ª tabela, ISOLADA (as duas acima são cumulativas): só os inputs que NENHUM EGP
  // contável lê — mesmo conjunto do card "Inputs dos extras". null = sem extras no
  // recorte, ou backend anterior à separação de 29/09.
  origem_extras?: ResumoOrigem | null;
}

// (aba Prioridades removida — tipos Prioridade/PrioridadeCreate/PrioridadePatch retirados;
// rotas /api/prioridades* e a Delta table permanecem no backend, dormentes)

// ── Monitoramento Outputs ────────────────────────────────────────────────────
export interface OutputRow {
  chave_canonica: string;
  artifact: string;
  categoria: string;
  areas: string;
  qtd_produtores: number;
  qtd_criadores?: number | string | null;  // quantos CRIAM (regra do criador); null em tabela pré-republish
  qtd_consumidores: number;
  terminal: boolean | string;
  modernizada_auto: string;
  escopo_indi: boolean | string;
  produtor_escolhido?: string | null;   // produtor canônico escolhido (sub-projeto 2)
  paths_fisicos: string;                // caminho(s) físico(s) do output (raw data), separados por " | "
}

export interface OutputsResponse {
  total: number;
  returned: number;
  capped: boolean;
  rows: OutputRow[];
}

// Recebimento manual por output (sas_outputs_pipeline) — mesmo espírito do toggle+data de
// Pré-working do EGP, mas por output (chave_canonica); SUBSTITUI modernizada_auto na conta
// de n_outputs_disp assim que tocado (ver egp_readiness no backend). Preenchido no
// GestaoStatusPanel, dentro da seção Outputs do EGP.
export interface OutputPipelineRow {
  chave_canonica: string;
  recebido: string | null;        // "true" | "false" (toggle, mesma convenção do checkbox de Recebimento do Input)
  recebido_data: string | null;   // "YYYY-MM-DD"
  carga_fria: string | null;      // "true" = output precisa de carga histórica (fria); gera card no Kanban de Inputs
  cf_etapa: string | null;        // funil de ingestão do card de carga fria (PIPELINE_INPUT)
  cf_status: string | null;
  cf_responsavel: string | null;
  cf_inicio: string | null;       // janela do histórico a ingerir, "YYYY-MM-DD"
  cf_fim: string | null;
  cf_caminho: string | null;      // destino final dos arquivos
  cf_tabela: string | null;       // nome da tabela modernizada que receberá o histórico
  updated_by: string | null;
  updated_at: string | null;
}

export interface OutputUsageEgp {
  projeto: string;
  area: string | null;
  onda: string | null;
  escopo_indi: boolean | string | null;
  ciclo_id: number | string | null;
  link_broken?: boolean;          // consumer (output): o EGP declarou vínculo quebrado com este output
  apenas_contribui?: boolean;     // producer (output): só apensa/atualiza, não cria (regra do criador)
}

export interface OutputDetail {
  produtores: OutputUsageEgp[];
  consumidores: OutputUsageEgp[];
  produtor_escolhido?: string | null;   // produtor canônico escolhido (sub-projeto 2)
}

// Versões novas de EGP enviadas pelo cliente, publicadas por script local em
// sas_egp_atualizados (backend separado, read-only). Uma linha = a VERSÃO RECEBIDA mais
// recente de cada egp_key; histórico no detalhe. A aba dedicada foi aposentada (spec §5):
// a lista sobra como catálogo da busca do vínculo, no detalhe do EGP.
export interface EgpAtualizadoRow {
  versao_id: string;               // <egp_key>@<data_recebimento>
  egp_key: string;                 // Área__Nome
  nome: string;
  area: string;
  egp_original: string | null;     // antecessor(es) no corpus; null = EGP inédito
  n_antecessores: number;
  confianca_par: string | null;    // ok | alerta | forcado | sem_par | recusado
  quadrante: string | null;        // Trocar agora | ... | EGP inédito
  valor: number | null;
  esforco: number | null;
  razao: number | null;
  n_vetos: number;
  autor_ultimo_save: string | null;
  data_ultimo_save: string | null; // ISO, do project.xml (ticks .NET)
  data_recebimento: string;        // ISO
  status_troca: string;            // recebida | trocada (fase 2)
  // O funil PRÓPRIO por versão (sas_egp_atualizados_pipeline) saiu com a aba (spec §5):
  // o sucessor usa sas_egp_pipeline, como qualquer EGP do corpus.
  // funil de MIGRAÇÃO do(s) antecessor(es) no corpus (sas_egp_pipeline, vivo);
  // etapa/status nulos = antecessor fora do funil. `recorte` (só no DETALHE, do
  // _enrich_egp_contexto do main): indi = escopo direto · dep = dependência transitiva ·
  // ex = ex-dependência · fora = fora do recorte. `preworking` idem (só no DETALHE):
  // null = antecessor sem linha no funil de migração (nunca chegou lá).
  antecessores: { projeto: string; etapa: string | null; status: string | null;
    recorte?: "indi" | "dep" | "ex" | "fora" | null;
    preworking?: boolean | null; preworking_data?: string | null }[];
  n_versoes: number;               // total de versões recebidas desta egp_key
  n_inputs: number;                // inputs da versão (inventário congelado)
  n_disp: number;                  // resolvidos: vivo (JOIN monitor) ou congelado p/ fora do corpus
  n_novos: number;                 // inputs que não existiam no antecessor
  pct: number;                     // prontidão % viva (100 se n_inputs=0)
  // Datas do funil da TROCA (sas_gestao_datas, entity='egp_atualizado', grão egp_key) —
  // MESMA tabela/edição da aba EGPs (PATCH /api/gestao/datas), sobrevive a novas versões
  // igual a etapa/status/responsavel acima.
  inicio: string | null;
  fim_conversao: string | null;
  fim: string | null;
}

export interface EgpsAtualizadosResponse {
  rows: EgpAtualizadoRow[];
  sem_tabela: boolean;             // schema ainda sem nenhuma publicação
}

// Versão recebida que ainda NÃO virou projeto do corpus (spec §5): já foi comparada e
// publicada na aba, mas o pipeline (extrator → orquestrador → publish) ainda não rodou.
// Uma linha por VERSÃO recebida, não por egp_key. Contador derivado: zera sozinho quando
// o pipeline roda e some sozinho quando a versão é descartada.
export interface RecebidaAguardandoCorpus {
  versao_id: string;
  egp_key: string;                 // Área__Nome
  nome: string;
  area: string;
  data_recebimento: string;        // ISO
  egp_original: string | null;     // antecessor(es) no corpus; null = EGP inédito
  chave_prevista: string;          // Área__nome__ATU<data de recebimento>
  // "pareamento não resolvido" / "falha na extração": os dois valores da antiga taxonomia
  // "Situação" que NÃO são tipo de vínculo — a comparação não pôde ser feita. null = ok.
  pendencia: string | null;
}

export interface AguardandoCorpusPayload {
  rows: RecebidaAguardandoCorpus[];
  n: number;
  // Versões COM pendência que já entraram no corpus (fora de `rows`): entrar no corpus
  // resolve o "aguardando", não a pendência. `n_pendencias` conta cada versão uma vez.
  pendencias: RecebidaAguardandoCorpus[];
  n_pendencias: number;
  sem_tabela: boolean;             // schema ainda sem nenhuma publicação
}

// Contrapartida de AguardandoCorpusPayload: ali a versão ainda não entrou no corpus, aqui
// ela ENTROU e mesmo assim não tem linha em tela nenhuma — fora da linha de base, fora do
// recorte e sem vínculo nas duas direções. Existe porque o silêncio custa número de
// gestão: sem vínculo o app não sabe que é versão nova de alguém, trata o EGP como
// produtor qualquer e joga os inputs dele no card de dependências (30/09: 3 EGPs, 26
// inputs, o card marcando 88 contra os 61 de prod).
export interface EgpSemVinculo {
  projeto: string;
  // antecessor pelo pareamento JÁ MEDIDO em sas_egp_atualizados (hash de tasks), não por
  // semelhança de nome: null quer dizer "não há candidato", não "não procuramos".
  antecessor_sugerido: string | null;
}

// Vínculo declarado cujo ANTECESSOR está fora do recorte: existe e não faz nada — não
// exibe Desatualizado, não espelha etapa e não puxa o sucessor para dentro.
export interface VinculoOrfao {
  antecessor: string;
  sucessor: string;
  tipo: string | null;             // o vínculo pode ter sido gravado sem tipo
  // false = o sucessor TAMBÉM não aparece em lugar nenhum (pede ação); true = o vínculo é
  // inerte mas o EGP está em tela por outro caminho; null = servidor não informou.
  sucessor_em_tela: boolean | null;
}

export interface EgpsSemVinculoPayload {
  sem_vinculo: EgpSemVinculo[];
  orfaos: VinculoOrfao[];
  n: number;
  n_orfaos: number;
  n_orfaos_invisiveis: number;
}

export interface EgpAtualizadoInput {
  chave_canonica: string;
  artefato: string;                // caminho/nome completo como o EGP lê
  categoria: string;               // tabela | arquivo | script
  source: string | null;
  situacao_no_recebimento: string; // disponivel | a_ingerir | arquivo | script (congelado)
  novo: boolean | null;            // não existia no antecessor; null = EGP inédito
  no_corpus: boolean;              // chave casou com sas_inputs_monitor (JOIN vivo)
  chave_familia?: string | null;   // chave exibida na aba Inputs quando a safra é de família
  disponivel_vivo: boolean;        // resolvido: vivo quando no corpus, congelado se fora
  etapa_corpus: string | null;     // etapa/status atuais do monitor (só quando no_corpus)
  status_corpus: string | null;
  origem_corpus: string | null;
  qtd_projetos: number | null;     // quantos EGPs do corpus leem este input
}

export interface EgpAtualizadoOutput {
  chave_canonica: string;
  artefato: string;
  situacao: string;                // novo | mantido | removido | novo_egp (inédito)
  novo: boolean | null;
  removido: boolean;
  n_consumidores_externos: number | null; // só p/ removidos (base do veto)
  // escrita permanente REAL com nome parametrizado por macro (ex. RENEG.X_&SAFRA —
  // uma tabela por execução/safra); o corpus não a monitora por chave, mas é output
  // de verdade — badge "padrão &macro" na tela.
  padrao: boolean | null;
  categoria: "tabela" | "arquivo";  // arquivo = EXPORTED FILES (handoff por arquivo)
}

export interface EgpAtualizadoDetail {
  // GET /api/egp-atualizado faz um SELECT * cru em sas_egp_atualizados (sem o JOIN
  // com pipeline/_prontidao que a LISTA faz) e calcula n_inputs/n_disp/pct em cima dos
  // `inputs` já buscados (ver egps_atualizados.py:egp_atualizado_detalhe) — mas
  // n_versoes só existe na LISTA (window function). Um `& {...}` com EgpAtualizadoRow
  // inteiro prometia esse campo como sempre presente e o TS aceitava acesso a campo que o
  // endpoint nunca preenche — omite explicitamente em vez de mentir o contrato.
  versao: Omit<EgpAtualizadoRow, "n_versoes" | "n_novos"> & {
    arquivo: string; arquivo_hash: string; origem: string | null;
    overlap_tasks: number | null; login_autor: string | null;
    data_criacao: string | null; vetos: string | null; alertas: string | null;
    loc_antigo: number | null; loc_novo: number | null;
    linhas_add: number | null; linhas_rem: number | null; tasks_novas: number | null;
    alcance_total: number | null;
    outputs_antigo: number | null; outputs_novo: number | null;
    outputs_removidos_com_consumidor: number | null;
    publicado_por: string; publicado_em: string;
  };
  inputs: EgpAtualizadoInput[];
  outputs: EgpAtualizadoOutput[];
  historico: EgpAtualizadoVersaoRef[]; // todas as versões da mesma egp_key, mais recente 1º
  mais_recente: boolean;               // esta versao_id é a mais recente da chave
}

export interface EgpAtualizadoVersaoRef {
  versao_id: string;
  data_recebimento: string;
  data_ultimo_save: string | null;
  quadrante: string | null;
  status_troca: string;
  arquivo_hash: string;
  publicado_em: string;
}
