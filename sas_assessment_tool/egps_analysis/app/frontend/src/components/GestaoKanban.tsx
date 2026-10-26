// Kanban de EGPs/Inputs (entity), UM componente reusado nas 2 variantes — mesmo padrão de
// parametrização por entityType já usado em GestaoMigracao. EGP: colunas = etapas do funil de
// migração (pipeline.ts:PIPELINE_PROJETO.migracao), com "Pré-conversão" (fantasma, fora do
// funil) fixada como PRIMEIRA coluna — é o estado mais cedo possível (conversão iniciada antes
// de "Projetos Habilitados") — e "Conversão pela Área" (a outra fantasma) no fim. Cards =
// GestaoRow hidratado com prontidão de inputs/outputs/pré-working (ReadinessRow do
// /api/egp-readiness). Input: colunas = etapas do funil de ingestão (PIPELINE_INPUT); sem
// fantasmas (Sanitizado é STATUS, não etapa, e /api/gestao/rows já exclui sanitizados do
// recorte — nunca aparece aqui). Card hidratado com o checklist de pré-working
// (PreworkingRow), único indicador de "prontidão" que existe por input (não há inputs/outputs
// aninhados como no EGP). A lista de EGPs consumidores (nome + badge de pendência via
// pendenciaInputParaEgp, exportado abaixo) NÃO fica no card — poluía demais o board (pedido
// cliente BV 2026-08) — mora no drawer de status do Input (GestaoStatusPanel), seção "Usado
// por". Reusado por 2 telas: a Gestão interna (clique no card abre o drawer de status/
// comentário — editar a Etapa por lá invalida o cache e move o card sozinho, sem
// drag-and-drop) e a Acompanhamento/cliente (showResponsavel opcional via chip "mostrar
// responsável", sem onOpenCard = card não clicável).
import { useState } from "react";
import { SEG, STATUS_ABBR, statusTrocaLabel } from "../pipeline";
// O bloco `export { ... } from "../kanbanColunas"` abaixo é RE-EXPORT: não traz os nomes
// para o escopo local. O corpo usa STATUS_DESPRIORIZADO (pill da troca), então precisa do
// import de verdade — os dois convivem de propósito.
import { STATUS_DESPRIORIZADO } from "../kanbanColunas";
import { egpShort } from "../csv";
import { preworkingPercentual } from "../inputs";
import { tabelaModernizada } from "../tabelaCorresp";
import { fmtTsBR, diasEmValidacaoBV } from "../diasUteis";
import { comBvAtual, hojeSP, type GestaoRow, type EntityType } from "../gestaoApi";
import { mesTag } from "../mesPlan";
import type { ReadinessRow, PreworkingRow } from "../types";
import { SEM_ETAPA, buildKanbanColunas, kanbanColKeyOf } from "../kanbanColunas";

