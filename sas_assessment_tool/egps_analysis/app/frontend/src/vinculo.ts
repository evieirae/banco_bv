// Vínculo antecessor -> sucessor: o pouco que a TELA decide — lógica PURA, testável sob
// `node --experimental-strip-types` (`.tsx` não roda: o JSX não é removido).
// Tudo o mais do vínculo é derivado no backend (app/backend/vinculos.py); aqui mora só a
// SUGESTÃO do Substituído, que é UI por definição: um aviso com um botão.
// Extensão explícita no import pelo mesmo motivo de kanbanColunas.ts (único import que
// sobra em runtime no teste).
import { STATUS_DESPRIORIZADO } from "./kanbanColunas.ts";
import type { ReadinessRow } from "./types";

export const TIPO_SUBSTITUIDO = "Substituído";
// Desfecho sugerido pelo Substituído. Mesmo valor de STATUS_PROJETO (pipeline.ts) —
// reusado daqui para não repetir a string acentuada, que já quebrou correspondência
// em silêncio neste repo.
export const STATUS_FECHAMENTO = STATUS_DESPRIORIZADO;

/** No `Substituído` o antecessor fecha e o sucessor começa do zero — mas **classificar
 * nunca muda status sozinho** (spec §3.5.21): o app SUGERE e quem aplica é a gestão, pelo
 * caminho normal de edição de status. Esta função só decide se o aviso aparece.
 *
 * Some assim que o antecessor está fechado — inclusive quando já estava antes do vínculo
 * (despriorizado vence, §3.2.9). */
export function sugereFecharAntecessor(r?: ReadinessRow | null): boolean {
  if (!r || r.vinculo_tipo !== TIPO_SUBSTITUIDO || !r.sucessor) return false;
  return r.status !== STATUS_FECHAMENTO;
}

// ---------------------------------------------------------------------------
// Ignição do vínculo (ticket 20): o motor existia desde o ticket 03 e não havia
// como LIGÁ-LO pela tela. O que segue é o pouco que a UI de criar/desfazer precisa
// decidir sozinha — vocabulário, sugestão de sucessor e leitura do erro do servidor.
// ---------------------------------------------------------------------------

export const TIPO_ATUALIZADO = "Atualizado";
export const TIPO_UNIFICADO = "Unificado";
/** Espelha TIPOS_VINCULO de app/backend/vinculos.py — mesma ordem, mesmos acentos.
 * Acento aqui é significativo: "Substituido" seria recusado com 400 pelo servidor. */
export const TIPOS_VINCULO = [TIPO_ATUALIZADO, TIPO_SUBSTITUIDO, TIPO_UNIFICADO];

/** O tipo NÃO é derivável (spec §1, medido em 24/09/2026: `tipos_acordo` tem nome idêntico
 * ao antecessor e overlap 0,0; quatro renomeações têm overlap ≥0,8). A tela explica o que
 * cada um significa e a gestão escolhe — nada de pré-seleção. */
export const TIPO_AJUDA: Record<string, string> = {
  [TIPO_ATUALIZADO]: "nova versão do mesmo EGP: este fica com status Desatualizado e a etapa vira espelho da do sucessor",
  [TIPO_SUBSTITUIDO]: "outro EGP entra no lugar deste: o sucessor entra no escopo e a gestão fecha este como Despriorizado e Contabilizado",
  [TIPO_UNIFICADO]: "N antecessores viram 1 sucessor: este fica Desatualizado e espelha a etapa do unificador",
};

/** Só vale PATCH quando os dois campos estão preenchidos — vínculo pela metade não é
 * vínculo (mesma régua de `mapa_vinculos` no backend, que ignora a linha incompleta). */
export function vinculoCompleto(tipo: string, sucessor: string): boolean {
  return TIPOS_VINCULO.includes(tipo.trim()) && sucessor.trim() !== "";
}

// Sufixo da chave do sucessor no corpus: `Área__nome__ATU<data de recebimento>`
// (spec §2 etapa 2). Mesmo separador de `_ATU` em app/backend/egps_atualizados.py.
const SUF_ATU = "__ATU";

