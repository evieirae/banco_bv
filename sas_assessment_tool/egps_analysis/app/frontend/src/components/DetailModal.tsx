import { useEffect, useRef, type KeyboardEvent, type ReactNode } from "react";

interface Props {
  onClose: () => void;
  children: ReactNode;
  /** Título no cabeçalho; omitido = só o ✕ (o conteúdo traz a própria identidade, ex.: .egp-head). */
  title?: string;
  /** Variante estreita (formulários, ex.: painel de status da Gestão). */
  narrow?: boolean;
}

// Modal centrado de detalhe — substituiu o expand inline (.rd-expand-detail) dos detalhes
// de EGP e Input: em notebook o inline virava uma janela de ~450px com scroll aninhado
// dentro do scroll da tabela (pedido 2026-08-28; formato escolhido pelo usuário: modal
// centrado, não drawer lateral). Overlay/ESC/✕ fecham; reusa o vocabulário visual dos
// drawers do app (.drawer-head/-title/-x) p/ manter o mesmo idioma de componente.
// A11y (critique 2026-08-28): foco entra no modal ao abrir, Tab fica preso dentro
// (focus-trap) e o foco volta ao elemento de origem ao fechar.
export function DetailModal({ onClose, children, title, narrow }: Props) {
  const ref = useRef<HTMLElement>(null);

  useEffect(() => {
    const onKey = (e: globalThis.KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose]);

  // foco: entra no modal ao montar, devolve ao elemento de origem ao desmontar
  useEffect(() => {
    const prev = document.activeElement as HTMLElement | null;
    ref.current?.focus();
    return () => { prev?.focus?.(); };
  }, []);

  // focus-trap: Tab/Shift+Tab circulam só entre os focáveis do modal
  const trapTab = (e: KeyboardEvent<HTMLElement>) => {
    if (e.key !== "Tab" || !ref.current) return;
    const focusables = ref.current.querySelectorAll<HTMLElement>(
      'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), ' +
      'textarea:not([disabled]), [tabindex]:not([tabindex="-1"])');
    if (!focusables.length) return;
    const first = focusables[0];
    const last = focusables[focusables.length - 1];
    if (e.shiftKey && (document.activeElement === first || document.activeElement === ref.current)) {
      e.preventDefault(); last.focus();
    } else if (!e.shiftKey && document.activeElement === last) {
      e.preventDefault(); first.focus();
    }
  };

  return (
    <>
      <div className="drawer-overlay" onClick={onClose} />
      <section className={`modal${narrow ? " modal-narrow" : ""}`} role="dialog"
        aria-modal="true" aria-label={title ?? "Detalhe"} ref={ref} tabIndex={-1}
        onKeyDown={trapTab}>
        {/* ✕ flutua fixo no canto (fora do fluxo): continua alcançável com o corpo rolado */}
        <button className="drawer-x modal-x" onClick={onClose} aria-label="Fechar (Esc)"
          title="Fechar (Esc)">✕</button>
        {title && (
          <header className="modal-head">
            <div className="drawer-title" title={title}>{title}</div>
          </header>
        )}
        <div className="modal-body">{children}</div>
      </section>
    </>
  );
}
