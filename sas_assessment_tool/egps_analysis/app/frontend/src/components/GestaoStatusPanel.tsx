// Painel de status do EGP/Input, no DetailModal centrado (era um drawer à direita).
// Desde 2026-08-28 usado SÓ pela aba Gestão e pela página Acompanhamento (cliente,
// readOnly) — nas abas EGPs/Inputs o conteúdo dele foi absorvido pelos modais de
// detalhe (GestaoStatusHistory + editores nos próprios modais). Seções da prontidão do
// EGP (Etapa/Status/Responsável, Inputs, Pré-working, Outputs) OU do Input (Etapa/Status/
// Responsável do funil de ingestão + checklist de pré-working — pedido 2026-08, mesmo
// PATCH /api/inputs e mesmo componente PreworkingChecklist da aba Inputs) + último status em
// destaque + histórico completo + "+ Adicionar Comentário" (modal). Concentra TODA a
// interação de status — não há seção de detalhe fora daqui. Reusa as classes .drawer-*.
// Editar Etapa aqui (EGP ou Input) invalida o cache e move o card sozinho no Kanban da
// Gestão, sem drag-and-drop.
import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { gestaoApi, hojeSP, CF_PREFIX, type EntityType, type GestaoRow, type GestaoUser } from "../gestaoApi";
import { fmtBR, fmtTsBR } from "../diasUteis";
import { egpShort } from "../csv";
import { api } from "../api";
import {
  PIPELINE_PROJETO, PIPELINE_INPUT, STATUS_INPUT, PHANTOM_ETAPAS_MIGRACAO, opcoesStatusEgp,
  SEG, STATUS_ABBR, STATUS_HELP,
} from "../pipeline";
import { effEtapa, effStatusInput } from "../inputs";
import type { OutputPipelineRow } from "../types";
import { PreworkingChecklist } from "./PreworkingChecklist";
import { DetailModal } from "./DetailModal";
import { pendenciaInputParaEgp, respBvOf } from "./GestaoKanban";
import { tabelaModernizada } from "../tabelaCorresp";
import { useSubareas } from "../useSubareas";
import { subareasDe } from "../subareas";
import { usePodeEscrever } from "../usePodeEscrever";

interface Props {
  entity: EntityType;
  row: GestaoRow;
  allRows: GestaoRow[];     // opções do select de EGP/Input do modal
  users: GestaoUser[];      // membros do grupo bv_users (dropdown "Nome")
  onClose: () => void;
  // Seção "Usado por" do Input (pedido cliente BV 2026-08): abre o EGP indicado direto no
  // Kanban de EGPs, com o card dele já aberto (mesmo drawer). Cada tela (GestaoMigracao/
  // AcompanhamentoView) implementa trocando entity + panelId (e, na Gestão, forçando
  // view="kanban"). Não usado no lado EGP (não há "abrir EGP" a partir de um EGP).
  onOpenEgp?: (projeto: string) => void;
  // Seção "Inputs" do EGP (mesmo pedido 2026-08, direção inversa): abre o input indicado
  // direto no Kanban de Inputs. Sanitizados ficam sem botão (texto simples) — /api/gestao/
  // rows exclui sanitizados do recorte de Inputs, então o card de destino nunca existiria.
  onOpenInput?: (chave: string) => void;
  // true na página Acompanhamento (cliente): esconde SÓ o select de Responsável (quem da
  // Indicium está executando) — etapa/status/pré-working e o histórico de comentários
  // continuam visíveis, é a mesma janela de todo dia, só sem esse campo específico.
  hideResponsavel?: boolean;
  // true na página Acompanhamento (cliente): TODOS os controles de edição (Etapa/Status/
  // Pré-working+data, no EGP e no Input) ficam desabilitados — só visualização. A lista de
  // Inputs dentro do EGP continua read-only nas 2 telas (não dá pra alterar etapa de input
  // por ali — só abrindo o card do Input, aqui ou na aba Inputs).
  readOnly?: boolean;
}

// `data` do status vem em UTC (current_timestamp() do warehouse) -> exibe em SP.
const fmtTs = (iso: string) => fmtTsBR(iso);

