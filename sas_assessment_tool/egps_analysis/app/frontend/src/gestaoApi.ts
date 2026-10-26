// Camada de dados da Gestão de EGPs/Inputs (aba Gestão) — PRODUÇÃO (deltaGestaoApi):
//   listRows   <- GET  /api/gestao/rows   (recorte indi_deps: escopo Indicium ∪ dependências;
//                                           egp: nós ⋈ sas_egp_pipeline; input: monitor consumido pelo frontier)
//   setDates   <- PATCH /api/gestao/datas (sas_gestao_datas, MERGE + auditoria funil 'gestao')
//   listStatus/addStatus <- /api/gestao/status (sas_gestao_status; último = "último status" —
//                           SEM resumo IA, por decisão do usuário: a tabela mostra o texto)
//   getUsers   <- /api/analistas (ativos)
//   getHolidays<- FERIADOS_BR local (configurável em diasUteis.ts)
// O mockGestaoApi permanece abaixo para dev/testes sem warehouse (mesma interface).

import { FERIADOS_BR, hojeSP } from "./diasUteis";

// "egp_atualizado" (grão egp_key) é usado por listStatus/addStatus — comentários da troca
// na aba EGPs Atualizados (EgpAtualizadoComentarios) — e, desde 2026-09, por setDates
// (datas do funil da troca, lidas via LEFT JOIN em /api/egps-atualizados, ver
// egps_atualizados.py:_ensure_gdt/egps_atualizados_lista). listRows/setBV continuam sem
// suporte no backend p/ esta entity — o funil da troca (etapa/status/responsável) vive em
// sas_egp_atualizados_pipeline via /api/egp-atualizado-pipeline, e não há "Com BV" pra
// troca — não chame essas duas com esta entity.
export type EntityType = "egp" | "input" | "egp_atualizado";

export interface BVEvento {
  id: string;
  comBv: boolean;
  data: string;         // "YYYY-MM-DD"
  autor: string | null; // email de quem registrou
}

export interface GestaoRow {
  id: string;                    // projeto (egp) | chave_canonica (input)
  nome: string;
  area: string | null;
  responsavel: string | null;    // email; a UI resolve o nome via getUsers()
  etapa: string | null;
  status: string | null;         // só a variante Input preenche (progresso na etapa); null no EGP
  inicioMigracao: string | null; // "YYYY-MM-DD"
  fimConversao: string | null;   // fim da conversão do código (usada na variante EGP)
  fimMigracao: string | null;
  resumoStatus: string | null;   // texto do ÚLTIMO status (a UI trunca em 1 linha)
  resumoStatusData: string | null; // ts (UTC, cru do banco) do último status; formatar com fmtTsBR
  egps: string[];                // EGPs consumidores (input); no egp = [id]
  bvEventos: BVEvento[];         // log append-only do switch "Com BV" (asc por data)
  // Contador MANUAL de revisão de regras de negócio (EGP devolvido de PRD p/ validação em DES).
  // >0 pinta o card no Kanban; só existe p/ EGP (Input vem 0/ausente).
  revisoesRegras?: number;
  // Card de CARGA FRIA (Kanban de Inputs): é um OUTPUT que precisa de carga histórica, id =
  // "cf::<chave_canonica>". Etapa/status/responsável moram em sas_outputs_pipeline, não em T_IN.
  cargaFria?: boolean;
  // "Tbl. Corresp." (input: observacao do monitor; carga fria: cf_tabela) — nome da tabela modernizada.
  tabelaCorresp?: string | null;
}

export const CF_PREFIX = "cf::";

// Estado atual do switch "Com BV" = comBv do evento mais recente (bvEventos vem asc por
// data) — usado pela tabela de Gestão (GestaoMigracao) e pelos cards do Kanban
// (GestaoKanban, quando onToggleBV é passado).
export const comBvAtual = (r: GestaoRow): boolean =>
  r.bvEventos.length > 0 && r.bvEventos[r.bvEventos.length - 1].comBv;

export interface StatusEntry {
  id: string;
  autor: string;   // email
  data: string;    // ISO "YYYY-MM-DDTHH:mm:ss"
  texto: string;   // multilinha/bullets
}

