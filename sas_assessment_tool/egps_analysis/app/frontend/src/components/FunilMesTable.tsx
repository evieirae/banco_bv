import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "../api";
import { PIPELINE_PROJETO, PHANTOM_ETAPAS_MIGRACAO, ETAPA_PADRAO_MIGRACAO, SEG, SEG_ORDER, STATUS_ABBR, STATUS_HELP } from "../pipeline";
import { mesTag } from "../mesPlan";
import type { PrioEgp } from "../types";

// Tabela do funil de migração cruzado com o mês do plano de priorização.
// Linhas = meses do plano; colunas = Backlog + etapas do funil, subdivididas pelos status.
//
// "Backlog" (1ª coluna) = etapas fantasma (Pré-conversão · Conversão pela Área): ficam
// fora da ordem do funil (PIPELINE_PROJETO), então não têm coluna própria lá e vêm
// antes de tudo aqui, somadas, como contagem cheia — sem quebra por status, por
// decisão do usuário.
//
// Semântica: CROSSTAB, não cumulativa (mudança pedida em 2026-08-17). Cada EGP conta em
// UMA célula — a etapa em que está hoje, na sub-coluna do seu status. A LINHA do mês soma
// o coorte; nenhum bloco de etapa soma o total. Difere de propósito de `_funnel_bars`
// (backend/main.py), que preenche toda etapa com Concluído/status/A Iniciar para desenhar
// as barras: aqui a leitura é "onde cada EGP do mês está parado".
//
// Fonte: /api/priorizacao (mesma queryKey ["priorizacao"] de useMesPlan => cache único),
// que já traz etapa/status por EGP. Recorte fixo da aba Priorização: Indicium +
// dependências transitivas.

const fmt = (n: number) => (n ?? 0).toLocaleString("pt-BR");

/** `extras`: mesma tabela, outra fonte — os EGPs extras, com o mês vindo do ANTECESSOR
 * (/api/funil-mes-extras). A régua de desenho é a MESMA de propósito: duas implementações
 * da mesma crosstab foi como a aba EGPs e o Resumo já discordaram sobre a mesma etapa. */
