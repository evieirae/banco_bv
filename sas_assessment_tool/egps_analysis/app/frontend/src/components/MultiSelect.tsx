import { useEffect, useRef, useState } from "react";

// Filtro multi-seleção reusável (dropdown com checkboxes; seleção vazia = todos).
// `colors` opcional pinta a bolinha por opção; `title` vira tooltip no botão.
// `labels` opcional mapeia value->texto exibido (ex.: email do responsável -> nome).
export function MultiSelect({ label, options, sel, onToggle, onSelectAll, onClear, colors, title, labels }: {
  label: string;
  options: string[];
  sel: Set<string>;
  onToggle: (s: string) => void;
  // "selecionar todos" em UMA transição de estado. Obrigatório p/ consumidores que derivam o
  // novo valor do estado CAPTURADO NO RENDER (FilterBar: toggleArr(filters.etapa, v)) — ver
  // selectAll abaixo. Quem usa setState funcional pode omitir.
  onSelectAll?: (options: string[]) => void;
  onClear: () => void;
  colors?: Record<string, { bg: string; fg: string }>;
  title?: string;
  labels?: Record<string, string>;
}) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const h = (e: MouseEvent) => { if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false); };
    const k = (e: KeyboardEvent) => { if (e.key === "Escape") setOpen(false); };
    document.addEventListener("mousedown", h);
    document.addEventListener("keydown", k);
    return () => { document.removeEventListener("mousedown", h); document.removeEventListener("keydown", k); };
  }, [open]);
  // "selecionar todos" — pedido 2026-08 p/ quando o usuário quer excluir só 1-2 categorias:
  // em vez de clicar em todas as OUTRAS uma a uma, marca tudo e desmarca o que não quer. Note
  // que isso NÃO é o mesmo que a seleção vazia (= "todos" sem filtrar) — aqui o Set fica com
  // TODAS as opções, então dá pra tirar uma sem cair de volta em "sem filtro".
  // Preferimos onSelectAll (1 update com a lista inteira). O fallback opção-a-opção só é
  // correto quando o consumidor usa setState FUNCIONAL: se ele calcular o próximo valor a
  // partir do estado capturado no render (o caso do FilterBar), as N chamadas partem todas
  // do mesmo valor velho e a última sobrescreve as outras — marcava só 1 item (fix 2026-09).
  const selectAll = () => {
    if (onSelectAll) { onSelectAll(options); return; }
    for (const o of options) if (!sel.has(o)) onToggle(o);
  };
  return (
    <div className="ms-wrap" ref={ref}>
      <button type="button" className="ms-btn" title={title} aria-expanded={open}
        aria-haspopup="listbox" onClick={() => setOpen((o) => !o)}>
        {sel.size === 0 ? `${label}: todos` : `${label}: ${sel.size} selec.`} ▾
      </button>
      {open && (
        <div className="ms-panel">
          {options.map((s) => (
            <label key={s} className="ms-opt">
              <input type="checkbox" checked={sel.has(s)} onChange={() => onToggle(s)} />
              {colors && <i className="ms-dot" style={{ background: colors[s]?.bg }} />}
              <span>{labels?.[s] ?? s}</span>
            </label>
          ))}
          {(sel.size < options.length || sel.size > 0) && (
            <div className="ms-actions">
              {sel.size < options.length && (
                <button type="button" className="ms-selectall" onClick={selectAll}>selecionar todos</button>
              )}
              {sel.size > 0 && <button type="button" className="ms-clear" onClick={onClear}>limpar seleção</button>}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
