// Organograma do time (aba "Home"). Os DADOS vêm de sas_analistas (Gestão → "Gestão de
// analistas"): quem tem organograma=true + papel entra na view. Aqui ficam só helpers PUROS
// (sem Vite/rede) p/ serem testáveis sob node; a resolução de foto (import.meta.glob) e o fetch
// ficam no componente.

export interface OrgPessoa { nome: string; papel: string; email: string }
export interface OrgGrupo  { titulo: string; pessoas: OrgPessoa[] }

// Grupos na ordem canônica das colunas. O grupo é DERIVADO do papel (decisão: 1 dropdown de
// papel na Gestão, sem campo de grupo separado).
export const ORG_GRUPOS = ["Time de Gestão", "Lideranças Técnicas", "Time de Desenvolvimento"] as const;

export const PAPEL_GRUPO: Record<string, string> = {
  "Delivery Manager": "Time de Gestão",
  "Consulting Director": "Time de Gestão",
  "Account Manager": "Time de Gestão",
  "Project Analyst": "Time de Gestão",
  "Tech Lead": "Lideranças Técnicas",
  "Team Lead": "Lideranças Técnicas",
  "DE": "Time de Desenvolvimento",
  "AE": "Time de Desenvolvimento",
};

// Opções do dropdown de papel na Gestão (ordem dos grupos).
export const PAPEIS = Object.keys(PAPEL_GRUPO);

type AnalistaLike = { nome: string; email: string; organograma?: boolean; papel?: string | null };

// Monta os grupos do organograma a partir dos analistas: só entra quem tem organograma=true e um
// papel mapeado; agrupa por PAPEL_GRUPO e devolve na ordem canônica (grupos vazios saem).
export function montarOrganograma(analistas: AnalistaLike[]): OrgGrupo[] {
  const porGrupo = new Map<string, OrgPessoa[]>();
  for (const a of analistas) {
    if (!a.organograma || !a.papel) continue;
    const grupo = PAPEL_GRUPO[a.papel];
    if (!grupo) continue;   // papel desconhecido → fora do organograma
    const lista = porGrupo.get(grupo) ?? [];
    lista.push({ nome: a.nome, papel: a.papel, email: a.email });
    porGrupo.set(grupo, lista);
  }
  return ORG_GRUPOS
    .map((titulo) => ({ titulo, pessoas: porGrupo.get(titulo) ?? [] }))
    .filter((g) => g.pessoas.length > 0);
}

// Iniciais p/ o avatar-fallback: 1ª letra da 1ª e da última palavra (1 palavra → 2 primeiras).
export function iniciais(nome: string): string {
  const t = nome.trim().split(/\s+/).filter(Boolean);
  if (t.length === 0) return "?";
  const s = t.length === 1 ? t[0].slice(0, 2) : t[0][0] + t[t.length - 1][0];
  return s.toUpperCase();
}

// Nome do arquivo de foto derivado do email (chave estável). "" / sem @ → null (→ iniciais).
// Regra: trim + lower-case, "@"→"_at_", "."→"_", sufixo ".png".
export function fotoKey(email: string): string | null {
  const e = email.trim().toLowerCase();
  if (!e || !e.includes("@")) return null;
  return e.replace("@", "_at_").replaceAll(".", "_") + ".png";
}
