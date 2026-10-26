// Gestão de EGPs / Gestão de Inputs — UM componente parametrizado por entityType,
// alternado pelo switch do header (layout e regras idênticos nas duas variantes).
// Vive no TOPO da aba Gestão (bv_users); a gestão de analistas segue abaixo.
// Dados REAIS via gestaoApi = deltaGestaoApi (endpoints /api/gestao/*, Delta).
import { useMemo, useState, type ReactNode } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { gestaoApi, hojeSP, comBvAtual, usuariosGestao, type EntityType, type GestaoRow } from "../gestaoApi";
import { diasUteis, diasEmValidacaoBV, fmtBR } from "../diasUteis";
import { MultiSelect } from "./MultiSelect";
import { RangeFilter } from "./RangeFilter";
import { useTableSort } from "../useTableSort";
import { GestaoStatusPanel } from "./GestaoStatusPanel";
import {
  GestaoKanban, buildKanbanColunas, pctPassaFiltro, respBvOf, PCT_CATEGORIAS, PCT_CATEGORIA_LABEL,
  DateEditPopup, type PctCategoria, type DateCampo, type DateEdit,
} from "./GestaoKanban";
import { preworkingPercentual } from "../inputs";
import { api } from "../api";
import { mesTag, useMesPlan } from "../mesPlan";
import { STATUS_PROJETO } from "../pipeline";
import { useSubareas } from "../useSubareas";
import { subareasDe, ordenarSubareas } from "../subareas";
import { usePodeEscrever } from "../usePodeEscrever";

// Concluído p/ o GRÁFICO: EGP = migrado/despriorizado (removido/despriorizado SEMPRE
// contam — esforço entregue mesmo se descartado). Input = etapa Modernizado OU status
// Sanitizado/Autoprodutor (mesma régua de _modern() no backend — sanitizado é esforço
// entregue mesmo sem migrar, autoprodutor é entregue via produção interna do próprio EGP).
const isConcluido = (r: GestaoRow, entity: EntityType): boolean => {
  if (entity === "input") return r.etapa === "Modernizado" || r.status === "Sanitizado" || r.status === "Autoprodutor";
  const e = (r.etapa ?? "").toLowerCase();
  return e === "migrado" || e.includes("removido") || e.includes("despriorizado");
};

// Rótulos por variante: EGP fala em "Migração"; Input fala em "Ingestão". `DateCampo`/
// `DateEdit`/`DateEditPopup` moraram aqui antes de 2026-09; movidos p/ GestaoKanban.tsx
// (módulo compartilhado que os dois arquivos já importam) quando EgpsAtualizadosKanban.tsx
// passou a precisar deles também — reusar por import direto criaria ciclo (este arquivo
// importa EgpsAtualizadosKanban).
const campoLabel = (entity: EntityType, campo: DateCampo): string => ({
  inicio: entity === "egp" ? "Início Migração" : "Início Ingestão",
  fimConversao: "Fim Conversão",
  fim: entity === "egp" ? "Fim Migração" : "Fim Ingestão",
}[campo]);

const MES_ABREV = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"];

// Ordenação: accessor ESTÁVEL (fora do componente, exigência do useTableSort).
// Datas ISO ordenam como string; dias úteis ordena pelo valor calculado (HOJE fixado
// no load da página); responsável ordena pelo email (a célula exibe o nome).
type GestaoSortKey =
  | "nome" | "area" | "responsavel" | "etapa"
  | "inicio" | "fimConversao" | "fim" | "dias" | "comBv" | "diasBV" | "status";
const HOJE_SORT = hojeSP();

// barra do gráfico vertical; sub = parte "concluída" (segmento verde dentro do total);
// parts = N barras lado-a-lado dentro do grupo (1 cor por índice, via `legend` do VChart —
// usado só no gráfico semanal de inputs).
interface VBar { label: string; n: number; sub?: number; parts?: number[]; partial?: boolean }
const gestaoAccessor = (r: GestaoRow, k: GestaoSortKey): string | number | null | undefined => {
  switch (k) {
    case "nome": return r.nome;
    case "area": return r.area;
    case "responsavel": return r.responsavel;
    case "etapa": return r.etapa;
    case "inicio": return r.inicioMigracao;
    case "fimConversao": return r.fimConversao;
    case "fim": return r.fimMigracao;
    case "dias": return diasUteis(r.inicioMigracao, r.fimMigracao ?? HOJE_SORT);
    case "comBv": return comBvAtual(r) ? 1 : 0;
    case "diasBV": return diasEmValidacaoBV(r.bvEventos, HOJE_SORT);
    case "status": return r.resumoStatus;
    default: return undefined;
  }
};

