import { useEffect, useMemo, useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "../api";
import type { IndiciumRow, IndiciumPayload } from "../types";
import { useTableSort } from "../useTableSort";
import { csvDownload, csvFromColumns, csvBool, csvDate, type CsvColumn } from "../csv";
import { mesTag, useMesPlan } from "../mesPlan";
import { pathFor, spaLinkClick } from "../routes";
import { usePodeEscrever } from "../usePodeEscrever";

// exibe o nome curto (sem o prefixo `area__`), igual à aba EGPs (shortName). O egp_dor1/projeto
// guardado continua com o prefixo canônico — é ele que liga a entrada ao nó real (Recebido/cross-nav).
const shortName = (id: string) => (id.includes("__") ? id.split("__").slice(1).join("__") : id);
const isRecebido = (r: IndiciumRow) => r.recebido === true || r.recebido === "true";
const isAtivo = (r: IndiciumRow) => !(r.ativo === false || r.ativo === "false");
// recebido → mostra o nome do EGP (do projeto/nó), não o rótulo do DOR1 (que às vezes é o nome da tabela);
// o rótulo original do DOR1 vai pro hover. Não-recebidos seguem com o egp_dor1.
const dispName = (r: IndiciumRow) => (isRecebido(r) && r.projeto ? shortName(r.projeto) : shortName(r.egp_dor1));

// extrai a mensagem limpa de um erro HTTP (FastAPI: {"detail":"…"}); senão devolve o texto cru
const prettyErr = (e: unknown) => {
  const m = String(e).match(/"detail":\s*"([^"]+)"/);
  return m ? m[1] : String(e);
};
const norm = (s: string) => s.trim().toLowerCase();

type SortKey = "egp_dor1" | "area" | "status_extracao" | "recebido";
const accessor = (r: IndiciumRow, k: SortKey): string | number => {
  if (k === "recebido") return isRecebido(r) ? 1 : 0;
  return r[k] ?? "";
};