export interface GestaoUser { email: string; nome: string; }

// Usuários dos dropdowns da Gestão, derivados do MESMO payload de /api/analistas que as
// outras abas leem sob ["analistas"]. Use como `select` em
// useQuery({ queryKey: ["analistas"], queryFn: () => api.analistas(), select: usuariosGestao }):
// uma query só — a antiga ["gestao-users"] buscava o mesmo endpoint de novo, e a invalidação
// de ["analistas"] (cadastro na aba Gestão) não alcançava esses dropdowns.
export const usuariosGestao = (p: { rows: { email: string; nome: string }[] }): GestaoUser[] =>
  p.rows.map((a) => ({ email: a.email, nome: a.nome || a.email }));

export interface GestaoDataSource {
  listRows(entity: EntityType): Promise<GestaoRow[]>;
  getUsers(): Promise<GestaoUser[]>;
  listStatus(entity: EntityType, id: string): Promise<StatusEntry[]>; // desc (índice 0 = último)
  addStatus(entity: EntityType, id: string, autor: string, texto: string): Promise<StatusEntry>;
  setDates(entity: EntityType, id: string,
           patch: { inicio?: string | null; fim?: string | null; fimConversao?: string | null }): Promise<void>;
  setBV(entity: EntityType, id: string, comBv: boolean, data?: string): Promise<void>;
  deleteBV(id: string): Promise<void>;
  ajustaRevisao(id: string, delta: 1 | -1): Promise<void>;   // só EGP
  getHolidays(year: number): Promise<string[]>;
}

// ─── PRODUÇÃO (Delta via backend) ────────────────────────────────────────────

async function j<T>(r: Response): Promise<T> {
  // `status` no Error: mesmo contrato do json() de api.ts (retry global não repete 4xx).
  if (!r.ok) throw Object.assign(new Error(`${r.status} ${await r.text()}`), { status: r.status });
  return r.json() as Promise<T>;
}

export const deltaGestaoApi: GestaoDataSource = {
  listRows: (entity) =>
    fetch(`api/gestao/rows?entity=${entity}`).then(j<{ rows: GestaoRow[] }>).then((p) => p.rows),
  getUsers: () =>
    fetch("api/analistas")
      .then(j<{ rows: { email: string; nome: string; ativo: boolean | string }[] }>)
      .then(usuariosGestao),
  listStatus: (entity, id) =>
    fetch(`api/gestao/status?entity=${entity}&id=${encodeURIComponent(id)}`)
      .then(j<{ rows: StatusEntry[] }>).then((p) => p.rows),
  addStatus: async (entity, id, autor, texto) => {
    const r = await fetch("api/gestao/status", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ entity, id, autor, texto }),
    }).then(j<{ ok: boolean; id: string }>);
    // eco local (a lista real é rebuscada via invalidação das queries)
    return { id: r.id, autor, data: new Date().toISOString().slice(0, 19), texto };
  },
  setDates: async (entity, id, patch) => {
    const MAP = { inicio: "inicio", fim: "fim", fimConversao: "fim_conversao" } as const;
    for (const k of Object.keys(MAP) as (keyof typeof MAP)[]) {
      if (k in patch) {
        await fetch("api/gestao/datas", {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ entity, id, campo: MAP[k], valor: patch[k] ?? null }),
        }).then(j<{ ok: boolean }>);
      }
    }
  },
  setBV: async (entity, id, comBv, data) => {
    await fetch("api/gestao/bv", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ entity, id, comBv, ...(data ? { data } : {}) }),
    }).then(j<{ ok: boolean; id: string }>);
  },
  deleteBV: async (id) => {
    await fetch(`api/gestao/bv?id=${encodeURIComponent(id)}`, { method: "DELETE" })
      .then(j<{ ok: boolean }>);
  },
  ajustaRevisao: async (id, delta) => {
    await fetch("api/gestao/revisao", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ id, delta }),
    }).then(j<{ ok: boolean; contador: number }>);
  },
  getHolidays: async (year) => FERIADOS_BR.filter((d) => d.startsWith(String(year))),
};