interface Props {
  entity?: EntityType;   // default "egp" (retrocompat)
  rows: GestaoRow[];
  // readiness do EGP (n_inputs/outputs, onda, responsavel_bv…). entity="input" também lê
  // aqui — herda campos (mês, Responsável BV) dos EGPs consumidores via r.egps.
  readiness?: Map<string, ReadinessRow>;
  preworking?: Map<string, PreworkingRow>;   // usado só entity="input"
  respLabelOf?: (email: string | null) => string;   // dispensável quando showResponsavel=false
  onOpenCard?: (id: string) => void;
  // false na página cliente: não expõe quem da Indicium está executando o EGP/Input.
  showResponsavel?: boolean;
  // true no Acompanhamento: mostra o(s) mês(es) do plano de priorização no card (M1, M2…;
  // campo do EGP via mesOf/useMesPlan; herdado das EGPs consumidoras p/ Input) — o cliente BV
  // planeja por mês, contexto que faltava no board. Substituiu o badge de "onda" (2026-09,
  // mesma troca de terminologia já feita no filtro — ver GuiaView.tsx/mesPlan.ts).
  showMes?: boolean;
  // Mapa projeto -> mês do plano (useMesPlan().mesOf) — obrigatório junto de showMes=true.
  mesOf?: Map<string, number>;
  // Filtro "Etapas do Kanban": quais colunas renderizar (chaves de KanbanColuna.key).
  // undefined/vazio = todas (comportamento atual, mesma convenção do MultiSelect: seleção
  // vazia = sem filtro). Não afeta o bucketing (byCol usa SEMPRE o funil completo) — só
  // decide quais colunas aparecem na tela.
  colunasVisiveis?: Set<string>;
  // Categorias selecionadas no filtro "Prontidão" (só entity="egp"): vazio (default) =
  // Completo (composto de sempre). 1+ = o card (gauge + métricas em destaque) passa a
  // refletir a MÉDIA entre as categorias escolhidas, cada uma na sua própria escala.
  pctCategorias?: Set<PctCategoria>;
  // true separa EGPs com status "Despriorizado e Contabilizado" numa coluna PRÓPRIA
  // (independente da etapa em que estavam quando saíram do backlog) — pedido do cliente
  // BV 2026-08: eles ficavam misturados na coluna de "Migrado" (ou onde quer que a etapa
  // estivesse), indistinguíveis de migração normal na visão do board. Só entity="egp" (é
  // status, não existe conceito de "despriorizado" p/ input). Default false: a Gestão
  // interna NÃO pediu essa separação (só o Acompanhamento/cliente).
  separarDespriorizados?: boolean;
  // Presente = card ganha o switch "Com BV" (mesmo controle da tabela de Gestão, ver
  // comBvAtual/gestaoApi.setBV) + o contador de dias em validação quando etapa === "Validação
  // da Área" (EGP), com aviso por cor ao se aproximar do prazo de 8 dias úteis (ver
  // diasEmValidacaoBV/docs/superpowers/specs/2026-07-12-bv-validation-switch-design.md). Só a
  // Gestão interna passa isto — a Acompanhamento (cliente) não expõe o toggle nem o contador
  // (a seção "Validação BV" do drawer já é restrita a bv_admins).
  onToggleBV?: (id: string, comBv: boolean) => void;
}

// Colunas e bucket vivem em ../kanbanColunas (lógica pura, testável — `.tsx` não roda sob
// node --experimental-strip-types). Re-exportado daqui para os importadores existentes
// (AcompanhamentoView, GestaoMigracao) seguirem inalterados.
export {
  SEM_ETAPA, STATUS_DESPRIORIZADO, STATUS_DESATUALIZADO,
  buildKanbanColunas, kanbanColKeyOf, type KanbanColuna,
} from "../kanbanColunas";

// Prontidão composta (0-100): 3 categorias, 1/3 cada — inputs e outputs usam a mesma
// convenção já existente no app p/ "0 itens = nada pendente = 100%" (_egp_readiness_rows.pct
// no backend); pré-working é binário (preenchido = 100%, senão 0%). Exportado p/ a página
// cliente reusar no cálculo dos KPIs médios.
export function pctBreakdown(rr: ReadinessRow | undefined) {
  const inputs = rr ? rr.pct : 100;
  // fatia de `inputs` (mesma escala 0-100) atribuível a inputs "desbloqueados" via Ingestão
  // PRD/Aplicação de Grant, ainda NÃO Modernizados — subconjunto de `inputs` por construção
  // (backend já garante n_prd <= n_faltam, ver _egp_readiness_rows). Só serve pra pintar a
  // 2ª cor/flag do anel — não é uma categoria própria do filtro (ver pctCardPrdShare).
  const inputsPrd = rr && rr.n_inputs > 0 ? Math.round((100 * rr.n_prd) / rr.n_inputs) : 0;
  const outputs = rr ? (rr.n_outputs > 0 ? (100 * rr.n_outputs_disp) / rr.n_outputs : 100) : 100;
  const preworking = rr?.preworking ? 100 : 0;
  const total = Math.round((inputs + outputs + preworking) / 3);
  return { inputs, inputsPrd, outputs, preworking, total };
}

// As 3 categorias reais — sem "total": nenhuma selecionada JÁ significa Completo, mesma
// convenção "seleção vazia = sem filtro" do MultiSelect usado em todo filtro desta tela.
// Multi-seleção (pedido 2026-08, era single-select): 1+ categorias = a linha só passa no
// filtro de faixa se TODAS caírem nela (E lógico — "falta tanto preworking quanto inputs" é
// isso, não a média das duas). O % do CARD é outra conta (ver pctCard): a média entre as
// categorias escolhidas — NÃO o mínimo, que travava em 0% sempre que pré-working (binário
// 0/100) entrava na seleção ou na conta do "Completo".
export type PctCategoria = "inputs" | "outputs" | "preworking";
export const PCT_CATEGORIAS: PctCategoria[] = ["inputs", "outputs", "preworking"];
export const PCT_CATEGORIA_LABEL: Record<PctCategoria, string> = {
  inputs: "Inputs", outputs: "Outputs", preworking: "Pré-working",
};

