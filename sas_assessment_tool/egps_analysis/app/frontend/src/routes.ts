// Roteamento client-side do SPA + deep-links compartilháveis de EGP.
//
// O app é servido na raiz no Databricks App, mas o build usa base relativa
// ("./"), então pode rodar sob um subpath. Derivamos APP_BASE da URL deste
// bundle (carregado de "<base>/assets/..."); sempre começa e termina com "/".
// O backend (_SPAStaticFiles) devolve index.html em qualquer 404, então
// "<base>egps/<id>" carrega o SPA mesmo num refresh/cold-load.

export type View =
  | "resumo" | "monitor" | "outputs" | "readiness"
  | "indicium" | "waves" | "lineage" | "history" | "guia" | "gestao"
  | "acompanhamento" | "tempoetapas" | "genie";

export const TABS: { id: View; label: string; slug: string }[] = [
  // Guia primeiro (onboarding dos analistas); a página INICIAL segue sendo o
  // Resumo (DEFAULT_VIEW) — posição na barra ≠ view de aterrissagem.
  { id: "guia", label: "Home", slug: "guia" },
  { id: "resumo", label: "Resumo", slug: "resumo" },
  { id: "monitor", label: "Inputs", slug: "monitoramento" },       // slug preservado (links salvos)
  { id: "outputs", label: "Outputs", slug: "monitoramento-outputs" },
  { id: "readiness", label: "EGPs", slug: "egps" },
  // Aba "EGPs Atualizados" aposentada (2026-09, spec §5): o sucessor é linha da aba EGPs e
  // a comparação com o antecessor virou seção do detalhe do EGP. /egps-atualizados (com ou
  // sem versao_id) cai no DEFAULT_VIEW via parsePath, como /arquivos-macros e /ingestao.
  { id: "indicium", label: "Escopo", slug: "escopo" },
  { id: "waves", label: "Priorização", slug: "ondas" },
  // Aba "Linhagem" desativada (removida da barra) — o grafo não reflete a escolha de
  // produtor canônico (sub-projeto 2). View/componente mantidos dormentes; re-habilitar =
  // reinserir este entry. /linhagem cai no DEFAULT_VIEW via parsePath.
  { id: "history", label: "Histórico", slug: "historico" },
  // Único Kanban visível ao cliente (BV) — sem responsável interno; ver ONBOARDING/README
  // para a diferença em relação ao Kanban da Gestão (bv_users).
  { id: "acompanhamento", label: "Acompanhamento", slug: "acompanhamento" },
  { id: "gestao", label: "Gestão", slug: "gestao" },
  // Restrita a bv_users (ver App.tsx) — não é dado pra expor a todo mundo (pedido 2026-09-30).
  { id: "tempoetapas", label: "Tempo por Etapa", slug: "tempo-etapas" },
  // Genie embutido (iframe) — restrita a bv_users E só com GENIE_EMBED_URL no ambiente.
  { id: "genie", label: "Perguntas", slug: "perguntas" },
];

export const DEFAULT_VIEW: View = "resumo";

function detectBase(): string {
  try {
    const p = new URL(import.meta.url).pathname;
    const i = p.indexOf("/assets/");
    if (i >= 0) return p.slice(0, i + 1);
  } catch {
    /* dev server / ambiente sem /assets/ -> raiz */
  }
  return "/";
}
export const APP_BASE = detectBase();

// pathname -> segmentos relativos ao APP_BASE (sem barras nas pontas)
function relSegments(pathname: string): string[] {
  let rest = pathname;
  if (APP_BASE !== "/" && rest.startsWith(APP_BASE)) rest = rest.slice(APP_BASE.length);
  else if (rest.startsWith("/")) rest = rest.slice(1);
  rest = rest.replace(/^\/+|\/+$/g, ""); // tira barras das pontas
  return rest ? rest.split("/") : [];
}

export interface Route { view: View; egp: string | null; }

// Views cujo 2º segmento é um id de detalhe: "/egps/<projeto>" (readiness) e
// "/monitoramento/<chave_canonica>" (Inputs). O campo `egp` da rota carrega o id da view
// corrente — projeto ou chave de input; o nome é histórico (a primeira view de detalhe
// foi a de EGP).
const DETAIL_VIEWS: ReadonlySet<View> = new Set(["readiness", "monitor"]);

// "/egps/COBR__x" -> { view:"readiness", egp:"COBR__x" }.
// O id do EGP é o `projeto` URL-encoded. Juntamos os segmentos restantes para
// tolerar "/" no nome: encodeURIComponent gera %2F, que alguns servidores
// decodificam de volta para "/" — o join + decode reconstrói o valor original.
export function parsePath(pathname: string): Route {
  const seg = relSegments(pathname);
  const slug = seg[0] ?? "";
  // alias: a antiga aba "Escopo de migração" foi fundida em "EGPs" — links salvos
  // (/escopo-migracao) devem seguir resolvendo para a aba de readiness.
  const view = slug === "escopo-migracao"
    ? "readiness"
    : (TABS.find((t) => t.slug === slug)?.id ?? DEFAULT_VIEW);
  let egp: string | null = null;
  if (DETAIL_VIEWS.has(view) && seg.length > 1) {
    const raw = seg.slice(1).join("/");
    try { egp = decodeURIComponent(raw); } catch { egp = raw; }
  }
  return { view, egp };
}

export function pathFor(view: View, egp: string | null = null): string {
  const slug = TABS.find((t) => t.id === view)?.slug ?? TABS[0].slug;
  let p = APP_BASE + slug;
  if (DETAIL_VIEWS.has(view) && egp) p += "/" + encodeURIComponent(egp);
  return p;
}

// URL absoluta compartilhável de um EGP (botão "copiar link").
export function egpShareUrl(projeto: string): string {
  return window.location.origin + pathFor("readiness", projeto);
}


// Clique num link interno do SPA (<a href={pathFor(...)}>). Botão do meio, ctrl/cmd+clique e
// shift/alt+clique são do NAVEGADOR (nova guia/janela) — só o clique simples vira navegação
// client-side. `stop` corta a propagação sempre, inclusive nos cliques que deixamos passar:
// quando o link mora dentro de uma linha clicável, abrir em nova guia não pode disparar
// também o onClick da linha na guia atual.
export interface SpaClick {
  button: number; metaKey: boolean; ctrlKey: boolean; shiftKey: boolean; altKey: boolean;
  preventDefault: () => void; stopPropagation: () => void;
}
export function spaLinkClick(e: SpaClick, onOpen: () => void, opts?: { stop?: boolean }): void {
  if (opts?.stop) e.stopPropagation();
  if (e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
  e.preventDefault();
  onOpen();
}
