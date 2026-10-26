// Helpers de classificação de inputs compartilhados entre as telas (detalhe do EGP e
// lista global). Mantidos puros (sem rede/estado) para serem triviais de reusar e testar.

import type { PreworkingRow } from "./types";
import { diasUteis } from "./diasUteis";

// Campos do checklist de pré-working que contam p/ completude (espelha PREWORKING_CAMPOS
// do backend). "" e null contam como "vazio" — só string não-vazia conta como preenchido;
// `recebido` é exceção: só "true" (caixa marcada) conta, "false" continua vazio (o arquivo
// precisa ter chegado de fato para liberar o próximo passo da esteira).
const PREWORKING_CAMPOS = [
  "origem_arquivo", "frequencia", "horario", "tipo_carga", "pos_processamento",
  "dados_sensiveis", "recebido", "data_recebimento",
] as const;

function campoPreenchido(row: PreworkingRow, campo: (typeof PREWORKING_CAMPOS)[number]): boolean {
  if (campo === "recebido") return row.recebido === "true";
  return !!(row[campo] ?? "").trim();
}

// % de completude do checklist de pré-working de 1 input (0-100) — usado no badge da
// tabela de Inputs e no cabeçalho do checklist dentro do InputDetailPanel. 100% = liberado
// para a próxima etapa da esteira (Ingestão UAT), ver auto_avancado no backend.
// `row` ausente = nenhum campo tocado ainda (0%).
export function preworkingPercentual(row: PreworkingRow | undefined | null): number {
  if (!row) return 0;
  const n = PREWORKING_CAMPOS.filter((c) => campoPreenchido(row, c)).length;
  return Math.round((100 * n) / PREWORKING_CAMPOS.length);
}

// Duração do checklist (dias úteis, mesma régua de diasUteis usada na Gestão): do 1º
// toque (iniciado_em) até bater 100% (concluido_em) — os dois setados 1x pelo backend.
// null = ainda não concluído (ou nunca sequer tocado) — não há duração a mostrar.
export function preworkingDuracaoDias(row: PreworkingRow | undefined | null): number | null {
  if (!row?.iniciado_em || !row?.concluido_em) return null;
  return diasUteis(row.iniciado_em.slice(0, 10), row.concluido_em.slice(0, 10));
}

// "Referência dinâmica": input cujo nome real só é resolvido em tempo de execução —
// macro var SAS (&x, &&x&i), loop, ou import em lote de uma pasta — e NÃO uma tabela
// física fixa. Sinais:
//   - '&' no artefato: em SAS '&' é sempre macro (cobre a forma HTML-escapada '&amp;');
//   - '{' / '}' no artefato: notação que o extrator usa p/ refs ambíguas (ex. {SAFRA_NUM});
//   - source_type "macro no membro": vindo da seção DYNAMIC REFS do extrator.
export function isDynamicRef(i: { artifact?: string; source_types?: string }): boolean {
  if (/[&{}]/.test(i.artifact ?? "")) return true;
  return (i.source_types ?? "").includes("macro no membro");
}

export const DYNAMIC_REF_TITLE =
  "Referência dinâmica: o nome real é resolvido em tempo de execução (macro/loop SAS). " +
  "Só se conhece na execução — ex.: import em lote de arquivos de uma pasta, ou tabela com " +
  "a safra no nome. Não é uma tabela física fixa.";

// Chaves canônicas que uma LINHA representa: as safras, quando a linha é uma família de
// safras; a própria chave, quando é um input físico. Serve para cruzar a linha com tabelas
// que continuam chaveadas por safra (gestão, pré-working) — o estado dessas tabelas não
// migrou para a família de propósito (ADR 0002: o estado mora nas safras, por fan-out).
export function chavesDoInput(r: { chave_canonica: string; is_familia?: boolean; membros?: string[] }): string[] {
  // A chave da FAMÍLIA entra junto das safras: anotação nova (comentário da Gestão,
  // checklist de pré-working) é gravada na família — é config de ingestão, uma por
  // família —, e as safras carregam o que já existia antes da unificação.
  return r.is_familia && r.membros?.length ? [r.chave_canonica, ...r.membros] : [r.chave_canonica];
}

