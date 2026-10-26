// Constantes dos funis de migração — espelham PIPELINE_PROJETO/STATUS_PROJETO do backend
// (main.py). Mantenha em sincronia.

export const PIPELINE_PROJETO: Record<"migracao", string[]> = {
  migracao: [
    "Projetos Habilitados", "Pré-Working + Outputs", "Conversão do Código", "Validação em DES",
    "Aprv. PR + Validação Governança", "Implant. em PRD", "Aplicação de Grant",
    "Validação da Área", "Migrado",
  ],
};

// Etapas "phantom" (fora do funil): espelha PHANTOM_ETAPAS_MIGRACAO no backend
// (main.py). Não deslocam índices em PIPELINE_PROJETO; aparecem só como contagem no
// topo do funil (top_stats), fora de coorte/migrados/total.
//   - "Pré-conversão": EGP pode chegar aqui sem passar por "Conversão do Código"
//     (destrava o funil enquanto BV atrasa outputs).
//   - "Conversão pela Área" (2026-08): a conversão de código deste EGP é feita pela
//     própria área de negócio do BV, fora do escopo da Indicium — só a ingestão dos
//     inputs é acompanhada.
export const PHANTOM_ETAPAS_MIGRACAO = ["Pré-conversão", "Conversão pela Área"];

// Padrão inicial das tabelas de funil por mês: EGP sem etapa gravada é lido como estando
// no COMEÇO do funil, do mesmo jeito que status vazio já era lido como "A Iniciar". Antes
// ele virava nota de rodapé ou coluna própria, e nos dois casos a linha do mês não batia
// com o total. É default de EXIBIÇÃO — `etapa_real` segue vazia, e é ela que o critério
// 189 e a Gestão leem. As BARRAS não usam isto: lá quem não tem etapa fica fora do coorte
// por decisão do backend (ver comentário de `migracao_extras` em main.py).
export const ETAPA_PADRAO_MIGRACAO = PIPELINE_PROJETO.migracao[0];

// Em que balde do funil o EGP está, pelo STATUS. Partição EXAUSTIVA e por construção:
// todo EGP cai em exatamente um balde, então migrado + despriorizado + a_migrar = total da
// linha. Isso é o ponto: as colunas anteriores da tabela por sub-área ("Bloqueados" e
// "Inputs faltando") não fechavam com o total — a 2ª nem era somável entre sub-áreas,
// porque um mesmo input é lido por EGPs de sub-áreas diferentes e pertence às duas.
// Lê STATUS, nunca etapa (ver contaNoTotalEgp e o README §Sub-área BV).
//
// O status lido é o de CONTAGEM (`status_contagem`), não o exibido: no antecessor de um
// vínculo que espelha, `status` diz `Desatualizado`, que é um rótulo de RELAÇÃO e não uma
// posição de trabalho — ele cairia em "a migrar" mesmo com o sucessor já Migrado. O
// backend resolve a cadeia (vinculos.mapa_contagem) e serve o resultado por linha; aqui
// só se escolhe o campo. Fallback para `status` cobre payload antigo e linha sem vínculo,
// onde os dois campos são iguais por construção.
export type BaldeEgp = "migrado" | "despriorizado" | "a_migrar";

export function baldeEgp(
  r: string | null | undefined | { status?: string | null; status_contagem?: string | null },
): BaldeEgp {
  const status = typeof r === "object" && r !== null
    ? (r.status_contagem !== undefined ? r.status_contagem : r.status)
    : r;
  if (status === "Migrado") return "migrado";
  if (status === "Despriorizado e Contabilizado") return "despriorizado";
  return "a_migrar";
}