export function GestaoMigracao() {
  const qc = useQueryClient();
  const pode = usePodeEscrever();
  const [entity, setEntity] = useState<EntityType>("egp");
  const [busca, setBusca] = useState("");
  const [etapasSel, setEtapasSel] = useState<Set<string>>(new Set());
  const [respsSel, setRespsSel] = useState<Set<string>>(new Set());
  // Responsável do lado BV (campo livre responsavel_bv, editado na aba EGPs) — herdado dos
  // EGPs consumidores na variante Input, mesmo padrão de mesesSel/statusSel abaixo. Mesma
  // fonte do filtro já existente no Acompanhamento (ver respBvOf em GestaoKanban.tsx).
  const [respsBvSel, setRespsBvSel] = useState<Set<string>>(new Set());
  const [subareasSel, setSubareasSel] = useState<Set<string>>(new Set());
  const [mesesSel, setMesesSel] = useState<Set<string>>(new Set());
  const [statusSel, setStatusSel] = useState<Set<string>>(new Set());
  // Quais colunas (etapas) do Kanban aparecem — só tem efeito em view="kanban"; chaves de
  // GestaoKanban.buildKanbanColunas(entity), específicas por variante.
  const [colunasKanbanSel, setColunasKanbanSel] = useState<Set<string>>(new Set());
  // Faixa [min,max] do indicador de prontidão (EGP: composto ou 1 categoria) / checklist
  // (Input) — um valor de corte fixo é ruim, a faixa deixa o usuário escolher o que é
  // "pronto o suficiente".
  const [pctRange, setPctRange] = useState<[number, number] | null>(null);
  // Categorias do indicador de prontidão (só EGP) selecionadas no filtro: vazio = Completo
  // (composto de sempre, 1/3 cada). 1+ selecionadas: o FILTRO (RangeFilter acima) exige TODAS
  // dentro da faixa — E lógico (pedido 2026-08: "falta tanto preworking quanto inputs" = as
  // duas simultaneamente); já o % exibido no card do Kanban é a MÉDIA entre as escolhidas
  // (não o mínimo — pré-working é binário 0/100 e travava tudo em 0%, ver pctCard).
  const [pctCategoriasSel, setPctCategoriasSel] = useState<Set<PctCategoria>>(new Set());
  // por padrão a aba mostra SÓ quem tem responsável (senão a lista fica gigante —
  // pedido 2026-07); o checkbox inclui os sem responsável quando preciso.
  const [soComResp, setSoComResp] = useState(true);
  // só EGPs com Fim Conversão preenchido (sas_gestao_datas). Aparece só na variante EGP;
  // p/ Input não faz sentido (só o funil migração tem "Conversão do Código").
  const [convOnly, setConvOnly] = useState(false);
  // só EGPs onde 100% do que falta já está em PDI+GMUD/Ingestão PRD (ver
  // desbloqueia_remessa em ReadinessRow/ReadinessView) — mesmo filtro da aba EGPs,
  // reusado aqui pra achar rápido quem fica pronto quando a remessa em trânsito completar.
  const [remessaOnly, setRemessaOnly] = useState(false);
  // Só variante input: o board mistura inputs reais e outputs de carga fria (cards sintéticos).
  const [tipoSel, setTipoSel] = useState<"ambos" | "inputs" | "outputs">("ambos");
  const [panelId, setPanelId] = useState<string | null>(null);
  const [dateEdit, setDateEdit] = useState<DateEdit | null>(null);
  // Tabela/Kanban existe nas 2 variantes — cada uma com seu próprio funil de colunas
  // (GestaoKanban.buildKanbanColunas por entity).
  const [view, setView] = useState<"tabela" | "kanban">("tabela");

  const rowsQ = useQuery({ queryKey: ["gestao", entity], queryFn: () => gestaoApi.listRows(entity) });
  const usersQ = useQuery({ queryKey: ["analistas"], queryFn: () => api.analistas(), select: usuariosGestao });
  // Série semanal "Sanitizados/Modernizados (BV)/Recebidos" — só na variante Input. 3
  // colunas mutuamente exclusivas por semana (prioridade sanitizado > BV > recebido), 1×
  // cada input. Ver /api/inputs-recebidos-serie.
  const recebidosQ = useQuery({
    queryKey: ["inputs-recebidos-serie"],
    queryFn: () => fetch("api/inputs-recebidos-serie").then((r) => r.json() as Promise<{
      rows: { dia: string; sanitizados: number; modernizados_bv: number; recebidos: number }[];
      kickoff: string; sem_categoria: number; universo_total: number;
    }>),
    enabled: entity === "input",
  });
  // Mês do plano de priorização (M1, M2…) e status do funil (aba EGPs) — o input HERDA
  // ambos dos EGPs consumidores (r.egps; na variante egp r.egps = [id], então a regra é
  // uma só). Mesmas query keys das outras abas => cache compartilhado, sem custo extra.
  const { mesOf, meses } = useMesPlan();
  const readinessQ = useQuery({
    queryKey: ["egp-readiness", "base"],
    queryFn: () => api.egpReadiness("base"),
    staleTime: 5 * 60 * 1000,
  });
  // map completo (projeto -> ReadinessRow); statusOf deriva dele. O Kanban usa o map
  // inteiro (também precisa de n_inputs/n_disp/n_outputs/n_outputs_disp por EGP).
  const readinessMap = useMemo(
    () => new Map((readinessQ.data?.rows ?? []).map((r) => [r.projeto, r])),
    [readinessQ.data]);
  // Checklist de pré-working — só a variante Input usa (indicador de prontidão do Kanban de
  // Input, análogo à prontidão composta do EGP). Mesma queryKey ["preworking"] de
  // InputDetailPanel/InputsTable — cache compartilhado, react-query dedupa.
  const preworkingQ = useQuery({
    queryKey: ["preworking"],
    queryFn: () => api.preworkingRows(),
    enabled: entity === "input",
  });
  const preworkingMap = useMemo(
    () => new Map((preworkingQ.data?.rows ?? []).map((r) => [r.chave_canonica, r])),
    [preworkingQ.data]);
  const statusOf = useMemo(
    () => new Map(Array.from(readinessMap, ([k, v]) => [k, v.status])),
    [readinessMap]);
  const rows = rowsQ.data ?? [];
  const users = usersQ.data ?? [];
  const nomeDe = (email: string | null) =>
    email ? (users.find((u) => u.email === email)?.nome ?? email.split("@")[0]) : "—";

  // opções derivadas dos dados (acompanham o vocabulário real; nada hardcoded).
  // etapa: valores distintos presentes; responsável: emails distintos (exibidos como nome).
  const etapaOptions = useMemo(
    () => Array.from(new Set(rows.map((r) => r.etapa).filter((e): e is string => !!e))).sort(),
    [rows]);
  const respOptions = useMemo(
    () => Array.from(new Set(rows.map((r) => r.responsavel).filter((e): e is string => !!e))).sort(),
    [rows]);
  const respLabels = useMemo(
    () => Object.fromEntries(respOptions.map((email) => [email, nomeDe(email)])),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [respOptions, users]);
  // Responsável BV: texto livre (não é email da lista de analistas), por isso sem respLabels.
  const respBvOptions = useMemo(() => {
    const s = new Set<string>();
    for (const r of rows) for (const bv of respBvOf(r, entity, readinessMap)) s.add(bv);
    return Array.from(s).sort((a, b) => a.localeCompare(b, "pt-BR"));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [rows, readinessMap, entity]);
  // Sub-área BV: derivada do Responsável BV pelo cadastro (Gestão → Responsáveis BV).
  // Multi-valorada na variante "input" — herda de todos os EGPs consumidores.
  const { mapa: mapaSub } = useSubareas();
  const subareasDaLinha = useMemo(
    () => (r: GestaoRow) => subareasDe(respBvOf(r, entity, readinessMap), mapaSub),
    [mapaSub, entity, readinessMap]);
  const subareaOptions = useMemo(
    () => ordenarSubareas(rows.flatMap(subareasDaLinha)), [rows, subareasDaLinha]);
  // mês: opções = meses do plano (mesmo vocabulário da aba EGPs); linha fora do plano ("—")
  // só some quando há seleção. status: distintos presentes nos EGPs das linhas, na ordem
  // canônica do funil (STATUS_PROJETO).
  const mesOptions = useMemo(() => meses.map((n) => mesTag(n)), [meses]);
  const statusOptions = useMemo(() => {
    const s = new Set<string>();
    for (const r of rows) for (const e of r.egps) {
      const st = statusOf.get(e);
      if (st) s.add(st);
    }
    return Array.from(s).sort((a, b) => STATUS_PROJETO.indexOf(a) - STATUS_PROJETO.indexOf(b));
  }, [rows, statusOf]);

  // colunas do funil da variante ativa — fonte das opções do filtro "Etapas do Kanban".
  const colunasKanban = useMemo(() => buildKanbanColunas(entity), [entity]);

  const filtered = useMemo(() => {
    const t = busca.trim().toLowerCase();
    return rows.filter((r) => {
      if (soComResp && !r.responsavel) return false;
      if (entity === "input" && tipoSel !== "ambos" && !!r.cargaFria !== (tipoSel === "outputs")) return false;
      if (convOnly && entity === "egp" && !r.fimConversao) return false;
      if (remessaOnly) {
        // herdado dos EGPs consumidores na variante input (n:n) — passa se QUALQUER um bate,
        // mesmo padrão de mesesSel/statusSel acima.
        const bate = entity === "egp"
          ? !!readinessMap.get(r.id)?.desbloqueia_remessa
          : r.egps.some((e) => readinessMap.get(e)?.desbloqueia_remessa);
        if (!bate) return false;
      }
      if (t && !(`${r.nome} ${r.id}`.toLowerCase().includes(t))) return false;
      if (etapasSel.size && !(r.etapa && etapasSel.has(r.etapa))) return false;
      if (respsSel.size && !(r.responsavel && respsSel.has(r.responsavel))) return false;
      if (respsBvSel.size && !respBvOf(r, entity, readinessMap).some((bv) => respsBvSel.has(bv))) return false;
      if (subareasSel.size && !subareasDaLinha(r).some((s) => subareasSel.has(s))) return false;
      // herdados dos EGPs consumidores (n:n na variante input) — passa se QUALQUER um bate
      if (mesesSel.size && !r.egps.some((e) => mesesSel.has(mesTag(mesOf.get(e))))) return false;
      if (statusSel.size && !r.egps.some((e) => {
        const st = statusOf.get(e);
        return !!st && statusSel.has(st);
      })) return false;
      if (pctRange) {
        if (entity === "egp") {
          if (!pctPassaFiltro(readinessMap.get(r.id), pctCategoriasSel, pctRange)) return false;
        } else {
          const p = preworkingPercentual(preworkingMap.get(r.id));
          if (p < pctRange[0] || p > pctRange[1]) return false;
        }
      }
      return true;
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [rows, busca, etapasSel, respsSel, respsBvSel, subareasSel, subareasDaLinha, mesesSel, statusSel,
    pctRange, pctCategoriasSel, mesOf, statusOf, readinessMap, preworkingMap, soComResp, convOnly,
    remessaOnly, tipoSel, entity]);

  const { sorted, onSort, indicator } = useTableSort<GestaoRow, GestaoSortKey>(
    filtered, gestaoAccessor, { key: "nome", dir: "asc" });

  const comResp = filtered.filter((r) => r.responsavel).length;
  // convertido = Fim Conversão preenchido (só faz sentido na variante EGP);
  // migrado/modernizado = etapa terminal exata (removido/despriorizado NÃO contam aqui)
  const nConvertidos = filtered.filter((r) => r.fimConversao).length;
  const nMigrados = filtered.filter((r) => isConcluido(r, entity)).length;
  const hoje = hojeSP();

  const setDates = useMutation({
    mutationFn: (v: { id: string; patch: { inicio?: string | null; fim?: string | null } }) =>
      gestaoApi.setDates(entity, v.id, v.patch),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["gestao", entity] }); setDateEdit(null); },
  });

  // Optimista (espelha o patchMut do MonitorView): a UI reflete o toggle na hora — anexa um
  // evento sintético ao bvEventos da linha no cache — e reconcilia com o refetch no onSettled.
  // Sem `disabled`, então o switch continua clicável (append-only: cliques rápidos são benignos).
  const setBV = useMutation({
    mutationFn: (v: { id: string; comBv: boolean }) => gestaoApi.setBV(entity, v.id, v.comBv),
    onMutate: async (v) => {
      await qc.cancelQueries({ queryKey: ["gestao", entity] });
      const prev = qc.getQueryData<GestaoRow[]>(["gestao", entity]);
      qc.setQueryData<GestaoRow[]>(["gestao", entity], (old) =>
        old?.map((r) => (r.id === v.id
          ? { ...r, bvEventos: [...r.bvEventos, { id: `optimistic-${v.id}`, comBv: v.comBv, data: hojeSP(), autor: null }] }
          : r)));
      return { prev };
    },
    onError: (_e, _v, ctx) => { if (ctx?.prev) qc.setQueryData(["gestao", entity], ctx.prev); },
    onSettled: () => qc.invalidateQueries({ queryKey: ["gestao", entity] }),
  });

  // gráficos (respeitam filtros + switch): concluídos por responsável e por mês de Fim
  // ATRIBUÍDOS por colaborador (balanceamento da distribuição do time — pedido 2026-07):
  // altura = total atribuído, independente de status; segmento verde = já concluídos.
  const chartUsers = useMemo<VBar[]>(() => {
    const por = new Map<string, { n: number; sub: number }>();
    for (const r of filtered) {
      if (!r.responsavel) continue;
      const e = por.get(r.responsavel) ?? { n: 0, sub: 0 };
      e.n += 1;
      if (isConcluido(r, entity)) e.sub += 1;
      por.set(r.responsavel, e);
    }
    return Array.from(por.entries()).sort((a, b) => b[1].n - a[1].n)
      .map(([email, v]) => ({ label: nomeDe(email), n: v.n, sub: v.sub }));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filtered, users, entity]);
  const porMesDe = (get: (r: GestaoRow) => string | null, only?: (r: GestaoRow) => boolean) => {
    const por = new Map<string, number>();
    let semData = 0;
    for (const r of filtered) {
      if (only && !only(r)) continue;
      const d = get(r);
      if (!d) { semData++; continue; }
      const ym = d.slice(0, 7); // YYYY-MM
      por.set(ym, (por.get(ym) ?? 0) + 1);
    }
    const bars = Array.from(por.entries()).sort((a, b) => (a[0] < b[0] ? -1 : 1))
      .map(([ym, n]) => ({ label: `${MES_ABREV[Number(ym.slice(5, 7)) - 1]}/${ym.slice(2, 4)}`, n }));
    // "s/ data" só faz sentido com `only` (chartMeses = concluídos): fecha o gap entre a soma
    // do gráfico e o total concluído — inputs/EGPs marcados como migrado/modernizado sem data
    // de Fim preenchida caem aqui. Some quando zero p/ não poluir os gráficos saudáveis.
    if (only && semData > 0) bars.unshift({ label: "s/ data", n: semData });
    return bars;
  };
  // migrações/ingestões por mês de Fim (concluídos) · conversões por mês de Fim Conversão
  const chartMeses = useMemo<VBar[]>(
    () => porMesDe((r) => r.fimMigracao, (r) => isConcluido(r, entity)),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [filtered, entity]);
  const chartConv = useMemo<VBar[]>(
    () => porMesDe((r) => r.fimConversao),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [filtered]);
  // "Sanitizados/Modernizados (BV)/Recebidos" — barra "pré" (baseline antes do kick-off)
  // + 1 trio de barras por semana (Ter→Seg) desde o kick-off, mutuamente exclusivas
  // (parts[0]=sanitizados, parts[1]=modernizados_bv, parts[2]=recebidos). Última barra =
  // semana em curso, marcada `partial` p/ fill dessaturado. NÃO respeita filtros da tabela.
  const chartRecebidos = useMemo<VBar[]>(() => {
    const src = recebidosQ.data?.rows ?? [];
    return src.map((r, i) => ({
      label: r.dia === "pre" ? "pré" : `${r.dia.slice(8, 10)}/${r.dia.slice(5, 7)}`,
      n: r.sanitizados + r.modernizados_bv + r.recebidos,
      parts: [r.sanitizados, r.modernizados_bv, r.recebidos],
      partial: r.dia !== "pre" && i === src.length - 1,
    }));
  }, [recebidosQ.data]);

  const rotulo = entity === "egp" ? "EGPs" : "Inputs";
  const panelRow = panelId ? rows.find((r) => r.id === panelId) ?? null : null;

  // Navegação cruzada EGP<->Input a partir do painel de status (GestaoStatusPanel):
  // "Usado por" no Input abre o EGP consumidor (onOpenEgp); "Inputs" no EGP abre o input
  // (onOpenInput) — pedido cliente BV 2026-08. Troca de entity + força Kanban (a lista de
  // pendência/o botão só existem lá) + já abre o card do alvo, com o MESMO reset de filtros
  // do switch manual abaixo — senão o alvo pode nem aparecer no recorte filtrado atual.
  const jumpTo = (targetEntity: EntityType, id: string) => {
    setEntity(targetEntity); setEtapasSel(new Set()); setRespsSel(new Set());
    setMesesSel(new Set()); setStatusSel(new Set());
    setColunasKanbanSel(new Set()); setPctRange(null); setPctCategoriasSel(new Set());
    setView("kanban"); setPanelId(id);
  };

  return (
    <div className="gm">
      {/* 1. Header: título dinâmico + switch + KPI */}
      <div className="gm-head">
        <h3>Gestão de {rotulo}</h3>
        <div className="gm-switch" role="tablist" aria-label="Alternar EGP/Input">
          {(["egp", "input"] as EntityType[]).map((e) => (
            <button key={e} className={entity === e ? "on" : ""}
              onClick={() => {
                setEntity(e); setEtapasSel(new Set()); setRespsSel(new Set()); setRespsBvSel(new Set());
                setMesesSel(new Set()); setStatusSel(new Set());
                setColunasKanbanSel(new Set()); setPctRange(null); setPctCategoriasSel(new Set()); setPanelId(null);
              }}>
              {e === "egp" ? "EGPs" : "Inputs"}
            </button>
          ))}
        </div>
          <div className="gm-switch" role="tablist" aria-label="Alternar Tabela/Kanban">
            {(["tabela", "kanban"] as const).map((v) => (
              <button key={v} className={view === v ? "on" : ""} onClick={() => setView(v)}>
                {v === "tabela" ? "Tabela" : "Kanban"}
              </button>
            ))}
          </div>
          <div className="gm-kpis">
            <div className="card gm-kpi" title="Linhas com responsável preenchido, respeitando os filtros ativos">
              <div className="card-value">{rowsQ.isFetching && !rowsQ.data ? "…" : comResp}</div>
              <div className="card-label">Total {rotulo} com responsáveis</div>
            </div>
            {entity === "egp" && (
              <div className="card gm-kpi" title="EGPs com Fim Conversão preenchido, respeitando os filtros ativos">
                <div className="card-value">{rowsQ.isFetching && !rowsQ.data ? "…" : nConvertidos}</div>
                <div className="card-label">Total EGPs Convertidos</div>
              </div>
            )}
            <div className="card gm-kpi"
              title={entity === "egp"
                ? 'Etapa "Migrado" (ou "Despriorizado e Contabilizado"), respeitando os filtros ativos'
                : 'Etapa "Modernizado" ou status "Sanitizado", respeitando os filtros ativos'}>
              <div className="card-value">{rowsQ.isFetching && !rowsQ.data ? "…" : nMigrados}</div>
              <div className="card-label">Total {rotulo} {entity === "egp" ? "Migrados" : "Modernizados"}</div>
            </div>
          </div>
      </div>

      {/* 2. Filtros */}
      <div className="filters">
        <input type="search" placeholder="filtrar por nome do projeto…" value={busca}
          onChange={(e) => setBusca(e.target.value)} />
        <MultiSelect label="Etapa" options={etapaOptions} sel={etapasSel}
          onToggle={(v) => setEtapasSel((p) => { const n = new Set(p); n.has(v) ? n.delete(v) : n.add(v); return n; })}
          onClear={() => setEtapasSel(new Set())} />
        <MultiSelect label="Mês" options={mesOptions} sel={mesesSel}
          title={entity === "egp"
            ? "Mês do plano de priorização (mesmo da aba EGPs). EGP fora do plano some quando há seleção."
            : "Mês do plano dos EGPs consumidores — o input aparece se QUALQUER consumidor cai no mês selecionado."}
          onToggle={(v) => setMesesSel((p) => { const n = new Set(p); n.has(v) ? n.delete(v) : n.add(v); return n; })}
          onClear={() => setMesesSel(new Set())} />
        <MultiSelect label="Status" options={statusOptions} sel={statusSel}
          title={entity === "egp"
            ? "Status do funil (mesmo da aba EGPs): A Iniciar, Em Andamento, Concluído…"
            : "Status do funil dos EGPs consumidores — o input aparece se QUALQUER consumidor tem o status selecionado."}
          onToggle={(v) => setStatusSel((p) => { const n = new Set(p); n.has(v) ? n.delete(v) : n.add(v); return n; })}
          onClear={() => setStatusSel(new Set())} />
        <MultiSelect label="Responsável" options={respOptions} sel={respsSel} labels={respLabels}
          onToggle={(v) => setRespsSel((p) => { const n = new Set(p); n.has(v) ? n.delete(v) : n.add(v); return n; })}
          onClear={() => setRespsSel(new Set())} />
        <MultiSelect label="Responsável BV" options={respBvOptions} sel={respsBvSel}
          title={entity === "egp"
            ? "Responsável pelo lado BV (texto livre, editado na aba EGPs)."
            : "Responsável BV dos EGPs consumidores — o input aparece se QUALQUER consumidor tiver o responsável selecionado."}
          onToggle={(v) => setRespsBvSel((p) => { const n = new Set(p); n.has(v) ? n.delete(v) : n.add(v); return n; })}
          onClear={() => setRespsBvSel(new Set())} />
        <MultiSelect label="Sub-área BV" options={subareaOptions} sel={subareasSel}
          title={entity === "egp"
            ? "Área interna do BV do responsável (cadastro em Gestão → Responsáveis BV, no topo desta aba)."
            : "Sub-área dos EGPs consumidores — o input aparece se QUALQUER consumidor for da sub-área selecionada."}
          onToggle={(v) => setSubareasSel((p) => { const n = new Set(p); n.has(v) ? n.delete(v) : n.add(v); return n; })}
          onClear={() => setSubareasSel(new Set())} />
        {entity === "egp" && (
          <MultiSelect label="Categoria de prontidão" options={PCT_CATEGORIAS} sel={pctCategoriasSel}
            labels={PCT_CATEGORIA_LABEL}
            title="Em qual(is) pedaço(s) da prontidão olhar. Nenhuma selecionada = Completo (média de inputs/outputs/pré-working). Selecionando 1+, a faixa ao lado só deixa passar quem tem TODAS elas dentro do intervalo (ex.: Inputs + Pré-working na faixa 0–99% = falta em AMBAS, não a média das duas) — e o % do card do Kanban passa a ser a média entre as categorias escolhidas."
            onToggle={(v) => setPctCategoriasSel((p) => {
              const c = v as PctCategoria;
              const n = new Set(p);
              n.has(c) ? n.delete(c) : n.add(c);
              return n;
            })}
            onClear={() => setPctCategoriasSel(new Set())} />
        )}
        <RangeFilter
          label={entity === "egp"
            ? pctCategoriasSel.size === 0 ? "Prontidão" : `Prontidão (${Array.from(pctCategoriasSel).map((c) => PCT_CATEGORIA_LABEL[c]).join(" + ")})`
            : "Checklist"}
          min={0} max={100} value={pctRange} onChange={setPctRange}
          title={entity === "egp"
            ? pctCategoriasSel.size === 0
              ? "Faixa do indicador de prontidão geral (média de inputs/outputs/pré-working)."
              : pctCategoriasSel.size === 1
                ? `Faixa do indicador de prontidão, olhando só a categoria ${PCT_CATEGORIA_LABEL[Array.from(pctCategoriasSel)[0]]}.`
                : `Faixa do indicador de prontidão — só passa quem tem TODAS as categorias selecionadas (${Array.from(pctCategoriasSel).map((c) => PCT_CATEGORIA_LABEL[c]).join(", ")}) dentro dela.`
            : "Faixa do indicador de checklist de pré-working."} />
        {view === "kanban" && (
          <MultiSelect label="Etapas do Kanban" options={colunasKanban.map((c) => c.key)} sel={colunasKanbanSel}
            labels={Object.fromEntries(colunasKanban.map((c) => [c.key, c.label]))}
            title="Quais colunas (etapas) aparecem no Kanban abaixo — não afeta a tabela."
            onToggle={(v) => setColunasKanbanSel((p) => { const n = new Set(p); n.has(v) ? n.delete(v) : n.add(v); return n; })}
            onClear={() => setColunasKanbanSel(new Set())} />
        )}
        {entity === "input" && (
          <label style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 12 }}
            title="Inputs reais, outputs de carga fria (cards ❄) ou ambos.">
            Tipo
            <select value={tipoSel} onChange={(e) => setTipoSel(e.target.value as typeof tipoSel)}>
              <option value="ambos">Inputs e outputs</option>
              <option value="inputs">Apenas inputs</option>
              <option value="outputs">Apenas outputs (carga fria)</option>
            </select>
          </label>
        )}
        <label style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 12, cursor: "pointer" }}
          title="Ligado: mostra só linhas com responsável atribuído (a atribuição é feita nas abas Inputs/EGPs). Desligue para ver tudo.">
          <input type="checkbox" checked={soComResp}
            onChange={(e) => setSoComResp(e.target.checked)} />
          só com responsável
        </label>
        {entity === "egp" && (
          <label style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 12, cursor: "pointer" }}
            title="Ligado: mostra só EGPs com Fim Conversão preenchido — presença da data marca como convertido (inclui pré-conversões fora do funil).">
            <input type="checkbox" checked={convOnly}
              onChange={(e) => setConvOnly(e.target.checked)} />
            só convertidos
          </label>
        )}
        <label style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 12, cursor: "pointer" }}
          title={entity === "egp"
            ? "Ligado: mostra só EGPs onde 100% do que falta já está em PDI+GMUD ou Ingestão PRD — ficariam prontos se essa remessa em trânsito completasse (virasse Modernizado)."
            : "Ligado: mostra só inputs de EGPs onde 100% do que falta já está em PDI+GMUD ou Ingestão PRD (herdado do(s) EGP(s) consumidor(es))."}>
          <input type="checkbox" checked={remessaOnly}
            onChange={(e) => setRemessaOnly(e.target.checked)} />
          🚚 desbloqueia c/ remessa PDI+GMUD/PRD
        </label>
        <span className="count">{rowsQ.isFetching ? "carregando…" : `${filtered.length} de ${rows.length}`}</span>
      </div>

      {/* 3. Gráficos (barras VERTICAIS): concluídos por colaborador + migrações por mês */}
      <div className="gm-charts">
        <VChart
          title={`${rotulo} atribuídos por colaborador`}
          hint="Total ATRIBUÍDO a cada responsável (independente do status) — p/ ver o balanceamento da distribuição do time. O segmento verde é a parte já concluída (migrado/modernizado; removido/despriorizado sempre contam). Respeita filtros e o switch."
          loading={rowsQ.isFetching && !rowsQ.data}
          empty="Nenhum responsável no recorte atual."
          data={chartUsers}
        />
        {entity === "egp" && (
          <VChart
            title="EGPs convertidos por mês"
            hint="EGPs por mês de Fim Conversão. Respeita filtros."
            loading={rowsQ.isFetching && !rowsQ.data}
            empty="Nenhuma conversão concluída no recorte atual."
            data={chartConv}
            cor="amber"
          />
        )}
        <VChart
          title={entity === "egp" ? "Migrações por mês" : "Ingestões por mês"}
          hint={`Concluídos por mês de ${campoLabel(entity, "fim")}. Respeita filtros e o switch.`}
          loading={rowsQ.isFetching && !rowsQ.data}
          empty="Nada concluído no recorte atual."
          data={chartMeses}
          cor="indigo"
        />
        {entity === "input" && (
          <VChart
            title="Inputs sanitizados/modernizados (BV)/recebidos por semana"
            hint="Três colunas por semana (Ter→Seg) desde o kick-off (07/07/2026), MUTUAMENTE EXCLUSIVAS (cada input soma em no máx. 1, por prioridade). Sanitizados = status atual Sanitizado, qualquer etapa (única com lógica de evento válido/reset via audit). Modernizados (BV) = checkbox manual 'modernizado fora da nossa esteira' no checklist de pré-working, datado pelo campo de data ao lado (opcional, sem relação com detecção automática). Recebidos = checkbox 'arquivo recebido' do checklist, excluindo quem já caiu nas 2 colunas acima. Inputs no meio da esteira (Ingestão UAT/PDI+GMUD/Ingestão PRD/Aplicação de Grant) sem nenhuma das 3 flags não aparecem em nenhuma coluna. Última barra = semana em curso (fill dessaturado). Universo indi_deps; NÃO respeita filtros."
            titleHelp="Sanitizados e Modernizados (BV) e Recebidos particionam o universo por prioridade: se o status atual é Sanitizado, conta só em Sanitizados; senão, se o checklist de pré-working tem 'Modernizado pelo BV' marcado, conta só em Modernizados (BV); senão, se tem 'Recebimento do Arquivo' marcado, conta em Recebidos. Sanitizados é datado por audit trail (evento válido = 1º após o último reset p/ 'A Receber'); Modernizados (BV) e Recebidos são datados por um campo de data digitado 1x no checklist, sem lógica de reset."
            loading={recebidosQ.isFetching && !recebidosQ.data}
            empty="Sem dados desde o kick-off."
            data={chartRecebidos}
            cor="indigo"
            legend={[
              { label: "sanitizados", className: "rose", help: "Status atual Sanitizado, qualquer etapa" },
              { label: "modernizados (BV)", className: "amber", help: "Modernizado pelo BV fora da nossa esteira (checklist de pré-working)" },
              { label: "recebidos", className: "indigo", help: "Arquivo recebido (checklist de pré-working), excluindo sanitizados e modernizados (BV)" },
            ]}
            footer={recebidosQ.data && (
              <span title="Etapa entre Ingestão UAT e Aplicação de Grant (ou ainda 'A Receber'), sem nenhuma das 3 flags acima — não tem data p/ virar barra, por isso fica fora do gráfico.">
                {recebidosQ.data.sem_categoria} de {recebidosQ.data.universo_total} inputs ainda sem classificação (fora do gráfico)
              </span>
            )}
          />
        )}
      </div>

      {rowsQ.error && <div className="error">{String(rowsQ.error)}</div>}
      {setDates.isError && <div className="error">Falha ao salvar data: {String(setDates.error)}</div>}

      {/* 4. Tabela principal (ou Kanban — colunas = etapas do funil da variante ativa).
          Coluna FUTURA (não implementar agora): "Responsável Validação BV" — habilitada
          apenas quando etapa === "Validação da Área"; exigirá evidência de validação. */}
      {view === "kanban" ? (
        <GestaoKanban entity={entity} rows={sorted} readiness={readinessMap} preworking={preworkingMap}
          respLabelOf={nomeDe} onOpenCard={setPanelId}
          colunasVisiveis={colunasKanbanSel} pctCategorias={pctCategoriasSel}
          onToggleBV={pode ? (id, comBv) => setBV.mutate({ id, comBv }) : undefined} />
      ) : (
      <div className="rsm-card">
        <table className="rsm-tbl gm-tbl">
          <thead>
            <tr>
              <Th k="comBv" label="Com BV" onSort={onSort} indicator={indicator}
                title="Ligado = a bola está com o BV (em validação). Desligado = conosco. Clique no switch de cada linha p/ alternar; clique aqui p/ ordenar." />
              <Th k="nome" label="Nome do Projeto" onSort={onSort} indicator={indicator} />
              <Th k="area" label="Área" onSort={onSort} indicator={indicator} />
              <Th k="responsavel" label="Responsável" onSort={onSort} indicator={indicator} />
              <Th k="etapa" label="Etapa" onSort={onSort} indicator={indicator} />
              {entity === "input" && <th>Status</th>}
              <Th k="inicio" label={campoLabel(entity, "inicio")} onSort={onSort} indicator={indicator} />
              {entity === "egp" && <Th k="fimConversao" label="Fim Conversão" onSort={onSort} indicator={indicator} />}
              <Th k="fim" label={campoLabel(entity, "fim")} onSort={onSort} indicator={indicator} />
              <Th k="dias" label={<>Dias úteis<br />c/ resp.</>} onSort={onSort} indicator={indicator}
                title={`Dias úteis entre ${campoLabel(entity, "inicio")} e hoje (congela no ${campoLabel(entity, "fim")} quando preenchido). Exclui fins de semana e feriados nacionais BR (lista configurável em diasUteis.ts). Clique para ordenar.`} />
              <Th k="diasBV" label={<>Dias em val.<br />(BV)</>} onSort={onSort} indicator={indicator}
                title="Total de dias úteis que a linha ficou com o BV (soma de todas as entregas). O prazo do BV é 8 dias úteis, fixo entre entregas. Correções ficam no painel lateral (só admin)." />
              <Th k="status" label="Último status" onSort={onSort} indicator={indicator} />
            </tr>
          </thead>
          <tbody>
            {/* teto de renderização: tabela não virtualizada; inputs do escopo passam de 2k */}
            {sorted.slice(0, 800).map((r) => (
              <tr key={r.id}>
                <td>
                  <label className="gm-bv-toggle" title={comBvAtual(r) ? "Com o BV — clique p/ trazer p/ nós" : "Conosco — clique p/ entregar ao BV"}>
                    <input type="checkbox" checked={comBvAtual(r)} disabled={!pode}
                      onChange={(e) => setBV.mutate({ id: r.id, comBv: e.target.checked })} />
                    <span className="gm-bv-track"><span className="gm-bv-thumb" /></span>
                  </label>
                </td>
                <td title={r.id}>
                  <div className="gm-nome">
                    <span className="gm-nome-text">{r.nome}</span>
                    <CopyBtn value={r.nome} label="copiar nome" />
                  </div>
                </td>
                <td>{r.area ?? "—"}</td>
                <td title={r.responsavel ?? ""}>{nomeDe(r.responsavel)}</td>
                <td>{r.etapa ?? "—"}</td>
                {entity === "input" && <td>{r.status ?? "—"}</td>}
                <td>
                  <button className="gm-date" title="Editar (abre confirmação)" disabled={!pode}
                    onClick={() => setDateEdit({ id: r.id, nome: r.nome, campo: "inicio", atual: r.inicioMigracao })}>
                    {fmtBR(r.inicioMigracao)}
                  </button>
                </td>
                {entity === "egp" && (
                  <td>
                    <button className="gm-date" title="Editar (abre confirmação)" disabled={!pode}
                      onClick={() => setDateEdit({ id: r.id, nome: r.nome, campo: "fimConversao", atual: r.fimConversao })}>
                      {fmtBR(r.fimConversao)}
                    </button>
                  </td>
                )}
                <td>
                  <button className="gm-date" title="Editar (abre confirmação)" disabled={!pode}
                    onClick={() => setDateEdit({ id: r.id, nome: r.nome, campo: "fim", atual: r.fimMigracao })}>
                    {fmtBR(r.fimMigracao)}
                  </button>
                </td>
                <td className="gm-num">{diasUteis(r.inicioMigracao, r.fimMigracao ?? hoje) ?? "—"}</td>
                <td className="gm-num">{diasEmValidacaoBV(r.bvEventos, hoje)}</td>
                <td>
                  <button className="gm-resumo" title={r.resumoStatus ?? "sem status — clique para abrir/comentar"}
                    onClick={() => setPanelId(r.id)}>
                    {r.resumoStatus ?? "— sem status —"}
                  </button>
                </td>
              </tr>
            ))}
            {filtered.length > 800 && (
              <tr><td colSpan={11} className="muted">
                mostrando os primeiros 800 de {filtered.length} — refine com os filtros acima
              </td></tr>
            )}
            {rowsQ.isFetching && !rowsQ.data && (
              <tr><td colSpan={11} className="muted">carregando…</td></tr>
            )}
            {!rowsQ.isFetching && filtered.length === 0 && (
              <tr><td colSpan={11} className="muted">Nenhum registro para os filtros atuais.</td></tr>
            )}
          </tbody>
        </table>
      </div>
      )}

      {/* 5. Sidepanel + modal */}
      {panelRow && (
        <GestaoStatusPanel entity={entity} row={panelRow} allRows={rows} users={users}
          onOpenEgp={(p) => jumpTo("egp", p)} onOpenInput={(c) => jumpTo("input", c)}
          onClose={() => setPanelId(null)} />
      )}

      {/* pop-up de edição de data (2 cliques: célula -> confirmar) */}
      {dateEdit && (
        <DateEditPopup edit={dateEdit} titulo={campoLabel(entity, dateEdit.campo)} busy={setDates.isPending}
          onCancel={() => setDateEdit(null)}
          onConfirm={(valor) => setDates.mutate({
            id: dateEdit.id,
            patch: { [dateEdit.campo]: valor },
          })} />
      )}
    </div>
  );
}

