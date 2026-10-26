// Colunas do Kanban e o bucket de cada linha — lógica PURA, extraída de GestaoKanban.tsx
// (2026-09) para poder ser testada: `.tsx` não roda sob `node --experimental-strip-types`,
// porque o JSX não é removido. GestaoKanban re-exporta tudo daqui, então os importadores
// (AcompanhamentoView, GestaoMigracao) seguem inalterados.
// Extensão explícita (única no src/): é o único import que sobra em RUNTIME, e o
// `node --experimental-strip-types` do teste não resolve especificador sem extensão. Os
// demais são `import type` e somem na remoção de tipos. Permitido pelo tsconfig
// (allowImportingTsExtensions) e resolvido normalmente pelo Vite.
import { PIPELINE_PROJETO, PIPELINE_INPUT, PHANTOM_ETAPAS_MIGRACAO } from "./pipeline.ts";
import type { GestaoRow, EntityType } from "./gestaoApi";
import type { ReadinessRow } from "./types";

export const SEM_ETAPA = "__sem_etapa";
const PRE_CONVERSAO = "Pré-conversão";
// Mesmo valor de STATUS_PROJETO (pipeline.ts) — reusado aqui como CHAVE de coluna quando
// separarDespriorizados=true (ver Props). Não colide com nenhuma etapa real.
export const STATUS_DESPRIORIZADO = "Despriorizado e Contabilizado";
// Idem, para o EGP que tem sucessor: ele sai da trilha de etapas porque o trabalho está
// acontecendo no sucessor, e deixá-lo numa etapa sugere um andamento que não é dele.
// É STATUS, não etapa — a coluna sai da mesma precedência do despriorizado (spec §3.2.10).
export const STATUS_DESATUALIZADO = "Desatualizado";

export interface KanbanColuna { key: string; label: string; fantasma?: boolean }

// Ordem das colunas — extraída p/ outras telas reusarem exatamente a mesma (não duplicar a
// regra "Pré-conversão primeiro" em dois lugares). `separarDespriorizados` acrescenta as
// colunas extras (ver STATUS_DESPRIORIZADO/STATUS_DESATUALIZADO) no FIM — são desfechos à
// parte do funil principal, não passos dele; `fantasma: true` faz elas só aparecerem quando
// têm card (mesmo padrão de "Conversão pela Área").
export function buildKanbanColunas(
  entity: EntityType = "egp", opts?: { separarDespriorizados?: boolean },
): KanbanColuna[] {
  if (entity === "input") {
    return [
      { key: SEM_ETAPA, label: "Sem etapa" },
      ...PIPELINE_INPUT.map((e) => ({ key: e, label: e })),
    ];
  }
  const fantasmasFim = PHANTOM_ETAPAS_MIGRACAO.filter((e) => e !== PRE_CONVERSAO);
  const colunas: KanbanColuna[] = [
    { key: PRE_CONVERSAO, label: PRE_CONVERSAO, fantasma: true },
    { key: SEM_ETAPA, label: "Sem etapa" },
    ...PIPELINE_PROJETO.migracao.map((e) => ({ key: e, label: e })),
    ...fantasmasFim.map((e) => ({ key: e, label: e, fantasma: true })),
  ];
  if (opts?.separarDespriorizados) {
    colunas.push({ key: STATUS_DESATUALIZADO, label: STATUS_DESATUALIZADO, fantasma: true });
    colunas.push({ key: STATUS_DESPRIORIZADO, label: STATUS_DESPRIORIZADO, fantasma: true });
  }
  return colunas;
}

// Chave de coluna (bucket) de 1 linha — compartilhada entre o bucketing do próprio Kanban e
// o filtro de linha "Etapas do Kanban" da Acompanhamento (que reusa a mesma noção de bucket
// p/ o cliente poder excluir despriorizados via aquele filtro, sem precisar de um controle
// novo). Com separarDespriorizados, um EGP com status "Despriorizado e Contabilizado" cai
// nessa coluna INDEPENDENTE da etapa em que estava — por isso precisa do `readiness` map
// (status vem do funil/ReadinessRow, não de GestaoRow).
export function kanbanColKeyOf(
  r: GestaoRow, entity: EntityType, etapasValidas: Set<string>,
  opts?: { separarDespriorizados?: boolean; readiness?: Map<string, ReadinessRow> },
): string {
  if (opts?.separarDespriorizados && entity === "egp") {
    const st = opts.readiness?.get(r.id)?.status;
    // Despriorizado PRIMEIRO: só cabe um status por EGP, e a despriorização é decisão de
    // gestão — o vínculo com um sucessor não a apaga (spec §3.2.9).
    if (st === STATUS_DESPRIORIZADO) return STATUS_DESPRIORIZADO;
    if (st === STATUS_DESATUALIZADO) return STATUS_DESATUALIZADO;
  }
  return r.etapa && etapasValidas.has(r.etapa) ? r.etapa : SEM_ETAPA;
}
