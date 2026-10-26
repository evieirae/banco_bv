import { useCallback, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "../api";
import type { AppConfig, OutputRow } from "../types";
import { OutputsTable, type OutputSortKey } from "./OutputsTable";
import { OutputsDrawer } from "./OutputsDrawer";
import { MultiSelect } from "./MultiSelect";
import { useTableSort } from "../useTableSort";
import { csvBool, csvDate, csvDownload, egpShort } from "../csv";
import { useMesPlan, mesTag } from "../mesPlan";

const isTruthy = (v: boolean | string | null | undefined): boolean => v === true || v === "true";

const EMPTY: OutputRow[] = [];

const outputAccessor = (r: OutputRow, k: OutputSortKey): string | number | null | undefined => {
  switch (k) {
    case "artifact": return r.artifact;
    case "categoria": return r.categoria;
    case "areas": return r.areas;
    case "qtd_produtores": return r.qtd_produtores;
    case "qtd_consumidores": return r.qtd_consumidores;
    case "terminal": return isTruthy(r.terminal) ? 1 : 0;
    default: return undefined;
  }
};

export function OutputsView({ cfg: _cfg, onOpenEgp }: { cfg: AppConfig | null; onOpenEgp: (projeto: string) => void }) {
  const [scope, setScope] = useState("indi_deps");
  const [areasSel, setAreasSel] = useState<Set<string>>(new Set());
  const [categoriasSel, setCategoriasSel] = useState<Set<string>>(new Set());
  const [mesSel, setMesSel] = useState<Set<string>>(new Set());
  const [somenteTerminais, setSomenteTerminais] = useState(false);
  const [somenteMulti, setSomenteMulti] = useState(false);
  const [somenteConsumidos, setSomenteConsumidos] = useState(false);
  const [prodFilter, setProdFilter] = useState<"" | "sel" | "pend">("");
  const [q, setQ] = useState("");
  const [selected, setSelected] = useState<OutputRow | null>(null);

  const outputsQ = useQuery({
    queryKey: ["outputs", scope],
    queryFn: () => api.outputs(scope),
  });

  const all = outputsQ.data?.rows ?? EMPTY;

  // Filtro de mês: um output herda os meses (plano) dos EGPs PRODUTORES a que se relaciona
  // (n:n). Carregamos o par output×produtor UMA vez (base, mesma query do export) e cruzamos
  // com o plano (mesOf) — multi-produtor => output pode cair em vários meses.
  const { mesOf, meses } = useMesPlan();
  const outputsEgpsQ = useQuery({
    queryKey: ["outputs-egps", "base"],
    queryFn: () => api.outputsEgps("base"),
  });
  const mesByOutput = useMemo(() => {
    const m = new Map<string, Set<number>>();
    for (const p of outputsEgpsQ.data?.rows ?? []) {
      const mes = mesOf.get(p.projeto);
      if (mes == null) continue;
      const s = m.get(p.chave_canonica);
      if (s) s.add(mes); else m.set(p.chave_canonica, new Set([mes]));
    }
    return m;
  }, [outputsEgpsQ.data, mesOf]);
  // Palheiro de EGPs produtores por output — alimenta o fuzzy match (permite buscar
  // "produzido por <EGP>"). Concatena forma completa (area__nome) e short (nome),
  // já em lowercase, p/ o filtro só fazer `includes`.
  const egpsByOutput = useMemo(() => {
    const m = new Map<string, string>();
    for (const p of outputsEgpsQ.data?.rows ?? []) {
      const cur = m.get(p.chave_canonica);
      const add = `${p.projeto} ${egpShort(p.projeto)}`.toLowerCase();
      m.set(p.chave_canonica, cur ? `${cur} ${add}` : add);
    }
    return m;
  }, [outputsEgpsQ.data]);

  // distinct area options from `areas` field (may be comma/pipe-separated)
  const areaOptions = useMemo(() => {
    const set = new Set<string>();
    for (const r of all) {
      if (r.areas) {
        r.areas.split(/\s*[|,]\s*/).forEach((a) => { if (a) set.add(a); });
      }
    }
    return Array.from(set).sort();
  }, [all]);

  const categoriaOptions = useMemo(() => {
    const set = new Set<string>();
    for (const r of all) { if (r.categoria) set.add(r.categoria); }
    return Array.from(set).sort();
  }, [all]);

  const filtered = useMemo(() => {
    const terms = q.toLowerCase().split(/\s+/).filter(Boolean);
    return all.filter((r) => {
      if (areasSel.size) {
        const rowAreas = (r.areas || "").split(/\s*[|,]\s*/).filter(Boolean);
        if (!rowAreas.some((a) => areasSel.has(a))) return false;
      }
      if (categoriasSel.size && !categoriasSel.has(r.categoria)) return false;
      if (mesSel.size) {
        const ms = mesByOutput.get(r.chave_canonica);
        if (!ms || ![...mesSel].some((x) => ms.has(Number(x)))) return false;
      }
      if (somenteTerminais && !isTruthy(r.terminal)) return false;
      const nCria = r.qtd_criadores != null ? Number(r.qtd_criadores) : Number(r.qtd_produtores);
      if (somenteMulti && nCria <= 1) return false;
      if (somenteConsumidos && Number(r.qtd_consumidores) <= 0) return false;
      if (prodFilter === "sel" && !r.produtor_escolhido) return false;
      if (prodFilter === "pend" && (nCria <= 1 || !!r.produtor_escolhido)) return false;
      if (terms.length) {
        const hay = [r.artifact, r.categoria, r.areas].filter(Boolean).join(" ").toLowerCase()
          + " " + (egpsByOutput.get(r.chave_canonica) ?? "");
        if (!terms.every((t) => hay.includes(t))) return false;
      }
      return true;
    });
  }, [all, areasSel, categoriasSel, mesByOutput, egpsByOutput, mesSel, somenteTerminais, somenteMulti, somenteConsumidos, prodFilter, q]);

  const { sorted, onSort, indicator } = useTableSort<OutputRow, OutputSortKey>(
    filtered,
    outputAccessor,
    { key: "qtd_consumidores", dir: "desc" },
  );

  const toggleArea = useCallback((s: string) => {
    setAreasSel((prev) => { const n = new Set(prev); if (n.has(s)) n.delete(s); else n.add(s); return n; });
  }, []);

  const toggleCategoria = useCallback((s: string) => {
    setCategoriasSel((prev) => { const n = new Set(prev); if (n.has(s)) n.delete(s); else n.add(s); return n; });
  }, []);

  const exportCsv = useCallback(async () => {
    // build chave -> projeto[] map com TODOS os produtores (base). A granularidade do CSV é
    // artefato × produtor; o escopo filtra só a LISTA de outputs, não recorta os produtores de
    // cada output (senão a explosão fica incompleta — ex.: output indi com produtor fora do escopo).
    const egpMap = new Map<string, string[]>();
    try {
      const pairs = await api.outputsEgps("base");
      for (const p of pairs.rows) {
        const arr = egpMap.get(p.chave_canonica);
        if (arr) arr.push(p.projeto); else egpMap.set(p.chave_canonica, [p.projeto]);
      }
    } catch { /* fallback: export with empty EGP */ }

    const header = ["EGP", "Produtor correto?", "Artefato", "Categoria", "Área(s)", "Produtores", "Criadores", "Consumidores", "Terminal/Intermediário", "Caminho(s)"];
    const esc = (v: string | number | boolean | null | undefined): string => {
      const s = v === null || v === undefined ? "" : String(v);
      return /[";\n\r]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
    };
    const lines = [header.join(";")];
    for (const r of sorted) {
      const base = [
        esc(r.artifact),
        esc(r.categoria),
        esc(r.areas),
        esc(r.qtd_produtores),
        esc(r.qtd_criadores ?? ""),
        esc(r.qtd_consumidores),
        esc(csvBool(r.terminal)),
        esc(r.paths_fisicos),
      ];
      const egps = egpMap.get(r.chave_canonica);
      if (!egps || egps.length === 0) {
        lines.push([esc(""), esc(""), ...base].join(";"));
      } else {
        for (const eg of [...egps].sort()) {
          const correto = r.produtor_escolhido && eg === r.produtor_escolhido ? "sim" : "";
          lines.push([esc(egpShort(eg)), esc(correto), ...base].join(";"));
        }
      }
    }
    csvDownload(`outputs_${scope}_${csvDate()}.csv`, lines);
  }, [sorted, scope]);

  const loading = outputsQ.isFetching;

  return (
    <>
      <div className="filters">
        <select
          value={scope}
          onChange={(e) => setScope(e.target.value)}
          title="Recorte"
        >
          <option value="indi">Indicium</option>
          <option value="indi_deps">Indicium + dependências</option>
          <option value="base">Base</option>
        </select>

        <MultiSelect
          label="Área"
          options={areaOptions}
          sel={areasSel}
          onToggle={toggleArea}
          onClear={() => setAreasSel(new Set())}
        />

        <MultiSelect
          label="Categoria"
          options={categoriaOptions}
          sel={categoriasSel}
          onToggle={toggleCategoria}
          onClear={() => setCategoriasSel(new Set())}
        />

        {meses.length > 0 && (
          <MultiSelect
            label="Mês"
            title="Filtra outputs pelos meses do plano dos EGPs produtores (um output pode aparecer em vários meses)"
            options={meses.map(String)}
            labels={Object.fromEntries(meses.map((m) => [String(m), mesTag(m)]))}
            sel={mesSel}
            onToggle={(v) => setMesSel((prev) => { const n = new Set(prev); if (n.has(v)) n.delete(v); else n.add(v); return n; })}
            onClear={() => setMesSel(new Set())}
          />
        )}

        <label style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 12, cursor: "pointer" }}>
          <input
            type="checkbox"
            checked={somenteTerminais}
            onChange={(e) => setSomenteTerminais(e.target.checked)}
          />
          só terminais
        </label>

        <label style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 12, cursor: "pointer" }}
          title="Só outputs com mais de um EGP produtor (candidatos a escolher o produtor correto)">
          <input
            type="checkbox"
            checked={somenteMulti}
            onChange={(e) => setSomenteMulti(e.target.checked)}
          />
          só multi-produtor
        </label>

        <label style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 12, cursor: "pointer" }}
          title="Esconde outputs sem consumidor (terminais / fan-out 0) — só os que geram dependência">
          <input
            type="checkbox"
            checked={somenteConsumidos}
            onChange={(e) => setSomenteConsumidos(e.target.checked)}
          />
          só consumidos
        </label>

        <select
          value={prodFilter}
          onChange={(e) => setProdFilter(e.target.value as "" | "sel" | "pend")}
          title="Produtor correto (sub-projeto 2): definido = já escolhido; a definir = multi-produtor ainda ambíguo"
        >
          <option value="">produtor: todos</option>
          <option value="sel">✓ produtor definido</option>
          <option value="pend">● a definir</option>
        </select>

        <input
          type="search"
          placeholder="buscar artefato…"
          value={q}
          onChange={(e) => setQ(e.target.value)}
        />

        <span style={{ fontSize: 12, color: "var(--mut)" }}>
          {loading ? "carregando…" : `${sorted.length} / ${all.length}`}
        </span>

        <button
          className="ghost csv-btn"
          onClick={exportCsv}
          disabled={loading || sorted.length === 0}
        >
          ⬇ Exportar CSV
        </button>
      </div>

      {outputsQ.error && (
        <div className="error">{String(outputsQ.error)}</div>
      )}

      <OutputsTable
        rows={sorted}
        onSort={onSort}
        indicator={indicator}
        onSelect={(r) => setSelected((cur) => (cur?.chave_canonica === r.chave_canonica ? null : r))}
      />

      {selected && (
        <OutputsDrawer
          row={selected}
          onClose={() => setSelected(null)}
          onOpenEgp={(p) => { setSelected(null); onOpenEgp(p); }}
        />
      )}
    </>
  );
}