// Valores a considerar: vazio = as 3 (o composto de sempre); com seleção, só as escolhidas —
// cada uma na sua própria escala, não a fatia de 1/3 dela dentro do composto.
function pctValores(rr: ReadinessRow | undefined, sel: Set<PctCategoria>): number[] {
  const b = pctBreakdown(rr);
  return (sel.size ? Array.from(sel) : PCT_CATEGORIAS).map((c) => b[c]);
}

// % exibido no card: média entre as categorias consideradas — as 3 (Completo) sem seleção,
// só as escolhidas com 1+. NÃO é o filtro (esse é E lógico, ver pctPassaFiltro) — por isso
// PODE "compensar" uma categoria baixa com outra alta; é só o indicador visual do card, no
// mesmo espírito do composto de sempre. (Min já foi tentado e travava em 0% toda vez que
// pré-working, binário 0/100, entrava na conta — ver pedido 2026-08.)
export function pctCard(rr: ReadinessRow | undefined, sel: Set<PctCategoria>): number {
  const vals = pctValores(rr, sel);
  return Math.round(vals.reduce((a, v) => a + v, 0) / vals.length);
}

// Fatia do % do card (mesma média/categorias de pctCard) atribuível a inputs "desbloqueados"
// via Ingestão PRD/Aplicação de Grant — só "inputs" tem esse tier intermediário, então some 0
// quando a categoria não está entre as consideradas. Usado só pra desenhar a 2ª cor do anel
// (Gauge secondaryPct); nunca maior que o próprio pctCard (inputsPrd <= inputs, ver
// pctBreakdown).
export function pctCardPrdShare(rr: ReadinessRow | undefined, sel: Set<PctCategoria>): number {
  const cats = sel.size ? Array.from(sel) : PCT_CATEGORIAS;
  if (!cats.includes("inputs")) return 0;
  return Math.round(pctBreakdown(rr).inputsPrd / cats.length);
}

// Filtro de faixa. Com 1+ categorias selecionadas: passa só se TODAS caem em [lo,hi] — E
// lógico (uma categoria em 100% não "compensa" outra em 0% aqui) — é o que o tooltip do
// RangeFilter promete nesse caso. SEM seleção (Completo, default): filtra pela MESMA % média
// que o card/coluna mostra (pctCard), não pelo E lógico das 3 categorias cruas — senão
// pré-working (binário, quase sempre 0% enquanto o checklist não é preenchido) reprova o
// filtro sozinho pra praticamente todo EGP assim que lo > 0 (bug reportado 2026-08-26: faixa
// "40 a 100%" não retornava nada, mesmo com cards mostrando 60-90% de prontidão).
export function pctPassaFiltro(
  rr: ReadinessRow | undefined, sel: Set<PctCategoria>, range: [number, number] | null,
): boolean {
  if (!range) return true;
  const [lo, hi] = range;
  if (sel.size === 0) {
    const v = pctCard(rr, sel);
    return v >= lo && v <= hi;
  }
  return pctValores(rr, sel).every((v) => v >= lo && v <= hi);
}

// Exportado p/ a aba EGPs (ReadinessView) reusar o mesmo texto de tooltip da coluna
// "Prontidão" — mesmo indicador, mesma explicação.
export function pctGaugeTitulo(pct: number, sel: Set<PctCategoria>): string {
  if (sel.size === 0) return `Prontidão geral: ${pct}% (média de inputs, outputs e pré-working)`;
  const labels = Array.from(sel).map((c) => PCT_CATEGORIA_LABEL[c]);
  return sel.size === 1
    ? `Prontidão de ${labels[0]}: ${pct}%`
    : `Prontidão (média entre ${labels.join(" + ")}): ${pct}%`;
}

// Mês(es) do plano de priorização do EGP (M1, M2…; via mesOf/useMesPlan) — Input HERDA dos
// EGPs consumidores (pode ter mais de um, mesmo espírito de "passa se QUALQUER um bate" já
// usado no filtro de Responsável BV). Lista deduplicada e ordenada; [] = fora do plano.
export function mesLabelsOf(r: GestaoRow, entity: EntityType, mesOf?: Map<string, number>): string[] {
  if (entity === "egp") {
    const m = mesOf?.get(r.id);
    return m != null ? [mesTag(m)] : [];
  }
  const s = new Set<string>();
  for (const e of r.egps) {
    const m = mesOf?.get(e);
    if (m != null) s.add(mesTag(m));
  }
  return Array.from(s).sort();
}

