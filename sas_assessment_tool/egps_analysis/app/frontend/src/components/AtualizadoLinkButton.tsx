import { useEffect, useMemo, useRef, useState } from "react";
import type { EgpAtualizadoRow, ReadinessRow } from "../types";

// Badge/botão "EGP atualizado" na aba EGPs — pedido 2026-09: dado que o pareamento
// AUTOMÁTICO (hash de tasks, feito offline em publish_egps_atualizados.py e exposto
// como egp_original em sas_egp_atualizados) nem sempre acerta (confianca_par pode ser
// alerta/forçado), o botão mostra a sugestão automática mas deixa o humano CONFIRMAR ou
// TROCAR via busca — o vínculo manual (sas_egp_pipeline.egp_atualizado_key) sempre vence
// o automático quando presente (ver resolução em _egp_readiness_rows, main.py).
const CONF_LABEL: Record<string, string> = {
  ok: "pareamento automático confiável",
  alerta: "pareamento automático com alerta — confira antes de confiar",
  forcado: "pareamento automático forçado (baixa confiança)",
};

export function AtualizadoLinkButton({ row, options, onLink }: {
  row: ReadinessRow;
  options: EgpAtualizadoRow[];
  onLink: (egpKey: string | null) => void;
}) {
  const [open, setOpen] = useState(false);
  const [q, setQ] = useState("");
  const ref = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (!open) return;
    setQ("");
    inputRef.current?.focus();
    const h = (e: MouseEvent) => { if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false); };
    const k = (e: KeyboardEvent) => { if (e.key === "Escape") setOpen(false); };
    document.addEventListener("mousedown", h);
    document.addEventListener("keydown", k);
    return () => { document.removeEventListener("mousedown", h); document.removeEventListener("keydown", k); };
  }, [open]);

  const confirmed = !!row.egp_atualizado_key;
  const linkKey = row.atualizado_link_key ?? null;
  const linkNome = row.atualizado_link_nome ?? null;

  const filtered = useMemo(() => {
    const t = q.trim().toLowerCase();
    if (!t) return options;
    return options.filter((o) =>
      o.nome.toLowerCase().includes(t) || o.area.toLowerCase().includes(t) || o.egp_key.toLowerCase().includes(t));
  }, [q, options]);

  const label = linkKey ? (confirmed ? linkNome : `${linkNome}?`) : "vincular atualização";

  return (
    <div className="atu-wrap" ref={ref} onClick={(e) => e.stopPropagation()}>
      <button type="button"
        className={`atu-btn ${confirmed ? "confirmed" : linkKey ? "suggested" : "empty"}`}
        aria-expanded={open} aria-haspopup="listbox"
        title={confirmed
          ? `Vínculo confirmado com a versão atualizada "${linkNome}" — clique para trocar/desvincular`
          : linkKey
            ? `Sugestão automática (${CONF_LABEL[row.atualizado_auto_confianca ?? ""] ?? row.atualizado_auto_confianca}) — clique para confirmar ou trocar`
            : "Vincular este EGP a uma versão atualizada recebida (aba EGPs Atualizados)"}
        onClick={() => setOpen((o) => !o)}>
        {confirmed ? "🔗" : linkKey ? "❔" : "＋"} {label}
      </button>
      {open && (
        <div className="atu-panel">
          <input ref={inputRef} type="text" className="atu-search" placeholder="Buscar por nome, área ou chave…"
            value={q} onChange={(e) => setQ(e.target.value)} />
          {(linkKey || (row.atualizado_auto_key && row.atualizado_auto_key !== row.egp_atualizado_key)) && (
            <div className="atu-quick">
              {row.atualizado_auto_key && row.atualizado_auto_key !== row.egp_atualizado_key && (
                <button type="button" className="atu-confirm"
                  onClick={() => { onLink(row.atualizado_auto_key!); setOpen(false); }}>
                  ✓ confirmar sugestão: <b>{row.atualizado_auto_nome}</b>
                </button>
              )}
              {linkKey && (
                <button type="button" className="atu-unlink"
                  onClick={() => { onLink(null); setOpen(false); }}>
                  ✕ desvincular
                </button>
              )}
            </div>
          )}
          <div className="atu-list" role="listbox">
            {filtered.length === 0 && <div className="atu-empty">nenhum EGP atualizado encontrado</div>}
            {filtered.slice(0, 200).map((o) => (
              <button key={o.egp_key} type="button" role="option" aria-selected={o.egp_key === linkKey}
                className={`atu-opt ${o.egp_key === linkKey ? "sel" : ""}`}
                onClick={() => { onLink(o.egp_key); setOpen(false); }}>
                <span className="atu-opt-nome">{o.nome}</span>
                <span className="atu-opt-area">{o.area}</span>
                {o.confianca_par && <span className={`atu-conf atu-conf-${o.confianca_par}`}>{o.confianca_par}</span>}
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