// ─── MOCK ────────────────────────────────────────────────────────────────────

const delay = (ms = 250) => new Promise((r) => setTimeout(r, ms));

const USERS: GestaoUser[] = [
  { email: "lucas.muller@indicium.tech", nome: "Lucas Müller" },
  { email: "ana.souza@indicium.tech", nome: "Ana Souza" },
  { email: "pedro.lima@indicium.tech", nome: "Pedro Lima" },
  { email: "maria.santos@indicium.tech", nome: "Maria Santos" },
  { email: "joao.pereira@bancobv.com.br", nome: "João Pereira (BV)" },
];

interface Seed {
  id: string; nome: string; area: string; responsavel: string | null; etapa: string | null;
  // status do funil (só a variante Input preenche) — nome distinto de `status` abaixo
  // (que é o histórico de comentários) pra não colidir.
  pipeStatus?: string | null;
  inicio: string | null; fim: string | null; fimConv?: string | null;
  egps?: string[]; status: [string, string, string][]; // [autor, ts, texto]
}

const EGP_SEED: Seed[] = [
  {
    id: "Cobranças__Carteira_CA_COMPLETA_GCP", nome: "Carteira_CA_COMPLETA_GCP", area: "Cobrança",
    responsavel: "ana.souza@indicium.tech", etapa: "Conversão do Código", inicio: "2026-06-15", fim: null,
    status: [
      ["ana.souza@indicium.tech", "2026-07-06T14:20:00", "Conversão 70% concluída.\n- Faltam 3 queries de pass-through BigQuery\n- Bloqueio da tabela X resolvido ontem"],
      ["ana.souza@indicium.tech", "2026-06-28T09:10:00", "Iniciada a conversão dos steps de macro. Sem bloqueios."],
    ],
  },
  {
    id: "Cobranças__Project_Atualiza_Base_Collection", nome: "Project_Atualiza_Base_Collection", area: "Cobrança",
    responsavel: "pedro.lima@indicium.tech", etapa: "Validação em DES", inicio: "2026-05-20", fim: null, fimConv: "2026-06-26",
    status: [
      ["pedro.lima@indicium.tech", "2026-07-03T17:45:00", "Validação em DES: 2 divergências de contagem investigadas; causa = filtro de data no SAS original."],
    ],
  },
  {
    id: "Cobranças__ALIMENTAR_DASH_NPSv10", nome: "ALIMENTAR_DASH_NPSv10", area: "Cobrança",
    responsavel: "maria.santos@indicium.tech", etapa: "Migrado", inicio: "2026-04-01", fim: "2026-06-10", fimConv: "2026-05-08",
    status: [
      ["maria.santos@indicium.tech", "2026-06-10T11:00:00", "Migração concluída e validada pela área. Job agendado em produção."],
      ["maria.santos@indicium.tech", "2026-05-15T10:00:00", "Em validação final com a área de negócio."],
    ],
  },
  {
    id: "Riscos__etl_dmt_bacenpeprmoedas", nome: "etl_dmt_bacenpeprmoedas", area: "Riscos",
    responsavel: null, etapa: "Projetos Habilitados", inicio: null, fim: null,
    status: [],
  },
  {
    id: "Finanças__GERA_BASE_GASTOS_GCP", nome: "GERA_BASE_GASTOS_GCP", area: "Finanças",
    responsavel: "pedro.lima@indicium.tech", etapa: "Despriorizado", inicio: "2026-03-10", fim: "2026-04-02",
    status: [
      ["pedro.lima@indicium.tech", "2026-04-02T16:30:00", "Despriorizado pela área após ingestão inicial — esforço contabilizado."],
    ],
  },
  {
    id: "Cobranças__Project_Atualiza_Base_D0", nome: "Project_Atualiza_Base_D0", area: "Cobrança",
    responsavel: "ana.souza@indicium.tech", etapa: "Migrado", inicio: "2026-05-02", fim: "2026-06-25", fimConv: "2026-05-29",
    status: [
      ["ana.souza@indicium.tech", "2026-06-25T15:00:00", "Migrado. Reconciliação de 30 dias sem divergência."],
    ],
  },
  {
    id: "SAS_UC4__etl_dmt_ifbacen_regespecial", nome: "etl_dmt_ifbacen_regespecial", area: "SAS_UC4",
    responsavel: "lucas.muller@indicium.tech", etapa: "Pré-Working + Outputs", inicio: "2026-07-01", fim: null,
    status: [
      ["lucas.muller@indicium.tech", "2026-07-02T08:30:00", "Levantamento de dependências upstream em andamento; 2 produtores ausentes identificados."],
    ],
  },
];