// Responsável(is) BV do EGP (campo livre responsavel_bv, via readiness — editado na aba EGPs/
// ReadinessView) — Input HERDA dos EGPs consumidores, mesmo padrão de mesLabelsOf/ondaOf
// acima. Lista deduplicada e ordenada; [] = sem responsável BV atribuído. Reusado pelo filtro
// "Responsável BV" (Gestão e Acompanhamento) e pelo badge no card/drawer.
export function respBvOf(r: GestaoRow, entity: EntityType, readiness?: Map<string, ReadinessRow>): string[] {
  if (entity === "egp") {
    const bv = readiness?.get(r.id)?.responsavel_bv?.trim();
    return bv ? [bv] : [];
  }
  const s = new Set<string>();
  for (const e of r.egps) {
    const bv = readiness?.get(e)?.responsavel_bv?.trim();
    if (bv) s.add(bv);
  }
  return Array.from(s).sort((a, b) => a.localeCompare(b, "pt-BR"));
}

// "Pendência" de 1 input p/ 1 EGP consumidor específico — pedido do cliente BV 2026-08:
// não o %, mas se LIBERAR ESTE input resolve tudo que falta pro EGP ou se ainda sobra algo
// (outros inputs, outputs, pré-working). `null` = não há o que "liberar" (input já
// Modernizado, Sanitizado = terminal/descartado, ou Autoprodutor = conta como feito) ou
// EGP sem readiness carregada ainda.
// Dedução: este input, por já estar confirmado em r.egps e NÃO modernizado/sanitizado/
// autoprodutor, conta em rr.n_faltam DAQUELE EGP — se n_faltam=1, é matematicamente ELE
// o único que falta (não é heurística). Simplificação aceita: ignora overlay per-(EGP,
// Input) de vínculo quebrado (link_broken), que reduziria n_faltam mais rápido pra 1 EGP
// específico — dado não disponível neste nível (só no detalhe do EGP).
export interface PendenciaInput { ultima: boolean; outras: number }
export function pendenciaInputParaEgp(
  input: GestaoRow, egpId: string, readiness?: Map<string, ReadinessRow>,
): PendenciaInput | null {
  if (input.etapa === "Modernizado" || input.status === "Sanitizado" || input.status === "Autoprodutor") return null;
  const rr = readiness?.get(egpId);
  if (!rr) return null;
  const outputsOk = rr.n_outputs === 0 || rr.n_outputs_disp >= rr.n_outputs;
  const preworkingOk = !!rr.preworking;
  const inputsRestantes = Math.max(0, rr.n_faltam - 1); // -1 = este próprio input
  const outras = inputsRestantes + (outputsOk ? 0 : 1) + (preworkingOk ? 0 : 1);
  return { ultima: outras === 0, outras };
}

// Vermelho (0%) -> verde (100%), mesma fórmula usada no anel e reutilizável em qualquer
// outro indicador percentual que precise da mesma escala.
export function gaugeColor(pct: number): string {
  return `hsl(${Math.round(pct * 1.2)}, 70%, 42%)`;
}

// Cor da fatia "desbloqueada via PRD" no anel — deliberadamente NUNCA a mesma cor do resto
// (verde/vermelho da escala gaugeColor), pra nunca se confundir com "realmente pronto"
// (Modernizado). Âmbar = mesma semântica de "atenção/parcial" já usada no app.
const PRD_TIER_COLOR = "#f2a91c";