/** Chave da ABA (`Área__nome`) embutida numa chave do CORPUS (`Área__nome__ATU<data>`),
 * ou null quando o projeto não nasceu de uma versão recebida. É a ponte entre as duas
 * colunas que o ticket 20 encontrou confundidas. */
export function baseAtu(projeto: string): string | null {
  const i = (projeto || "").lastIndexOf(SUF_ATU);
  return i > 0 ? projeto.slice(0, i) : null;
}

/** Projetos do corpus que nasceram da versão apontada por `egp_atualizado_key`, os mais
 * ANTIGOS primeiro. A ordem é a da cadeia (§2 etapa 5): numa v3, o sucessor imediato do
 * antecessor original é a v2, não a última chegada. */
export function sucessoresCandidatos(atuKey: string | null | undefined,
                                     projetos: readonly string[]): string[] {
  const alvo = (atuKey || "").trim();
  if (!alvo) return [];
  return projetos.filter((p) => baseAtu(p) === alvo).sort();
}

/** Sucessor a PRÉ-PREENCHER no formulário: só quando a chave antiga casa com **um**
 * projeto do corpus. Com duas ou mais versões no corpus a escolha é da cadeia e o app
 * não adivinha — os candidatos aparecem na busca e o humano aponta.
 *
 * Isto economiza a busca entre ~1.260 projetos sem inventar nada: o `egp_atualizado_key`
 * já foi confirmado por um humano, e o que falta ali é só o TIPO, que não é derivável. */
export function sucessorSugerido(atuKey: string | null | undefined,
                                 projetos: readonly string[]): string | null {
  const c = sucessoresCandidatos(atuKey, projetos);
  return c.length === 1 ? c[0] : null;
}

/** Mensagem legível de um erro do PATCH. As 4 guardas do servidor (tipo inválido 400,
 * não-gestão 403, sucessor fora do corpus 404, EGP já Migrado 409) já vêm com texto em
 * português no `detail` do FastAPI; o que faltava era não perdê-lo no caminho.
 *
 * Nunca devolve vazio: erro invisível é exatamente a falha silenciosa que o ticket 20
 * descreve. Sem `detail` reconhecível, o texto cru vale mais do que nada. */
