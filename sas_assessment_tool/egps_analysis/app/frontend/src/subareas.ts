// Sub-área BV: a área INTERNA do cliente (Digital, MIS, Operações, Estratégia - cartões,
// Estratégia - rodas, Riscos) a que pertence o Responsável BV de um EGP. Não confundir com
// "Área" (Cobrança/Riscos/Jurídico), que é a área de NEGÓCIO do EGP e já existe no app.
//
// A sub-área é atributo da PESSOA (cadastro sas_responsaveis_bv, editado na Gestão); o EGP
// a herda do seu responsavel_bv. Aqui ficam só helpers PUROS (sem React/rede) p/ serem
// testáveis sob node; o fetch do cadastro vive em useSubareas.ts.

export interface ResponsavelBvLike { nome: string; subarea?: string | null }

export type MapaSubarea = Map<string, string>;   // nome normalizado -> sub-área

// Bucket de quem não tem sub-área resolvida (sem responsável, responsável fora do cadastro
// ou cadastrado sem sub-área). NUNCA some das listas: é justamente o sinal de "falta
// cadastrar alguém" — esconder viraria EGP invisível.
export const SEM_SUBAREA = "Sem sub-área";

// Chave canônica do nome. `sas_egp_pipeline.responsavel_bv` é texto livre digitado à mão,
// então caixa/acento/espaço duplo não podem separar a mesma pessoa. Espelha _norm_nome_bv
// em backend/main.py — mudou lá, muda aqui.
// Espaços "invisíveis" que JS e Python classificam DIFERENTE: U+0085 (NEL) e U+001C-1F
// (separadores de registro) vêm de export de mainframe; U+200B (zero-width) e U+FEFF (BOM)
// vêm de CSV do Excel. Listados à mão porque `\s` do JS não casa NEL/001C-1F e o do Python
// casa; e `trim()` come o BOM, `strip()` não. Verificado por fuzz diferencial (4k casos).
const ESPACOS = /[\s\u0085\u001c-\u001f\u200b\ufeff]+/gu;

export function normNome(nome: string | null | undefined): string {
  return (nome ?? "")
    .toLowerCase()
    .normalize("NFKD")
    .replace(/\p{M}/gu, "")
    .replace(ESPACOS, " ")
    .trim();
}

export function mapaSubarea(rows: ResponsavelBvLike[]): MapaSubarea {
  const m: MapaSubarea = new Map();
  for (const r of rows) {
    const sub = (r.subarea ?? "").trim();
    if (!sub) continue;              // cadastrado sem sub-área -> cai em SEM_SUBAREA
    m.set(normNome(r.nome), sub);
  }
  return m;
}

export function subareaDe(resp: string | null | undefined, mapa: MapaSubarea): string | null {
  const k = normNome(resp);
  return k ? mapa.get(k) ?? null : null;
}

// Versão multi-valorada: um input herda a sub-área dos EGPs que o consomem, que podem ser
// de sub-áreas diferentes (ver respBvOf em GestaoKanban.tsx). Lista vazia ou nomes sem
// sub-área devolvem [SEM_SUBAREA], nunca [] — senão a linha sumiria de toda contagem.
export function subareasDe(resps: (string | null | undefined)[], mapa: MapaSubarea): string[] {
  const out = new Set<string>();
  for (const r of resps) out.add(subareaDe(r, mapa) ?? SEM_SUBAREA);
  if (out.size === 0) out.add(SEM_SUBAREA);
  return [...out];
}

// Ordem canônica de opções e chips: alfabética pt-BR com SEM_SUBAREA sempre por último.
// Ordem ESTÁVEL de propósito (não por contagem): chip que pula de lugar quando o filtro
// muda é impossível de clicar duas vezes seguidas.
export function ordenarSubareas(subs: Iterable<string>): string[] {
  return [...new Set(subs)].sort((a, b) => {
    if (a === SEM_SUBAREA) return 1;
    if (b === SEM_SUBAREA) return -1;
    return a.localeCompare(b, "pt-BR");
  });
}