// Quais linhas do /api/egp-readiness entram nos TOTAIS de EGP. Espelha _ex_deps_contab no
// backend (critério 2026-08-10): a ex-dependência continua LISTADA com badge (retenção e
// auditoria), mas só conta no total se tiver etapa REAL — etapa vazia ou fantasma fica de
// fora. É o que faz o card da aba EGPs dizer 194 enquanto a tabela lista 208.
// Quem soma EGPs (Resumo, cards, tabelas por recorte) tem de filtrar por isto; quem só
// LISTA, não.
// A etapa lida aqui é a GRAVADA (`etapa_real`), nunca a espelhada de um sucessor: o
// critério é denominador, e o backend (_ex_deps_contab / _prio_contabiliza) também lê a
// gravada. Sem isso, uma ex-dependência sem etapa entraria no total só porque ganhou
// vínculo — e o front diria um número e o card do backend, outro.
//
// EXCEÇÃO (2026-09-25, develop): etapa fantasma CONTA quando o status é "Despriorizado e
// Contabilizado". Pré-conversão fica fora da ordem do funil (é anterior a "Projetos
// Habilitados": só conversão de código, sem tabela correta nem nada pronto) — mas
// despriorizar um EGP que já teve pré-conversão é reconhecer o esforço gasto, que é o que
// o nome do status diz. Ver _ex_deps_contab no backend; os dois têm de concordar.
export function contaNoTotalEgp(
  r: { tipo?: string; etapa?: string | null; etapa_real?: string | null; e_extra?: boolean;
       na_linha_base?: boolean; status?: string | null },
): boolean {
  // Extra (sucessor de qualquer tipo de vínculo, ou casca): listado, filtrável e com os
  // inputs dele contando — mas FORA do total base, em contador próprio ao lado. A linha de
  // base não sobe porque o BV mandou versão nova (spec §3.1.2, 28/09/2026).
  if (r.e_extra) return false;
  // Quando o backend serve a LISTA CONGELADA por linha (`na_linha_base`), é ela que
  // decide — o critério "189" foi absorvido por ela (spec §3.1.2): a ex-dependência que
  // estava contabilizada no dia da foto entrou na lista e lá fica, mesmo que a etapa
  // gravada tenha sido limpa depois. Medido em 29/09: no schema de dev, 6 ex da lista
  // já tinham perdido a etapa e a tabela mostrava 187 onde o card dizia 193.
  // A exceção do despriorizado abaixo não se aplica aqui de propósito: com a lista
  // congelada quem decide é a foto, não a etapa de hoje.
  if (r.na_linha_base !== undefined) return r.na_linha_base;
  if (r.tipo !== "ex_dependencia") return true;
  // `undefined` = payload sem o campo (linha antiga) -> usa a exibida, que ali é a mesma.
  // `null`/"" = etapa gravada VAZIA e isso é a resposta, não um motivo para cair na exibida.
  const etapa = r.etapa_real !== undefined ? r.etapa_real : r.etapa;
  if (!etapa) return false;
  return !PHANTOM_ETAPAS_MIGRACAO.includes(etapa)
    || r.status === "Despriorizado e Contabilizado";
}

// "Removido" foi extinto (2026-07): única saída de backlog é "Despriorizado e Contabilizado"
// — EGP nesse status não puxa dependências exclusivas (regra no backend); no plano de
// Priorização ele segue aparecendo como um EGP normal.
// "Em espera" (2026-10-01): EGP parado porque o responsável só avança 1 EGP por vez — não
// é bloqueio externo (Block) nem falta de trabalho (A Iniciar). Tempo neste status é
// EXCLUÍDO das métricas de tempo no backend (_dias_uteis_segmentos em main.py). É valor
// de ESCRITA normal (está em STATUS_PROJETO no backend também) — diferente de
// "Desatualizado" abaixo, que é só leitura.
export const STATUS_PROJETO = ["A Iniciar", "Em Andamento", "Em espera", "Concluído", "Block",
  "Despriorizado e Contabilizado", "Desatualizado", "Migrado"];

// `Desatualizado` é DERIVADO do vínculo, nunca gravado (spec §3.2.6): o status real do
// antecessor fica intacto por baixo e reaparece quando o vínculo é desfeito. O backend
// não o tem em STATUS_PROJETO (main.py) e recusa a escrita com 400.
export const STATUS_DERIVADO_VINCULO = "Desatualizado";
// Vocabulário de ESCRITA: o que um <select> de edição pode oferecer. STATUS_PROJETO segue
// com os 8 porque ele é o vocabulário de LEITURA — filtros, cores (SEG) e colunas do
// Kanban precisam conhecer o derivado. Oferecer o derivado para gravar era um 400 certo.
export const STATUS_PROJETO_EDITAVEL = STATUS_PROJETO.filter((s) => s !== STATUS_DERIVADO_VINCULO);

/** Opções de um <select> de status de EGP. O derivado só entra quando JÁ é o valor atual —
 * e desabilitado, para o select não aparecer vazio num EGP desatualizado (o que leria como
 * "sem status") nem deixar regravá-lo. Para sair de `Desatualizado` desfaz-se o vínculo. */