// Exportado (com variante `size="sm"`) p/ a coluna "Prontidão" da aba EGPs (ReadinessView)
// reusar o mesmo anel — mesmo indicador visual em Gestão e EGPs, só menor p/ caber na tabela.
// `secondaryPct` (opcional, ver pctCardPrdShare): fatia FINAL do anel (0..pct) pintada com
// PRD_TIER_COLOR em vez da cor normal — sinaliza que parte do % já contado vem de inputs só
// desbloqueados (Ingestão PRD/Aplicação de Grant), ainda não Modernizados. 0/omitido = anel
// de 1 cor só, comportamento anterior inalterado.
export function Gauge(
  { pct, title, size = "md", secondaryPct = 0 }:
  { pct: number; title: string; size?: "md" | "sm"; secondaryPct?: number },
) {
  const cor = gaugeColor(pct);
  const sec = Math.max(0, Math.min(secondaryPct, pct));
  const bordaSec = (pct - sec) * 3.6;
  const fimSec = pct * 3.6;
  const background = sec > 0
    ? `conic-gradient(${cor} ${bordaSec}deg, ${PRD_TIER_COLOR} ${bordaSec}deg ${fimSec}deg, var(--fill-muted) ${fimSec}deg)`
    : `conic-gradient(${cor} ${pct * 3.6}deg, var(--fill-muted) 0)`;
  return (
    <div className={`kanban-gauge${size === "sm" ? " kanban-gauge-sm" : ""}`}
      style={{ background }}
      title={sec > 0 ? `${title} — inclui inputs desbloqueados via Ingestão PRD/Aplicação de Grant, ainda não Modernizados` : title}>
      <div className="kanban-gauge-inner" style={{ color: cor }}>
        {pct}%{sec > 0 && <span className="kanban-gauge-flag">⚑</span>}
      </div>
    </div>
  );
}

// Carga fria: o nome é digitado no campo próprio (cf_tabela) -> vale como está. Input: o campo
// "Tbl. Corresp." é texto livre (também guarda notas) -> só o nome da tabela vai pro card.
const tabelaCard = (r: GestaoRow) => (r.cargaFria ? r.tabelaCorresp : tabelaModernizada(r.tabelaCorresp));

// Pirâmide de 3 cubinhos de gelo isométricos (2 embaixo, 1 em cima) — ícone de "carga fria"
// no card de EGP. Faces: topo claro, esquerda média, direita escura, p/ ler como gelo.
function IceCube({ x, y, on }: { x: number; y: number; on: boolean }) {
  const W = 7, H = 3.5, D = 7;
  // pendente: mesmo cubo, mas dessaturado (cinza-azulado) — continua visível, só "sem vida"
  const f = on ? ["#e9f8ff", "#a9dcf2", "#7cc6e8"] : ["#e4ecf0", "#c9d6dd", "#b3c3cc"];
  return (
    <g stroke={on ? "#4fb3d9" : "#8aa3b0"} strokeWidth=".8" strokeLinejoin="round">
      <polygon points={`${x},${y} ${x + W},${y + H} ${x},${y + 2 * H} ${x - W},${y + H}`} fill={f[0]} />
      <polygon points={`${x - W},${y + H} ${x},${y + 2 * H} ${x},${y + 2 * H + D} ${x - W},${y + H + D}`} fill={f[1]} />
      <polygon points={`${x + W},${y + H} ${x},${y + 2 * H} ${x},${y + 2 * H + D} ${x + W},${y + H + D}`} fill={f[2]} />
      <path d={`M${x - W * 0.55},${y + H * 0.7} L${x - W * 0.1},${y + H * 0.15}`} stroke="#fff" strokeWidth="1" strokeLinecap="round" opacity={on ? 1 : 0.7} />
    </g>
  );
}

// Cubos cheios da pirâmide (de 3) por proporção de cargas frias finalizadas: 0 -> nenhum,
// total -> todos; qualquer parcial fica entre 1 e 2, p/ nunca parecer vazio nem completo.
const cubosCheios = (ok: number, total: number) =>
  ok <= 0 ? 0 : ok >= total ? 3 : Math.min(2, Math.max(1, Math.round((ok / total) * 3)));

function IceIcon({ ok, total }: { ok: number; total: number }) {
  const n = cubosCheios(ok, total);
  return (
    <svg width="26" height="22" viewBox="-1 -1 30 25" aria-hidden>
      <IceCube x={7} y={10.5} on={n >= 1} />
      <IceCube x={21} y={10.5} on={n >= 2} />
      <IceCube x={14} y={0} on={n >= 3} />
    </svg>
  );
}