export function GestaoStatusPanel({ entity, row, allRows, users, onClose, hideResponsavel, readOnly: readOnlyProp, onOpenEgp, onOpenInput }: Props) {
  const pode = usePodeEscrever();
  const readOnly = readOnlyProp || !pode;
  const qc = useQueryClient();
  const [modal, setModal] = useState(false);
  const { mapa: mapaSub } = useSubareas();

  const statusQ = useQuery({
    queryKey: ["gestao-status", entity, row.id],
    queryFn: () => gestaoApi.listStatus(entity, row.id),
  });
  const entries = statusQ.data ?? [];
  const ultimo = entries[0];
  const nomeDe = (email: string) => users.find((u) => u.email === email)?.nome ?? email;

  const cfgQ = useQuery({ queryKey: ["config"], queryFn: () => api.config() });
  const isAdmin = !!cfgQ.data?.is_admin;
  const isGestao = !!cfgQ.data?.is_gestao;
  const invalidateRows = () => qc.invalidateQueries({ queryKey: ["gestao", entity] });

  // Etapa/Status/Responsável (funil de migração, só EGP) — mesmo endpoint/queryKey
  // compartilhado que a aba EGPs já usa (ReadinessView.tsx), cache React Query dedupa a
  // query. Editar aqui grava na hora (PATCH /api/egp-pipeline) e invalida o cache — é essa
  // invalidação que move o card entre colunas no Kanban da Gestão automaticamente.
  // Sem `enabled` — precisa carregar nas 2 variantes: EGP usa pra editar etapa/status/
  // pré-working; Input usa (read-only) na seção "Usado por" p/ calcular a pendência de cada
  // EGP consumidor (pendenciaInputParaEgp). Mesma queryKey em toda a tela — cache
  // compartilhado, react-query dedupa mesmo com os 2 usos.
  const readinessQ = useQuery({
    queryKey: ["egp-readiness", "base"],
    queryFn: () => api.egpReadiness("base"),
  });
  const readinessMap = useMemo(
    () => new Map((readinessQ.data?.rows ?? []).map((r) => [r.projeto, r])), [readinessQ.data]);
  const pipeRow = readinessQ.data?.rows.find((r) => r.projeto === row.id);
  const pipeStatus = pipeRow?.status || "A Iniciar";
  const preworkingVal = pipeRow?.preworking ?? false;
  // Data do pré-working: 100% manual (não é setada por automação, ao contrário do checklist
  // do Input). Controlado com buffer local pq vem de uma query separada (readinessQ) que
  // pode resolver DEPOIS do 1º render — useEffect resincroniza quando o valor do servidor
  // chega/muda (inclui após o próprio mutate, via invalidação).
  const [pwDataInput, setPwDataInput] = useState(pipeRow?.preworking_data ?? "");
  useEffect(() => {
    setPwDataInput(pipeRow?.preworking_data ?? "");
  }, [pipeRow?.preworking_data]);
  const pipeMut = useMutation({
    mutationFn: (v: { etapa?: string; status?: string; responsavel?: string; preworking?: boolean; preworking_data?: string | null }) =>
      api.egpPipeline({ projeto: row.id, ...v }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["egp-readiness"] });
      qc.invalidateQueries({ queryKey: ["gestao", entity] });
      qc.invalidateQueries({ queryKey: ["funis"] });
    },
  });

  // Etapa/Status/Responsável do INPUT (funil de ingestão) — mesmo endpoint (PATCH
  // /api/inputs) e mesma convenção de invalidação da tabela de Inputs (MonitorView.tsx:
  // patchMut), pedido 2026-08 p/ mover o card sozinho no Kanban de Inputs sem precisar abrir
  // a aba Inputs. `row.etapa`/`row.status` já vêm EFETIVOS do backend (/api/gestao/rows usa
  // _eff_etapa()/_eff_status_input() nas SELECTs), então não precisa reaplicar effEtapa aqui.
  const inputPatchMut = useMutation({
    mutationFn: (v: { etapa?: string; status?: string; responsavel?: string }): Promise<unknown> =>
      // card de carga fria: o funil vive em sas_outputs_pipeline (cf_*), não em T_IN
      row.cargaFria
        ? api.outputPipelinePatch({
            chave_canonica: row.id.slice(CF_PREFIX.length),
            ...(v.etapa !== undefined ? { cf_etapa: v.etapa } : {}),
            ...(v.status !== undefined ? { cf_status: v.status } : {}),
            ...(v.responsavel !== undefined ? { cf_responsavel: v.responsavel } : {}),
          })
        : api.patch({ chave_canonica: row.id, ...v }),
    // Card de carga fria: atualização otimista — o <select> lê row.etapa/status do cache e, sem
    // isto, voltaria ao valor antigo até o /api/gestao/rows recarregar (dezenas de segundos no
    // dev), parecendo que a mudança não pegou. Rollback no erro.
    onMutate: async (v) => {
      if (!row.cargaFria) return undefined;
      await qc.cancelQueries({ queryKey: ["gestao", entity] });
      const prev = qc.getQueryData<GestaoRow[]>(["gestao", entity]);
      qc.setQueryData<GestaoRow[]>(["gestao", entity], (old) =>
        (old ?? []).map((r) => (r.id === row.id ? {
          ...r,
          ...(v.etapa !== undefined ? { etapa: v.etapa } : {}),
          ...(v.status !== undefined ? { status: v.status } : {}),
          ...(v.responsavel !== undefined ? { responsavel: v.responsavel || null } : {}),
        } : r)));
      return { prev };
    },
    onError: (_e, _v, ctx) => {
      if (ctx?.prev) qc.setQueryData(["gestao", entity], ctx.prev);
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["gestao", entity] });
      if (row.cargaFria) {   // output não entra em inputs/métricas/prontidão: só o próprio card
        qc.invalidateQueries({ queryKey: ["outputs-pipeline"] });
        return;
      }
      qc.invalidateQueries({ queryKey: ["inputs"] });
      qc.invalidateQueries({ queryKey: ["metrics"] });
      qc.invalidateQueries({ queryKey: ["resumo"] });
      qc.invalidateQueries({ queryKey: ["landing"] });
      qc.invalidateQueries({ queryKey: ["egp"] });
      qc.invalidateQueries({ queryKey: ["egp-readiness"] });
      qc.invalidateQueries({ queryKey: ["funis"] });
    },
  });

  // Inputs do EGP (etapa/status efetivos, mesma lógica de effEtapa/effStatusInput usada na
  // aba EGPs) — mesma queryKey ["egp", projeto] do EgpDetailPanel, cache compartilhado.
  const egpQ = useQuery({ queryKey: ["egp", row.id], queryFn: () => api.egp(row.id), enabled: entity === "egp" });
  // Outputs PRODUZIDOS por este EGP — mesma composição (outputs base × outputs-egps base)
  // já usada no EgpDetailPanel, mesmas queryKeys => cache compartilhado.
  const outputsQ = useQuery({ queryKey: ["outputs", "base"], queryFn: () => api.outputs("base"), enabled: entity === "egp" });
  const pairsQ = useQuery({ queryKey: ["outputs-egps", "base"], queryFn: () => api.outputsEgps("base"), enabled: entity === "egp" });
  const producedOutputs = useMemo(() => {
    const mine = new Set(
      (pairsQ.data?.rows ?? []).filter((p) => p.projeto === row.id).map((p) => p.chave_canonica));
    return (outputsQ.data?.rows ?? []).filter((r) => mine.has(r.chave_canonica));
  }, [outputsQ.data, pairsQ.data, row.id]);
  // Recebimento manual por output (sas_outputs_pipeline) — mesma queryKey em toda a tela,
  // cache react-query compartilhado (mesmo padrão de ["preworking"] p/ inputs). Assim que
  // tocado, SUBSTITUI modernizada_auto na conta de n_outputs_disp/prontidão (backend).
  const outPipeQ = useQuery({
    queryKey: ["outputs-pipeline"], queryFn: () => api.outputsPipeline(), enabled: entity === "egp" || !!row.cargaFria,
  });
  const outPipeMap = useMemo(
    () => new Map((outPipeQ.data?.rows ?? []).map((r) => [r.chave_canonica, r])), [outPipeQ.data]);
  const outPipeMut = useMutation({
    mutationFn: (v: { chave_canonica: string; recebido?: boolean; recebido_data?: string | null; carga_fria?: boolean;
      cf_inicio?: string; cf_fim?: string; cf_caminho?: string; cf_tabela?: string }) =>
      api.outputPipelinePatch(v),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["outputs-pipeline"] });
      qc.invalidateQueries({ queryKey: ["gestao", "input"] });
      qc.invalidateQueries({ queryKey: ["egp-readiness"] });
      qc.invalidateQueries({ queryKey: ["gestao", entity] });
      qc.invalidateQueries({ queryKey: ["funis"] });
    },
  });
  const addBV = useMutation({
    mutationFn: (v: { comBv: boolean; data?: string }) => gestaoApi.setBV(entity, row.id, v.comBv, v.data),
    onSuccess: invalidateRows,
  });
  const delBV = useMutation({
    mutationFn: (id: string) => gestaoApi.deleteBV(id),
    onSuccess: invalidateRows,
  });
  // Contador manual de revisão de regras de negócio (EGP devolvido de PRD p/ validação em DES).
  const ajustaRevisao = useMutation({
    mutationFn: (delta: 1 | -1) => gestaoApi.ajustaRevisao(row.id, delta),
    onSuccess: invalidateRows,
  });
  const revisoes = entity === "egp" ? (row.revisoesRegras ?? 0) : 0;
  const [corrData, setCorrData] = useState("");
  const [corrOn, setCorrOn] = useState(true);

  return (
    <>
      <DetailModal title={row.nome} narrow onClose={onClose}>
        <div className="muted" style={{ fontSize: 12 }}>
          {row.area ?? "—"} · etapa atual: <b>{row.etapa ?? "—"}</b>
        </div>

        {entity === "egp" && (
          <div className="gm-pipe-edit">
            <label className="gm-field">
              <span>Etapa</span>
              <select value={row.etapa ?? ""} disabled={pipeMut.isPending || readOnly}
                onChange={(e) => pipeMut.mutate({ etapa: e.target.value })}>
                <option value="">— etapa —</option>
                {PIPELINE_PROJETO.migracao.map((s) => <option key={s} value={s}>{s}</option>)}
                <optgroup label="Fora do funil">
                  {PHANTOM_ETAPAS_MIGRACAO.map((s) => <option key={s} value={s}>{s}</option>)}
                </optgroup>
              </select>
            </label>
            <label className="gm-field">
              <span>Status</span>
              <select value={pipeStatus} title={STATUS_HELP} disabled={pipeMut.isPending || readOnly}
                style={{ background: SEG[pipeStatus]?.bg, color: SEG[pipeStatus]?.fg }}
                onChange={(e) => pipeMut.mutate({ status: e.target.value })}>
                {opcoesStatusEgp(pipeStatus).map((o) => <option key={o.value} value={o.value} disabled={o.disabled}>{o.label}</option>)}
              </select>
            </label>
            {!hideResponsavel && (
              <label className="gm-field">
                <span>Responsável</span>
                <select value={row.responsavel ?? ""} disabled={pipeMut.isPending || readOnly}
                  onChange={(e) => pipeMut.mutate({ responsavel: e.target.value })}>
                  <option value="">—</option>
                  {row.responsavel && !users.some((u) => u.email === row.responsavel) && (
                    <option value={row.responsavel}>{row.responsavel}</option>
                  )}
                  {users.map((u) => <option key={u.email} value={u.email}>{u.nome}</option>)}
                </select>
              </label>
            )}
            {/* Read-only: campo livre editado na aba EGPs (ReadinessView), não duplicamos a
                edição aqui — só informamos quem é do lado BV. Sempre visível (inclusive
                readOnly/Acompanhamento): é o próprio responsável do cliente, não faz sentido
                escondê-lo dele. */}
            <div className="gm-field">
              <span>Resp. BV</span>
              <div className="muted" style={{ fontSize: 12 }}>
                {respBvOf(row, entity, readinessMap).join(", ") || "—"}
              </div>
            </div>
            <div className="gm-field">
              <span>Sub-área BV</span>
              <div className="muted" style={{ fontSize: 12 }}
                title="Área interna do BV — derivada do Responsável BV pelo cadastro em Gestão → Responsáveis BV">
                {subareasDe(respBvOf(row, entity, readinessMap), mapaSub).join(", ")}
              </div>
            </div>
            {pipeMut.isError && <div className="error">Falha ao salvar: {String(pipeMut.error)}</div>}
          </div>
        )}

        {entity === "egp" && (revisoes > 0 || !readOnly) && (
          <div className={`rev-box${revisoes > 0 ? " em-revisao" : ""}`}>
            <div className="rev-box-head">
              <b>Revisão de regras de negócio</b>
              <span className="rev-ctrl">
                {!readOnly && (
                  <button type="button" aria-label="Diminuir revisões"
                    disabled={revisoes === 0 || ajustaRevisao.isPending}
                    onClick={() => ajustaRevisao.mutate(-1)}>−</button>
                )}
                <span className="rev-n">{revisoes}</span>
                {!readOnly && (
                  <button type="button" aria-label="Aumentar revisões" disabled={ajustaRevisao.isPending}
                    onClick={() => ajustaRevisao.mutate(1)}>+</button>
                )}
              </span>
            </div>
            <div className="rev-box-msg">
              {revisoes > 0
                ? `Voltou de PRD para validação em DES ${revisoes === 1 ? "1 vez" : `${revisoes} vezes`}: em revisão de regras de negócio, retornando à esteira.`
                : "Some 1 cada vez que o EGP voltar de PRD para validação em DES. Acima de 0, o card ganha contorno laranja no Kanban."}
            </div>
            {ajustaRevisao.isError && <div className="error">Falha ao salvar: {String(ajustaRevisao.error)}</div>}
          </div>
        )}

        {/* Seções da prontidão do EGP: Inputs (lista, read-only — a etapa de um input só se
            edita pela aba Inputs) → Pré-working (toggle + data manual) → Outputs (lista,
            status = modernizada_auto do artefato; outputs não têm um funil de etapas próprio
            como os inputs, só "Disponível"/"A ingerir" + selo "terminal" quando ninguém do
            corpus consome). */}
        {entity === "egp" && (
          <>
            <h4>Inputs{egpQ.data ? ` (${egpQ.data.inputs.length})` : ""}</h4>
            {egpQ.isFetching && !egpQ.data && <div className="muted">carregando…</div>}
            {egpQ.data && egpQ.data.inputs.length === 0 && <div className="muted">— sem inputs</div>}
            {egpQ.data && egpQ.data.inputs.length > 0 && (
              <div className="gm-sublist">
                {egpQ.data.inputs.map((i) => {
                  const et = effEtapa(i.etapa, i.modernizada_auto);
                  const st = effStatusInput(i.status, i.etapa, i.modernizada_auto);
                  // Sanitizado fica sem botão: /api/gestao/rows exclui sanitizados do
                  // recorte de Inputs, então o Kanban de Inputs nunca teria esse card pra
                  // abrir (onOpenInput levaria a um painel vazio).
                  const sanitizado = st === "Sanitizado";
                  return (
                    <div className="gm-sub-row" key={i.chave_canonica} title={i.artifact}>
                      {sanitizado ? (
                        <span className="gm-sub-row-name">{i.artifact}</span>
                      ) : (
                        <button type="button" className="gm-sub-row-link"
                          onClick={() => onOpenInput?.(i.chave_canonica)}>
                          {i.artifact}
                        </button>
                      )}
                      {tabelaModernizada(i.observacao) && (
                        <span className="gm-sub-row-tabela" title={`Tabela correspondente (modernizada): ${tabelaModernizada(i.observacao)}`}>
                          🗄 {tabelaModernizada(i.observacao)}
                        </span>
                      )}
                      <span className="gm-sub-row-meta">
                        <span className="gm-sub-row-etapa">{et}</span>
                        <span className="kanban-pill" style={{ background: SEG[st]?.bg, color: SEG[st]?.fg }}>
                          {STATUS_ABBR[st] ?? st}
                        </span>
                      </span>
                    </div>
                  );
                })}
              </div>
            )}

            <h4>Pré-working</h4>
            <div className="gm-pipe-edit">
              <label className="gm-field">
                <span>Preenchido</span>
                <button type="button" className={`gm-toggle-btn${preworkingVal ? " on" : ""}`}
                  disabled={pipeMut.isPending || readOnly}
                  title="Questionário de pré-working específico do EGP (não é o checklist do input)"
                  onClick={() => pipeMut.mutate({ preworking: !preworkingVal })}>
                  {preworkingVal ? "✓ Preenchido" : "○ Não preenchido"}
                </button>
              </label>
              <label className="gm-field">
                <span>Data</span>
                <input type="date" value={pwDataInput} disabled={pipeMut.isPending || readOnly}
                  title="Data de referência do pré-working — 100% manual, escolhida pelo usuário"
                  onChange={(e) => setPwDataInput(e.target.value)}
                  onBlur={() => {
                    if (pwDataInput !== (pipeRow?.preworking_data ?? ""))
                      pipeMut.mutate({ preworking_data: pwDataInput || null });
                  }} />
              </label>
              {pipeMut.isError && <div className="error">Falha ao salvar: {String(pipeMut.error)}</div>}
            </div>

            <h4>Outputs{outputsQ.data ? ` (${producedOutputs.length})` : ""}</h4>
            <div className="muted" style={{ fontSize: 11, marginBottom: 4 }}>
              "Auto" é a detecção automática (Chameleon/BQ) — só informativa. O toggle
              "Recebido" é 100% manual e, assim que tocado, passa a valer para a prontidão
              deste output (mesmo espírito do Pré-working acima).
            </div>
            {(outputsQ.isFetching || pairsQ.isFetching) && !outputsQ.data && <div className="muted">carregando…</div>}
            {outputsQ.data && producedOutputs.length === 0 && <div className="muted">— sem outputs</div>}
            {producedOutputs.length > 0 && (
              <div className="gm-sublist">
                {producedOutputs.map((o) => (
                  <OutputManualRow key={o.chave_canonica} artifact={o.artifact}
                    terminal={String(o.terminal) === "true"} autoDisp={o.modernizada_auto === "Disponível"}
                    manual={outPipeMap.get(o.chave_canonica)}
                    disabled={outPipeMut.isPending || !!readOnly}
                    onToggle={(recebido) => outPipeMut.mutate({ chave_canonica: o.chave_canonica, recebido })}
                    onDataBlur={(recebido_data) => outPipeMut.mutate({ chave_canonica: o.chave_canonica, recebido_data })}
                    onCargaFria={(carga_fria) => outPipeMut.mutate({ chave_canonica: o.chave_canonica, carga_fria })} />
                ))}
              </div>
            )}
          </>
        )}

        {entity === "input" && (
          <>
            <div className="gm-pipe-edit">
              <label className="gm-field">
                <span>Etapa</span>
                <select value={row.etapa ?? ""} disabled={inputPatchMut.isPending || readOnly}
                  onChange={(e) => inputPatchMut.mutate({ etapa: e.target.value })}>
                  {PIPELINE_INPUT.map((s) => <option key={s} value={s}>{s}</option>)}
                </select>
              </label>
              <label className="gm-field">
                <span>Status</span>
                <select value={row.status || "A Iniciar"} title={STATUS_HELP} disabled={inputPatchMut.isPending || readOnly}
                  style={{ background: SEG[row.status || "A Iniciar"]?.bg, color: SEG[row.status || "A Iniciar"]?.fg }}
                  onChange={(e) => inputPatchMut.mutate({ status: e.target.value })}>
                  {STATUS_INPUT.map((s) => <option key={s} value={s}>{s}</option>)}
                </select>
              </label>
              {!hideResponsavel && (
                <label className="gm-field">
                  <span>Responsável</span>
                  <select value={row.responsavel ?? ""} disabled={inputPatchMut.isPending || readOnly}
                    onChange={(e) => inputPatchMut.mutate({ responsavel: e.target.value })}>
                    <option value="">—</option>
                    {row.responsavel && !users.some((u) => u.email === row.responsavel) && (
                      <option value={row.responsavel}>{row.responsavel}</option>
                    )}
                    {users.map((u) => <option key={u.email} value={u.email}>{u.nome}</option>)}
                  </select>
                </label>
              )}
              {/* Herdado dos EGPs consumidores (pode ter mais de um) — mesmo padrão de "Usado
                  por" abaixo, ver respBvOf em GestaoKanban.tsx. Read-only pelo mesmo motivo do
                  lado EGP: campo livre editado na aba EGPs, não duplicamos a edição aqui. */}
              <div className="gm-field">
                <span>Resp. BV</span>
                <div className="muted" style={{ fontSize: 12 }}>
                  {respBvOf(row, entity, readinessMap).join(", ") || "—"}
                </div>
              </div>
              <div className="gm-field">
                <span>Sub-área BV</span>
                <div className="muted" style={{ fontSize: 12 }}
                  title="Área interna do BV — derivada do Responsável BV pelo cadastro em Gestão → Responsáveis BV">
                  {subareasDe(respBvOf(row, entity, readinessMap), mapaSub).join(", ")}
                </div>
              </div>
              {inputPatchMut.isError && <div className="error">Falha ao salvar: {String(inputPatchMut.error)}</div>}
            </div>

            {row.cargaFria && (
              <CargaFriaDestino manual={outPipeMap.get(row.id.slice(CF_PREFIX.length))}
                disabled={outPipeMut.isPending || !!readOnly}
                onSave={(v) => outPipeMut.mutate({ chave_canonica: row.id.slice(CF_PREFIX.length), ...v })} />
            )}
            {row.cargaFria && (
              <div className="muted" style={{ fontSize: 12, margin: "6px 0" }}>
                ❄ Este card é um <b>output</b> que precisa de <b>carga fria</b> (histórico). A etapa/status
                acima controlam a ingestão do histórico; desmarque "Carga fria" na aba EGPs para removê-lo.
              </div>
            )}
            {!row.cargaFria && <PreworkingChecklist chave={row.id} readOnly={readOnly} onAutoAvancado={() => {
              qc.invalidateQueries({ queryKey: ["gestao", entity] });
              qc.invalidateQueries({ queryKey: ["inputs"] });
              qc.invalidateQueries({ queryKey: ["metrics"] });
              qc.invalidateQueries({ queryKey: ["resumo"] });
              qc.invalidateQueries({ queryKey: ["landing"] });
              qc.invalidateQueries({ queryKey: ["egp"] });
              qc.invalidateQueries({ queryKey: ["egp-readiness"] });
              qc.invalidateQueries({ queryKey: ["funis"] });
            }} />}

            {/* "Usado por" (pedido cliente BV 2026-08): quais EGPs consomem este input, cada
                um com um botão (abre aquele EGP no Kanban de EGPs, ver onOpenEgp) + um badge
                de PENDÊNCIA — não o %, mas se LIBERAR este input resolveria tudo que falta
                pro EGP ("última pendência") ou se sobra algo (outros inputs/outputs/pré-
                working, "+N pendências"). Os "última pendência" sobem pro topo (mais
                acionáveis primeiro) — ver pendenciaInputParaEgp em GestaoKanban.tsx. */}
            <h4>Usado por {row.egps.length} EGP{row.egps.length === 1 ? "" : "s"}</h4>
            {row.egps.length === 0 && <div className="muted">— nenhum EGP consumidor</div>}
            {row.egps.length > 0 && (
              <div className="gm-sublist">
                {[...row.egps]
                  .map((e) => ({ e, info: pendenciaInputParaEgp(row, e, readinessMap) }))
                  .sort((a, b) => {
                    const au = a.info?.ultima ? 0 : 1;
                    const bu = b.info?.ultima ? 0 : 1;
                    return au !== bu ? au - bu : egpShort(a.e).localeCompare(egpShort(b.e), "pt-BR");
                  })
                  .map(({ e, info }) => (
                    <div className="gm-sub-row" key={e} title={e}>
                      <button type="button" className="gm-sub-row-link"
                        onClick={() => onOpenEgp?.(e)}>
                        {egpShort(e)}
                      </button>
                      <span className="gm-sub-row-meta">
                        {info && (info.ultima ? (
                          <span className="kanban-pill" style={{ background: SEG["Concluído"]?.bg, color: SEG["Concluído"]?.fg }}
                            title="Liberar este input resolve TUDO que falta para este EGP (inputs, outputs e pré-working).">
                            última pendência
                          </span>
                        ) : (
                          <span className="gm-sub-row-etapa"
                            title={`Mesmo liberando este input, ainda restam ${info.outras} pendência(s) para este EGP (outros inputs, outputs e/ou pré-working).`}>
                            +{info.outras} pendência{info.outras === 1 ? "" : "s"}
                          </span>
                        ))}
                      </span>
                    </div>
                  ))}
              </div>
            )}
          </>
        )}

        <h4>Último status</h4>
        {statusQ.isFetching && !statusQ.data && <div className="muted">carregando…</div>}
        {!statusQ.isFetching && !ultimo && <div className="muted">— nenhum status registrado ainda</div>}
        {ultimo && (
          <div className="gm-status gm-status-last">
            <div className="gm-status-meta">{nomeDe(ultimo.autor)} · {fmtTs(ultimo.data)}</div>
            <div className="gm-status-texto">{ultimo.texto}</div>
          </div>
        )}
        {/* Logo abaixo do Último status (pedido 2026-08, todos os Kanbans): adicionar um novo
            comentário é sempre em relação ao MAIS RECENTE — ficar perto dele, sem precisar
            rolar por Validação BV + Histórico inteiro, agiliza o fluxo comum de "só bater o
            olho no último e já comentar de novo". */}
        {isGestao && pode && (
          <button className="theme-btn gm-add-btn" onClick={() => setModal(true)}>
            + Adicionar Comentário
          </button>
        )}

        {/* Seção de eventos de validação BV: visível SÓ para bv_admins (isAdmin). */}
        {isAdmin && (
          <>
            <h4>Validação BV</h4>
            {row.bvEventos.length === 0 && <div className="muted">— sem eventos de validação</div>}
            {row.bvEventos.length > 0 && (
              <div className="gm-bv-log">
                {[...row.bvEventos].reverse().map((ev) => (
                  <div className="gm-bv-ev" key={ev.id}>
                    <span>{fmtBR(ev.data)} · {ev.comBv ? "Com BV" : "Conosco"}{ev.autor ? ` · ${nomeDe(ev.autor)}` : ""}</span>
                    {pode && (
                      <button className="gm-bv-del" title="Remover este evento (correção)"
                        onClick={() => delBV.mutate(ev.id)} disabled={delBV.isPending}>✕</button>
                    )}
                  </div>
                ))}
              </div>
            )}
            {pode && <div className="gm-bv-corr">
              <select value={corrOn ? "on" : "off"} onChange={(e) => setCorrOn(e.target.value === "on")}>
                <option value="on">Com BV</option>
                <option value="off">Conosco</option>
              </select>
              <input type="date" value={corrData} onChange={(e) => setCorrData(e.target.value)} />
              <button className="theme-btn" disabled={!corrData || addBV.isPending}
                onClick={() => { addBV.mutate({ comBv: corrOn, data: corrData }); setCorrData(""); }}>
                + evento na data
              </button>
            </div>}
          </>
        )}

        <h4>Histórico</h4>
        <div className="gm-hist">
          {entries.slice(1).map((e) => (
            <div className="gm-status" key={e.id}>
              <div className="gm-status-meta">{nomeDe(e.autor)} · {fmtTs(e.data)}</div>
              <div className="gm-status-texto">{e.texto}</div>
            </div>
          ))}
          {!statusQ.isFetching && entries.length <= 1 && (
            <div className="muted">— sem registros anteriores</div>
          )}
        </div>
      </DetailModal>

      {modal && (
        <AddCommentModal
          entity={entity}
          defaultId={row.id}
          allRows={allRows}
          users={users}
          onClose={() => setModal(false)}
          onSaved={() => {
            // o comentário vira o novo "último status": tabela (resumo IA) e sidepanel
            // refletem via invalidação — sem reabrir nada.
            qc.invalidateQueries({ queryKey: ["gestao", entity] });
            qc.invalidateQueries({ queryKey: ["gestao-status", entity] });
            setModal(false);
          }}
        />
      )}
    </>
  );
}

