import type { Metrics, ScopeEgps } from "../types";

const fmt = (n: number | undefined) =>
  n === undefined ? "—" : n.toLocaleString("pt-BR");

function Card({ label, value, tone, title }: { label: string; value: string; tone?: string; title?: string }) {
  return (
    <div className={`card ${tone ?? ""}`} title={title}>
      <div className="card-value">{value}</div>
      <div className="card-label">{label}</div>
    </div>
  );
}

export function MetricsBar({ metrics, egps }: { metrics: Metrics | null; egps?: ScopeEgps | null }) {
  const m = metrics ?? {};
  return (
    <section className="metrics compact">
      {egps && (
        <Card label={egps.n_deps || egps.n_ex
            ? `EGPs (${fmt(egps.n_base)} + ${fmt(egps.n_deps)} deps${egps.n_ex ? ` + ${fmt(egps.n_ex)} ex` : ""})`
            : "EGPs no recorte"}
          value={fmt(egps.n_egps)} tone="egps"
          title="EGPs do recorte atual (escopo + filtros de área), incluindo ex-dependências — mesmo total do Resumo e da aba EGPs. Os contadores de inputs seguem o frontier vivo." />
      )}
      <Card label="Inputs a ingerir / distintos"
        value={`${fmt(m.inputs_a_ingerir)} / ${fmt(m.inputs_distintos)}`} tone="danger" />
      <Card label="SAS/Local" value={`${fmt(m.total_saslocal_falta)}/${fmt(m.total_saslocal)}`}
        title="A modernizar / total (SAS/Local — datasets/tabelas locais SAS). X = ainda não modernizadas." />
      <Card label="Transacional" value={`${fmt(m.total_transacional_falta)}/${fmt(m.total_transacional)}`}
        title="A modernizar / total (Transacional — fonte corporativa Sybase/SQL Server/…)." />
      <Card label="Arquivos/Scripts" value={`${fmt(m.total_arquivos_scripts_falta)}/${fmt(m.total_arquivos_scripts)}`}
        title="A modernizar / total (arquivos e scripts)." />
      <Card label="BigQuery" value={`${fmt(m.total_bigquery_falta)}/${fmt(m.total_bigquery)}`}
        title="A modernizar / total (BigQuery — em geral já modernizado por construção, então X≈0)." />
      <Card label="Modernizadas/Sanitizadas" value={fmt(m.total_modernizadas)} tone="ok" />
      <Card label="% modern./sanit." value={m.pct_modernizado !== undefined ? `${m.pct_modernizado}%` : "—"} tone="ok" />
    </section>
  );
}