export function FunilMesTable({ extras }: { extras?: boolean } = {}) {
  // o tipo comum é o que esta tabela de fato lê: mês + EGPs com etapa/status. Os dois
  // payloads têm mais coisa, e amarrar ao menor evita que a tabela passe a depender de
  // campo que só uma das fontes tem.
  const q = useQuery<{ meses: { mes: number; egps: PrioEgp[] }[]; sem_mes_egps?: PrioEgp[] }>({
    queryKey: extras ? ["funil-mes-extras"] : ["priorizacao"],
    queryFn: () => (extras ? api.funilMesExtras() : api.priorizacao()),
    staleTime: 60_000,
  });

  const model = useMemo(() => {
    const stages = PIPELINE_PROJETO.migracao;
    const idx = new Map(stages.map((s, i) => [s, i]));
    // Linhas = meses do plano e, nos extras, uma linha "—" para quem não tem antecessor
    // no plano (casca e EGP novo). Ela entra no total para a tabela fechar com o card;
    // sem isso o leitor vê 18 aqui e 24 lá e não tem como reconciliar.
    const meses: { mes: number | null; egps: PrioEgp[] }[] = [
      ...(q.data?.meses ?? []),
      ...((q.data?.sem_mes_egps ?? []).length ? [{ mes: null, egps: q.data!.sem_mes_egps! }] : []),
    ];

    // counts[m][j][status] = nº de EGPs; backlog[m] = Pré-conversão (etapa fantasma).
    const counts: Record<string, number>[][] = [];
    const totais: number[] = [];
    const backlog: number[] = [];
    // EGP sem etapa gravada entra no PADRÃO INICIAL (1ª etapa do funil), como o status
    // vazio já entrava em "A Iniciar". `padraoLinha` só alimenta a nota de rodapé — a
    // suposição fica declarada em vez de silenciosa.
    const padraoLinha: number[] = [];

    meses.forEach((mm) => {
      const porEtapa: Record<string, number>[] = stages.map(() => ({}));
      let coorte = 0, bl = 0, padrao = 0;
      mm.egps.forEach((e) => {
        let et = e.etapa;
        if (!et) { et = ETAPA_PADRAO_MIGRACAO; padrao += 1; }
        // Backlog: etapa fantasma (Pré-conversão / Conversão pela Área) não tem posição no
        // funil — conta inteira, sem quebra por status (pedido do usuário), e entra no
        // total do mês.
        if (PHANTOM_ETAPAS_MIGRACAO.includes(et)) { bl += 1; coorte += 1; return; }
        const i = idx.get(et);
        // Etapa que não existe no funil do front (backend adiantado): cai no padrão
        // inicial junto com quem não tem etapa. Descartar era o defeito anterior.
        const j2 = i === undefined ? idx.get(ETAPA_PADRAO_MIGRACAO)! : i;
        if (i === undefined) padrao += 1;
        const st = e.status || "A Iniciar";
        coorte += 1;
        porEtapa[j2][st] = (porEtapa[j2][st] ?? 0) + 1;  // uma única célula: etapa atual x status atual
      });
      counts.push(porEtapa);
      totais.push(coorte);
      backlog.push(bl);
      padraoLinha.push(padrao);
    });

    // Sub-colunas de cada etapa: só os status presentes em algum mês (união), na ordem do funil.
    const colsPorEtapa = stages.map((_, j) =>
      SEG_ORDER.filter((s) => counts.some((c) => (c[j]?.[s] ?? 0) > 0)));

    // Linha de total: soma dos meses (mesma estrutura de colunas).
    const totalRow = stages.map((_, j) => {
      const acc: Record<string, number> = {};
      counts.forEach((c) => Object.entries(c[j] ?? {}).forEach(([k, v]) => { acc[k] = (acc[k] ?? 0) + v; }));
      return acc;
    });

    const etapasVisiveis = stages.map((s, j) => ({ etapa: s, j })).filter((x) => colsPorEtapa[x.j].length > 0);

    return {
      meses, counts, totais, backlog, colsPorEtapa, totalRow, etapasVisiveis,
      backlogTotal: backlog.reduce((a, b) => a + b, 0),
      coorteTotal: totais.reduce((a, b) => a + b, 0),
      padraoTotal: padraoLinha.reduce((a, b) => a + b, 0),
    };
  }, [q.data]);

  if (q.error) return <div className="error">{String(q.error)}</div>;
  if (!q.data) return <div className="empty">carregando…</div>;
  if (model.etapasVisiveis.length === 0 && model.backlogTotal === 0)
    return <div className="empty">Sem EGPs com etapa definida no plano de priorização.</div>;

  const { colsPorEtapa, etapasVisiveis } = model;

  // `grp` marca a 1ª sub-coluna de cada etapa (separador vertical entre blocos).
  const cell = (v: number, key: string, grp: boolean) => (
    <td key={key} className={[v ? "" : "zero", grp ? "grp" : ""].filter(Boolean).join(" ") || undefined}>
      {v ? fmt(v) : "—"}
    </td>
  );

  return (
    <>
      <div className="rsm-card rsm-scroll">
        <table className="rsm-tbl fmt">
          <thead>
            <tr>
              <th rowSpan={2} className="fmt-mes">Mês</th>
              <th rowSpan={2} className="fmt-etapa fmt-bl">
                Backlog<span className="help" title="EGPs em etapa fantasma, fora da ordem do funil: Pré-conversão (a pré-conversão começa antes da Conversão do Código para destravar o fluxo) ou Conversão pela Área (conversão de código fora do escopo da Indicium — só a ingestão é acompanhada). Contagem cheia, sem quebra por status.">?</span>
              </th>
              {etapasVisiveis.map(({ etapa, j }) => (
                <th key={etapa} colSpan={colsPorEtapa[j].length} className="fmt-etapa">{etapa}</th>
              ))}
              <th rowSpan={2} className="fmt-etapa">
                Total<span className="help" title="Todos os EGPs da linha (Backlog + etapas do funil). Cada EGP conta em uma única célula, então a linha inteira soma este valor. EGP sem etapa gravada entra na 1ª etapa do funil (padrão inicial).">?</span>
              </th>
            </tr>
            <tr>
              {etapasVisiveis.map(({ etapa, j }) =>
                colsPorEtapa[j].map((s, k) => (
                  <th key={`${etapa}|${s}`} className={`fmt-st${k === 0 ? " grp" : ""}`} title={`${etapa} · ${s}`}
                    style={{ background: SEG[s].bg, color: SEG[s].fg }}>{STATUS_ABBR[s] ?? s}</th>
                )))}
            </tr>
          </thead>
          <tbody>
            {model.meses.map((mm, m) => (
              <tr key={mm.mes ?? "sem"}>
                <td title={mm.mes === null ? "Fora do escopo planejado: a casca (absorvida por um EGP unificado — é ela o antecessor) e o EGP novo, que não substitui ninguém. Nenhum dos dois tem antecessor no plano, então não há mês a herdar." : undefined}>
                  {mm.mes === null ? <b>Adicional</b> : mesTag(mm.mes)}
                </td>
                {cell(model.backlog[m], "bl", true)}
                {etapasVisiveis.map(({ etapa, j }) =>
                  colsPorEtapa[j].map((s, k) => cell(model.counts[m][j][s] ?? 0, `${etapa}|${s}`, k === 0)))}
                <td>{fmt(model.totais[m])}</td>
              </tr>
            ))}
            <tr className="tot">
              <td>Total</td>
              <td className="grp">{fmt(model.backlogTotal)}</td>
              {etapasVisiveis.map(({ etapa, j }) =>
                colsPorEtapa[j].map((s, k) => (
                  <td key={`${etapa}|${s}`} className={k === 0 ? "grp" : undefined}>{fmt(model.totalRow[j][s] ?? 0)}</td>
                )))}
              <td>{fmt(model.coorteTotal)}</td>
            </tr>
          </tbody>
        </table>
      </div>
      <div className="funnel-legend">
        {SEG_ORDER.filter((s) => etapasVisiveis.some(({ j }) => colsPorEtapa[j].includes(s))).map((s) => (
          <span key={s} className="leg"><i style={{ background: SEG[s].bg }} />{s}</span>
        ))}
        <span className="help" title={STATUS_HELP}>?</span>
      </div>
      {model.padraoTotal > 0 && (
        <p className="muted">
          {fmt(model.padraoTotal)} EGP(s) sem etapa gravada contam em
          <b> {ETAPA_PADRAO_MIGRACAO}</b> (padrão inicial) — a etapa real segue vazia até
          alguém definir.
        </p>
      )}
    </>
  );
}
