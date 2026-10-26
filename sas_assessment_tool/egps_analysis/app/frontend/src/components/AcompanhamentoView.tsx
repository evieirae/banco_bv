// Aba "Acompanhamento" — o ÚNICO Kanban que o cliente (BV) vê; a Gestão (com tabela,
// filtros e gráficos) é restrita a bv_users. Aqui:
//   - responsável interno (quem da Indicium executa) OPCIONAL no card — chip "mostrar
//     responsável" (pedido do cliente BV 2026-08), desligado por padrão (comportamento de
//     sempre); disponível pra QUALQUER um que abra a aba, inclusive o próprio cliente —
//     decisão do usuário, não é gated por is_gestao. Liga/desliga junto o campo Responsável
//     no drawer (GestaoStatusPanel.hideResponsavel = !showResp), pra não ficar inconsistente
//     entre card e painel;
//   - switch EGP/Input (mesmo padrão de GestaoMigracao) — cada variante com seu próprio
//     recorte, KPIs e board;
//   - filtros (mesmo padrão visual/comportamento da Gestão, mantidos em paridade — pedido
//     2026-08): Etapas do Kanban (quais colunas aparecem), Responsável BV (quais quadros
//     aparecem), Mês (do plano de priorização — trocou o antigo filtro por Onda, pedido
//     2026-08), "Categoria de prontidão" (só EGP — restringe o indicador a
//     inputs/outputs/pré-working isolados, ou combinações; muda o que a faixa abaixo e o %
//     do card do Kanban consideram, ver pctPassaFiltro/pctCard em GestaoKanban.tsx) e a
//     faixa do indicador de prontidão/checklist — um valor de corte fixo é ruim, a faixa
//     deixa o BV escolher o que é "pronto o suficiente" pra ele. O card do Kanban mostra o
//     mês do plano (showMes/mesOf, M1, M2…) — substituiu o badge de "onda" (2026-09), mesma
//     terminologia já usada no filtro acima;
//   - EGPs despriorizados (status "Despriorizado e Contabilizado") ganham coluna PRÓPRIA no
//     Kanban (separarDespriorizados=true, só nesta tela — pedido do cliente BV 2026-08: eles
//     ficavam indistinguíveis dos migrados normais, misturados na coluna da etapa em que
//     estavam quando saíram do backlog). A mesma noção de coluna alimenta "Etapas do Kanban"
//     acima, então o BV já consegue excluí-los ali, sem controle novo (ver kanbanColKeyOf em
//     GestaoKanban.tsx);
//   - separado por Responsável BV por padrão — cada um com seu próprio quadro Kanban completo,
//     como se fosse uma tela só dele; chip "agrupar por Responsável BV" desliga a separação e
//     mostra tudo num quadro único (o filtro "Responsável BV" continua funcionando, só não
//     quebra em vários boards);
//   - cada quadro RECOLHE no título (▾/▸) + "recolher/expandir todos" — com muitos responsáveis
//     a tela vira uma pilha enorme de Kanbans e ninguém acha o seu (pedido 2026-09). Recolhido,
//     a linha de resumo (nº de EGPs/inputs + média) continua visível e o Kanban nem monta.
//     O estado é PERSISTENTE (localStorage, mesmo espírito do useHeaderCollapse das abas de
//     tabela): quem só cuida do próprio quadro não recolhe os outros toda vez que abre a aba;
//   - só o Kanban + KPIs médios (sem tabela/gráficos, esses ficam na Gestão).
// Clicar no card abre o MESMO drawer de status/comentário de sempre (GestaoStatusPanel), com
// o campo Responsável escondido OU NÃO conforme showResp (ver acima) e TODOS os controles de
// edição desabilitados (readOnly) — Etapa/Status/Responsável, Pré-working+data (do EGP e do
// Input), checklist de pré-working do Input e o recebimento manual de Outputs são só
// visualização aqui; a edição fica exclusiva da Gestão interna. Histórico de comentários e
// "+ Adicionar Comentário" continuam disponíveis (gate é isGestao, não a aba).
import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "../api";
import { gestaoApi, usuariosGestao, type EntityType, type GestaoRow } from "../gestaoApi";
import {
  GestaoKanban, buildKanbanColunas, kanbanColKeyOf, pctBreakdown, pctPassaFiltro, respBvOf, PCT_CATEGORIAS,
  PCT_CATEGORIA_LABEL, type PctCategoria,
} from "./GestaoKanban";
import { GestaoStatusPanel } from "./GestaoStatusPanel";
import { MultiSelect } from "./MultiSelect";
import { RangeFilter } from "./RangeFilter";
import { preworkingPercentual } from "../inputs";
import { mesTag, useMesPlan } from "../mesPlan";
import { useSubareas } from "../useSubareas";
import { subareasDe, ordenarSubareas, SEM_SUBAREA } from "../subareas";

