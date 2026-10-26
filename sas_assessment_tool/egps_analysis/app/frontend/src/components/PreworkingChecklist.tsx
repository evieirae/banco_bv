import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api";
import { fmtTsBR } from "../diasUteis";
import type { PreworkingRow } from "../types";
import { PREWORKING_FREQUENCIA, PREWORKING_TIPO_CARGA, PREWORKING_POS_PROC, PREWORKING_DADOS_SENSIVEIS } from "../pipeline";
import { preworkingPercentual, preworkingDuracaoDias } from "../inputs";
import { usePodeEscrever } from "../usePodeEscrever";

interface Props {
  chave: string;
  readOnly?: boolean;
  // Chamado quando o checklist bate 100% e o input avança sozinho de etapa/status
  // (auto_avancado do backend) — cada tela invalida as queries que dependem disso (a aba
  // Inputs invalida ["inputs"]/["audit",...], a Gestão invalida ["gestao","input"], etc.).
  // A própria query ["preworking"] (compartilhada) já é atualizada aqui dentro.
  onAutoAvancado?: () => void;
}

// Checklist de pré-working de 1 input — extraído do InputDetailPanel (aba Monitoramento
// Inputs) p/ ser reusado também no GestaoStatusPanel (side panel do Kanban de Inputs, pedido
// 2026-08): mesmo componente, 2 pontos de entrada, queryKey ["preworking"] compartilhada
// (cache dedupa fetch entre os dois).
export function PreworkingChecklist({ chave, readOnly: readOnlyProp, onAutoAvancado }: Props) {
  const pode = usePodeEscrever();
  const readOnly = readOnlyProp || !pode;
  const qc = useQueryClient();
  const pwkKey = ["preworking"] as const;
  const pwkQ = useQuery({ queryKey: pwkKey, queryFn: () => api.preworkingRows() });
  const pwk = pwkQ.data?.rows.find((r) => r.chave_canonica === chave) ?? null;
  const pwkPct = preworkingPercentual(pwk);
  const pwkDias = preworkingDuracaoDias(pwk);
  const [justAdvanced, setJustAdvanced] = useState(false);
  useEffect(() => {
    if (!justAdvanced) return;
    const t = setTimeout(() => setJustAdvanced(false), 8000);
    return () => clearTimeout(t);
  }, [justAdvanced]);
  const pwkMut = useMutation({
    mutationFn: (patch: Partial<PreworkingRow>) =>
      api.preworkingPatch({ chave_canonica: chave, ...patch }),
    onSuccess: (updated) => {
      qc.setQueryData<{ rows: PreworkingRow[] }>(pwkKey, (old) => {
        const rows = old?.rows ?? [];
        const i = rows.findIndex((r) => r.chave_canonica === chave);
        if (i < 0) return { rows: [...rows, updated] };
        const next = [...rows];
        next[i] = { ...next[i], ...updated };
        return { rows: next };
      });
      if (updated.auto_avancado) {
        setJustAdvanced(true);
        onAutoAvancado?.();
      }
    },
  });
  const onPwkPatch = (patch: Partial<PreworkingRow>) => pwkMut.mutate(patch);

  return (
    <>
      <h4>
        Checklist de Pré-Working (Ingestão){" "}
        <span className={pwkPct === 100 ? "pwk-pct-ok" : pwkPct > 0 ? "pwk-pct-mid" : "pwk-pct-zero"}>
          {pwkPct}%
        </span>
      </h4>
      <div className="muted" style={{ fontSize: 11, marginBottom: 4 }}>
        Preenchimento manual (área de negócio) — ao chegar em 100% o input é liberado
        automaticamente para a próxima etapa da esteira (Ingestão UAT).
      </div>
      {pwk?.herdado_de && (
        <div className="muted" style={{ fontSize: 11, marginBottom: 4 }}>
          Herdado de <code>{pwk.herdado_de}</code>: o checklist tinha sido preenchido numa
          carga desta família. O primeiro salvamento aqui grava na família.
        </div>
      )}
      {pwk?.iniciado_em && (
        <div className="muted" style={{ fontSize: 11, marginBottom: 4 }}>
          Iniciado em {fmtTsBR(pwk.iniciado_em, false)}
          {pwk.concluido_em ? (
            <> · Concluído em {fmtTsBR(pwk.concluido_em, false)}
              {pwkDias !== null && <> · levou <b>{pwkDias}</b> {pwkDias === 1 ? "dia útil" : "dias úteis"}</>}
            </>
          ) : " · ainda em preenchimento"}
        </div>
      )}
      {justAdvanced && (
        <div className="pwk-advanced">
          🎉 Checklist completo — input liberado para <b>Ingestão UAT</b> (status "A Iniciar").
        </div>
      )}
      <div className="drawer-pwk">
        <label className="gm-field">
          <span>Origem</span>
          <input defaultValue={pwk?.origem_arquivo ?? ""} placeholder="Caminho de rede, S3, SFTP ou pasta…"
            disabled={readOnly}
            onBlur={(e) => {
              const v = e.target.value.trim();
              if (v !== (pwk?.origem_arquivo ?? "")) onPwkPatch({ origem_arquivo: v });
            }} />
        </label>
        <label className="gm-field">
          <span>Frequência</span>
          <select value={pwk?.frequencia ?? ""} disabled={readOnly} onChange={(e) => onPwkPatch({ frequencia: e.target.value })}>
            <option value="">— selecione —</option>
            {PREWORKING_FREQUENCIA.map((f) => <option key={f} value={f}>{f}</option>)}
          </select>
        </label>
        <label className="gm-field">
          <span>Horário</span>
          <input defaultValue={pwk?.horario ?? ""} placeholder="ex.: 06:00, ou após job X…"
            disabled={readOnly}
            onBlur={(e) => {
              const v = e.target.value.trim();
              if (v !== (pwk?.horario ?? "")) onPwkPatch({ horario: v });
            }} />
        </label>
        <label className="gm-field">
          <span>Tipo de carga</span>
          <select value={pwk?.tipo_carga ?? ""} disabled={readOnly} onChange={(e) => onPwkPatch({ tipo_carga: e.target.value })}>
            <option value="">— selecione —</option>
            {PREWORKING_TIPO_CARGA.map((t) => <option key={t} value={t}>{t}</option>)}
          </select>
        </label>
        <label className="gm-field">
          <span>Pós-process.</span>
          <select value={pwk?.pos_processamento ?? ""} disabled={readOnly} onChange={(e) => onPwkPatch({ pos_processamento: e.target.value })}>
            <option value="">— selecione —</option>
            {PREWORKING_POS_PROC.map((o) => <option key={o} value={o}>{o}</option>)}
          </select>
        </label>
        <label className="gm-field">
          <span>Dados sensíveis (LGPD)</span>
          <select value={pwk?.dados_sensiveis ?? ""} disabled={readOnly} onChange={(e) => onPwkPatch({ dados_sensiveis: e.target.value })}>
            <option value="">— selecione —</option>
            {PREWORKING_DADOS_SENSIVEIS.map((o) => <option key={o} value={o}>{o}</option>)}
          </select>
        </label>
        <label className="gm-field">
          <span>Recebimento</span>
          <span className="pwk-checkbox">
            <input type="checkbox" checked={pwk?.recebido === "true"} disabled={readOnly}
              onChange={(e) => onPwkPatch({ recebido: e.target.checked ? "true" : "false" })} />
            <span className="muted" style={{ fontSize: 11 }}>arquivo recebido</span>
          </span>
        </label>
        <label className="gm-field">
          <span>Data de recebimento</span>
          <input type="date" defaultValue={pwk?.data_recebimento ?? ""} disabled={readOnly}
            onBlur={(e) => {
              const v = e.target.value;
              if (v !== (pwk?.data_recebimento ?? "")) onPwkPatch({ data_recebimento: v });
            }} />
        </label>
      </div>
      <div className="drawer-pwk">
        <label className="gm-field">
          <span>Modernizado pelo BV</span>
          <span className="pwk-checkbox">
            <input type="checkbox" checked={pwk?.modernizado_bv === "true"} disabled={readOnly}
              onChange={(e) => onPwkPatch({ modernizado_bv: e.target.checked ? "true" : "false" })} />
            <span className="muted" style={{ fontSize: 11 }}>modernizado fora da nossa esteira</span>
          </span>
        </label>
        <label className="gm-field">
          <span>Data da modernização (BV)</span>
          <input type="date" defaultValue={pwk?.data_modernizado_bv ?? ""} disabled={readOnly}
            onBlur={(e) => {
              const v = e.target.value;
              if (v !== (pwk?.data_modernizado_bv ?? "")) onPwkPatch({ data_modernizado_bv: v });
            }} />
        </label>
      </div>
      <div className="muted" style={{ fontSize: 11, margin: "-4px 0 8px" }}>
        Marcação opcional — não conta para o % de completude do checklist acima.
      </div>
      {pwk?.updated_by && (
        <div className="muted" style={{ fontSize: 11, margin: "4px 0 8px" }}>
          atualizado por {pwk.updated_by} · {fmtTsBR(pwk.updated_at, false)}
        </div>
      )}
      {pwkMut.isError && <div className="error">Falha ao salvar checklist: {String(pwkMut.error)}</div>}
    </>
  );
}