export function GestaoKanban({ entity = "egp", rows, readiness, preworking, respLabelOf, onOpenCard, showResponsavel = true, showMes = false, mesOf, colunasVisiveis, pctCategorias = new Set<PctCategoria>(), separarDespriorizados = false, onToggleBV }: Props) {
  // fixado 1x por render (não por card) — o contador de dias em validação (Com BV) usa o
  // mesmo "hoje" pra todos os cards do board.
  const hoje = hojeSP();
  // etapasValidas SEMPRE do funil completo (bucketing correto independe do filtro de
  // visibilidade); `colunas` (o que renderiza) é que encolhe com colunasVisiveis.
  const todasColunas = buildKanbanColunas(entity, { separarDespriorizados });
  const etapasValidas = new Set(todasColunas.map((c) => c.key));
  const colunas = colunasVisiveis && colunasVisiveis.size > 0
    ? todasColunas.filter((c) => colunasVisiveis.has(c.key))
    : todasColunas;

  const byCol = new Map<string, GestaoRow[]>();
  for (const r of rows) {
    const k = kanbanColKeyOf(r, entity, etapasValidas, { separarDespriorizados, readiness });
    const list = byCol.get(k);
    if (list) list.push(r); else byCol.set(k, [r]);
  }

  return (
    <div className="kanban-board">
      {colunas.map((c) => {
        const cards = byCol.get(c.key) ?? [];
        // "Sem etapa" e as fantasma (fora do funil) só aparecem se tiverem card — as 9
        // etapas do funil aparecem sempre, mesmo vazias, p/ o board ficar estável.
        if ((c.key === SEM_ETAPA || c.fantasma) && cards.length === 0) return null;
        return (
          <div className={`kanban-col${c.fantasma ? " fantasma" : ""}`} key={c.key}>
            <div className="kanban-col-head">
              <span>{c.label}</span>
              <span className="kanban-col-count">{cards.length}</span>
            </div>
            <div className="kanban-col-body">
              {cards.map((r) => {
                const rr = entity === "egp" ? readiness?.get(r.id) : undefined;
                const pwk = entity === "input" ? preworking?.get(r.id) : undefined;
                const status = entity === "egp" ? (rr?.status || "A Iniciar") : (r.status || "A Iniciar");
                const pct = entity === "egp" ? pctCard(rr, pctCategorias) : preworkingPercentual(pwk);
                const meses = showMes ? mesLabelsOf(r, entity, mesOf) : [];
                const bvResps = respBvOf(r, entity, readiness);
                const openThis = () => onOpenCard?.(r.id);
                // contador manual de revisão de regras (editado no drawer, GestaoStatusPanel):
                // no card vira só o contorno laranja (ver .em-revisao no CSS)
                const revisoes = entity === "egp" ? (r.revisoesRegras ?? 0) : 0;
                // Tooltip do card = último status registrado (não mais o nome do EGP/input,
                // que já aparece no título do próprio card) — pedido do cliente BV 2026-08:
                // o hover é o jeito rápido de ver "o que está rolando" sem abrir o drawer.
                const dataStatus = r.resumoStatusData ? fmtTsBR(r.resumoStatusData, false).split(" ")[0] : "";
                const cardTooltip = r.resumoStatus
                  ? `${dataStatus ? `${dataStatus} - ` : ""}${r.resumoStatus}`
                  : "Sem status registrado";
                return (
                  <div className={`kanban-card${onOpenCard ? " clickable" : ""}${r.cargaFria ? " carga-fria" : ""}${revisoes > 0 ? " em-revisao" : ""}`} key={r.id} title={cardTooltip}
                    role={onOpenCard ? "button" : undefined} tabIndex={onOpenCard ? 0 : undefined}
                    onClick={onOpenCard ? openThis : undefined}
                    onKeyDown={onOpenCard
                      ? (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); openThis(); } }
                      : undefined}>
                      {r.cargaFria && (
                        <span className="kanban-cf-badge"
                          title="OUTPUT que precisa de carga fria (histórico) — não é um input; avalie priorizar">
                          ❄ Carga fria · output
                        </span>
                      )}
                    <div className="kanban-card-top">
                      <span className="kanban-card-title">{entity === "egp" ? egpShort(r.id) : r.nome}</span>
                      {/* Despriorizado e Contabilizado com egp_atualizado_key = SUBSTITUÍDO por uma
                          versão nova (aba EGPs Atualizados), não despriorizado pelo BV — mesmo
                          status (reaproveitado de propósito, ver EgpsAtualizadosView.tsx), rótulo
                          e tooltip diferentes pra não confundir os dois motivos. */}
                      <span className="kanban-pill"
                        style={{ background: SEG[status]?.bg, color: SEG[status]?.fg }}
                        title={status === STATUS_DESPRIORIZADO && rr?.egp_atualizado_key
                          ? `${statusTrocaLabel(rr.atualizado_link_tipo_vinculo)} pela versão atualizada "${rr.atualizado_link_nome ?? rr.egp_atualizado_key}"`
                          : undefined}>
                        {status === STATUS_DESPRIORIZADO && rr?.egp_atualizado_key
                          ? statusTrocaLabel(rr.atualizado_link_tipo_vinculo)
                          : (STATUS_ABBR[status] ?? status)}
                      </span>
                    </div>
                    <div className="kanban-card-area muted">
                      {r.area ?? "—"}
                      {showMes && ` · ${meses.length ? meses.join(", ") : "fora do plano"}`}
                    </div>
                    {entity === "input" && tabelaCard(r) && (
                      <div className="kanban-card-tabela" title={`Tabela correspondente (modernizada): ${tabelaCard(r)}`}>
                        <span aria-hidden>🗄</span> {tabelaCard(r)}
                      </div>
                    )}
                    <div className="kanban-card-body">
                      <div className="kanban-card-metrics">
                        {entity === "egp" ? (
                          <>
                            <div className={`kanban-card-metric${pctCategorias.has("inputs") ? " active" : ""}`}>
                              Inputs {rr ? `${rr.n_disp}/${rr.n_inputs}` : "—"}
                              {!!rr?.n_prd && (
                                <span className="kanban-card-prd-badge"
                                  title="Já em Ingestão PRD/Aplicação de Grant — desbloqueado, ainda não Modernizado">
                                  {" "}+{rr.n_prd} em PRD
                                </span>
                              )}
                              {rr?.desbloqueia_remessa && (
                                <span className="kanban-card-prd-badge"
                                  title={`Ficaria pronto (${rr.n_faltam} de ${rr.n_faltam} pendências) se a remessa em trânsito (PDI+GMUD/Ingestão PRD) completasse`}>
                                  {" "}🚚 remessa
                                </span>
                              )}
                            </div>
                            <div className={`kanban-card-metric${pctCategorias.has("outputs") ? " active" : ""}`}>
                              {rr && rr.n_outputs > 0 ? `Outputs ${rr.n_outputs_disp}/${rr.n_outputs}` : "Outputs —"}
                            </div>
                            <div className={`kanban-card-metric${pctCategorias.has("preworking") ? " active" : ""}`}>
                              Pré-working {rr?.preworking ? "1/1" : "0/1"}
                            </div>
                          </>
                        ) : (
                          r.cargaFria ? (
                            <>
                              <div className="kanban-card-metric">Histórico do output (carga fria)</div>
                              <div className="kanban-card-metric">
                                {r.egps.length} EGP{r.egps.length === 1 ? "" : "s"} produtor{r.egps.length === 1 ? "" : "es"}
                              </div>
                            </>
                          ) : (
                          <>
                            <div className="kanban-card-metric">Checklist pré-working {pct}%</div>
                            <div className="kanban-card-metric">
                              {r.egps.length} EGP{r.egps.length === 1 ? "" : "s"} consumidor{r.egps.length === 1 ? "" : "es"}
                            </div>
                          </>
                          )
                        )}
                      </div>
                      {!r.cargaFria && (
                        <div className="kanban-card-gauge-col">
                          {entity === "egp" && !!rr?.n_carga_fria && (() => {
                            const ok = (rr.n_carga_fria_ok ?? 0) >= rr.n_carga_fria;
                            return (
                              <span className={`kanban-cf-ico${ok ? " ok" : ""}`}
                                title={ok
                                  ? `Carga fria finalizada (${rr.n_carga_fria_ok}/${rr.n_carga_fria} outputs)`
                                  : `Carga fria pendente: ${rr.n_carga_fria_ok ?? 0}/${rr.n_carga_fria} outputs finalizados`}>
                                <IceIcon ok={rr.n_carga_fria_ok ?? 0} total={rr.n_carga_fria} />
                              </span>
                            );
                          })()}
                          <Gauge pct={pct}
                            secondaryPct={entity === "egp" ? pctCardPrdShare(rr, pctCategorias) : 0}
                            title={entity === "egp"
                              ? pctGaugeTitulo(pct, pctCategorias)
                              : `Checklist de pré-working: ${pct}% preenchido`} />
                        </div>
                      )}
                    </div>
                    {((showResponsavel && r.responsavel) || bvResps.length > 0 || onToggleBV) && (
                      <div className="kanban-card-meta">
                        {showResponsavel && r.responsavel && (
                          <div className="kanban-card-meta-row">
                            <span className="kanban-card-resp-ico" aria-hidden>👤</span>
                            {respLabelOf?.(r.responsavel) ?? r.responsavel}
                          </div>
                        )}
                        {bvResps.length > 0 && (
                          <div className="kanban-card-meta-row" title="Responsável pela validação do lado BV (editado na aba EGPs)">
                            <span className="kanban-card-resp-ico" aria-hidden>🏦</span>
                            Resp. BV: {bvResps.join(", ")}
                          </div>
                        )}
                        {onToggleBV && (
                          // stopPropagation: o card inteiro é clicável (abre o drawer) quando
                          // onOpenCard existe — sem isto, clicar no switch também dispararia o
                          // openThis() do wrapper.
                          <div className="kanban-card-meta-row" onClick={(e) => e.stopPropagation()}>
                            <label className="gm-bv-toggle"
                              title={comBvAtual(r) ? "Com o BV — clique p/ trazer p/ nós" : "Conosco — clique p/ entregar ao BV"}>
                              <input type="checkbox" checked={comBvAtual(r)}
                                onChange={(e) => onToggleBV(r.id, e.target.checked)} />
                              <span className="gm-bv-track"><span className="gm-bv-thumb" /></span>
                            </label>
                            <span className="kanban-card-bv-label">Com BV</span>
                            {entity === "egp" && r.etapa === "Validação da Área" && (
                              <DiasValidacaoBadge dias={diasEmValidacaoBV(r.bvEventos, hoje)} />
                            )}
                          </div>
                        )}
                      </div>
                    )}
                  </div>
                );
              })}
              {cards.length === 0 && <div className="muted kanban-col-empty">—</div>}
            </div>
          </div>
        );
      })}
    </div>
  );
}

