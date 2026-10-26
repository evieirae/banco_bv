import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "../api";
import { TempoEtapaChart } from "./TempoEtapaChart";
import { TempoEtapaStatusChart } from "./TempoEtapaStatusChart";
import { LeadTimeChart } from "./LeadTimeChart";
import { AgingTable } from "./AgingTable";
import { RetrabalhoPanel } from "./RetrabalhoPanel";
import { PorResponsavelChart } from "./PorResponsavelChart";
import { MultiSelect } from "./MultiSelect";
import type { AppConfig, ReadinessRow } from "../types";
import { useSubareas } from "../useSubareas";
import { SEM_SUBAREA, subareaDe, ordenarSubareas } from "../subareas";
import { STATUS_PROJETO, STATUS_INPUT } from "../pipeline";

// Opções fixas do filtro "Com BV" — valores batem com os aceitos por
// /api/tempo-etapas?com_bv= no backend (ver _tempo_base_filtrado). Current (não histórico):
// reflete o ÚLTIMO toggle registrado em sas_gestao_bv; EGP (ou input) sem nenhum evento
// entra em "Conosco" (mesmo fallback do resto da aba).
const TE_COMBV_OPTIONS = ["com_bv", "conosco"];
const TE_COMBV_LABELS: Record<string, string> = { com_bv: "Com BV", conosco: "Conosco" };

// Aba restrita (bv_users, ver App.tsx: `cfg?.is_gestao`) — tempo por etapa dos 2 funis
// (migração de EGP e ingestão de input), saído do Resumo (pedido 2026-09-30: não é dado
// pra todo mundo ver; pedido 2026-10-05: estender pro lado de inputs, mesma restrição).
// Toggle local decide qual funil mostrar — mesma aba, mesmo gate de acesso.
export function TempoEtapasView({ cfg }: { cfg: AppConfig | null }) {
  const [teFunil, setTeFunil] = useState<"migracao" | "ingestao">("migracao");
  return (
    <div className="resumo">
      <div className="filters" style={{ marginBottom: 4 }}>
        <div className="seg-toggle">
          <button type="button" className={teFunil === "migracao" ? "on" : ""}
            onClick={() => setTeFunil("migracao")}>Migração (EGPs)</button>
          <button type="button" className={teFunil === "ingestao" ? "on" : ""}
            onClick={() => setTeFunil("ingestao")}>Ingestão (Inputs)</button>
        </div>
      </div>
      {teFunil === "migracao" ? <TempoEtapasMigracao /> : <TempoEtapasIngestao cfg={cfg} />}
    </div>
  );
}