export function opcoesStatusEgp(atual?: string | null): { value: string; label: string; disabled?: boolean }[] {
  const base = STATUS_PROJETO_EDITAVEL.map((s) => ({ value: s, label: s }));
  if (atual !== STATUS_DERIVADO_VINCULO) return base;
  return [{ value: atual, label: `${atual} (derivado do vínculo)`, disabled: true }, ...base];
}

// Funil de INGESTÃO dos inputs — espelha PIPELINE_INPUT/STATUS_INPUT do backend
// (main.py). etapa = posição no funil; status = progresso na etapa (ortogonal, igual ao
// funil de migração acima). STATUS_INPUT reaproveita de propósito 4 das strings de
// STATUS_PROJETO (mesma paleta SEG) + "Sanitizado" (input que pulou a esteira — NÃO
// conta no funil de ingestão, só como contador informativo) + "Autoprodutor" (2026-08:
// EGP consumidor também cria a tabela — CONTA COMO FEITO, ao contrário de Sanitizado;
// ver _modern()/_autoprodutor_candidatos() no backend e README §Autoprodutor).
export const PIPELINE_INPUT = ["A Receber", "Recebido", "Pré-Working", "Ingestão UAT",
  "PDI + GMUD", "Ingestão PRD", "Aplicação de Grant", "Modernizado"];
export const STATUS_INPUT = ["A Iniciar", "Em Andamento", "Concluído", "Block", "Sanitizado", "Autoprodutor"];

// Checklist manual de pré-working (sas_inputs_preworking) — espelha PREWORKING_* do
// backend (main.py). Mantenha em sincronia.
// Confirmação p/ status TERMINAIS de efeito cascata (critique 2026-08-28, P1):
// Despriorizado recorta dependências exclusivas app-wide; Sanitizado tira o input da
// esteira (via resolvida). Reversível editando de volta — mas não deve acontecer por
// um toque acidental num <select>. Demais status seguem gravando direto.
export function confirmStatusTerminal(novo: string, alvo: string): boolean {
  if (novo !== "Despriorizado e Contabilizado" && novo !== "Sanitizado") return true;
  const efeito = novo === "Sanitizado"
    ? "sai da esteira de ingestão (via resolvida: deixa de gerar dependência)"
    : "sai do backlog (deixa de puxar dependências exclusivas no app inteiro)";
  return window.confirm(`Status "${novo}" em "${alvo}": ${efeito}.\nReversível editando o status de volta (o Histórico guarda o valor anterior). Confirmar?`);
}

export const PREWORKING_FREQUENCIA = ["Diária", "Semanal", "Quinzenal", "Mensal", "Sob demanda", "Carga única"];
export const PREWORKING_TIPO_CARGA = ["Full", "Incremental", "Full + Incremental"];
export const PREWORKING_POS_PROC = ["Mover", "Apagar", "Manter (nenhuma ação)"];
export const PREWORKING_DADOS_SENSIVEIS = ["Sim", "Não"];

// Definições dos status (tooltip único; usado no detalhe e na lista de EGPs).
export const STATUS_HELP = "A Iniciar: habilitado, não começou · Em Andamento: trabalhando · Em espera: parado porque o responsável está focado em outro EGP (tempo não entra nas métricas de tempo) · Concluído: concluiu a etapa · Block: bloqueado, segue no backlog · Desatualizado: existe versão nova (sucessor) e a etapa é espelho dela — edite no sucessor · Despriorizado e Contabilizado: saiu do backlog (esforço já gasto fica contabilizado; deixa de puxar dependências exclusivas — segue visível no plano) · Migrado";

// Natureza do vínculo entre o EGP novo e o(s) antecessor(es) na aba EGPs Atualizados —
// humano decide na troca (sas_egp_atualizados_pipeline.tipo_vinculo), não o pareamento
// automático. Ver EgpAtualizadoDetail (EgpsAtualizadosView.tsx).
export const TIPO_VINCULO_LABEL: Record<string, string> = {
  atualizacao: "Atualizado",
  substituicao: "Descontinuado",
  agrupamento: "Unificado",
};
export const TIPO_VINCULO_HELP = "Atualizado: 1 antecessor, mesmo escopo — o EGP novo faz o mesmo trabalho, numa versão mais nova · Descontinuado: o antecessor foi descontinuado; o EGP novo pode cobrir escopo diferente (inclusive itens que não estavam no corpus) · Unificado: o EGP novo consolida vários antecessores num só (N:1).";
// Rótulo do status "Despriorizado e Contabilizado" quando o motivo é uma troca (pedido
// 2026-09): usa o tipo_vinculo da versão vinculada quando já decidido; sem isso, cai no
// genérico "Substituído" — ainda dá pra saber PELO ícone que não é despriorização real do
// BV, só falta o humano classificar o tipo na aba EGPs Atualizados.
export function statusTrocaLabel(tipoVinculo: string | null | undefined): string {
  return (tipoVinculo && TIPO_VINCULO_LABEL[tipoVinculo]) || "Substituído";
}