// Botão "copiar" que aparece ao lado do nome truncado — usa Clipboard API nativa;
// feedback ✓ por 1.2s. Falha silenciosa se o navegador negar (contexto inseguro).
function CopyBtn({ value, label }: { value: string; label: string }) {
  const [ok, setOk] = useState(false);
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(value);
      setOk(true);
      setTimeout(() => setOk(false), 1200);
    } catch { /* clipboard indisponível — silencioso */ }
  };
  return (
    <button type="button" className={`gm-copy${ok ? " ok" : ""}`} onClick={copy}
      title={ok ? "copiado" : label} aria-label={label}>
      {ok ? (
        <svg width="12" height="12" viewBox="0 0 12 12" aria-hidden>
          <path d="M2.5 6.5 5 9l4.5-5.5" stroke="currentColor" strokeWidth="1.5"
            fill="none" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      ) : (
        <svg width="12" height="12" viewBox="0 0 12 12" aria-hidden>
          <rect x="3.5" y="3.5" width="6" height="7" rx="1" stroke="currentColor"
            strokeWidth="1" fill="none" />
          <path d="M2 8.5V2.5A1 1 0 0 1 3 1.5H7.5" stroke="currentColor"
            strokeWidth="1" fill="none" strokeLinecap="round" />
        </svg>
      )}
    </button>
  );
}