// Badge de dias úteis acumulados em validação com o BV (mesma conta da coluna "Dias em val.
// (BV)" da tabela de Gestão, ver diasEmValidacaoBV) — só aparece com etapa "Validação da
// Área", que é onde o prazo do BV (fixo, 8 dias úteis) mais aperta. Aviso por cor conforme se
// aproxima/estoura o prazo: verde folgado, âmbar a partir de 5 dias, vermelho a partir de 8
// (ver design doc 2026-07-12-bv-validation-switch-design.md, que deixou a indicação visual
// como YAGNI na 1ª versão — este é o pedido do cliente BV que a implementa).
function DiasValidacaoBadge({ dias }: { dias: number }) {
  const tone = dias >= 8 ? "danger" : dias >= 5 ? "warn" : "ok";
  return (
    <span className={`kanban-bv-dias ${tone}`}
      title={`${dias} dia${dias === 1 ? "" : "s"} útil(eis) em validação com o BV (prazo máximo: 8 dias úteis)`}>
      {dias}d
    </span>
  );
}

// `campo` = chave do patch de GestaoDataSource.setDates (mapeia 1:1) — genérico o bastante
// pra qualquer grade de Gestão com datas (EGP/Input em GestaoMigracao.tsx, EGPs Atualizados
// em EgpsAtualizadosKanban.tsx, ver setDates("egp_atualizado", egp_key, ...)). Vive aqui
// (módulo compartilhado pelos dois) pra evitar import circular entre eles.
export type DateCampo = "inicio" | "fimConversao" | "fim";
export interface DateEdit { id: string; nome: string; campo: DateCampo; atual: string | null; }