// 1 output na lista da seção Outputs do GestaoStatusPanel: nome + badges informativos
// (terminal, detecção automática) na 1ª linha; toggle "Recebido" + data manual na 2ª —
// mesmo padrão visual (gm-toggle-btn) da seção Pré-working do EGP, só que repetido por
// output. Data em buffer local (mesmo motivo do pwDataInput do painel: útil pq o valor do
// servidor pode chegar/mudar depois do 1º render, inclusive após o próprio mutate).
function OutputManualRow({ artifact, terminal, autoDisp, manual, disabled, onToggle, onDataBlur, onCargaFria }: {
  artifact: string;
  terminal: boolean;
  autoDisp: boolean;
  manual: OutputPipelineRow | undefined;
  disabled: boolean;
  onToggle: (recebido: boolean) => void;
  onDataBlur: (data: string | null) => void;
  onCargaFria: (v: boolean) => void;
}) {
  const recebidoVal = manual?.recebido === "true";
  const cargaFria = manual?.carga_fria === "true";
  const [dataInput, setDataInput] = useState(manual?.recebido_data ?? "");
  useEffect(() => {
    setDataInput(manual?.recebido_data ?? "");
  }, [manual?.recebido_data]);
  const autoSeg = autoDisp ? SEG["Concluído"] : SEG["A Iniciar"];
  return (
    <div className="gm-sub-row gm-out-row" title={artifact}>
      <div className="gm-sub-row-top">
        <span className="gm-sub-row-name">{artifact}</span>
        <span className="gm-sub-row-meta">
          {terminal && (
            <span className="gm-sub-row-etapa" title="Nenhum EGP do corpus consome este output">
              terminal
            </span>
          )}
          <span className="kanban-pill" style={{ background: autoSeg?.bg, color: autoSeg?.fg }}
            title="Detecção automática (Chameleon/BQ) — informativa, não conta mais para a prontidão">
            Auto: {autoDisp ? "Disponível" : "A ingerir"}
          </span>
        </span>
      </div>
      <div className="gm-out-manual">
        <button type="button" className={`gm-toggle-btn gm-toggle-btn-sm${recebidoVal ? " on" : ""}`}
          disabled={disabled}
          title="Recebimento manual deste output — conta para a prontidão"
          onClick={() => onToggle(!recebidoVal)}>
          {recebidoVal ? "✓ Recebido" : "○ Não recebido"}
        </button>
        <input type="date" className="gm-out-date" value={dataInput} disabled={disabled}
          title="Data de referência do recebimento — 100% manual"
          onChange={(e) => setDataInput(e.target.value)}
          onBlur={() => {
            if (dataInput !== (manual?.recebido_data ?? "")) onDataBlur(dataInput || null);
          }} />
        <button type="button" className={`gm-toggle-btn gm-toggle-btn-sm${cargaFria ? " on" : ""}`}
          disabled={disabled}
          title="Marca os outputs que precisam de carga fria (histórico) — só sinalização, não afeta a prontidão"
          onClick={() => onCargaFria(!cargaFria)}>
          {cargaFria ? "❄ Carga fria" : "○ Sem carga fria"}
        </button>
      </div>
    </div>
  );
}