// Cabeçalho ordenável (padrão sort-th das outras grades; ▲/▼ via indicator).
function Th({ k, label, title, onSort, indicator }: {
  k: GestaoSortKey; label: ReactNode; title?: string;
  onSort: (k: GestaoSortKey) => void; indicator: (k: GestaoSortKey) => string;
}) {
  return (
    <th className="sort-th" onClick={() => onSort(k)} title={title ?? "ordenar"}>
      {label}{indicator(k)}
    </th>
  );
}

// Bar chart VERTICAL simples (CSS puro, sem lib — padrão do app). Paleta fixa de "papel"
// porque vive dentro de .rsm-card (cartão branco que independe do tema).
// Modos: [n] simples · [n,sub] stacked (verde dentro) · [parts] N barras lado-a-lado dentro
// do grupo, com `legend` no topo (1 cor por índice) — usado só no gráfico semanal de inputs.
function VChart({ title, hint, titleHelp, data, loading, empty, cor, legend, footer }: {
  title: string; hint: string; titleHelp?: string; data: VBar[];
  loading: boolean; empty: string; cor?: "indigo" | "amber";
  legend?: { label: string; className: string; help?: string }[];
  footer?: ReactNode;
}) {
  // Escala inclui todos os `parts` quando presentes p/ as N colunas compartilharem o eixo Y.
  const max = Math.max(1, ...data.flatMap((d) => d.parts ?? [d.n]));
  // dense: >12 barras aperta labels horizontais — reduzimos o gap e rotacionamos os labels
  // p/ evitar truncamento (ellipsis "0..", "1..") em séries longas (ex.: semanal ao longo do ano).
  const dense = data.length > 12;
  // labels: mostramos ~25 no total (primeira, última e a cada N no meio). Hover mantém o
  // valor exato via title. Escala p/ semanal ao longo de meses sem virar bagunça visual.
  const labelStep = Math.max(1, Math.ceil(data.length / 25));
  return (
    <div className="rsm-card">
      <h4 className="gm-chart-title" title={hint}>
        {title}
        {titleHelp && <span className="help" title={titleHelp}>?</span>}
      </h4>
      {legend && (
        <div className="gm-chart-legend">
          {legend.map((l) => (
            <span key={l.label} className="gm-chart-legend-item">
              <span className={`gm-chart-legend-swatch ${l.className}`} />{l.label}
              {l.help && <span className="help" title={l.help}>?</span>}
            </span>
          ))}
        </div>
      )}
      {loading && <div className="gm-chart-empty">carregando…</div>}
      {!loading && data.length === 0 && <div className="gm-chart-empty">{empty}</div>}
      {data.length > 0 && (
        <div className={`gm-vchart${dense ? " dense" : ""}`}>
          {data.map((d, i) => {
            // n=0 -> coluna vazia (nenhuma altura mínima), preserva o eixo X contínuo p/ séries diárias.
            const hTotal = d.n === 0 ? 0 : Math.max(3, Math.round((82 * d.n) / max));
            const titulo = d.parts && legend
              ? `${d.label}: ` + d.parts.map((v, idx) => `${v} ${legend[idx]?.label ?? ""}`).join(" · ")
              : d.sub !== undefined
                ? `${d.label}: ${d.n} atribuídos · ${d.sub} concluídos`
                : `${d.label}: ${d.n}`;
            const showLabel = i === 0 || i === data.length - 1 || i % labelStep === 0;
            const partialCls = d.partial ? " partial" : "";
            return (
              <div className="gm-vbar" key={d.label} title={titulo}>
                {d.parts !== undefined ? (
                  <div className="gm-vbar-pair">
                    {d.parts.map((v, idx) => {
                      const h = v === 0 ? 0 : Math.max(3, Math.round((82 * v) / max));
                      return (
                        <div className="gm-vbar-pair-col" key={idx} title={`${v} ${legend?.[idx]?.label ?? ""}`}>
                          <span className="gm-vbar-n">{v || ""}</span>
                          <div className={`gm-vbar-fill multi${legend?.[idx] ? ` ${legend[idx].className}` : ""}${partialCls}`}
                            style={{ height: `${h}%` }} />
                        </div>
                      );
                    })}
                  </div>
                ) : d.sub !== undefined ? (
                  <>
                    <span className="gm-vbar-n">{d.n || ""}</span>
                    <div className="gm-vbar-stack" style={{ height: `${hTotal}%` }}>
                      <div className="gm-vbar-fill in-stack"
                        style={{ height: `${d.n > 0 ? Math.round((100 * d.sub) / d.n) : 0}%` }} />
                    </div>
                  </>
                ) : (
                  <>
                    <span className="gm-vbar-n">{d.n || ""}</span>
                    <div className={`gm-vbar-fill${cor ? ` ${cor}` : ""}${partialCls}`} style={{ height: `${hTotal}%` }} />
                  </>
                )}
                {showLabel && <span className="gm-vbar-label" title={d.label}>{d.label}</span>}
              </div>
            );
          })}
        </div>
      )}
      {footer && <div className="gm-chart-footer">{footer}</div>}
    </div>
  );
}