// Pop-up de confirmação da edição de data: date picker + Confirmar (persiste via API).
export function DateEditPopup({ edit, titulo, busy, onCancel, onConfirm }: {
  edit: DateEdit; titulo: string; busy: boolean; onCancel: () => void;
  onConfirm: (valor: string | null) => void;
}) {
  const [valor, setValor] = useState(edit.atual ?? "");
  return (
    <>
      <div className="drawer-overlay gm-modal-overlay" onClick={onCancel} />
      <div className="gm-modal gm-modal-sm" role="dialog" aria-label="Editar data">
        <h4>{titulo} — {edit.nome}</h4>
        <label className="gm-field">
          <span>Data</span>
          <input type="date" value={valor} onChange={(e) => setValor(e.target.value)} autoFocus />
        </label>
        <div className="gm-modal-actions">
          <button className="ghost" onClick={onCancel} disabled={busy}>Cancelar</button>
          {edit.atual && (
            <button className="ghost" onClick={() => onConfirm(null)} disabled={busy}
              title="Remove a data">Limpar</button>
          )}
          <button className="theme-btn" onClick={() => onConfirm(valor || null)}
            disabled={busy || (!valor && !edit.atual)}>
            {busy ? "Salvando…" : "Confirmar"}
          </button>
        </div>
      </div>
    </>
  );
}
