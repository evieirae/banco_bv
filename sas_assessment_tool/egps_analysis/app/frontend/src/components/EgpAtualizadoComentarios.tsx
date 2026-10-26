import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { gestaoApi, type StatusEntry } from "../gestaoApi";
import { fmtTsBR } from "../diasUteis";

// Comentários "dos dois lados" no mesmo card (pedido 2026-09): a aba EGPs Atualizados
// não tinha comentários próprios, só o funil etapa/status da troca — e o histórico do
// EGP ANTIGO (aba Gestão/EGPs, entity="egp") ficava numa tela totalmente separada da
// troca. Em vez de duplicar escrita entre os dois, este componente faz uma leitura
// COMBINADA (mesma tabela sas_gestao_status, sem tabela nova): comentários já existentes
// do(s) antecessor(es) (entity="egp", id=projeto — read-only aqui, não se comenta no
// antigo a partir daqui) + os da TROCA (entity="egp_atualizado", id=egp_key — onde o
// formulário abaixo escreve), unidos por timestamp e rotulados pela origem.
type Origem = { tipo: "novo" | "antecessor"; label: string };

export function EgpAtualizadoComentarios({ egpKey, antecessores, analistas }: {
  egpKey: string;
  antecessores: { projeto: string }[];
  analistas: { email: string; nome: string }[];
}) {
  const qc = useQueryClient();
  const antNomes = useMemo(
    () => [...new Set(antecessores.map((a) => a.projeto))].sort(),
    [antecessores]);
  const qKey = ["egp-atualizado-comentarios", egpKey, antNomes.join("|")];

  const q = useQuery({
    queryKey: qKey,
    queryFn: async () => {
      const [novo, ...ants] = await Promise.all([
        gestaoApi.listStatus("egp_atualizado", egpKey),
        ...antNomes.map((p) => gestaoApi.listStatus("egp", p)),
      ]);
      const rows: (StatusEntry & { origem: Origem })[] = [
        ...novo.map((e) => ({ ...e, origem: { tipo: "novo", label: "EGP novo" } as Origem })),
        ...ants.flatMap((entries, i) => entries.map((e) => ({
          ...e, origem: { tipo: "antecessor", label: `antecessor: ${nomeCurto(antNomes[i])}` } as Origem,
        }))),
      ];
      rows.sort((a, b) => (a.data < b.data ? 1 : -1));
      return rows;
    },
  });

  const [autor, setAutor] = useState("");
  const [texto, setTexto] = useState("");
  const add = useMutation({
    mutationFn: () => gestaoApi.addStatus("egp_atualizado", egpKey, autor, texto.trim()),
    onSuccess: () => {
      setTexto("");
      qc.invalidateQueries({ queryKey: qKey });
    },
  });
  const podeSalvar = texto.trim() !== "" && autor !== "" && !add.isPending;

  const entries = q.data ?? [];

  return (
    <div>
      {q.isFetching && !q.data && <div className="muted">carregando…</div>}
      {!q.isFetching && entries.length === 0 && (
        <div className="muted">— nenhum comentário ainda (nem no novo, nem no antecessor)</div>
      )}
      {entries.length > 0 && (
        <div className="gm-hist">
          {entries.map((e) => (
            <div className="gm-status" key={`${e.origem.tipo}:${e.id}`}>
              <div className="gm-status-meta">
                <span className={`mf-flag${e.origem.tipo === "novo" ? "" : " mf-warn"}`}
                      style={{ marginRight: 4 }}>
                  {e.origem.label}
                </span>
                {e.autor} · {fmtTsBR(e.data)}
              </div>
              <div className="gm-status-texto">{e.texto}</div>
            </div>
          ))}
        </div>
      )}

      <div className="gm-field gm-field-area" style={{ marginTop: 8 }}>
        <span>Novo comentário (fica do lado do EGP novo, na troca)</span>
        <textarea rows={3} value={texto} onChange={(e) => setTexto(e.target.value)}
          placeholder="Comentário sobre a troca…" />
      </div>
      <div className="gm-modal-actions" style={{ justifyContent: "flex-start", gap: 8 }}>
        <select value={autor} onChange={(e) => setAutor(e.target.value)}>
          <option value="">— autor —</option>
          {analistas.map((a) => <option key={a.email} value={a.email}>{a.nome || a.email}</option>)}
        </select>
        <button className="theme-btn" disabled={!podeSalvar} onClick={() => add.mutate()}>
          {add.isPending ? "Salvando…" : "+ Adicionar Comentário"}
        </button>
      </div>
      {add.isError && <div className="error">Falha ao salvar: {String(add.error)}</div>}
    </div>
  );
}

function nomeCurto(projeto: string) {
  return projeto.includes("__") ? projeto.split("__").slice(1).join("__") : projeto;
}