// Janela do histórico (de/até) e caminho final dos arquivos de um card de carga fria. Buffer
// local por campo (o valor do servidor pode chegar depois do 1º render); grava no blur, só se mudou.
function CargaFriaDestino({ manual, disabled, onSave }: {
  manual: OutputPipelineRow | undefined;
  disabled: boolean;
  onSave: (v: { cf_inicio?: string; cf_fim?: string; cf_caminho?: string; cf_tabela?: string }) => void;
}) {
  const [ini, setIni] = useState(manual?.cf_inicio ?? "");
  const [fim, setFim] = useState(manual?.cf_fim ?? "");
  const [cam, setCam] = useState(manual?.cf_caminho ?? "");
  const [tab, setTab] = useState(manual?.cf_tabela ?? "");
  useEffect(() => { setIni(manual?.cf_inicio ?? ""); }, [manual?.cf_inicio]);
  useEffect(() => { setFim(manual?.cf_fim ?? ""); }, [manual?.cf_fim]);
  useEffect(() => { setCam(manual?.cf_caminho ?? ""); }, [manual?.cf_caminho]);
  useEffect(() => { setTab(manual?.cf_tabela ?? ""); }, [manual?.cf_tabela]);
  const invalido = !!ini && !!fim && ini > fim;
  return (
    <div className="gm-pipe-edit">
      <label className="gm-field" title="Início do período de histórico a ser ingerido">
        <span>Histórico de</span>
        <input type="date" value={ini} disabled={disabled} onChange={(e) => setIni(e.target.value)}
          onBlur={() => { if (ini !== (manual?.cf_inicio ?? "") && !(ini && fim && ini > fim)) onSave({ cf_inicio: ini }); }} />
      </label>
      <label className="gm-field" title="Fim do período de histórico a ser ingerido">
        <span>Histórico até</span>
        <input type="date" value={fim} disabled={disabled} onChange={(e) => setFim(e.target.value)}
          onBlur={() => { if (fim !== (manual?.cf_fim ?? "") && !(ini && fim && ini > fim)) onSave({ cf_fim: fim }); }} />
      </label>
      {invalido && <div className="error">A data inicial não pode ser posterior à final.</div>}
      <label className="gm-field" title="Nome da tabela modernizada que receberá o histórico (equivale a Tbl. Corresp. dos inputs)">
        <span>Tabela modern.</span>
        <input type="text" value={tab} disabled={disabled} placeholder="ex.: bv-pdbd-prd.trusted_x.tabela"
          onChange={(e) => setTab(e.target.value)}
          onBlur={() => { if (tab.trim() !== (manual?.cf_tabela ?? "")) onSave({ cf_tabela: tab.trim() }); }} />
      </label>
      <label className="gm-field" title="Local final onde os arquivos do histórico estarão">
        <span>Caminho final</span>
        <input type="text" value={cam} disabled={disabled} placeholder="ex.: gs://bucket/pasta ou catalogo.schema.tabela"
          onChange={(e) => setCam(e.target.value)}
          onBlur={() => { if (cam.trim() !== (manual?.cf_caminho ?? "")) onSave({ cf_caminho: cam.trim() }); }} />
      </label>
    </div>
  );
}