export function mensagemErroVinculo(e: unknown): string {
  const cru = String((e as { message?: string })?.message ?? e ?? "").trim();
  const m = cru.match(/"detail"\s*:\s*"((?:[^"\\]|\\.)*)"/);
  const detalhe = m
    ? m[1].replace(/\\(["\\/])/g, "$1").replace(/\\n/g, " ").trim()
    : "";
  return detalhe || cru || "falha desconhecida ao salvar o vínculo";
}

// --- recorte da aba EGPs (ticket 21, 29/09/2026) -----------------------------
// O seletor de recorte ganhou dois valores. Eles NÃO são recortes do backend: os dois
// leem o mesmo payload de `indi_deps` e filtram na tela (ver `recorteApi`). Consultar o
// servidor duas vezes para o mesmo recorte é exatamente como a tabela e o contador de
// extras passam a discordar — foi o defeito que este ticket corrigiu (37 × 18).
export type RecorteEgp = "indi" | "indi_deps" | "base" | "indi_deps_extras" | "extras";

export const RECORTES: { id: RecorteEgp; label: string }[] = [
  { id: "indi", label: "escopo: só Indicium" },
  // os 193 da linha de base congelada: sem os extras, que têm contador próprio
  { id: "indi_deps", label: "Indicium + dependências" },
  { id: "base", label: "escopo: todos" },
  { id: "indi_deps_extras", label: "Indicium + dependências + extras" },
  { id: "extras", label: "só os extras" },
];

/** Qual recorte pedir ao `/api/egp-readiness`. Os dois recortes novos são vistas do
 * `indi_deps` — o payload já traz o extra marcado (`e_extra`) e o contador do card. */
export function recorteApi(r: RecorteEgp): string {
  return r === "extras" || r === "indi_deps_extras" ? "indi_deps" : r;
}

/** A linha passa neste recorte? Só o eixo EXTRA — área, status, chips e o filtro de
 * retenção (`na_linha_base`) são independentes e ficam na view.
 *
 * `indi_deps` exclui o extra de propósito: é o recorte dos 193, e o extra existe
 * justamente para contar à parte. `indi`/`base` seguem sem filtrar: ali o extra aparece
 * como sempre apareceu — a decisão da gestão foi sobre o recorte com dependências. */
export function passaNoRecorte(r: RecorteEgp, linha: { e_extra?: boolean }): boolean {
  if (r === "extras") return !!linha.e_extra;
  if (r === "indi_deps") return !linha.e_extra;
  return true;
}

// ---------------------------------------------------------------------------
// POR QUE um EGP é extra, no grão do filtro (29/09/2026). Antes era um valor só
// ("extra") e a distinção vivia no tooltip; a gestão pediu para separar. O backend manda
// `extra_tipos` pronto (`vinculos.tipos_do_extra`) — aqui só mora o vocabulário da tela.

/** Ordem de exibição: os três vínculos, depois os dois estruturais. */
export const TIPOS_EXTRA = ["Atualizado", "Substituído", "Unificado", "casca", "novo"] as const;
export type TipoExtra = (typeof TIPOS_EXTRA)[number];

export const TIPO_EXTRA_LABEL: Record<string, string> = {
  Atualizado: "atualizado",
  "Substituído": "substituído",
  Unificado: "unificado",
  casca: "casca",
  novo: "novo",
};

export const TIPO_EXTRA_AJUDA: Record<string, string> = {
  Atualizado: "versão nova de um EGP do corpus: o antecessor passa a exibir a etapa dele e fica como Desatualizado.",
  "Substituído": "entrou no lugar de um EGP que foi despriorizado — trajetórias independentes, o antecessor fecha.",
  Unificado: "absorveu um ou mais EGPs num só; os antecessores sem inventário próprio viram casca.",
  casca: "antecessor absorvido por um unificador, sem inventário próprio — existe para o esforço dele não sumir.",
  novo: "entrou no escopo depois do congelamento e não substitui ninguém; declarado à mão em Gestão.",
};

/** A linha passa no filtro de tipo de extra? Vazio = não filtra.
 *
 * Interseção, não igualdade: um sucessor pode ter antecessores de tipos DIFERENTES (o
 * `Project_Fyf_Reneg_BQ_202608 1` é Atualizado por um e Substituído por outro), e quem
 * filtra "unificado" quer ver todos que TÊM unificado, não só os exclusivamente unificados. */
// ---- papel no vínculo (os DOIS lados) -------------------------------------------------
// O mesmo vínculo tem dois nomes, um por ponta, e a tabela mostrava só o do antecessor
// (pelo status `Desatualizado`). Quem abre a lista quer saber de qualquer EGP se ele é o
// que saiu ou o que entrou — e um EGP no meio de uma cadeia é os dois.
export const PAPEL_ANTECESSOR: Record<string, string> = {
  [TIPO_ATUALIZADO]: "Desatualizado",
  [TIPO_UNIFICADO]: "Unificado",
  [TIPO_SUBSTITUIDO]: "Substituído",
};
export const PAPEL_SUCESSOR: Record<string, string> = {
  [TIPO_ATUALIZADO]: "Atualizado",
  [TIPO_UNIFICADO]: "Unificador",
  [TIPO_SUBSTITUIDO]: "Substituto",
};

/** Papel -> tipo do vínculo que o gerou, para o ícone reaproveitar a forma da família. */
export const PAPEL_FAMILIA: Record<string, string> = {
  Desatualizado: TIPO_ATUALIZADO, Atualizado: TIPO_ATUALIZADO,
  Unificado: TIPO_UNIFICADO, Unificador: TIPO_UNIFICADO,
  "Substituído": TIPO_SUBSTITUIDO, Substituto: TIPO_SUBSTITUIDO,
};

/** O vocabulário ÚNICO da coluna Tipo (30/09/2026): os seis papéis do vínculo mais os
 * casos de extra que não são papel nenhum ("novo" e, desde 13/10/2026, a dependência nova).
 * Antes eram dois grupos de badge lado a lado ("tipo de extra" + "papel"), dizendo a mesma
 * coisa com palavras diferentes. */
export const PAPEIS_VINCULO = ["Desatualizado", "Atualizado", "Unificado", "Unificador",
  "Substituído", "Substituto", "novo", "dependência nova"] as const;

export const PAPEL_AJUDA: Record<string, string> = {
  novo: "entrou no escopo depois do congelamento e não substitui ninguém; declarado à mão em Gestão.",
  "dependência nova": "dependência que o grafo puxou depois do congelamento: um EGP da linha de base lê o que ela produz. Os 193 estão fechados, então ela conta como extra e os inputs exclusivos dela vão para o balde dos extras.",
  Desatualizado: "existe versão nova deste EGP: a etapa vira espelho da do sucessor e não se edita aqui.",
  Atualizado: "é a versão nova de outro EGP do corpus, que passou a exibir Desatualizado.",
  Unificado: "foi absorvido por um unificador. Inclui a CASCA — antecessor sem inventário próprio, que existe para o esforço dele não sumir —, inclusive a declarada à mão cujo unificador ainda não está no corpus.",
  Unificador: "absorveu um ou mais EGPs num só.",
  "Substituído": "outro EGP entrou no lugar deste — as trajetórias seguem independentes e a gestão fecha este.",
  Substituto: "entrou no lugar de um EGP despriorizado; não herda a etapa dele.",
};

/** Os papéis desta linha no vínculo, sem repetir e na ordem dos tipos.
 *
 * Os dois lados vêm de fontes diferentes de propósito: o vínculo é GRAVADO no antecessor
 * (`vinculo_tipo`), e o lado do sucessor só existe pela inversão que o backend manda em
 * `antecessores`. Uma linha pode ter os dois (cadeia v1 -> v2 -> v3) e um sucessor pode ter
 * antecessores de tipos diferentes, então é lista. */
export function papeisDoVinculo(linha: {
  vinculo_tipo?: string | null;
  sucessor?: string | null;
  antecessores?: { tipo: string | null }[];
  extra_tipos?: string[];
}): string[] {
  const out: string[] = [];
  const push = (p?: string) => { if (p && !out.includes(p)) out.push(p); };
  if (linha.vinculo_tipo && linha.sucessor) push(PAPEL_ANTECESSOR[linha.vinculo_tipo]);
  for (const a of linha.antecessores ?? []) push(PAPEL_SUCESSOR[a.tipo ?? ""]);
  // A CASCA deixou de ser valor próprio (30/09/2026): ela É o antecessor de um
  // unificador, só que sem inventário, então entra em `Unificado` — que é o que ela é.
  // Isso também alcança a casca declarada à mão em egps_casca.csv cujo unificador não
  // está no corpus: ela não tem vínculo e, sem esta linha, ficaria sem papel nenhum.
  // `novo` e `dependencia` ficam, porque são os jeitos de ser extra sem ser ponta de
  // vínculo algum. O backend manda `dependencia` (sem acento, valor de dado); a tela diz
  // "dependência nova", que é o que ela é.
  for (const t of linha.extra_tipos ?? []) {
    if (t === "casca") push(PAPEL_ANTECESSOR[TIPO_UNIFICADO]);
    else if (t === "novo") push(t);
    else if (t === "dependencia") push("dependência nova");
  }
  return out;
}

/** A linha passa no filtro de papel? Vazio = não filtra. Interseção, não igualdade: quem
 * filtra "Unificador" quer todos que SÃO unificador, inclusive o que também é outra
 * coisa (o meio de uma cadeia é duas pontas ao mesmo tempo). */
export function passaNoPapel(sel: Set<string>, linha: Parameters<typeof papeisDoVinculo>[0]): boolean {
  if (!sel.size) return true;
  return papeisDoVinculo(linha).some((p) => sel.has(p));
}

export function passaNoTipoExtra(sel: Set<string>, linha: { extra_tipos?: string[] }): boolean {
  if (!sel.size) return true;
  return (linha.extra_tipos ?? []).some((t) => sel.has(t));
}

