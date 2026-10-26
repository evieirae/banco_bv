import { useEffect, useRef, useState } from "react";

// Popover "?" acessível — tira do title= (hover-only: invisível em touch, teclado e
// leitor de tela) a única cópia dos conceitos centrais (achado P2 do critique
// 2026-08-28). Fecha com Esc ou clique fora; o botão expõe aria-expanded.
export function InfoTip({ text, label = "o que significa" }: { text: string; label?: string }) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLSpanElement>(null);
  useEffect(() => {
    if (!open) return;
    const down = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    const key = (e: KeyboardEvent) => { if (e.key === "Escape") setOpen(false); };
    document.addEventListener("mousedown", down);
    document.addEventListener("keydown", key);
    return () => {
      document.removeEventListener("mousedown", down);
      document.removeEventListener("keydown", key);
    };
  }, [open]);
  return (
    <span className="infotip" ref={ref}>
      <button type="button" className="infotip-btn" aria-expanded={open} aria-label={label}
        title={label} onClick={() => setOpen((o) => !o)}>?</button>
      {open && <span className="infotip-pop" role="note">{text}</span>}
    </span>
  );
}