function TempoEtapasMigracao() {
  const readiness = useQuery({ queryKey: ["egp-readiness", "indi_deps"], queryFn: () => api.egpReadiness("indi_deps") });
  const { mapa: teMapaSub } = useSubareas();
  // responsavel é email (login); analistas resolve email -> nome pro rótulo do MultiSelect
  // (mesmo padrão de WavesView/GestaoMigracao — ver nomeDe nesses arquivos). O filtro em
  // si continua mandando o email pro backend (chave real em sas_egp_pipeline.responsavel).
  const analistasQ = useQuery({ queryKey: ["analistas"], queryFn: () => api.analistas() });
  const teNomeDe = (email: string) =>
    analistasQ.data?.rows.find((a) => a.email === email)?.nome ?? email.split("@")[0];
  const escopoRows = useMemo(
    () => (readiness.data?.rows ?? []).filter((r: ReadinessRow) => r.tipo === "escopo"), [readiness.data]);
  // Área de negócio (Cobrança/Riscos/…) fica de fora do lado de propósito — neste corpus é
  // sempre Cobrança, então o filtro não distinguiria nada; Sub-área BV (área interna do
  // cliente, pelo cadastro de Responsáveis BV) é o corte que importa aqui.
  const teSubareaOf = (r: ReadinessRow) => subareaDe(r.responsavel_bv, teMapaSub) ?? SEM_SUBAREA;
  const teSubareaOptions = useMemo(() => ordenarSubareas(escopoRows.map(teSubareaOf)), [escopoRows, teMapaSub]);
  const teRespOptions = useMemo(
    () => [...new Set(escopoRows.map((r) => r.responsavel).filter((v): v is string => !!v))].sort(), [escopoRows]);
  const teRespLabels = useMemo(
    () => Object.fromEntries(teRespOptions.map((email) => [email, teNomeDe(email)])),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [teRespOptions, analistasQ.data]);
  const teRespBvOptions = useMemo(
    () => [...new Set(escopoRows.map((r) => r.responsavel_bv).filter((v): v is string => !!v))].sort(), [escopoRows]);
  const teEgpOptions = useMemo(() => escopoRows.map((r) => r.projeto).sort(), [escopoRows]);
  const [teSubarea, setTeSubarea] = useState<Set<string>>(new Set());
  const [teResp, setTeResp] = useState<Set<string>>(new Set());
  const [teRespBv, setTeRespBv] = useState<Set<string>>(new Set());
  const [teStatus, setTeStatus] = useState<Set<string>>(new Set());
  const [teComBv, setTeComBv] = useState<Set<string>>(new Set());
  const [teEgpBusca, setTeEgpBusca] = useState("");
  const teEgp = teEgpOptions.includes(teEgpBusca) ? teEgpBusca : "";
  // Sub-área não é coluna própria (é derivada no cliente), então vira lista de projetos
  // antes de mandar pro backend, que só entende `projeto` (ver docstring de /api/tempo-etapas).
  // Busca de 1 EGP tem precedência sobre a sub-área (mais específica) em vez de interseção.
  const teSubareaProjetos = useMemo(
    () => (teSubarea.size ? escopoRows.filter((r) => teSubarea.has(teSubareaOf(r))).map((r) => r.projeto) : []),
    [escopoRows, teSubarea, teMapaSub]);
  const teProjetoFiltro = teEgp ? [teEgp] : teSubareaProjetos;
  const teFilterKey = {
    responsavel: [...teResp].sort(), responsavel_bv: [...teRespBv].sort(),
    projeto: [...teProjetoFiltro].sort(),
    status: [...teStatus].sort(), com_bv: [...teComBv].sort(),
  };
  const tempoEtapas = useQuery({
    queryKey: ["tempoEtapas", teFilterKey],
    queryFn: () => api.tempoEtapas(teFilterKey),
  });
  const tempoAnalises = useQuery({
    queryKey: ["tempoAnalises", teFilterKey],
    queryFn: () => api.tempoAnalises(teFilterKey),
  });
  const TE = tempoEtapas.data;
  const TA = tempoAnalises.data;
  const teFiltrado = teSubarea.size > 0 || teResp.size > 0 || teRespBv.size > 0
    || teStatus.size > 0 || teComBv.size > 0 || !!teEgp;

  return (
    <>
      <h3>Tempo por etapa (Funil de Migração)</h3>
      <p className="muted">Quanto tempo, em média, os EGPs do escopo Indicium ficam parados em cada etapa do funil de migração, calculado a partir do histórico de transições (aba Histórico) e repartido entre <b>Conosco</b> (trabalho nosso) e <b>Com BV</b> (bloqueado esperando a área/banco), via o switch "Com BV" da Gestão. Etapa ainda em curso conta até hoje. Cobre só transições feitas a partir de quando a auditoria passou a existir — EGPs importados direto numa etapa (sem passar pelo editor) não entram na amostra; EGP sem nenhum toggle "Com BV" registrado conta o tempo todo como Conosco (melhor aproximação sem o dado).</p>
      <div className="filters">
        <MultiSelect label="Sub-área BV" options={teSubareaOptions} sel={teSubarea}
          onToggle={(v) => setTeSubarea((p) => { const n = new Set(p); n.has(v) ? n.delete(v) : n.add(v); return n; })}
          onClear={() => setTeSubarea(new Set())} />
        <MultiSelect label="Responsável" options={teRespOptions} sel={teResp} labels={teRespLabels}
          onToggle={(v) => setTeResp((p) => { const n = new Set(p); n.has(v) ? n.delete(v) : n.add(v); return n; })}
          onClear={() => setTeResp(new Set())} />
        <MultiSelect label="Responsável BV" options={teRespBvOptions} sel={teRespBv}
          onToggle={(v) => setTeRespBv((p) => { const n = new Set(p); n.has(v) ? n.delete(v) : n.add(v); return n; })}
          onClear={() => setTeRespBv(new Set())} />
        <MultiSelect label="Status" options={STATUS_PROJETO} sel={teStatus}
          onToggle={(v) => setTeStatus((p) => { const n = new Set(p); n.has(v) ? n.delete(v) : n.add(v); return n; })}
          onClear={() => setTeStatus(new Set())} />
        <MultiSelect label="Com BV" options={TE_COMBV_OPTIONS} sel={teComBv} labels={TE_COMBV_LABELS}
          onToggle={(v) => setTeComBv((p) => { const n = new Set(p); n.has(v) ? n.delete(v) : n.add(v); return n; })}
          onClear={() => setTeComBv(new Set())} />
        <input list="te-egps" placeholder="buscar 1 EGP…" value={teEgpBusca}
          onChange={(e) => setTeEgpBusca(e.target.value)} style={{ minWidth: 220 }} />
        <datalist id="te-egps">{teEgpOptions.map((p) => <option key={p} value={p} />)}</datalist>
        {teFiltrado && (
          <button type="button" className="ms-clear"
            onClick={() => {
              setTeSubarea(new Set()); setTeResp(new Set()); setTeRespBv(new Set());
              setTeStatus(new Set()); setTeComBv(new Set()); setTeEgpBusca("");
            }}>
            limpar filtros
          </button>
        )}
      </div>
      {tempoEtapas.error && <div className="error">{String(tempoEtapas.error)}</div>}
      {TE && (
        <div className="funnels">
          <TempoEtapaChart title="Dias úteis por etapa — Conosco x Com BV" rows={TE.etapas} />
          <TempoEtapaStatusChart title="Dias úteis por etapa — por status" rows={TE.etapas} />
        </div>
      )}

      <h3>Outras análises de tempo</h3>
      <p className="muted">4 cortes complementares do mesmo histórico de transições — respeitam os mesmos filtros acima.</p>
      {tempoAnalises.error && <div className="error">{String(tempoAnalises.error)}</div>}
      {TA && (
        <div className="funnels">
          <LeadTimeChart title="Tempo total até Migrado (lead time)" data={TA.lead_time} />
          <AgingTable title="EGPs parados agora (aging)" rows={TA.aging} nomeDe={teNomeDe} />
          <RetrabalhoPanel title="Retrabalho (regressão de etapa)" data={TA.retrabalho} />
          <PorResponsavelChart title="Lead time por responsável" rows={TA.por_responsavel} nomeDe={teNomeDe} />
        </div>
      )}
    </>
  );
}

