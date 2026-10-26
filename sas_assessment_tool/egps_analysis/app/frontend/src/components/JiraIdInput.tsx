import { useEffect, useRef, useState } from "react";
import { usePodeEscrever } from "../usePodeEscrever";

// Regex do Jira ID — espelhe se mudar em backend/main.py:JIRA_ID_RE.
// ^[A-Z][A-Z0-9]+-\d+$ cobre PROJ-123, ABC1-42, X1Y2-9.
export const JIRA_ID_RE = /^[A-Z][A-Z0-9]+-\d+$/;

// Adicionar é fácil (input aberto quando value=null); trocar exige clicar no ✎ p/
// destravar (pedido do usuário: evitar reeditar sem querer). Save-on-blur; regex ao
// vivo via `pattern` + guard em onBlur (defesa em profundidade — backend valida também).
// Compartilhado entre EgpDetailPanel e ReadinessView (edição inline).
export function JiraIdInput({ value, onSave, className }:
  { value: string | null; onSave: (v: string | null) => void; className?: string }) {
  const [draft, setDraft] = useState(value ?? "");
  const [editing, setEditing] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);
  useEffect(() => { setDraft(value ?? ""); }, [value]);
  useEffect(() => { if (editing) inputRef.current?.focus(); }, [editing]);
  const pode = usePodeEscrever();

  // Sem escrita: só o valor, sem ✎ nem input.
  if (!pode) return <span className="jira-value">{value ?? "—"}</span>;

  // Trava: value definido & não editando → só leitura + botão ✎.
  if (value && !editing) {
    return (
      <span className="jira-locked">
        <span className="jira-value" title={`JIRA ID: ${value}`}>{value}</span>
        <button type="button" className="jira-edit-btn" title="Editar JIRA ID"
          onClick={(e) => { e.stopPropagation(); setEditing(true); }}>✎</button>
      </span>
    );
  }

  const invalid = draft !== "" && !JIRA_ID_RE.test(draft);
  return (
    <input ref={inputRef} type="text" className={className ?? "pipe-jira"} placeholder="JIRA ID"
      value={draft} pattern="[A-Z][A-Z0-9]+-\d+"
      aria-invalid={invalid} title={invalid ? "Formato esperado: PROJ-123" : "Jira ID vinculado a este EGP"}
      onChange={(e) => setDraft(e.target.value.toUpperCase())}
      onBlur={(e) => {
        setEditing(false);
        const v = e.target.value.trim();
        if (v === (value ?? "")) return;
        if (v !== "" && !JIRA_ID_RE.test(v)) return;
        onSave(v === "" ? null : v);
      }} />
  );
}