const INPUT_SEED: Seed[] = [
  {
    id: "table::dba.tb_collection_full", nome: "dba.tb_collection_full", area: "Cobrança",
    responsavel: "maria.santos@indicium.tech", etapa: "Ingestão UAT", pipeStatus: "Em Andamento",
    inicio: "2026-06-20", fim: null, egps: ["Cobranças__Project_Atualiza_Base_Collection", "Cobranças__Carteira_CA_COMPLETA_GCP"],
    status: [
      ["maria.santos@indicium.tech", "2026-07-05T13:15:00", "Ingestão D-1 configurada no lake; aguardando janela de homologação."],
    ],
  },
  {
    id: "table::insight.carteira_ca", nome: "insight.carteira_ca", area: "Cobrança",
    responsavel: "ana.souza@indicium.tech", etapa: "Modernizado", pipeStatus: "Concluído",
    inicio: "2026-05-05", fim: "2026-06-01", egps: ["Cobranças__Carteira_CA_COMPLETA_GCP"],
    status: [
      ["ana.souza@indicium.tech", "2026-06-01T09:40:00", "Disponível no BigQuery (trusted_cobranca.carteira_ca). Consumidores notificados."],
    ],
  },
  {
    id: "file::/sas/data/npsv10.xlsx", nome: "npsv10.xlsx", area: "Cobrança",
    responsavel: null, etapa: "A Receber", pipeStatus: "A Iniciar",
    inicio: null, fim: null, egps: ["Cobranças__ALIMENTAR_DASH_NPSv10"],
    status: [],
  },
  {
    id: "table::bacen.pepr_moedas", nome: "bacen.pepr_moedas", area: "Riscos",
    responsavel: "pedro.lima@indicium.tech", etapa: "Recebido", pipeStatus: "Concluído",
    inicio: "2026-06-28", fim: null, egps: ["Riscos__etl_dmt_bacenpeprmoedas", "SAS_UC4__etl_dmt_ifbacen_regespecial"],
    status: [
      ["pedro.lima@indicium.tech", "2026-06-30T10:05:00", "Amostra recebida da área.\n- Falta dicionário de dados\n- Volumetria estimada: 2M linhas/mês"],
    ],
  },
  {
    id: "table::gastos.base_gastos", nome: "gastos.base_gastos", area: "Finanças",
    responsavel: "lucas.muller@indicium.tech", etapa: "Modernizado", pipeStatus: "Sanitizado",
    inicio: "2026-03-12", fim: "2026-03-30", egps: ["Finanças__GERA_BASE_GASTOS_GCP"],
    status: [
      ["lucas.muller@indicium.tech", "2026-03-30T14:00:00", "Removido do escopo junto com a despriorização do EGP consumidor."],
    ],
  },
];

// estado "servidor" do mock (module-level: sobrevive a troca de aba, morre no refresh)
// egp_atualizado sem seed (mock não cobre a aba EGPs Atualizados) — só precisa existir
// para o Record<EntityType, Map<...>> compilar com o terceiro membro do union.
const db: Record<EntityType, Map<string, GestaoRow>> =
  { egp: new Map(), input: new Map(), egp_atualizado: new Map() };
const statusDb: Record<EntityType, Map<string, StatusEntry[]>> =
  { egp: new Map(), input: new Map(), egp_atualizado: new Map() };
const bvDb: Record<EntityType, Map<string, BVEvento[]>> =
  { egp: new Map(), input: new Map(), egp_atualizado: new Map() };
let seq = 0;

