import { useEffect, useRef, useState } from "react";

// Filtro de faixa [min,max] reusável — mesmo padrão visual/interação do MultiSelect (dropdown
// chip, fecha ao clicar fora); value=null = sem filtro ("todos"). Usado nos indicadores de
// prontidão/checklist do Kanban: um valor de corte FIXO é ruim (não existe "o" percentual
// certo), uma FAIXA deixa o usuário decidir o que conta como "pronto o suficiente" pra ele.
export function RangeFilter({ label, min, max, value, onChange, title }: {
  label: string;
  min: number;
  max: number;
  value: [number, number] | null;
  onChange: (v: [number, number] | null) => void;
  title?: string;
}) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const h = (e: MouseEvent) => { if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false); };
    document.addEventListener("mousedown", h);
    return () => document.removeEventListener("mousedown", h);
  }, [open]);
  const [lo, hi] = value ?? [min, max];
  const clamp = (v: number, a: number, b: number) => Math.min(b, Math.max(a, v));

  return (
    <div className="ms-wrap" ref={ref}>
      <button type="button" className="ms-btn" title={title} onClick={() => setOpen((o) => !o)}>
        {value ? `${label}: ${lo}–${hi}%` : `${label}: todos`} ▾
      </button>
      {open && (
        <div className="ms-panel">
          <div className="ms-range-row">
            <label>De
              <input type="number" min={min} max={hi} value={lo}
                onChange={(e) => onChange([clamp(Number(e.target.value) || 0, min, hi), hi])} />%
            </label>
            <label>até
              <input type="number" min={lo} max={max} value={hi}
                onChange={(e) => onChange([lo, clamp(Number(e.target.value) || 0, lo, max)])} />%
            </label>
          </div>
          {value && <button type="button" className="ms-clear" onClick={() => onChange(null)}>limpar seleção</button>}
        </div>
      )}
    </div>
  );
}
