import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "../api";
import { PIPELINE_INPUT, SEG, SEG_ORDER, STATUS_ABBR } from "../pipeline";
import { mesTag } from "../mesPlan";
import type { FunilIngestaoBucket } from "../types";

// Funil de INGESTÃO (inputs) cruzado com o mês do plano de priorização — irmã da
// FunilMesTable, que faz o mesmo para EGPs. Linhas = meses; colunas = etapas do funil de
// ingestão (PIPELINE_INPUT), subdivididas pelos status.
//
// Universo (/api/funil-ingestao-mes): os inputs do FRONTIER VIVO — os mesmos dos cards da
// Visão geral e das barras de funis.ingestao_deps. Não é o universo do plano congelado (o
// contador de inputs por mês da aba Priorização usa aquele e pode divergir).
//
// Semântica: CROSSTAB — cada input conta em UMA célula (a etapa em que está, na sub-coluna
// do seu status), então a LINHA soma o total. Difere das barras do funil da landing, que
// são cumulativas e ainda escondem a coluna "A Receber" (lá ela vira KPI); aqui "A Receber"
// é coluna normal — é o que explica a maior parte da diferença de escala entre as duas.
//
// Linha "— (sem mês)": input do frontier que nenhum EGP do plano consome. O plano é um
// snapshot congelado e o frontier é vivo, então essa linha é esperada, não erro.

const fmt = (n: number) => (n ?? 0).toLocaleString("pt-BR");
const VAZIO: FunilIngestaoBucket = { ingestao: {}, sanitizados: 0, total: 0 };

/** `extras`: mesma tabela sobre os inputs que NENHUM EGP contável lê, com o mês vindo do
 * ANTECESSOR do extra que os consome (/api/funil-ingestao-mes-extras). */
export function FunilIngestaoMesTable({ extras }: { extras?: boolean } = {}) {
  const q = useQuery({
    queryKey: extras ? ["funil-ingestao-mes-extras"] : ["funil-ingestao-mes"],
    queryFn: extras ? api.funilIngestaoMesExtras : api.funilIngestaoMes,
    staleTime: 60_000,
  });

  const model = useMemo(() => {
    const meses = q.data?.meses ?? [];
    const semMes = q.data?.sem_mes ?? VAZIO;
    // linhas na ordem de exibição: meses do plano + "sem mês" (só se tiver algo)
    const linhas: { key: string; label: string; b: FunilIngestaoBucket }[] = meses.map((m) => ({
      key: `m${m.mes}`, label: mesTag(m.mes), b: m,
    }));
    // Nos extras a linha sem mês é o "Adicional": inputs de quem não tem antecessor no
    // plano (casca e EGP novo). No plano ela é outra coisa — input que ninguém do coorte
    // congelado consome — e continua como "—".
    if (semMes.total > 0 || semMes.sanitizados > 0)
      linhas.push({ key: "sem", label: extras ? "Adicional" : "—", b: semMes });

    // Sub-colunas de cada etapa: só os status presentes em alguma linha (união), na ordem do funil.
    const colsPorEtapa = PIPELINE_INPUT.map((et) =>
      SEG_ORDER.filter((s) => linhas.some((l) => (l.b.ingestao[et]?.[s] ?? 0) > 0)));

    // Linha de total: soma das linhas (mesma estrutura de colunas).
    const totalRow = PIPELINE_INPUT.map((et) => {
      const acc: Record<string, number> = {};
      linhas.forEach((l) => Object.entries(l.b.ingestao[et] ?? {})
        .forEach(([k, v]) => { acc[k] = (acc[k] ?? 0) + v; }));
      return acc;
    });

    const etapasVisiveis = PIPELINE_INPUT.map((etapa, j) => ({ etapa, j })).filter((x) => colsPorEtapa[x.j].length > 0);
    return { linhas, colsPorEtapa, totalRow, etapasVisiveis, semMes };
  }, [q.data, extras]);

  if (q.error) return <div className="error">{String(q.error)}</div>;
  if (!q.data) return <div className="empty">carregando…</div>;
  if (model.etapasVisiveis.length === 0)
    return <div className="empty">Sem inputs no recorte.</div>;

  const { colsPorEtapa, etapasVisiveis } = model;
  const d = q.data;

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
              {etapasVisiveis.map(({ etapa, j }) => (
                <th key={etapa} colSpan={colsPorEtapa[j].length} className="fmt-etapa">{etapa}</th>
              ))}
              <th rowSpan={2} className="fmt-etapa">
                Total<span className="help" title="Inputs distintos com vínculo ativo nos EGPs do recorte (escopo Indicium + dependências) — o mesmo universo do card 'Total de Inputs'. Cada input conta em uma única célula, então a linha inteira soma este valor. Sanitizados ficam fora.">?</span>
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
            {model.linhas.map((l) => (
              <tr key={l.key}>
                <td title={l.key === "sem"
                  ? (extras
                      ? "Fora do escopo planejado: inputs dos extras sem antecessor no plano — a casca (absorvida por um EGP unificado) e o EGP novo. Sem antecessor não há mês a herdar."
                      : "Inputs do recorte que nenhum EGP do plano de priorização consome (o plano é um snapshot congelado; o recorte é vivo).")
                  : undefined}>
                  {l.key === "sem" && extras ? <b>{l.label}</b> : l.label}
                </td>
                {etapasVisiveis.map(({ etapa, j }) =>
                  colsPorEtapa[j].map((s, k) => cell(l.b.ingestao[etapa]?.[s] ?? 0, `${etapa}|${s}`, k === 0)))}
                <td>{fmt(l.b.total)}</td>
              </tr>
            ))}
            <tr className="tot">
              <td>Total</td>
              {etapasVisiveis.map(({ etapa, j }) =>
                colsPorEtapa[j].map((s, k) => (
                  <td key={`${etapa}|${s}`} className={k === 0 ? "grp" : undefined}>{fmt(model.totalRow[j][s] ?? 0)}</td>
                )))}
              <td>{fmt(d.total)}</td>
            </tr>
          </tbody>
        </table>
      </div>
      <div className="funnel-legend">
        {SEG_ORDER.filter((s) => etapasVisiveis.some(({ j }) => colsPorEtapa[j].includes(s))).map((s) => (
          <span key={s} className="leg"><i style={{ background: SEG[s].bg }} />{s}</span>
        ))}
        <span className="help" title="A Iniciar: ainda não começou a etapa · Em Andamento: trabalhando · Concluído: concluiu a etapa · Block: bloqueado">?</span>
      </div>
      <p className="muted">
        Universo: {fmt(d.total + d.sanitizados)} inputs dos {fmt(d.n_egps)} EGPs do recorte
        {d.sanitizados > 0 && <> · {fmt(d.sanitizados)} Sanitizado(s) fora do funil (status terminal — pularam a esteira)</>}
        {model.semMes.total > 0 && <> · {fmt(model.semMes.total)} sem mês (consumidos só por EGPs fora do plano congelado)</>}.
      </p>
    </>
  );
}
