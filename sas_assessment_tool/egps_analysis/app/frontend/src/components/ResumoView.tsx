import { useMemo, type ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "../api";
import { FunnelChart } from "./FunnelChart";
import { FunilMesTable } from "./FunilMesTable";
import { FunilIngestaoMesTable } from "./FunilIngestaoMesTable";
import type { ReadinessRow, ResumoFunil, ResumoOrigem, AppConfig, EgpExtra } from "../types";
import type { View } from "../routes";
import { setTabState } from "../tabState";
import { useSubareas } from "../useSubareas";
import { SEM_SUBAREA, subareaDe, ordenarSubareas } from "../subareas";
import { baldeEgp, contaNoTotalEgp } from "../pipeline";

const fmt = (n: number) => (n ?? 0).toLocaleString("pt-BR");

// Por que cada extra está fora da lista — só no detalhe, nunca no filtro (§3.1.2).
const EXTRA_MOTIVO: Record<string, string> = {
  sucessor: "versão nova",
  casca: "casca",
  // "entrou no corpus depois do congelamento" era a redação do ticket 19, quando `novo`
  // significava "está fora da lista" — e por isso pegava ex-dependência antiga. Agora é
  // declaração explícita (sas_app_config): entrou no escopo e não substitui ninguém.
  novo: "novo no escopo, não substitui ninguém",
};

// A lista dos extras para o tooltip do card. Trunca em 20: o tooltip é para reconhecer o
// que chegou, não para auditar — a aba EGPs, filtrada por Tipo=extra, tem a lista inteira.
function extrasLabel(rows: EgpExtra[]): string {
  const vis = rows.slice(0, 20).map(
    (r) => `• ${r.projeto}${r.motivo ? ` (${EXTRA_MOTIVO[r.motivo] ?? r.motivo})` : ""}`);
  if (rows.length > vis.length) vis.push(`… e mais ${rows.length - vis.length}`);
  return vis.join("\n");
}

function Card({ label, value, tone, big, extra, title }: { label: string; value: number; tone?: string; big?: boolean; extra?: string; title?: string }) {
  return (
    <div className={`lg-card ${tone ?? ""} ${big ? "big" : ""}`} title={title}>
      <div className="lg-val">{fmt(value)}{extra ? <span className="lg-extra"> {extra}</span> : null}</div>
      <div className="lg-lbl">{label}</div>
    </div>
  );
}

// Tabela "Funil por área": visão escopo (5 colunas) ou + dependências (coluna extra "Dependências").
function FunilTable({ d, withDeps }: { d: ResumoFunil; withDeps?: boolean }) {
  return (
    <div className="rsm-card">
      <table className="rsm-tbl">
        <thead>
          <tr>
            <th>
              Área Principal
              <span className="help" title="Um input pode estar relacionado a múltiplas áreas, podendo ser áreas qualificadas ou não. Áreas qualificadas são áreas que possuem ao menos 1 EGP consumindo do input. A área principal é definida da seguinte forma: dentre as áreas qualificadas, escolhe-se Cobrança preferencialmente, seguindo para a área qualificada com mais EGPs relacionados ao input; em caso de empate escolhe-se por ordem alfabética. Uma área não qualificada nunca vira principal — por isso pode aparecer aqui com 0 projetos e, ainda assim, ter inputs relacionados a ela na aba Inputs.">?</span>
            </th><th>Qtd. Projetos · DOR 1</th>
            {withDeps && <th>Dependências</th>}
            <th>EGPs Enviados</th><th>EGPs Analisados</th><th>Inputs não Modernizados</th>
          </tr>
        </thead>
        <tbody>
          {d.rows.map((r) => r.a_parte ? (
            // Extras à parte: os EGPs ficam fora do Total (como o "(+N extra)" do card Total
            // de EGPs), os inputs entram — o Total de Inputs do card também os conta.
            <tr key={r.area} title="Extras (versões novas, cascas e dependências novas): os EGPs ficam fora do Total, que é a linha de base — como o (+N extra) do card Total de EGPs. Os inputs que só eles leem entram no Total, como no card Total de Inputs.">
              <td>{r.area} (à parte)</td><td>+{fmt(r.qtd_dor1)}</td>
              {withDeps && <td className="zero">—</td>}
              <td>+{fmt(r.egps_enviados)}</td><td>+{fmt(r.egps_analisados)}</td>
              <td className={r.inputs_nao_modernizados > 0 ? "neg" : "zero"}>{fmt(r.inputs_nao_modernizados)}</td>
            </tr>
          ) : (
            <tr key={r.area}>
              <td>{r.area}</td><td>{fmt(r.qtd_dor1)}</td>
              {withDeps && <td className={!(r.deps ?? 0) ? "zero" : undefined}>{fmt(r.deps ?? 0)}</td>}
              <td>{fmt(r.egps_enviados)}</td><td>{fmt(r.egps_analisados)}</td>
              <td className={r.inputs_nao_modernizados > 0 ? "neg" : "zero"}>{fmt(r.inputs_nao_modernizados)}</td>
            </tr>
          ))}
          <tr className="tot">
            <td>Total</td><td>{fmt(d.total.qtd_dor1)}</td>
            {withDeps && <td>{fmt(d.total.deps ?? 0)}</td>}
            <td>{fmt(d.total.egps_enviados)}</td><td>{fmt(d.total.egps_analisados)}</td>
            <td>{fmt(d.total.inputs_nao_modernizados)}</td>
          </tr>
        </tbody>
      </table>
    </div>
  );
}

// Tabela "Inputs por origem" com coluna visual de % modernizado (barra + valor).
// O bucket "Arquivo" agrega arquivos E scripts (%INCLUDE) — mesmo agrupamento do card
// "Arquivos/Scripts" da aba Inputs; o rótulo explicita isso.
const BUCKET_LABEL: Record<string, string> = { Arquivo: "Arquivo/Script" };

// `notaCasco`: só na visão + dependências, a que o card Total de Inputs acompanha — lá o
// card conta também o placeholder `casco::` dos unificados, que não é origem de ingestão.
function OrigemTable({ d, notaCasco }: { d: ResumoOrigem; notaCasco?: boolean }) {
  const pctCell = (mod: number, total: number) => {
    const pct = total > 0 ? Math.round((100 * mod) / total) : 0;
    return (
      <td className="rsm-pct">
        <div className="rsm-bar"><div style={{ width: `${pct}%` }} /></div>
        <span>{pct}%</span>
      </td>
    );
  };
  return (
    <div className="rsm-card">
      <table className="rsm-tbl">
        <thead>
          <tr><th>Origem</th><th>Total</th><th>Modernizado</th><th>Não Modernizado</th><th>% Modernizado</th></tr>
        </thead>
        <tbody>
          {d.rows.map((r) => (
            <tr key={r.bucket} className={r.bucket === "BigQuery" ? "hl" : undefined}>
              <td>{BUCKET_LABEL[r.bucket] ?? r.bucket}</td>
              <td>{fmt(r.total)}</td>
              <td className={r.modernizado > 0 ? "pos" : "zero"}>{fmt(r.modernizado)}</td>
              <td className={r.nao_modernizado > 0 ? "neg" : "zero"}>{fmt(r.nao_modernizado)}</td>
              {pctCell(r.modernizado, r.total)}
            </tr>
          ))}
          <tr className="tot">
            <td>Total</td><td>{fmt(d.total.total)}</td><td>{fmt(d.total.modernizado)}</td>
            <td>{fmt(d.total.nao_modernizado)}</td>
            {pctCell(d.total.modernizado, d.total.total)}
          </tr>
        </tbody>
      </table>
      {notaCasco && (d.fora_das_origens ?? 0) > 0 && (
        <p className="muted">
          + {fmt(d.fora_das_origens ?? 0)} placeholder(s) <code>casco::</code> dos EGPs unificados,
          que o card Total de Inputs conta e esta tabela não (não são origem de ingestão).
        </p>
      )}
    </div>
  );
}

// Par escopo | + dependências, lado a lado, com chip identificando o universo de cada tabela.
function Pair({ esc, deps }: { esc: ReactNode; deps: ReactNode | null }) {
  return (
    <div className="rsm-pair">
      <div className="rsm-block"><span className="rsm-chip esc">Escopo Indicium</span>{esc}</div>
      {deps && <div className="rsm-block"><span className="rsm-chip deps">+ dependências</span>{deps}</div>}
    </div>
  );
}

// "EGPs por sub-área BV": recorte por ÁREA INTERNA DO CLIENTE (quem cobra o quê do lado
// do BV), não por área de negócio do EGP. Calculada no cliente sobre /api/readiness —
// mesma queryKey da aba EGPs, então sai do cache sem query nova no warehouse.
// `extras`: a mesma tabela sobre os EXTRAS (o "+N extra" do card Total de EGPs), que a
// tabela da linha de base deixa de fora — as duas são disjuntas e juntas dão o recorte.
function SubareaTable({ onNav, extras }: { onNav: (v: View) => void; extras?: boolean }) {
  const q = useQuery({ queryKey: ["egp-readiness", "indi_deps"], queryFn: () => api.egpReadiness("indi_deps") });
  const { mapa, pronto: cadastroPronto } = useSubareas();
  // /api/egp-readiness LISTA todas as ex-dependências (badge de retenção/auditoria), mas só
  // as com ETAPA REAL entram nos totais de EGP — mesmo critério de _ex_deps_contab no
  // backend (2026-08-10), usado pelo card da aba EGPs, pelo funil e pela tabela por área.
  // Sem esse filtro esta tabela somava 208 onde o resto do app mostra 194.
  // Nos extras o filtro é `e_extra`, o mesmo do recorte "só os extras" da aba EGPs
  // (passaNoRecorte) — contaNoTotalEgp os exclui por definição.
  const rows: ReadinessRow[] = (q.data?.rows ?? []).filter(extras ? (r) => !!r.e_extra : contaNoTotalEgp);

  const linhas = useMemo(() => {
    type Acc = { sub: string; egps: number; aMigrar: number; migrados: number; despri: number };
    const m = new Map<string, Acc>();
    for (const r of rows) {
      const sub = subareaDe(r.responsavel_bv, mapa) ?? SEM_SUBAREA;
      const a = m.get(sub) ?? { sub, egps: 0, aMigrar: 0, migrados: 0, despri: 0 };
      a.egps++;
      // Partição por STATUS (baldeEgp): a migrar + migrados + despriorizados = EGPs da
      // linha, sempre. Migrado é STATUS e nunca etapa — mesma leitura da Priorização
      // (WavesView) e do funil do topo desta página (main.py: "status-based (nao 'chegou na
      // ultima etapa'), por pedido"). EGP despriorizado também chega na etapa Migrado, e EGP
      // com status Migrado pode estar numa etapa anterior.
      const balde = baldeEgp(r);
      if (balde === "migrado") a.migrados++;
      else if (balde === "despriorizado") a.despri++;
      else a.aMigrar++;
      m.set(sub, a);
    }
    const ordem = ordenarSubareas([...m.keys()]);
    return ordem.map((s) => m.get(s)!);
  }, [rows, mapa]);

  const tot = useMemo(() => linhas.reduce((t, l) => ({
    egps: t.egps + l.egps, aMigrar: t.aMigrar + l.aMigrar, migrados: t.migrados + l.migrados,
    despri: t.despri + l.despri,
  }), { egps: 0, aMigrar: 0, migrados: 0, despri: 0 }), [linhas]);

  const pct = (num: number, den: number) => (den > 0 ? Math.round((100 * num) / den) : 0);
  // % Migrado: dos EGPs que entram no fluxo de migração (a migrar + migrados, excluindo
  // despriorizados: denominador = egps - despri, equivalente a migrados + aMigrar mas
  // expresso a partir do total da linha, mais direto de ler). % Total: dos EGPs da sub-área
  // (todos, incluindo despriorizados no denominador), quantos já saíram do fluxo — migrados
  // OU despriorizados contam como "resolvidos" no numerador — visão de progresso absoluto
  // da carteira.
  const pctMigrado = (l: { migrados: number; despri: number; egps: number }) => pct(l.migrados, l.egps - l.despri);
  const pctTotal = (l: { migrados: number; despri: number; egps: number }) => pct(l.migrados + l.despri, l.egps);

  // Clique: prepara o filtro da aba EGPs e navega (a view lê o store ao montar). Zera os
  // demais filtros E força o recorte (indi_deps, ou "só os extras") — o tabState PERSISTE
  // entre navegações, então sem isso a aba abriria com o escopo/área que o usuário deixou
  // lá antes e mostraria um número diferente do que ele acabou de clicar.
  const abrir = (sub: string) => {
    setTabState("egps.scope", extras ? "extras" : "indi_deps");
    for (const k of ["egps.area", "egps.mes", "egps.status", "egps.etapa", "egps.respbv", "egps.tipo",
      "egps.tipoExtra", "egps.vinculo"]) {
      setTabState(k, new Set<string>());
    }
    setTabState("egps.q", "");
    setTabState("egps.subarea", new Set([sub]));
    onNav("readiness");
  };

  // espera TAMBÉM o cadastro: sem ele todas as linhas cairiam em "Sem sub-área" por um frame
  if (!cadastroPronto || (q.isFetching && rows.length === 0)) return <div className="rsm-card muted">carregando…</div>;
  if (q.error) return <div className="error">{String(q.error)}</div>;

  return (
    <div className="rsm-card">
      <table className="rsm-tbl">
        <thead>
          <tr>
            <th>Sub-área BV</th><th>EGPs</th><th>A migrar</th><th>Migrados</th>
            <th>Despriorizados</th><th>% Migrado</th><th>% Total</th>
          </tr>
        </thead>
        <tbody>
          {linhas.map((l) => (
            <tr key={l.sub} style={{ cursor: "pointer" }} title="Abrir a aba EGPs filtrada por esta sub-área"
              onClick={() => abrir(l.sub)}>
              <td>{l.sub}</td>
              <td>{fmt(l.egps)}</td>
              <td className={l.aMigrar > 0 ? "neg" : "zero"}>{fmt(l.aMigrar)}</td>
              <td>{fmt(l.migrados)}</td>
              <td className="zero">{fmt(l.despri)}</td>
              <td className="rsm-pct">
                <div className="rsm-bar"><div style={{ width: `${pctMigrado(l)}%` }} /></div>
                <span>{pctMigrado(l)}%</span>
              </td>
              <td className="rsm-pct">
                <div className="rsm-bar"><div style={{ width: `${pctTotal(l)}%` }} /></div>
                <span>{pctTotal(l)}%</span>
              </td>
            </tr>
          ))}
          <tr className="tot">
            <td>Total</td><td>{fmt(tot.egps)}</td><td>{fmt(tot.aMigrar)}</td>
            <td>{fmt(tot.migrados)}</td><td>{fmt(tot.despri)}</td>
            <td>{pctMigrado(tot)}%</td>
            <td>{pctTotal(tot)}%</td>
          </tr>
        </tbody>
      </table>
    </div>
  );
}

export function ResumoView({ cfg, onNav }: { cfg: AppConfig | null; onNav: (v: View) => void }) {
  const land = useQuery({ queryKey: ["landing"], queryFn: api.landing });
  const resumo = useQuery({ queryKey: ["resumo"], queryFn: api.resumo });
  const funis = useQuery({ queryKey: ["funis"], queryFn: api.funis });
  // Os extras por extenso. O "(+N extra)" diz QUANTOS; sem a lista, "chegou trabalho novo"
  // vira um número que ninguém consegue rastrear até um EGP. Falha de leitura -> só o
  // número, sem inventar lista vazia.
  const extrasQ = useQuery({ queryKey: ["egps-extras"], queryFn: api.egpsExtras });
  const extrasList = extrasQ.data?.rows ?? [];
  const L = land.data;
  const F = funis.data;
  const R = resumo.data;

  return (
    <div className="resumo">
      <h3>Visão geral</h3>
      {cfg?.familias_safra && (
        <p className="muted">
          <b>A unidade de input é a família de safras.</b> Safras datadas da mesma tabela
          (<code>…_202505</code>, <code>…_202506</code>, …) contam como <b>um</b> input em
          todos os números desta aba: a ingestão de uma família cria UMA tabela particionada
          no destino, e acrescentar safra depois é carga incremental, não ingestão nova. É por
          isso que a fila é menor que a contagem de tabelas físicas — o esforço não mudou, a
          unidade mudou. Safra já sanitizada não some do histórico, mas também não pesa na
          fila. O grafo de linhagem continua no grão da safra.
        </p>
      )}
      {land.error && <div className="error">{String(land.error)}</div>}
      {!L && !land.error && <div className="empty">carregando…</div>}
      {L && (
        <div className="landing">
          <div className="lg-group">
            <div className="lg-title">Escopo Indicium</div>
            <div className="lg-cards">
              <Card label="EGPs no escopo" value={L.egps_escopo} />
              <Card label="EGPs analisados" value={L.egps_analisados} />
              <Card label="Inputs no escopo" value={L.inputs_escopo} />
              <Card label="Inputs a ingerir" value={L.inputs_a_ingerir} tone="danger" />
            </div>
          </div>
          <div className="lg-group">
            <div className="lg-title">Dependências (transitivas, fora do escopo)</div>
            <div className="lg-cards">
              <Card label="Dependências" value={L.deps}
                extra={(L.deps_ex ?? 0) > 0 ? `(+${fmt(L.deps_ex)} ex)` : undefined}
                title={(L.deps_ex ?? 0) > 0 ? `${fmt(L.deps_ex)} ex-dependência(s): EGPs que já foram dependência e saíram do recorte (via resolvida, desvinculada ou cadeia despriorizada) — retidos nas contagens de EGP para o esforço não desaparecer.` : undefined} />
              <Card label="Inputs das dependências" value={L.inputs_deps} />
              <Card label="Inputs das deps a ingerir" value={L.inputs_deps_a_ingerir} tone="danger" />
            </div>
          </div>
          {((L.extras ?? 0) > 0 || (L.inputs_extras ?? 0) > 0) && (
            <div className="lg-group">
              <div className="lg-title">Extras (fora da linha de base)</div>
              <div className="lg-cards">
                <Card label="EGPs extras" value={L.extras ?? 0}
                  title={`EGPs do recorte com vínculo de atualização — versão nova enviada pelo BV (atualizado, substituído, unificado) ou casca. Ficam FORA do total de EGPs, que é congelado:\n${extrasLabel(extrasList)}`} />
                <Card label="Inputs dos extras" value={L.inputs_extras ?? 0}
                  title="Inputs que NENHUM EGP da linha de base lê — o inventário que entrou na fila por causa da versão nova. Os que a linha de base também lê ficam no grupo dela: contá-los aqui somaria a mesma chave duas vezes e o Total deixaria de fechar. Para ver TUDO que os extras leem (inclusive o compartilhado), use o filtro 'só inputs de extras' na aba Inputs — é um número maior, de propósito." />
                <Card label="Inputs dos extras a ingerir" value={L.inputs_extras_a_ingerir ?? 0} tone="danger" />
              </div>
            </div>
          )}
          <div className="lg-group">
            <div className="lg-title">Totais (sem dupla contagem)</div>
            <div className="lg-cards">
              <Card label="Total de EGPs" value={L.total_egps} big
                extra={(L.extras ?? 0) > 0 ? `(+${fmt(L.extras ?? 0)} extra)` : undefined}
                title={`Total CONGELADO (linha de base de 29/09/2026): é o tamanho de uma lista versionada, não uma conta sobre o corpus. Não sobe quando chega versão nova, casca ou dependência inédita, e não cai quando um EGP sai do escopo — só o que cada um está FAZENDO (etapas, funis, migrados) é vivo.${
                  (L.extras ?? 0) > 0
                    ? `\n\n${fmt(L.extras ?? 0)} extra(s) — EGPs do recorte fora da lista. Ficam listados e trazem os inputs deles, mas contam à parte:\n${extrasLabel(extrasList)}`
                    : ""}`} />
              <Card label="Total de Inputs" value={L.total_inputs} big
                title={`Unidades de input distintas no recorte Indicium + dependências. Os três grupos acima o PARTICIONAM — escopo ${fmt(L.inputs_escopo)} + dependências ${fmt(L.inputs_deps)}${(L.inputs_extras ?? 0) > 0 ? ` + extras ${fmt(L.inputs_extras ?? 0)}` : ""} —, nenhuma chave conta em dois. Separar os extras (29/09/2026) NÃO mudou este número: input de versão nova é trabalho real e sempre esteve aqui dentro; o que mudou é dar pra ver quanto dele é deles.`} />
              <Card label="Total não modernizados" value={L.total_nao_modernizados} big tone="danger" />
            </div>
          </div>
        </div>
      )}

      {funis.error && <div className="error">{String(funis.error)}</div>}
      {F && (
        <>
          <h3>Funis de migração</h3>
          <div className="funnels">
            <FunnelChart title="Funil de Migração SAS" data={F.migracao} unidade="EGPs" />
            <FunnelChart title="Funil de Ingestão" data={F.ingestao} unidade="inputs" />
          </div>

          <h3>Funis de migração (+ dependências)</h3>
          <p className="muted">Mesmos funis incluindo as dependências transitivas (fora do escopo Indicium), sem dupla contagem. O denominador cresce com o universo ampliado.</p>
          <div className="funnels">
            <FunnelChart title="Funil de Migração SAS" data={F.migracao_deps} unidade="EGPs" />
            <FunnelChart title="Funil de Ingestão" data={F.ingestao_deps} unidade="inputs" />
          </div>

          <h3>Funis (extras)</h3>
          <p className="muted">A visão isolada do que entrou no corpus <b>depois</b> da linha de base: versões novas enviadas pelo BV (atualizados, substituídos, unificados), cascas e EGPs declarados novos. Mesmas etapas dos funis acima — é um recorte sobre os mesmos EGPs e os mesmos inputs, não outra contagem. Estes EGPs <b>não somam</b> nos dois funis acima: contam à parte, no "(+N extra)" do card Total de EGPs. Extra que ainda não tem etapa entra no denominador sem entrar nas barras, que é o estado honesto — trabalho que chegou e ainda não começou.</p>
          <p className="muted">No <b>funil de ingestão</b> o universo são os inputs que <b>nenhum</b> EGP da linha de base lê — o mesmo conjunto do card "Inputs dos extras" e da tabela de origem dos extras. O que um extra lê <b>em comum</b> com a linha de base pertence ao funil dela: contar nos dois somaria a mesma chave duas vezes. Por isso este funil é menor que o filtro <b>só inputs de extras</b> da aba Inputs, que mostra tudo que os extras consomem.</p>
          <div className={F.ingestao_extras ? "funnels" : "funnels solo"}>
            <FunnelChart title="Funil de Migração SAS" data={F.migracao_extras} unidade="EGPs" />
            {F.ingestao_extras && (
              <FunnelChart title="Funil de Ingestão" data={F.ingestao_extras} unidade="inputs" />
            )}
          </div>
        </>
      )}

      <h3>Funil de migração por mês de priorização</h3>
      <details className="rsm-como"><summary>como estes números são contados</summary>
      <p className="muted">Onde cada EGP do plano de priorização está parado hoje (recorte fixo: Indicium + dependências transitivas). Cada EGP conta em uma única célula — a etapa atual, na sub-coluna do seu status —, então é a LINHA do mês que soma o total, não a coluna de etapa. A 1ª coluna, "Backlog", junta os EGPs em Pré-conversão (etapa fantasma, fora da ordem do funil), sem quebra por status. Diferente das barras do funil acima, que são cumulativas (lá um EGP conta como "Concluído" em todas as etapas que já passou). O plano é um snapshot congelado: EGP que entrou no recorte depois do último salvamento não aparece aqui (os cards acima são vivos e podem contar a mais) até a gestão re-salvar o plano na aba Priorização.</p>
      </details>
      <FunilMesTable />

      <h3>Funil de ingestão por mês de priorização</h3>
      <details className="rsm-como"><summary>como estes números são contados</summary>
      <p className="muted">O mesmo corte para os <b>inputs</b>, sobre o universo dos cards acima (Total de Inputs — escopo Indicium + dependências), distribuído pelo mês do plano: cada input cai no 1º mês em que algum EGP do plano o consome, então a linha soma sem dupla contagem. O que nenhum EGP do plano consome fica na linha "—" (o plano é um snapshot congelado; o recorte é vivo). "A Receber" aparece como coluna normal — nas barras do funil acima ela é só KPI, o que responde pela maior parte da diferença de escala entre as duas visões. Inputs Sanitizados ficam fora (status terminal).</p>
      </details>
      <FunilIngestaoMesTable />

      {(F?.migracao_extras?.total ?? 0) > 0 && (
        <>
          <h3>Funil de migração por mês (extras)</h3>
          <details className="rsm-como"><summary>como estes números são contados</summary>
          <p className="muted">Mesma leitura da tabela por mês lá em cima, só que sobre os <b>extras</b> — e o mês vem do <b>antecessor</b>. O extra não está no plano de priorização: ele chegou depois do congelamento. Mas o trabalho dele é o do antecessor continuando noutro arquivo, então o mês que vale é o de quem ele substitui; sem isso todo extra cairia em "sem mês" e a tabela não diria nada. Numa cadeia (v1 → v2 → v3) o mês sobe até achar quem está no plano. Unificador com vários antecessores fica com o <b>menor</b> mês, a mesma régua "conta no 1º mês" do plano. Extra sem antecessor no plano — a casca, que <i>é</i> o antecessor, e o EGP novo, que não substitui ninguém — vai na linha <b>Adicional</b>, e entra no total: a tabela fecha com o card de extras. EGP sem etapa gravada aparece na coluna <b>Sem etapa</b> em vez de sumir.</p>
          </details>
          <FunilMesTable extras />

          <h3>Funil de ingestão por mês (extras)</h3>
          <details className="rsm-como"><summary>como estes números são contados</summary>
          <p className="muted">O mesmo corte para os <b>inputs dos extras</b>: os que <b>nenhum</b> EGP da linha de base lê — mesmo conjunto do card "Inputs dos extras" e do funil de ingestão dos extras. O mês de cada input é o do antecessor do extra que o consome, pelo menor entre eles. O que um extra lê em comum com a linha de base aparece na tabela por mês lá de cima, não aqui. Os inputs de quem não tem antecessor no plano ficam na linha <b>Adicional</b>.</p>
          </details>
          <FunilIngestaoMesTable extras />
        </>
      )}

      {resumo.error && <div className="error">{String(resumo.error)}</div>}
      {R && (
        <>
          <h3>Funil por área (DOR1)</h3>
          <p className="muted">À esquerda o escopo Indicium; à direita o universo com as dependências transitivas (a coluna "Dependências" mostra quantos EGPs da linha vêm de fora do escopo). Os EGPs contam pela linha de base, como o card Total de EGPs; os extras ficam numa linha à parte, com os inputs que só eles leem.</p>
          <Pair
            esc={<FunilTable d={R.funil} />}
            deps={R.funil_deps ? <FunilTable d={R.funil_deps} withDeps /> : null}
          />

          <h3>Inputs por origem (DOR1)</h3>
          <p className="muted">Inputs distintos por origem, com o avanço de modernização por linha. Sem dupla contagem entre as duas visões.</p>
          <Pair
            esc={<OrigemTable d={R.origem} />}
            deps={R.origem_deps ? <OrigemTable d={R.origem_deps} notaCasco /> : null}
          />

          {R.origem_extras && R.origem_extras.total.total > 0 && (
            <>
              <h3>Inputs por origem (extras)</h3>
              <p className="muted">O inventário que entrou no recorte <b>por causa</b> das
                versões novas: os inputs que <b>nenhum</b> EGP da linha de base lê. As duas
                tabelas acima são cumulativas (escopo ⊂ escopo + dependências); esta é um
                recorte à parte. O que um extra lê <b>em comum</b> com a linha de base fica
                na tabela dela — contar aqui somaria a mesma chave duas vezes. Para ver tudo
                que os extras consomem, inclusive o compartilhado, use o filtro <b>só inputs
                de extras</b> na aba Inputs: é um número maior, de propósito.
                <br />Como as tabelas acima, esta conta <b>só as quatro origens</b>: o
                placeholder <code>casco::</code> dos EGPs unificados não é ingestão e fica
                fora, então o total aqui é menor que o do card "Inputs dos extras" da Visão
                geral, pela quantidade de cascas.</p>
              <div className="rsm-pair">
                <div className="rsm-block">
                  <span className="rsm-chip deps">só os extras</span>
                  <OrigemTable d={R.origem_extras} />
                </div>
              </div>
            </>
          )}
        </>
      )}

      <h3>EGPs por sub-área BV</h3>
      <details className="rsm-como"><summary>como estes números são contados</summary>
      <p className="muted">Recorte fixo: Indicium + dependências transitivas (o mesmo default da aba EGPs). A <b>sub-área BV</b> é a área interna do cliente (Digital, MIS, Operações, Estratégia…) e vem do <b>Responsável BV</b> do EGP pelo cadastro em Gestão → Responsáveis BV — quem não estiver cadastrado cai em "Sem sub-área". <b>A migrar</b>, <b>Migrados</b> e <b>Despriorizados</b> são uma partição por <b>status</b>: todo EGP cai em exatamente uma, então as três somam a coluna EGPs em toda linha. Migrado é status, não etapa — a mesma leitura da Priorização (EGP despriorizado também chega na etapa Migrado, e EGP com status Migrado pode estar numa etapa anterior). Não há coluna de bloqueio nem de inputs pendentes aqui: bloqueio é por EGP e vive nos chips da aba EGPs, e input pendente não é somável por sub-área — a mesma tabela é lida por EGPs de sub-áreas diferentes e pertence às duas, então qualquer total por linha contaria o mesmo input mais de uma vez. O número certo de inputs distintos a ingerir está no card "A ingerir" da aba EGPs. <b>% Migrado</b> é migrados / (EGPs − despriorizados) — desconsidera despriorizados, então mede o avanço só do que ainda está em jogo. <b>% Total</b> é (migrados + despriorizados) / EGPs da linha — despriorizado também conta como "resolvido" no numerador, medindo o progresso absoluto da carteira. Clique numa linha para abrir a aba EGPs só com esta sub-área — os demais filtros daquela aba são zerados para o número bater.</p>
      </details>
      <SubareaTable onNav={onNav} />

      {(F?.migracao_extras?.total ?? 0) > 0 && (
        <>
          <h3>EGPs por sub-área BV (extras)</h3>
          <details className="rsm-como"><summary>como estes números são contados</summary>
          <p className="muted">A mesma tabela sobre os <b>extras</b>: versões novas enviadas pelo BV (atualizados, substituídos, unificados), cascas e EGPs declarados novos — o mesmo conjunto do "(+N extra)" do card Total de EGPs e do funil dos extras. Eles <b>não somam</b> na tabela acima, que é a da linha de base: as duas são disjuntas e juntas dão o recorte inteiro. Mesmas colunas e mesma partição por status. A sub-área vem do <b>Responsável BV do próprio extra</b>, não do antecessor: versão nova que ainda não teve o Responsável BV preenchido cai em "Sem sub-área" até ser preenchida na aba EGPs. Clique numa linha para abrir a aba EGPs no recorte "só os extras", só com esta sub-área.</p>
          </details>
          <SubareaTable onNav={onNav} extras />
        </>
      )}

      <p className="muted">Indicadores 3/4/6/7 refletem edições em tempo real (status efetivo). Modernizado = Modernizado/Sanitizado; o restante (A receber/Recebido/Em ingestão) conta como a ingerir. Escopo: DOR1 (Indicium).</p>
    </div>
  );
}
