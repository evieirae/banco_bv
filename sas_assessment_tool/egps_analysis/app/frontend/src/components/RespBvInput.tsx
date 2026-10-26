import { useEffect, useId, useState } from "react";
import { useSubareas } from "../useSubareas";
import { usePodeEscrever } from "../usePodeEscrever";

// Input de texto com commit no blur/Enter — responsável do lado BV (sas_egp_pipeline).
// Extraído de ReadinessView p/ ser compartilhado com o modal de detalhe (EgpDetailPanel).
// A datalist sugere as grafias já cadastradas (Gestão → Responsáveis BV) sem travar o campo:
// atribuir alguém novo não pode depender de cadastro prévio. Sugerir importa porque o nome
// é a chave que resolve a sub-área — "Leticia" e "Leticia Domingos Duarte" viram 2 pessoas.
export function RespBvInput({ value, onSave }: { value: string | null; onSave: (v: string | null) => void }) {
  const [draft, setDraft] = useState(value ?? "");
  const { nomes } = useSubareas();
  const listId = useId();
  const pode = usePodeEscrever();
  useEffect(() => { setDraft(value ?? ""); }, [value]);
  const commit = (v: string) => {
    const t = v.trim();
    if (t === (value ?? "")) return;
    onSave(t === "" ? null : t);
  };
  return (
    <>
      <input type="text" placeholder="—" value={draft} list={listId} disabled={!pode}
        title="Responsável do lado BV por este EGP (sugestões vêm do cadastro da Gestão)"
        onChange={(e) => setDraft(e.target.value)}
        onBlur={(e) => commit(e.target.value)}
        onKeyDown={(e) => { if (e.key === "Enter") (e.target as HTMLInputElement).blur(); }} />
      <datalist id={listId}>
        {nomes.map((n) => <option key={n} value={n} />)}
      </datalist>
    </>
  );
}