const SEM_RESP_BV = "__sem_resp_bv";
const TODOS = "__todos";
// Quadros recolhidos (chaves = Responsável BV / SEM_RESP_BV). Persistido como no
// useHeaderCollapse: leitura/escrita defensivas — localStorage pode lançar (storage bloqueado).
const COLAPSO_KEY = "acomp-colapsados";
const lerColapsados = (): Set<string> => {
  try {
    const raw = localStorage.getItem(COLAPSO_KEY);
    return new Set(raw ? (JSON.parse(raw) as string[]) : []);
  } catch { return new Set(); }
};
const salvaColapsados = (s: Set<string>) => {
  try { localStorage.setItem(COLAPSO_KEY, JSON.stringify(Array.from(s))); } catch { /* sem storage */ }
  return s;
};
const avg = (vals: number[]) => (vals.length ? Math.round(vals.reduce((a, b) => a + b, 0) / vals.length) : 0);

export function AcompanhamentoView() {
  const [entity, setEntity] = useState<EntityType>("egp");
  const [panelId, setPanelId] = useState<string | null>(null);
  // Filtros — mesmo comportamento/rótulos da Gestão (GestaoMigracao): seleção vazia = todos.
  const [etapasSel, setEtapasSel] = useState<Set<string>>(new Set());
  const [respsBvSel, setRespsBvSel] = useState<Set<string>>(new Set());
  const [subareasSel, setSubareasSel] = useState<Set<string>>(new Set());
  const [mesesSel, setMesesSel] = useState<Set<string>>(new Set());
  const [pctRange, setPctRange] = useState<[number, number] | null>(null);
  // Categorias do indicador de prontidão (só EGP; mesmo comportamento da Gestão — ver
  // GestaoMigracao.tsx/GestaoKanban.tsx): vazio = Completo (composto de sempre, 1/3 cada). 1+
  // selecionadas: a faixa acima exige TODAS dentro dela (E lógico) e o % do card do Kanban
  // vira a MÉDIA entre as escolhidas.
  const [pctCategoriasSel, setPctCategoriasSel] = useState<Set<PctCategoria>>(new Set());
  // Separar em 1 board por Responsável BV (padrão) vs. tudo num quadro único — preferência de
  // VISUALIZAÇÃO, não um filtro (não reseta ao trocar EGP/Input nem limpa seleções).
  // Eixo de agrupamento dos quadros. Um por vez, de propósito: agrupar pelos dois ao mesmo
  // tempo daria quadros aninhados (sub-área > responsável), e as duas dimensões já são
  // multi-valoradas na variante Input — o aninhamento duplicaria linha em dois níveis.
  const [agruparPor, setAgruparPor] = useState<"respbv" | "subarea" | "nenhum">("respbv");
  // Mostrar o Responsável INTERNO (quem da Indicium executa) no card — pedido do cliente BV
  // 2026-08: opcional (padrão desligado, mesmo comportamento de sempre) em vez de escondido
  // sem alternativa; disponível pra QUALQUER um que abra a aba (inclusive o próprio cliente
  // BV — decisão do usuário, não é gated por is_gestao). Preferência de VISUALIZAÇÃO, mesmo
  // espírito de agruparPor: não reseta ao trocar EGP/Input.
  const [showResp, setShowResp] = useState(false);
  // Quais quadros estão recolhidos — preferência de VISUALIZAÇÃO persistente, por Responsável BV
  // (não por entidade: quem cuida de um responsável cuida dos EGPs E dos inputs dele).
  const [colapsados, setColapsados] = useState<Set<string>>(lerColapsados);
  const toggleColapso = (key: string) => setColapsados((p) => {
    const n = new Set(p);
    n.has(key) ? n.delete(key) : n.add(key);
    return salvaColapsados(n);
  });

  // Mês do plano de priorização (M1, M2…) — o input HERDA dos EGPs consumidores (r.egps; na
  // variante egp r.egps = [id]), mesmo padrão "passa se QUALQUER um bate" já usado no
  // Responsável BV. Mesma queryKey/hook da Gestão (GestaoMigracao.tsx) => cache compartilhado.
  const { mesOf, meses } = useMesPlan();
  const rowsQ = useQuery({ queryKey: ["gestao", entity], queryFn: () => gestaoApi.listRows(entity) });
  const usersQ = useQuery({ queryKey: ["analistas"], queryFn: () => api.analistas(), select: usuariosGestao });
  const readinessQ = useQuery({
    queryKey: ["egp-readiness", "base"],
    queryFn: () => api.egpReadiness("base"),
    staleTime: 5 * 60 * 1000,
  });
  // Checklist de pré-working — só a variante Input usa (indicador de prontidão do Kanban de
  // Input, análogo à prontidão composta do EGP). Mesma queryKey ["preworking"] usada na
  // Gestão/InputDetailPanel — cache compartilhado, react-query dedupa.
  const preworkingQ = useQuery({
    queryKey: ["preworking"],
    queryFn: () => api.preworkingRows(),
    enabled: entity === "input",
    staleTime: 5 * 60 * 1000,
  });
  const readinessMap = useMemo(
    () => new Map((readinessQ.data?.rows ?? []).map((r) => [r.projeto, r])),
    [readinessQ.data]);
  const preworkingMap = useMemo(
    () => new Map((preworkingQ.data?.rows ?? []).map((r) => [r.chave_canonica, r])),
    [preworkingQ.data]);
  const rows = rowsQ.data ?? [];
  const users = usersQ.data ?? [];
  const rotulo = entity === "egp" ? "EGPs" : "Inputs";
  const nomeDe = (email: string | null) =>
    email ? (users.find((u) => u.email === email)?.nome ?? email.split("@")[0]) : "—";

  // Responsável BV: campo PRÓPRIO do EGP (sas_egp_pipeline, via readinessMap); Input não tem
  // campo próprio — HERDA dos EGPs consumidores (pode ter mais de um, mesmo espírito de
  // "passa se QUALQUER um bate" já usado nos filtros de mês/status da Gestão). Indicador de
  // prontidão: composto (EGP) ou % do checklist de pré-working (Input) — mesma escala 0-100
  // do gauge do Kanban.
  // colunas do funil da variante ativa — fonte das opções do filtro "Etapas do Kanban" e do
  // bucketing usado p/ decidir se uma linha "bate" numa etapa selecionada, mesma regra do
  // GestaoKanban (kanbanColKeyOf) — inclui a coluna "Despriorizado e Contabilizado" (pedido
  // do cliente BV 2026-08: separar da coluna de migrado normal, ver GestaoKanban.tsx), só
  // nesta tela (Gestão interna não pediu a separação).
  const colunasKanban = useMemo(
    () => buildKanbanColunas(entity, { separarDespriorizados: true }), [entity]);
  const colunasValidas = useMemo(() => new Set(colunasKanban.map((c) => c.key)), [colunasKanban]);
  const etapaKeyOf = (r: GestaoRow) =>
    kanbanColKeyOf(r, entity, colunasValidas, { separarDespriorizados: true, readiness: readinessMap });

  const respBvOptions = useMemo(() => {
    const s = new Set<string>();
    for (const r of rows) for (const bv of respBvOf(r, entity, readinessMap)) s.add(bv);
    return Array.from(s).sort((a, b) => a.localeCompare(b, "pt-BR"));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [rows, readinessMap, entity]);

  const mesOptions = useMemo(() => meses.map((n) => mesTag(n)), [meses]);

  const { mapa: mapaSub } = useSubareas();
  // Multi-valorado: na variante "input" a linha herda o Responsável BV de TODOS os EGPs
  // consumidores, que podem ser de sub-áreas diferentes — a linha entra nas duas.
  const subareasDaLinha = useMemo(
    () => (r: GestaoRow) => subareasDe(respBvOf(r, entity, readinessMap), mapaSub),
    [mapaSub, entity, readinessMap]);
  const subareaOptions = useMemo(
    () => ordenarSubareas(rows.flatMap(subareasDaLinha)), [rows, subareasDaLinha]);

  const filteredSemSubarea = useMemo(() => rows.filter((r) => {
    if (etapasSel.size && !etapasSel.has(etapaKeyOf(r))) return false;
    if (respsBvSel.size && !respBvOf(r, entity, readinessMap).some((bv) => respsBvSel.has(bv))) return false;
    // herdado dos EGPs consumidores (n:n na variante input) — passa se QUALQUER um bate
    if (mesesSel.size && !r.egps.some((e) => mesesSel.has(mesTag(mesOf.get(e))))) return false;
    if (pctRange) {
      if (entity === "egp") {
        if (!pctPassaFiltro(readinessMap.get(r.id), pctCategoriasSel, pctRange)) return false;
      } else {
        const p = preworkingPercentual(preworkingMap.get(r.id));
        if (p < pctRange[0] || p > pctRange[1]) return false;
      }
    }
    return true;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }), [rows, etapasSel, respsBvSel, mesesSel, pctRange, pctCategoriasSel, mesOf, colunasValidas, readinessMap, preworkingMap, entity]);
  const filtered = useMemo(
    () => (subareasSel.size
      ? filteredSemSubarea.filter((r) => subareasDaLinha(r).some((s) => subareasSel.has(s)))
      : filteredSemSubarea),
    [filteredSemSubarea, subareasSel, subareasDaLinha]);
  // contagem dos chips: ignora o próprio filtro de sub-área
  const subareaCounts = useMemo(() => {
    const m = new Map<string, number>();
    for (const r of filteredSemSubarea) for (const s of subareasDaLinha(r)) m.set(s, (m.get(s) ?? 0) + 1);
    return m;
  }, [filteredSemSubarea, subareasDaLinha]);

  // Separação total pelo eixo escolhido — cada grupo vira seu próprio board completo, a
  // partir do recorte já filtrado (etapas/responsável BV/sub-área/faixa de prontidão). Com
  // "nenhum", 1 grupo só com TODAS as linhas filtradas — sem risco de duplicar linha, que só
  // acontece no split por grupo: na variante Input tanto o Responsável BV quanto a sub-área
  // são HERDADOS dos EGPs consumidores, então um input lido por dois responsáveis (ou duas
  // sub-áreas) aparece nos dois quadros de propósito. Por isso a soma dos quadros pode passar
  // do total filtrado.
  const grupos = useMemo(() => {
    if (agruparPor === "nenhum") return [[TODOS, filtered]] as [string, GestaoRow[]][];
    const vazio = agruparPor === "respbv" ? SEM_RESP_BV : SEM_SUBAREA;
    const chavesDe = (r: GestaoRow) => (agruparPor === "respbv"
      ? respBvOf(r, entity, readinessMap)
      // subareasDe nunca devolve [] (linha sem sub-área já vem como SEM_SUBAREA), então o
      // fallback `chaves.length === 0` abaixo só dispara no eixo Responsável BV.
      : subareasDaLinha(r));
    const m = new Map<string, GestaoRow[]>();
    const add = (key: string, r: GestaoRow) => {
      const list = m.get(key);
      if (list) list.push(r); else m.set(key, [r]);
    };
    for (const r of filtered) {
      const chaves = chavesDe(r);
      if (chaves.length === 0) add(vazio, r);
      else for (const k of chaves) add(k, r);
    }
    return Array.from(m.entries()).sort(([a], [b]) => {
      // o balde "sem" sempre por último, seja qual for o eixo
      if (a === vazio) return 1;
      if (b === vazio) return -1;
      return a.localeCompare(b, "pt-BR");
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filtered, readinessMap, entity, agruparPor, subareasDaLinha]);

  // "recolher/expandir todos": um botão só, que segue o estado predominante (se sobrou algum
  // quadro aberto, recolhe todos; senão abre todos). Só faz sentido com a separação ligada.
  const algumAberto = grupos.some(([key]) => key !== TODOS && !colapsados.has(key));
  const toggleTodos = () =>
    setColapsados(() => salvaColapsados(algumAberto ? new Set(grupos.map(([key]) => key)) : new Set()));

  const pcts = useMemo(() => filtered.map((r) => pctBreakdown(readinessMap.get(r.id))), [filtered, readinessMap]);
  const checklistPcts = useMemo(
    () => filtered.map((r) => preworkingPercentual(preworkingMap.get(r.id))),
    [filtered, preworkingMap]);
  const panelRow = panelId ? rows.find((r) => r.id === panelId) ?? null : null;

  // Navegação cruzada EGP<->Input a partir do painel de status (GestaoStatusPanel):
  // "Usado por" no Input abre o EGP consumidor (onOpenEgp); "Inputs" no EGP abre o input
  // (onOpenInput) — pedido cliente BV 2026-08. Mesmo reset de filtros do switch manual
  // abaixo, senão o alvo pode nem aparecer no recorte filtrado atual. Não existe view
  // tabela/kanban aqui (Acompanhamento só tem Kanban).
  const jumpTo = (targetEntity: EntityType, id: string) => {
    setEntity(targetEntity); setEtapasSel(new Set()); setRespsBvSel(new Set()); setSubareasSel(new Set());
    setMesesSel(new Set()); setPctRange(null); setPctCategoriasSel(new Set());
    setPanelId(id);
  };

  return (
    <div className="gm">
      <div className="gm-head">
        <h3>Acompanhamento</h3>
        <div className="gm-switch" role="tablist" aria-label="Alternar EGP/Input">
          {(["egp", "input"] as EntityType[]).map((e) => (
            <button key={e} className={entity === e ? "on" : ""}
              onClick={() => {
                setEntity(e); setEtapasSel(new Set()); setRespsBvSel(new Set()); setSubareasSel(new Set());
                setMesesSel(new Set()); setPctRange(null); setPctCategoriasSel(new Set()); setPanelId(null);
              }}>
              {e === "egp" ? "EGPs" : "Inputs"}
            </button>
          ))}
        </div>
      </div>

      {/* Filtros — mesmo padrão visual da Gestão (MultiSelect/RangeFilter) */}
      <div className="filters">
        <MultiSelect label="Etapas do Kanban" options={colunasKanban.map((c) => c.key)} sel={etapasSel}
          labels={Object.fromEntries(colunasKanban.map((c) => [c.key, c.label]))}
          title="Quais colunas (etapas) aparecem nos quadros abaixo."
          onToggle={(v) => setEtapasSel((p) => { const n = new Set(p); n.has(v) ? n.delete(v) : n.add(v); return n; })}
          onClear={() => setEtapasSel(new Set())} />
        <MultiSelect label="Responsável BV" options={respBvOptions} sel={respsBvSel}
          title="Quais quadros (agrupados por Responsável BV) aparecem."
          onToggle={(v) => setRespsBvSel((p) => { const n = new Set(p); n.has(v) ? n.delete(v) : n.add(v); return n; })}
          onClear={() => setRespsBvSel(new Set())} />
        <MultiSelect label="Sub-área BV" options={subareaOptions} sel={subareasSel}
          title="Área interna do BV do responsável. Na visão de inputs, o input aparece se QUALQUER EGP consumidor for da sub-área selecionada."
          onToggle={(v) => setSubareasSel((p) => { const n = new Set(p); n.has(v) ? n.delete(v) : n.add(v); return n; })}
          onClear={() => setSubareasSel(new Set())} />
        <label className="chk"
          title="Em que eixo quebrar os quadros. 'Nenhum' mostra tudo num quadro único — os filtros acima continuam valendo nos três casos.">
          agrupar por
          <select value={agruparPor} onChange={(e) => setAgruparPor(e.target.value as typeof agruparPor)}>
            <option value="respbv">Responsável BV</option>
            <option value="subarea">Sub-área BV</option>
            <option value="nenhum">nenhum (quadro único)</option>
          </select>
        </label>
        <label className="chk"
          title="Mostra, no card do Kanban, quem da Indicium está executando cada EGP/Input (o mesmo Responsável da aba Gestão). Desligado por padrão.">
          <input type="checkbox" checked={showResp} onChange={(e) => setShowResp(e.target.checked)} />
          mostrar responsável
        </label>
        <MultiSelect label="Mês" options={mesOptions} sel={mesesSel}
          title={entity === "egp"
            ? "Mês do plano de priorização (mesmo da aba EGPs). EGP fora do plano some quando há seleção."
            : "Mês do plano dos EGPs consumidores — o input aparece se QUALQUER consumidor cai no mês selecionado."}
          onToggle={(v) => setMesesSel((p) => { const n = new Set(p); n.has(v) ? n.delete(v) : n.add(v); return n; })}
          onClear={() => setMesesSel(new Set())} />
        {entity === "egp" && (
          <MultiSelect label="Categoria de prontidão" options={PCT_CATEGORIAS} sel={pctCategoriasSel}
            labels={PCT_CATEGORIA_LABEL}
            title="Em qual(is) pedaço(s) da prontidão olhar. Nenhuma selecionada = Completo (média de inputs/outputs/pré-working). Selecionando 1+, a faixa ao lado só deixa passar quem tem TODAS elas dentro do intervalo — e o % do card do Kanban passa a ser a média entre as categorias escolhidas."
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
        <span className="count">{rowsQ.isFetching ? "carregando…" : `${filtered.length} de ${rows.length}`}</span>
      </div>

      <div className="rd-chips">
        <span className="rd-chips-lbl">Sub-área BV</span>
        {subareaOptions.map((s) => (
          <button key={s} className={`chip ${s === SEM_SUBAREA ? "todo" : "wip"} ${subareasSel.has(s) ? "on" : ""}`}
            title={s === SEM_SUBAREA
              ? "Sem Responsável BV, ou responsável fora do cadastro da Gestão"
              : `Sub-área ${s}`}
            onClick={() => setSubareasSel((p) => { const n = new Set(p); n.has(s) ? n.delete(s) : n.add(s); return n; })}>
            {s}: {subareaCounts.get(s) ?? 0}
          </button>
        ))}
      </div>

      <section className="metrics">
        <div className="card">
          <div className="card-value">{rowsQ.isFetching && !rowsQ.data ? "…" : filtered.length}</div>
          <div className="card-label">{rotulo} acompanhados</div>
        </div>
        {entity === "egp" ? (
          <>
            <div className="card ok">
              <div className="card-value">{avg(pcts.map((p) => p.total))}%</div>
              <div className="card-label">Prontidão média geral</div>
            </div>
            <div className="card">
              <div className="card-value">{avg(pcts.map((p) => p.inputs))}%</div>
              <div className="card-label">Inputs — média</div>
            </div>
            <div className="card">
              <div className="card-value">{avg(pcts.map((p) => p.outputs))}%</div>
              <div className="card-label">Outputs — média</div>
            </div>
            <div className="card">
              <div className="card-value">{avg(pcts.map((p) => p.preworking))}%</div>
              <div className="card-label">Pré-working — média</div>
            </div>
          </>
        ) : (
          <div className="card ok">
            <div className="card-value">{avg(checklistPcts)}%</div>
            <div className="card-label">Checklist pré-working — média</div>
          </div>
        )}
      </section>

      {rowsQ.error && <div className="error">{String(rowsQ.error)}</div>}
      {!rowsQ.isFetching && filtered.length === 0 && (
        <div className="muted">
          {rows.length === 0
            ? `Nenhum ${entity === "egp" ? "EGP" : "input"} no recorte atual.`
            : "Nenhum resultado para os filtros atuais."}
        </div>
      )}

      {agruparPor !== "nenhum" && grupos.length > 1 && (
        <div className="acomp-grupos-bar">
          <button type="button" className="ghost" onClick={toggleTodos}
            title={algumAberto
              ? "Recolhe todos os quadros — só os títulos com o resumo de cada grupo."
              : "Reabre todos os quadros."}>
            {algumAberto ? "Recolher todos" : "Expandir todos"}
          </button>
        </div>
      )}

      {grupos.map(([key, grupoRows]) => {
        const grupoPct = entity === "egp"
          ? avg(grupoRows.map((r) => pctBreakdown(readinessMap.get(r.id)).total))
          : avg(grupoRows.map((r) => preworkingPercentual(preworkingMap.get(r.id))));
        // TODOS = quadro único (separação desligada): não tem título nem recolhimento.
        const colapsado = key !== TODOS && colapsados.has(key);
        const resumo = `${grupoRows.length} ${entity === "egp"
          ? (grupoRows.length === 1 ? "EGP" : "EGPs")
          : (grupoRows.length === 1 ? "input" : "inputs")} · ${
          entity === "egp" ? "prontidão" : "checklist"} média ${grupoPct}%`;
        return (
          <section className={colapsado ? "acomp-grupo colapsado" : "acomp-grupo"} key={key}>
            {key !== TODOS && (
              <h4 className="acomp-grupo-head">
                <button type="button" className="acomp-grupo-toggle" aria-expanded={!colapsado}
                  onClick={() => toggleColapso(key)}
                  title={colapsado ? "Expandir este quadro" : "Recolher este quadro"}>
                  <span className="acomp-grupo-caret" aria-hidden="true">{colapsado ? "▸" : "▾"}</span>
                  <span className="acomp-grupo-nome">{key === SEM_RESP_BV ? "Sem responsável BV" : key}</span>
                  <span className="muted">{resumo}</span>
                </button>
              </h4>
            )}
            {!colapsado && (
              <GestaoKanban entity={entity} rows={grupoRows} readiness={readinessMap} preworking={preworkingMap}
                showResponsavel={showResp} respLabelOf={nomeDe} showMes mesOf={mesOf} onOpenCard={setPanelId}
                colunasVisiveis={etapasSel} pctCategorias={pctCategoriasSel} separarDespriorizados />
            )}
          </section>
        );
      })}

      {panelRow && (
        <GestaoStatusPanel entity={entity} row={panelRow} allRows={rows} users={users}
          hideResponsavel={!showResp} readOnly onOpenEgp={(p) => jumpTo("egp", p)}
          onOpenInput={(c) => jumpTo("input", c)} onClose={() => setPanelId(null)} />
      )}
    </div>
  );
}
