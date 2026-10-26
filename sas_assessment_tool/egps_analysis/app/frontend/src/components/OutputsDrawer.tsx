import { useEffect } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "../api";
import type { OutputRow } from "../types";
import { pathFor, spaLinkClick } from "../routes";
import { usePodeEscrever } from "../usePodeEscrever";

const shortName = (id: string) => (id.includes("__") ? id.split("__").slice(1).join("__") : id);
const isIndi = (v: string | boolean | null | undefined) => v === true || v === "true";
const isTruthy = (v: boolean | string | null | undefined) => v === true || v === "true";

interface Props {
  row: OutputRow;
  onClose: () => void;
  onOpenEgp: (projeto: string) => void;
}

export function OutputsDrawer({ row, onClose, onOpenEgp }: Props) {
  const qc = useQueryClient();
  const detail = useQuery({
    queryKey: ["output", row.chave_canonica],
    queryFn: () => api.outputDetail(row.chave_canonica),
  });

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose]);

  const produtores = detail.data?.produtores ?? [];
  const criadores = produtores.filter((e) => !e.apenas_contribui);
  const consumidores = detail.data?.consumidores ?? [];
  const brokenConsumers = consumidores.filter((c) => c.link_broken).length;
  const activeConsumers = consumidores.length - brokenConsumers;
  const escolhido = detail.data?.produtor_escolhido ?? null;
  const isTerminal = isTruthy(row.terminal);
  const ambiguo = criadores.length > 1;

  // Uma escolha poda o grafo (backend _prune_edges) — reflete na hora; invalidamos o
  // conjunto de superfícies derivadas, igual ao fluxo do escopo (IndiciumView).
  const invalidate = () =>
    ["output", "outputs", "egp-readiness", "funis", "priorizacao", "landing"]
      .forEach((k) => qc.invalidateQueries({ queryKey: [k] }));
  const setMut = useMutation({
    mutationFn: (projeto: string) => api.setOutputProducer(row.chave_canonica, projeto),
    onSettled: invalidate,
  });
  const clearMut = useMutation({
    mutationFn: () => api.clearOutputProducer(row.chave_canonica),
    onSettled: invalidate,
  });
  const busy = setMut.isPending || clearMut.isPending;
  const pode = usePodeEscrever();

  return (
    <>
      <div className="drawer-overlay" onClick={onClose} />
      <aside className="drawer" role="dialog" aria-label="Detalhe do output">
        <header className="drawer-head">
          <div className="drawer-title" title={row.artifact}>{row.artifact}</div>
          <button className="drawer-x" onClick={onClose} aria-label="Fechar">✕</button>
        </header>

        <div className="drawer-meta">
          <div><span className="k">Categoria</span><span>{row.categoria}</span></div>
          <div><span className="k">Área(s)</span><span title={row.areas}>{row.areas || "—"}</span></div>
          <div><span className="k">Tipo</span><span>{isTerminal ? "Terminal" : "Intermediário"}</span></div>
          <div><span className="k">Disponível</span>
            <span className={`pill ${row.modernizada_auto === "Disponível" ? "ok" : "todo"}`}>
              {row.modernizada_auto === "Disponível" ? "BQ" : "ingerir"}
            </span>
          </div>
        </div>

        <h4>
          Produzido por {produtores.length} EGP{produtores.length === 1 ? "" : "s"}
          {ambiguo && (
            <span style={{ marginLeft: 8, fontSize: 11, fontWeight: 600, color: "#b45309",
              background: "#fef3c7", borderRadius: 4, padding: "1px 6px" }}>
              {escolhido ? "produtor definido" : "ambíguo — escolha o correto"}
            </span>
          )}
        </h4>
        {ambiguo && (
          <div className="muted" style={{ fontSize: 12, marginBottom: 6 }}>
            Selecione o produtor <b>correto</b> — as dependências dos demais são podadas do grafo (na hora).
            {escolhido && pode && (
              <button className="linklike" style={{ marginLeft: 8 }} disabled={busy}
                onClick={() => clearMut.mutate()}>limpar escolha</button>
            )}
            {busy && <span style={{ marginLeft: 8 }}>salvando…</span>}
          </div>
        )}
        {detail.isFetching && <div className="muted">carregando…</div>}
        <div className="drawer-egps">
          {produtores.map((e) => {
            const chosen = escolhido === e.projeto;
            const pruned = ambiguo && !!escolhido && !chosen;
            return (
              <div key={e.projeto} style={{ display: "flex", alignItems: "center", gap: 6, opacity: pruned ? 0.45 : 1 }}>
                {ambiguo && !e.apenas_contribui && pode && (
                  <input type="radio" name={`prod-${row.chave_canonica}`} checked={chosen}
                    disabled={busy} onChange={() => setMut.mutate(e.projeto)}
                    title="marcar como produtor correto" style={{ flex: "0 0 auto" }} />
                )}
                <a className="drawer-egp" style={{ flex: 1 }}
                  href={pathFor("readiness", e.projeto)}
                  title={`${e.apenas_contribui ? `${e.projeto} — só contribui (INSERT/UPDATE), não cria a tabela` : e.projeto} · botão do meio/ctrl+clique: nova guia`}
                  onClick={(ev) => spaLinkClick(ev, () => onOpenEgp(e.projeto))}>
                  <span className="de-name">
                    {Number(e.ciclo_id) > 0 ? "⟳ " : ""}{shortName(e.projeto)}
                    {isIndi(e.escopo_indi) ? " ◆" : ""}{chosen ? " ✓" : ""}
                  </span>
                  <span className="de-meta">{e.area ?? "?"} · {e.onda ?? "—"}{e.apenas_contribui ? " · contribui (não cria)" : ""}</span>
                </a>
              </div>
            );
          })}
          {!detail.isFetching && produtores.length === 0 && (
            <div className="muted">— nenhum produtor no corpus</div>
          )}
        </div>

        <h4>
          Consumido por {activeConsumers} EGP{activeConsumers === 1 ? "" : "s"}
          {brokenConsumers > 0 && <span className="muted" style={{ fontSize: 12, fontWeight: 400, marginLeft: 6 }}>+ {brokenConsumers} com vínculo quebrado</span>}
        </h4>
        {detail.isFetching && <div className="muted">carregando…</div>}
        {detail.error && <div className="error">{String(detail.error)}</div>}
        <div className="drawer-egps">
          {consumidores.map((e) => (
            <a key={e.projeto} className="drawer-egp"
              style={{ opacity: e.link_broken ? 0.55 : 1 }}
              href={pathFor("readiness", e.projeto)}
              title={`${e.projeto} — clique: abre o EGP · botão do meio/ctrl+clique: nova guia`}
              onClick={(ev) => spaLinkClick(ev, () => onOpenEgp(e.projeto))}>
              <span className="de-name">
                {Number(e.ciclo_id) > 0 ? "⟳ " : ""}{shortName(e.projeto)}{isIndi(e.escopo_indi) ? " ◆" : ""}
                {e.link_broken && <span style={{ marginLeft: 4 }} title="Vínculo quebrado — este EGP declarou não depender deste output">⛓️‍💥</span>}
              </span>
              <span className="de-meta">{e.area ?? "?"} · {e.onda ?? "—"}</span>
            </a>
          ))}
          {!detail.isFetching && consumidores.length === 0 && (
            <div className="muted">— nenhum consumidor — output terminal</div>
          )}
        </div>
      </aside>
    </>
  );
}