// Confirmação antes de escrever numa FAMÍLIA com estado divergente entre as safras.
// A escrita de família é fan-out (grava nas N safras — ADR 0002), então editar etapa/status
// numa família mista SOBRESCREVE estado que alguém pôs safra a safra — inclusive as
// sanitizações da regra 12M/3M. É o comportamento desejado, mas não pode ser silencioso:
// quem clica tem que saber quantas linhas está mexendo. Família homogênea não pergunta nada
// (não há o que sobrescrever).
export function confirmEscritaFamilia(
  r: { is_familia?: boolean; artifact: string; n_safras?: number; estado_misto?: boolean },
  campo: string,
): boolean {
  if (!r.is_familia || !r.estado_misto) return true;
  const n = r.n_safras ?? 0;
  return window.confirm(
    `"${r.artifact}" é uma família de ${n} safras que hoje estão em estados DIFERENTES.\n\n` +
    `Gravar ${campo} aqui escreve nas ${n} safras e sobrescreve o estado divergente ` +
    `(inclusive safras marcadas como Sanitizado).\n` +
    `O valor anterior de cada safra fica no Histórico. Confirmar?`,
  );
}

// Área(s) de um input p/ EXIBIÇÃO e ORDENAÇÃO: principal primeiro entre colchetes, demais
// depois separadas por "|". Ex.: "[Jurídico]|Riscos". Sem principal (ou "(sem área)") -> só a
// lista original. Usada tanto no render quanto no accessor de sort (senão a ordem exibida não
// bate com a ordenada).
export function fmtAreas(areas: string, principal: string | null): string {
  const all = (areas || "").split("|").map((s) => s.trim()).filter(Boolean);
  if (!principal || principal === "(sem área)") return all.join("|");
  const rest = all.filter((a) => a !== principal);
  return `[${principal}]${rest.length ? "|" + rest.join("|") : ""}`;
}

// Etapa/status EFETIVOS de um input — ESPELHO de _eff_etapa()/_eff_status_input() do
// backend (main.py). Mantenha os dois em sincronia: o humano prevalece; sem humano,
// deriva do auto (etapa) / da etapa efetiva (status).
// Trava de etapa/status do input sanitizado por DERIVAÇÃO (14/10/2026): o backend exibe
// Modernizado + Sanitizado e recusa a edição com 409. Devolve o tooltip do select travado,
// ou undefined quando o input é editável. Gravar a etapa à mão tirava o input da derivação
// e ele passava a contar como modernizado (37 inputs em prod, ver sanitizacao.py).
export function travaDerivada(r: { sanitizado_derivado?: string; sanitizado_motivo?: string }): string | undefined {
  if (!r.sanitizado_derivado) return undefined;
  return `Sanitizado automaticamente (${r.sanitizado_motivo ?? r.sanitizado_derivado}): etapa e `
    + "status são derivados e não se editam. O input volta para a fila sozinho se a condição "
    + "deixar de valer — vínculo com a versão nova desfeito ou consumidor repriorizado.";
}

export function effEtapa(etapa: string | null, auto: string): string {
  if (etapa) return etapa;
  return auto === "Disponível" ? "Modernizado" : "A Receber";
}

// Sem status humano, o padrão é "ainda não começou a trabalhar NESSA etapa" (A Iniciar)
// para qualquer etapa que não seja a terminal — não só para "A Receber". Manter só
// "A Receber"->A Iniciar (como antes) tornava impossível um item chegar numa etapa
// intermediária (ex.: Recebido, Pré-Working) sem status humano e aparecer como A Iniciar.
export function effStatusInput(status: string | null, etapa: string | null, auto: string): string {
  if (status) return status;
  const ee = effEtapa(etapa, auto);
  return ee === "Modernizado" ? "Concluído" : "A Iniciar";
}