function seed(entity: EntityType, seeds: Seed[]) {
  for (const s of seeds) {
    const entries: StatusEntry[] = s.status
      .map(([autor, data, texto]) => ({ id: `st${++seq}`, autor, data, texto }))
      .sort((a, b) => (a.data < b.data ? 1 : -1));
    statusDb[entity].set(s.id, entries);
    db[entity].set(s.id, {
      id: s.id, nome: s.nome, area: s.area, responsavel: s.responsavel, etapa: s.etapa,
      status: s.pipeStatus ?? null,
      inicioMigracao: s.inicio, fimConversao: s.fimConv ?? null, fimMigracao: s.fim,
      resumoStatus: entries[0] ? entries[0].texto : null,
      resumoStatusData: entries[0] ? entries[0].data : null,
      egps: s.egps ?? [s.id],
      bvEventos: [],
    });
  }
}
seed("egp", EGP_SEED);
seed("input", INPUT_SEED);

export const mockGestaoApi: GestaoDataSource = {
  async listRows(entity) {
    await delay();
    return Array.from(db[entity].values()).map((r) => ({ ...r }));
  },
  async getUsers() {
    await delay(120);
    return USERS.map((u) => ({ ...u }));
  },
  async listStatus(entity, id) {
    await delay(150);
    return (statusDb[entity].get(id) ?? []).map((e) => ({ ...e }));
  },
  async addStatus(entity, id, autor, texto) {
    await delay(300);
    const row = db[entity].get(id);
    if (!row) throw new Error(`registro não encontrado: ${id}`);
    // `data` em UTC sem sufixo, igual ao que o backend grava (current_timestamp() do
    // warehouse) — a exibição converte p/ SP em fmtTsBR. Mock e real precisam casar.
    const entry: StatusEntry = { id: `st${++seq}`, autor, data: new Date().toISOString().slice(0, 19), texto };
    statusDb[entity].set(id, [entry, ...(statusDb[entity].get(id) ?? [])]);
    row.resumoStatus = texto;
    row.resumoStatusData = entry.data;
    return { ...entry };
  },
  async setDates(entity, id, patch) {
    await delay(200);
    const row = db[entity].get(id);
    if (!row) throw new Error(`registro não encontrado: ${id}`);
    if ("inicio" in patch) row.inicioMigracao = patch.inicio ?? null;
    if ("fim" in patch) row.fimMigracao = patch.fim ?? null;
    if ("fimConversao" in patch) row.fimConversao = patch.fimConversao ?? null;
  },
  async setBV(entity, id, comBv, data) {
    await delay(200);
    const row = db[entity].get(id);
    if (!row) throw new Error(`registro não encontrado: ${id}`);
    const dia = data ?? hojeSP();
    const ev: BVEvento = { id: `bv${++seq}`, comBv, data: dia, autor: "lucas.muller@indicium.tech" };
    const list = [...(bvDb[entity].get(id) ?? []), ev].sort((a, b) => (a.data < b.data ? -1 : 1));
    bvDb[entity].set(id, list);
    row.bvEventos = list.map((e) => ({ ...e }));
  },
  async deleteBV(id) {
    await delay(150);
    for (const entity of ["egp", "input"] as EntityType[]) {
      for (const [rid, list] of bvDb[entity]) {
        const next = list.filter((e) => e.id !== id);
        if (next.length !== list.length) {
          bvDb[entity].set(rid, next);
          const row = db[entity].get(rid);
          if (row) row.bvEventos = next.map((e) => ({ ...e }));
        }
      }
    }
  },
  async ajustaRevisao(id, delta) {
    await delay(150);
    const row = db.egp.get(id);
    if (!row) throw new Error(`registro não encontrado: ${id}`);
    row.revisoesRegras = Math.max(0, (row.revisoesRegras ?? 0) + delta);
  },
  async getHolidays(year) {
    await delay(50);
    return FERIADOS_BR.filter((d) => d.startsWith(String(year)));
  },
};

export { hojeSP };
export const gestaoApi: GestaoDataSource = deltaGestaoApi; // produção; mockGestaoApi p/ dev sem warehouse