// Modal "Adicionar Comentário": data de hoje travada, autor do grupo bv_users, EGP/Input
// pré-selecionado (editável), textarea. Persiste via gestaoApi.addStatus (nunca só local).
export function AddCommentModal({ entity, defaultId, allRows, users, onClose, onSaved }: {
  entity: EntityType;
  defaultId: string;
  allRows: GestaoRow[];
  users: GestaoUser[];
  onClose: () => void;
  onSaved: () => void;
}) {
  const [autor, setAutor] = useState("");
  const [target, setTarget] = useState(defaultId);
  const [texto, setTexto] = useState("");

  const save = useMutation({
    mutationFn: () => gestaoApi.addStatus(entity, target, autor, texto.trim()),
    onSuccess: onSaved,
  });
  const podeSalvar = texto.trim() !== "" && autor !== "" && !save.isPending;

  return (
    <>
      <div className="drawer-overlay gm-modal-overlay" onClick={onClose} />
      <div className="gm-modal" role="dialog" aria-label="Adicionar comentário">
        <h4>Adicionar Comentário</h4>
        <label className="gm-field">
          <span>Data</span>
          <input type="text" value={fmtBR(hojeSP())} disabled title="Preenchida automaticamente (hoje)" />
        </label>
        <label className="gm-field">
          <span>Nome</span>
          <select value={autor} onChange={(e) => setAutor(e.target.value)}>
            <option value="">— selecione (grupo bv_users) —</option>
            {users.map((u) => <option key={u.email} value={u.email}>{u.nome}</option>)}
          </select>
        </label>
        <label className="gm-field">
          <span>{entity === "egp" ? "EGP" : "Input"}</span>
          <select value={target} onChange={(e) => setTarget(e.target.value)}>
            {allRows.map((r) => (
              <option key={r.id} value={r.id}>{entity === "egp" ? egpShort(r.id) : r.nome}</option>
            ))}
          </select>
        </label>
        <label className="gm-field gm-field-area">
          <span>Comentário</span>
          <textarea rows={6} value={texto} onChange={(e) => setTexto(e.target.value)}
            placeholder="Status/comentário (suporta múltiplas linhas e bullets)…" autoFocus />
        </label>
        {save.isError && <div className="error">Falha ao salvar: {String(save.error)}</div>}
        <div className="gm-modal-actions">
          <button className="ghost" onClick={onClose} disabled={save.isPending}>Cancelar</button>
          <button className="theme-btn" onClick={() => save.mutate()} disabled={!podeSalvar}>
            {save.isPending ? "Salvando…" : "Salvar"}
          </button>
        </div>
      </div>
    </>
  );
}