// Cor por segmento do funil. Paleta separada por matiz E luminosidade (distinguível sob
// daltonismo — reforçada pela ordem fixa de empilhamento + legenda) com texto "on-color"
// que garante ≥4.5:1 do rótulo. Valores vêm de tokens CSS (única fonte da verdade; ver
// styles.css :root). `bg`/`fg` apontam para as variáveis.
export const SEG: Record<string, { bg: string; fg: string }> = {
  "A Iniciar":                    { bg: "var(--seg-todo)",  fg: "var(--seg-todo-on)" },
  "Em Andamento":                 { bg: "var(--seg-wip)",   fg: "var(--seg-wip-on)" },
  "Em espera":                    { bg: "var(--seg-espera)", fg: "var(--seg-espera-on)" },
  "Concluído":                    { bg: "var(--seg-done)",  fg: "var(--seg-done-on)" },
  "Block":                        { bg: "var(--seg-block)", fg: "var(--seg-block-on)" },
  "Despriorizado e Contabilizado":{ bg: "var(--seg-remc)",  fg: "var(--seg-remc-on)" },
  // Desatualizado: existe versão nova e a etapa é espelho dela. Tom de "atenção, não
  // erro" — conta nos totais e NUNCA conta como migrado, então não pode reusar --seg-migr.
  // Cor PRÓPRIA (não --seg-wip): na barra empilhada ele fica colado em "Em Andamento" e
  // com o mesmo tom os dois viravam um bloco só, sem como ler onde um termina.
  "Desatualizado":                { bg: "var(--seg-desat)", fg: "var(--seg-desat-on)" },
  "Migrado":                      { bg: "var(--seg-migr)",  fg: "var(--seg-migr-on)" },
  // Sanitizado (status de input, exceção terminal) reusa o tom de "saiu do fluxo" de
  // Despriorizado e Contabilizado — mesma semântica ("resolvido, mas não migrado").
  "Sanitizado":                   { bg: "var(--seg-remc)",  fg: "var(--seg-remc-on)" },
  // Autoprodutor reusa o tom de "Concluído" (--seg-done), NÃO o de Sanitizado — é
  // trabalho entregue (via produção interna do próprio EGP), não descarte.
  "Autoprodutor":                 { bg: "var(--seg-done)",  fg: "var(--seg-done-on)" },
};

// Rótulos curtos de status (cabeçalho das tabelas de funil, que são largas); o `title` da
// célula mantém o nome cheio. Só UI — não espelha nada do backend.
export const STATUS_ABBR: Record<string, string> = {
  "A Iniciar": "A Iniciar",
  "Em Andamento": "Em And.",
  "Em espera": "Em espera",
  "Concluído": "Concl.",
  "Block": "Block",
  "Despriorizado e Contabilizado": "Despr.",
  "Desatualizado": "Desatu.",
  "Migrado": "Migrado",
  "Sanitizado": "Sanit.",
  "Autoprodutor": "Autoprod.",
};

// Ordem de empilhamento de baixo p/ cima (espelha os mockups).
// `Desatualizado` está aqui (30/09/2026) porque é status EXIBIDO como qualquer outro: o
// backend já o emite nas barras e nas crosstabs, e ficar fora desta lista fazia o segmento
// ser silenciosamente descartado no desenho — o EGP contava no coorte (denominador) mas não
// aparecia em barra nenhuma, e a barra não fechava 100%. Fica junto de "Despriorizado e
// Contabilizado": os dois dizem "este EGP saiu do fluxo normal", não "andou uma etapa".
export const SEG_ORDER = ["A Iniciar", "Em Andamento", "Em espera", "Concluído", "Block", "Migrado",
  "Desatualizado", "Despriorizado e Contabilizado", "Sanitizado", "Autoprodutor"];
