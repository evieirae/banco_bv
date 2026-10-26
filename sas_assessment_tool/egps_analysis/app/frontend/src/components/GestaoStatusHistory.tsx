import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { gestaoApi, usuariosGestao, type EntityType, type GestaoRow } from "../gestaoApi";
import { fmtBR, fmtTsBR } from "../diasUteis";
import { api } from "../api";
import { AddCommentModal } from "./GestaoStatusPanel";
import { usePodeEscrever } from "../usePodeEscrever";

// Último status + histórico de comentários da Gestão (entity/id) + "+ Adicionar
// Comentário" + Validação BV (só admins) — embutível em qualquer modal de detalhe.
// Extraído do GestaoStatusPanel (pedido 2026-08-28: ver o histórico direto no modal do
// EGP/Input, sem o clique extra no "último status"). Auto-suficiente: todas as queries
// usam as MESMAS query keys das abas Gestão/EGPs, então o react-query dedupa.
export function GestaoStatusHistory({ entity, id }: { entity: EntityType; id: string }) {
  const qc = useQueryClient();
  const [modal, setModal] = useState(false);
  const statusQ = useQuery({
    queryKey: ["gestao-status", entity, id],
    queryFn: () => gestaoApi.listStatus(entity, id),
  });
  const entries = statusQ.data ?? [];
  const ultimo = entries[0];
  const usersQ = useQuery({ queryKey: ["analistas"], queryFn: () => api.analistas(), select: usuariosGestao });
  const users = usersQ.data ?? [];
  const rowsQ = useQuery({ queryKey: ["gestao", entity], queryFn: () => gestaoApi.listRows(entity) });
  const allRows: GestaoRow[] = rowsQ.data ?? [];
  const gRow = allRows.find((r) => r.id === id);
  const cfgQ = useQuery({ queryKey: ["config"], queryFn: () => api.config() });
  const isGestao = !!cfgQ.data?.is_gestao;
  const isAdmin = !!cfgQ.data?.is_admin;
  const pode = usePodeEscrever();
  const nomeDe = (email: string) => users.find((u) => u.email === email)?.nome ?? email;
  const invalidateRows = () => qc.invalidateQueries({ queryKey: ["gestao", entity] });

  // Validação BV (append-only + correção retroativa) — mesmo fluxo do GestaoStatusPanel
  const addBV = useMutation({
    mutationFn: (v: { comBv: boolean; data?: string }) => gestaoApi.setBV(entity, id, v.comBv, v.data),
    onSuccess: invalidateRows,
  });
  const delBV = useMutation({
    mutationFn: (bid: string) => gestaoApi.deleteBV(bid),
    onSuccess: invalidateRows,
  });
  const [corrData, setCorrData] = useState("");
  const [corrOn, setCorrOn] = useState(true);

  return (
    <>
      {statusQ.isFetching && !statusQ.data && <div className="muted">carregando…</div>}
      {!statusQ.isFetching && !ultimo && <div className="muted">— nenhum status registrado ainda</div>}
      {ultimo && (
        <div className="gm-status gm-status-last">
          <div className="gm-status-meta">{nomeDe(ultimo.autor)} · {fmtTsBR(ultimo.data)}</div>
          <div className="gm-status-texto">{ultimo.texto}</div>
        </div>
      )}

      {/* Seção de eventos de validação BV: visível SÓ para bv_admins (isAdmin). */}
      {isAdmin && gRow && (
        <>
          <h4>Validação BV</h4>
          {gRow.bvEventos.length === 0 && <div className="muted">— sem eventos de validação</div>}
          {gRow.bvEventos.length > 0 && (
            <div className="gm-bv-log">
              {[...gRow.bvEventos].reverse().map((ev) => (
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

      {/* botão perto do Último status (decisão do develop 2026-08: comentar é sempre em
          relação ao mais recente — sem rolar pelo histórico inteiro) */}
      {isGestao && pode && (
        <button className="theme-btn gm-add-btn" onClick={() => setModal(true)}>
          + Adicionar Comentário
        </button>
      )}
      {entries.length > 1 && (
        <div className="gm-hist">
          {entries.slice(1).map((e) => (
            <div className="gm-status" key={e.id}>
              <div className="gm-status-meta">{nomeDe(e.autor)} · {fmtTsBR(e.data)}</div>
              <div className="gm-status-texto">{e.texto}</div>
            </div>
          ))}
        </div>
      )}
      {modal && (
        <AddCommentModal
          entity={entity} defaultId={id} allRows={allRows} users={users}
          onClose={() => setModal(false)}
          onSaved={() => {
            // o comentário vira o novo "último status": tabelas e stats refletem via invalidação
            qc.invalidateQueries({ queryKey: ["gestao", entity] });
            qc.invalidateQueries({ queryKey: ["gestao-status", entity] });
            setModal(false);
          }}
        />
      )}
    </>
  );
}