export function IndiciumView({ onOpenEgp }: { onOpenEgp: (projeto: string) => void }) {
  const qc = useQueryClient();
  const pode = usePodeEscrever();
  const { mesOf } = useMesPlan();
  const q1 = useQuery({ queryKey: ["indicium"], queryFn: api.indicium });
  const nodesQ = useQuery({ queryKey: ["nodes-all"], queryFn: () => api.lineageSearch("", "", "", 5000) });
  const rows = useMemo(() => q1.data?.rows ?? [], [q1.data]);
  const sugg = useMemo(() => (nodesQ.data?.rows ?? []).map((n) => n.projeto), [nodesQ.data]);
  // área canônica por projeto (do mapeamento/linhagem) — pra puxar a área ao adicionar um EGP já mapeado
  const nodeArea = useMemo(() => {
    const m = new Map<string, string>();
    (nodesQ.data?.rows ?? []).forEach((n) => { if (n.projeto) m.set(n.projeto, n.area); });
    return m;
  }, [nodesQ.data]);

  const [area, setArea] = useState("");
  const [q, setQ] = useState("");
  const [soNao, setSoNao] = useState(false);
  const [newEgp, setNewEgp] = useState("");
  const [newArea, setNewArea] = useState("");
  const [dupErr, setDupErr] = useState<string | null>(null);
  // EGP já no mapeamento → puxa a área direto (o usuário ainda pode sobrescrever editando o campo).
  useEffect(() => {
    const a = nodeArea.get(newEgp.trim());
    if (a) setNewArea(a);
  }, [newEgp, nodeArea]);

  // Uma edição de escopo dispara recompute_escopo() no backend → reflete em todas as
  // superfícies derivadas; por isso invalidamos o conjunto inteiro, não só ["indicium"].
  const invalidateAll = () =>
    ["indicium", "metrics", "resumo", "landing", "egp-readiness", "egp", "inputs", "nodes-all", "priorizacao"]
      .forEach((k) => qc.invalidateQueries({ queryKey: [k] }));
  // As variáveis vão por PARÂMETRO, nunca lidas do state dentro do mutationFn: o onMutate
  // abaixo limpa os campos (otimista) e o React Query v5 repassa as options do render novo
  // p/ a mutation em voo (mutationObserver: `#currentMutation.setOptions`) ANTES de chamar
  // o mutationFn — o fn do closure novo via newEgp="" e o POST ia sem nome, devolvendo
  // "nome do EGP obrigatório" com o campo preenchido na tela. Corrida (2026-08-18).
  const addMut = useMutation({
    mutationFn: (v: { egp: string; area: string }) =>
      api.escopoAdd({ egp_dor1: v.egp, projeto: v.egp, area: v.area }),
    // Otimista: o backend roda recompute_escopo() (~10 statements Delta) e demora alguns segundos —
    // sem isso a tela "congela" até o POST voltar. Inserimos a linha na hora (com a classificação/recebido
    // derivados do mapeamento, igual ao backend) e limpamos os campos; onSettled reconcilia com o dado real.
    onMutate: async ({ egp, area }: { egp: string; area: string }) => {
      await qc.cancelQueries({ queryKey: ["indicium"] });
      const prev = qc.getQueryData<IndiciumPayload>(["indicium"]);
      const node = (nodesQ.data?.rows ?? []).find((n) => n.projeto === egp);
      const optimistic: IndiciumRow = {
        id: `optim-${egp}`, egp_dor1: egp, area, status_extracao: node ? "exato" : "faltante",
        projeto: egp, origem: "manual", node_projeto: node ? egp : null,
        onda: node?.onda ?? null, ciclo_id: node?.ciclo_id ?? null, recebido: !!node,
      };
      qc.setQueryData<IndiciumPayload>(["indicium"], (old) => (old ? { ...old, rows: [optimistic, ...old.rows] } : old));
      setNewEgp(""); setNewArea(""); setDupErr(null);
      return { prev, egp, area };
    },
    onError: (_e, v, ctx) => {
      if (ctx?.prev) qc.setQueryData(["indicium"], ctx.prev);   // desfaz a linha otimista
      setNewEgp(v.egp); setNewArea(v.area);                     // devolve o que foi digitado
    },
    onSettled: () => invalidateAll(),
  });
  // Otimista: o backend roda recompute_escopo() (~segundos); sem isso a linha só muda após o
  // round-trip (o usuário tinha que dar refresh). Viramos `ativo` no cache na hora; onSettled reconcilia.
  const setAtivoLocal = (id: string, ativo: boolean) =>
    qc.setQueryData<IndiciumPayload>(["indicium"], (old) =>
      old ? { ...old, rows: old.rows.map((r) => (r.id === id ? { ...r, ativo } : r)) } : old);
  const delMut = useMutation({
    mutationFn: (id: string) => api.escopoDel(id),   // soft (desativar) por padrão no backend
    onMutate: async (id) => {
      await qc.cancelQueries({ queryKey: ["indicium"] });
      const prev = qc.getQueryData<IndiciumPayload>(["indicium"]);
      setAtivoLocal(id, false);
      return { prev };
    },
    onError: (_e, _v, ctx) => { if (ctx?.prev) qc.setQueryData(["indicium"], ctx.prev); },
    onSettled: invalidateAll,
  });
  const reactMut = useMutation({
    mutationFn: (id: string) => api.escopoReactivate(id),
    onMutate: async (id) => {
      await qc.cancelQueries({ queryKey: ["indicium"] });
      const prev = qc.getQueryData<IndiciumPayload>(["indicium"]);
      setAtivoLocal(id, true);
      return { prev };
    },
    onError: (_e, _v, ctx) => { if (ctx?.prev) qc.setQueryData(["indicium"], ctx.prev); },
    onSettled: invalidateAll,
  });

  const areasList = useMemo(() => [...new Set(rows.map((r) => r.area))].filter(Boolean).sort(), [rows]);
  const counts = useMemo(() => {
    const ativos = rows.filter(isAtivo);
    const recebidos = ativos.filter(isRecebido).length;
    return { total: ativos.length, recebidos, nao: ativos.length - recebidos, desativados: rows.length - ativos.length };
  }, [rows]);

  const filtered = useMemo(() => {
    let v = rows;
    if (area) v = v.filter((r) => r.area === area);
    if (soNao) v = v.filter((r) => !isRecebido(r));
    if (q) {
      const ql = q.toLowerCase();
      v = v.filter((r) => r.egp_dor1.toLowerCase().includes(ql) || r.projeto.toLowerCase().includes(ql));
    }
    return v;
  }, [rows, area, soNao, q]);

  const { sorted, onSort, indicator } = useTableSort<IndiciumRow, SortKey>(filtered, accessor, { key: "recebido", dir: "asc" });
  // desativados sempre no fim (sort estável preserva a ordenação da coluna dentro de cada grupo)
  const display = useMemo(() => [...sorted].sort((a, b) => (isAtivo(a) === isAtivo(b) ? 0 : isAtivo(a) ? -1 : 1)), [sorted]);

  const busy = q1.isFetching;
  const err = dupErr ?? (q1.error ? String(q1.error) : addMut.error ? prettyErr(addMut.error) : delMut.error ? prettyErr(delMut.error) : null);

  const doAdd = () => {
    const egp = newEgp.trim();
    if (!egp || addMut.isPending) return;
    // bloqueia adicionar o mesmo EGP de novo (por rótulo DOR1 ou projeto) — feedback instantâneo,
    // sem esperar o round-trip; o backend tem o mesmo guard (autoritativo, cobre corrida).
    if (rows.some((r) => isAtivo(r) && (norm(r.egp_dor1) === norm(egp) || (!!r.projeto && norm(r.projeto) === norm(egp))))) {
      setDupErr(`O EGP "${shortName(egp)}" já está no escopo.`);
      return;
    }
    addMut.mutate({ egp, area: newArea.trim() || nodeArea.get(egp) || "" });
  };

  // Exporta as linhas EXIBIDAS (filtros + ordenação; desativados no fim). EGP = nome sem `area__`
  // (dispName); DOR1/Projeto(nó) crus vão em colunas próprias p/ rastreio.
  const exportCsv = () => {
    const cols: CsvColumn<IndiciumRow>[] = [
      { header: "EGP", get: (r) => dispName(r) },
      { header: "Área", get: (r) => r.area },
      { header: "Classificação", get: (r) => r.status_extracao },
      { header: "Recebido", get: (r) => csvBool(isRecebido(r)) },
      { header: "Ativo", get: (r) => csvBool(isAtivo(r)) },
      { header: "Projeto (nó)", get: (r) => r.projeto ?? "" },
      { header: "DOR1", get: (r) => r.egp_dor1 },
      { header: "Origem", get: (r) => r.origem },
      { header: "Mês", get: (r) => mesTag(mesOf.get(r.projeto)) },
      { header: "Ciclo", get: (r) => r.ciclo_id ?? "" },
    ];
    csvDownload(`escopo_indicium_${csvDate()}.csv`, csvFromColumns(display, cols));
  };

  return (
    <div className="readiness">
      <div className="filters">
        {pode && (
          <>
            <input list="esc-egps" placeholder="adicionar EGP (nome)…" value={newEgp}
              onChange={(e) => { setNewEgp(e.target.value); if (dupErr) setDupErr(null); }} onKeyDown={(e) => e.key === "Enter" && doAdd()} style={{ minWidth: 260 }} />
            <datalist id="esc-egps">{sugg.map((p) => <option key={p} value={p} />)}</datalist>
            <input placeholder="área (auto se mapeado)" value={newArea} onChange={(e) => setNewArea(e.target.value)} style={{ minWidth: 130 }} />
            <button className="btn-add" onClick={doAdd} disabled={!newEgp.trim() || addMut.isPending}>+ Adicionar</button>
            <span className="sep" />
          </>
        )}
        <select value={area} onChange={(e) => setArea(e.target.value)}>
          <option value="">todas as áreas</option>
          {areasList.map((a) => <option key={a} value={a}>{a}</option>)}
        </select>
        <input type="search" placeholder="filtrar EGP…" value={q} onChange={(e) => setQ(e.target.value)} />
        <label className="chk"><input type="checkbox" checked={soNao} onChange={(e) => setSoNao(e.target.checked)} /> só não recebidos</label>
        <span className="count">{busy ? "carregando…" : `${sorted.length} de ${rows.length}`}</span>
        <button className="ghost csv-btn" onClick={exportCsv} disabled={busy || !display.length}
          title="Baixar CSV com as linhas exibidas (filtros + ordenação; desativados no fim)">⬇ Exportar CSV</button>
      </div>

      <div className="rd-chips">
        <button className="chip ok" style={{ cursor: "default" }}>🟢 Recebidos: {counts.recebidos}</button>
        <button className={`chip todo ${soNao ? "on" : ""}`} onClick={() => setSoNao(!soNao)}>🔴 Não recebidos: {counts.nao}</button>
        <button className="chip" style={{ cursor: "default" }}>Total escopo: {counts.total}</button>
        {counts.desativados > 0 && <button className="chip" style={{ cursor: "default" }}>⏸ Desativados: {counts.desativados}</button>}
      </div>
      <div className="lin-hint">
        Lista de escopo <b>(DOR1)</b> editável — fonte do que é/não é Indicium. <b>Recebido</b> = o EGP foi extraído (existe nas tabelas). Adicione um EGP (com autocomplete dos extraídos, ou nome livre para registrar "esperado mas não recebido"). Clique num recebido para abrir na aba EGPs.
        <br /><i>Cada edição re-deriva o escopo no app todo (Resumo/Monitoramento/EGPs/landing) na hora.</i>
      </div>
      {err && <div className="error">{err}</div>}

      <div className="rd-table">
        <div className="ind-thead">
          <div className="rd-th" onClick={() => onSort("egp_dor1")}>EGP{indicator("egp_dor1")}</div>
          <div className="rd-th" onClick={() => onSort("area")}>Área{indicator("area")}</div>
          <div className="rd-th" onClick={() => onSort("status_extracao")}>Classificação{indicator("status_extracao")}</div>
          <div className="rd-th" onClick={() => onSort("recebido")}>Recebido{indicator("recebido")}</div>
          <div>Mês</div>
          <div></div>
        </div>
        <div className="rd-tbody">
          {display.map((r) => {
            const rec = isRecebido(r);
            const ativo = isAtivo(r);
            return (
              <div key={r.id}
                className={`ind-trow ${rec && ativo ? "clickable" : ""} ${ativo ? "" : "inativo"}`}
                title={!ativo ? "desativado do escopo" : rec ? `${r.projeto} — abrir na aba EGPs` : "não recebido"}
                onClick={() => rec && ativo && onOpenEgp(r.projeto)}>
                <div title={isRecebido(r) && r.projeto ? `DOR1: ${r.egp_dor1}` : r.egp_dor1}>
                  {/* link real p/ o deep-link do EGP: botão do meio/ctrl+clique/"abrir em nova
                      guia" funcionam nativamente. Vale também para linha DESATIVADA — a linha
                      segue não-clicável, mas o EGP existe e continua consultável (o deep-link
                      cai no escopo "base" da aba EGPs). Sem `rec` não há projeto para abrir. */}
                  {rec
                    ? <a className="rd-egp-link" href={pathFor("readiness", r.projeto)}
                        title={`${r.projeto} — clique: abre na aba EGPs · botão do meio/ctrl+clique: nova guia${ativo ? "" : " (desativado do escopo)"}`}
                        onClick={(ev) => spaLinkClick(ev, () => onOpenEgp(r.projeto), { stop: true })}>
                        {dispName(r)}
                      </a>
                    : dispName(r)}
                  {!ativo && <span className="pill todo" style={{ marginLeft: 6 }}>desativado</span>}
                </div>
                <div>{r.area}</div>
                <div>{r.status_extracao}</div>
                <div><span className={`pill ${rec ? "ok" : "todo"}`}>{rec ? "Recebido" : "Não recebido"}</span></div>
                <div className={Number(r.ciclo_id) > 0 ? "cyc-txt" : ""}>{rec ? mesTag(mesOf.get(r.projeto)) + (Number(r.ciclo_id) > 0 ? " ⟳" : "") : "—"}</div>
                <div>
                  {pode && (ativo
                    ? <button className="row-x" title="desativar do escopo (fica guardado p/ reativar)"
                        onClick={(e) => { e.stopPropagation(); if (confirm(`Desativar "${shortName(r.egp_dor1)}" do escopo? Fica guardado — dá pra reativar depois.`)) delMut.mutate(r.id); }}>✕</button>
                    : <button className="row-x" title="reativar no escopo"
                        onClick={(e) => { e.stopPropagation(); reactMut.mutate(r.id); }}>↺</button>)}
                </div>
              </div>
            );
          })}
          {!busy && sorted.length === 0 && <div className="empty">Nenhum EGP para os filtros.</div>}
        </div>
      </div>
    </div>
  );
}