// Irmã de TempoEtapasMigracao pro funil de INGESTÃO (PIPELINE_INPUT/STATUS_INPUT) — mesmos
// 2+4 gráficos, via /api/tempo-etapas-input e /api/tempo-analises-input (sas_inputs_audit,
// chaveado por chave_canonica). Pedido 2026-10-05. Universo: inputs do escopo Indicium
// ("universo por vínculo", mesmo recorte padrão da aba Inputs) — sem deps, de propósito
// (mesma razão do lado EGP não incluir deps aqui: a análise é sobre O QUE A GENTE INGERE,
// não quem mais lê a mesma tabela).
function TempoEtapasIngestao({ cfg }: { cfg: AppConfig | null }) {
  const baseQ = useQuery({
    queryKey: ["inputs-base-tempo"],
    queryFn: () => api.inputs({
      scope: "indi", categoria: [], origem: [], etapa: [], status: [], area: [], responsavel: [], mes: [],
      q: "", divergence: false, bloqueador: false, exDeps: false, semExtras: false,
      extra: false, pendentes: false, safra: false,
    }),
  });
  const analistasQ = useQuery({ queryKey: ["analistas"], queryFn: () => api.analistas() });
  const tiNomeDe = (email: string) =>
    analistasQ.data?.rows.find((a) => a.email === email)?.nome ?? email.split("@")[0];
  const baseRows = baseQ.data?.rows ?? [];
  const tiRespOptions = useMemo(
    () => [...new Set(baseRows.map((r) => r.responsavel).filter((v): v is string => !!v))].sort(), [baseRows]);
  const tiRespLabels = useMemo(
    () => Object.fromEntries(tiRespOptions.map((email) => [email, tiNomeDe(email)])),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [tiRespOptions, analistasQ.data]);

  const [tiResp, setTiResp] = useState<Set<string>>(new Set());
  const [tiCategoria, setTiCategoria] = useState<Set<string>>(new Set());
  const [tiOrigem, setTiOrigem] = useState<Set<string>>(new Set());
  const [tiStatus, setTiStatus] = useState<Set<string>>(new Set());
  const [tiComBv, setTiComBv] = useState<Set<string>>(new Set());
  const [tiBusca, setTiBusca] = useState("");
  // Busca livre (substring, chave OU artifact) resolvida em chaves ANTES de mandar pro
  // backend — mesmo papel do filtro de 1 EGP do lado migração, mas sem exigir match exato
  // (datalist de milhares de inputs seria inviável; aqui ela filtra o que já está carregado).
  const tiBuscaChaves = useMemo(() => {
    if (!tiBusca.trim()) return [];
    const q = tiBusca.trim().toLowerCase();
    return baseRows.filter((r) => r.chave_canonica.toLowerCase().includes(q)
      || r.artifact.toLowerCase().includes(q)).map((r) => r.chave_canonica);
  }, [baseRows, tiBusca]);

  const tiFilterKey = {
    responsavel: [...tiResp].sort(), categoria: [...tiCategoria].sort(), origem: [...tiOrigem].sort(),
    chave: [...tiBuscaChaves].sort(), status: [...tiStatus].sort(), com_bv: [...tiComBv].sort(),
  };
  const tempoEtapasInput = useQuery({
    queryKey: ["tempoEtapasInput", tiFilterKey],
    queryFn: () => api.tempoEtapasInput(tiFilterKey),
  });
  const tempoAnalisesInput = useQuery({
    queryKey: ["tempoAnalisesInput", tiFilterKey],
    queryFn: () => api.tempoAnalisesInput(tiFilterKey),
  });
  const TEI = tempoEtapasInput.data;
  const TAI = tempoAnalisesInput.data;
  const tiFiltrado = tiResp.size > 0 || tiCategoria.size > 0 || tiOrigem.size > 0
    || tiStatus.size > 0 || tiComBv.size > 0 || !!tiBusca.trim();

  return (
    <>
      <h3>Tempo por etapa (Funil de Ingestão)</h3>
      <p className="muted">Mesma análise do lado de Migração, agora pro funil de ingestão dos inputs: quanto tempo, em média, cada input do escopo Indicium fica em cada etapa, repartido entre <b>Conosco</b> e <b>Com BV</b> (switch "Com BV" da Gestão, aplicado também a inputs). Etapa ainda em curso conta até hoje; "Modernizado" (etapa terminal) fica fora do gráfico pelo mesmo motivo de "Migrado" do lado EGP — não há próxima etapa pra medir o intervalo. Exploratório: ainda sem a validação cruzada contra prod que o lado EGP já teve.</p>
      <div className="filters">
        <MultiSelect label="Responsável" options={tiRespOptions} sel={tiResp} labels={tiRespLabels}
          onToggle={(v) => setTiResp((p) => { const n = new Set(p); n.has(v) ? n.delete(v) : n.add(v); return n; })}
          onClear={() => setTiResp(new Set())} />
        <MultiSelect label="Categoria" options={cfg?.categorias ?? []} sel={tiCategoria}
          onToggle={(v) => setTiCategoria((p) => { const n = new Set(p); n.has(v) ? n.delete(v) : n.add(v); return n; })}
          onClear={() => setTiCategoria(new Set())} />
        <MultiSelect label="Origem" options={cfg?.origens ?? []} sel={tiOrigem}
          onToggle={(v) => setTiOrigem((p) => { const n = new Set(p); n.has(v) ? n.delete(v) : n.add(v); return n; })}
          onClear={() => setTiOrigem(new Set())} />
        <MultiSelect label="Status" options={STATUS_INPUT} sel={tiStatus}
          onToggle={(v) => setTiStatus((p) => { const n = new Set(p); n.has(v) ? n.delete(v) : n.add(v); return n; })}
          onClear={() => setTiStatus(new Set())} />
        <MultiSelect label="Com BV" options={TE_COMBV_OPTIONS} sel={tiComBv} labels={TE_COMBV_LABELS}
          onToggle={(v) => setTiComBv((p) => { const n = new Set(p); n.has(v) ? n.delete(v) : n.add(v); return n; })}
          onClear={() => setTiComBv(new Set())} />
        <input placeholder="buscar input (chave ou nome)…" value={tiBusca}
          onChange={(e) => setTiBusca(e.target.value)} style={{ minWidth: 220 }} />
        {tiFiltrado && (
          <button type="button" className="ms-clear"
            onClick={() => {
              setTiResp(new Set()); setTiCategoria(new Set()); setTiOrigem(new Set());
              setTiStatus(new Set()); setTiComBv(new Set()); setTiBusca("");
            }}>
            limpar filtros
          </button>
        )}
      </div>
      {tempoEtapasInput.error && <div className="error">{String(tempoEtapasInput.error)}</div>}
      {TEI && (
        <div className="funnels">
          <TempoEtapaChart title="Dias úteis por etapa — Conosco x Com BV" rows={TEI.etapas} nounPlural="inputs" />
          <TempoEtapaStatusChart title="Dias úteis por etapa — por status" rows={TEI.etapas} nounPlural="inputs" />
        </div>
      )}

      <h3>Outras análises de tempo (ingestão)</h3>
      <p className="muted">4 cortes complementares do mesmo histórico de transições — respeitam os mesmos filtros acima.</p>
      {tempoAnalisesInput.error && <div className="error">{String(tempoAnalisesInput.error)}</div>}
      {TAI && (
        <div className="funnels">
          <LeadTimeChart title="Tempo total até Modernizado (lead time)" data={TAI.lead_time}
            nounPlural="inputs" nounSingular="input" terminal="Modernizado" />
          <AgingTable title="Inputs parados agora (aging)" rows={TAI.aging} nomeDe={tiNomeDe}
            nounSingular="input" nounPlural="inputs" colLabel="Input" />
          <RetrabalhoPanel title="Retrabalho (regressão de etapa)" data={TAI.retrabalho}
            nounSingular="input" nounPlural="inputs" />
          <PorResponsavelChart title="Lead time por responsável" rows={TAI.por_responsavel} nomeDe={tiNomeDe}
            nounPlural="inputs" nounSingular="input" terminal="modernizado" />
        </div>
      )}
    </>
  );
}
