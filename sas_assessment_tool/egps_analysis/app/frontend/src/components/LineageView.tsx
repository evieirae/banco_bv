import { useCallback, useEffect, useRef, useState } from "react";
import cytoscape from "cytoscape";
import fcose from "cytoscape-fcose";
import expandCollapse from "cytoscape-expand-collapse";
import { api } from "../api";
import { useMesPlan } from "../mesPlan";
import type { AreaStat, LineageEdge, LineageNode, LineagePayload } from "../types";

const AREA_COLOR: Record<string, string> = {
  Atacado: "#f59e0b", Cartões: "#84cc16", Cobrança: "#3b82f6", Crédito: "#ef4444",
  Finanças: "#06b6d4", Jurídico: "#10b981", Operações: "#64748b", Riscos: "#8b5cf6",
  SAS_UC4: "#92400e", Seguros: "#ec4899", Pricing: "#14b8a6", Rodas: "#f97316",
  "Negócios Transacionais Varejo e NaPista": "#0d9488",
  "Negócios e Produtos Relacional e Seguros": "#a21caf",
};
const areaColor = (a: string) => AREA_COLOR[a] || "#6b7280";
const shortName = (id: string) => (id.includes("__") ? id.split("__").slice(1).join("__") : id);
const trunc = (s: string, n = 26) => (s.length > n ? s.slice(0, n - 1) + "…" : s);
const indiOf = (n: LineageNode) => n.escopo_indi === true || n.escopo_indi === "true";
// rótulo do nó = nome curto + tag do mês (Mn) + ⟳ se em ciclo. Usado no build e no patch ao vivo.
const nodeLabel = (projeto: string, mes: number | undefined, ciclo: number) => {
  const tag = (mes != null ? `M${mes}` : "") + (ciclo > 0 ? " ⟳" : "");
  return `${trunc(shortName(projeto))}${tag ? "\n" + tag : ""}`;
};

// aplica o mês do plano nos nós já renderizados (label + data.mes) — chamado quando mesOf muda.
function applyMes(cy: cytoscape.Core | null, mesOf: Map<string, number>) {
  if (!cy) return;
  cy.nodes().forEach((node) => {
    if (node.data("kind") !== "egp") return;
    const mt = mesOf.get(String(node.id()));
    node.data("mes", mt != null ? `M${mt}` : "—");
    node.data("label", nodeLabel(String(node.id()), mt, Number(node.data("ciclo_id")) || 0));
  });
}

type Dir = "both" | "up" | "down";
type Mode = "egp" | "bulk";
const AREA_PREFIX = "area:::";

// fCoSE: empacota componentes e tila nós isolados -> ocupa o espaço dinamicamente.
const FCOSE: Record<string, unknown> = {
  name: "fcose", quality: "default", randomize: true, animate: true, animationDuration: 500,
  fit: true, padding: 45, nodeDimensionsIncludeLabels: true, uniformNodeDimensions: false,
  packComponents: true, tile: true, nodeSeparation: 95, idealEdgeLength: 115, nodeRepulsion: 8500,
  gravity: 0.28, gravityRange: 3.8, gravityCompound: 1.4, gravityRangeCompound: 1.5,
};

const EC_OPTS = {
  layoutBy: { ...FCOSE, animate: true, animationDuration: 400 },
  fisheye: false, animate: true, undoable: false, cueEnabled: true,
  expandCollapseCueSize: 14, expandCollapseCueLineSize: 9,
  groupEdgesOfSameTypeOnCollapse: true, allowNestedEdgeCollapse: false,
};

const STYLE: cytoscape.StylesheetStyle[] = ([
  { selector: "node[kind = 'egp']", style: {
      "background-color": "data(color)", shape: "round-rectangle", label: "data(label)",
      color: "#fff", "font-size": 11, "text-wrap": "wrap", "text-max-width": "150px",
      "text-valign": "center", "text-halign": "center", width: "label", height: "label",
      padding: "7px", "border-width": 1, "border-color": "#cbd5e1" } },
  { selector: "node[kind = 'egp'][?indi]", style: { "border-color": "#0f172a", "border-width": 2 } },
  { selector: "node[kind = 'egp'].ciclo", style: { "border-color": "#dc2626", "border-width": 3 } },
  { selector: "node[kind = 'egp'][?isroot]", style: { "border-color": "#fde047", "border-width": 4 } },
  { selector: ":parent", style: {
      "background-color": "data(color)", "background-opacity": 0.1, "border-color": "data(color)",
      "border-width": 2, shape: "round-rectangle", label: "data(label)", color: "data(color)",
      "font-size": 14, "font-weight": "bold", "text-valign": "top", "text-halign": "center",
      padding: "16px", "text-margin-y": -4 } },
  { selector: ".cy-expand-collapse-collapsed-node", style: {
      "background-opacity": 0.9, color: "#fff", "font-size": 14, "font-weight": "bold",
      shape: "round-rectangle", "text-valign": "center", "border-width": 2, padding: "14px" } },
  { selector: "edge", style: {
      width: 1.2, "line-color": "#9ca3af", "target-arrow-color": "#9ca3af",
      "target-arrow-shape": "triangle", "arrow-scale": 0.75, "curve-style": "bezier",
      opacity: 0.75 } },
  { selector: "edge.cy-expand-collapse-meta-edge", style: {
      width: 2.4, "line-color": "#6b7280", "line-style": "dashed",
      "target-arrow-color": "#6b7280", opacity: 0.9 } },
  { selector: "edge.cycle", style: {
      "line-color": "#dc2626", "target-arrow-color": "#dc2626", "line-style": "dashed",
      width: 2.6, opacity: 0.95, "z-index": 15 } },
  { selector: "node:selected", style: { "border-color": "#3b82f6", "border-width": 3 } },
  { selector: "edge.hl", style: {
      "line-color": "#3b82f6", "target-arrow-color": "#3b82f6", width: 2.6, opacity: 1, "z-index": 20 } },
] as unknown[]) as cytoscape.StylesheetStyle[];

let _registered = false;
function ensureExt() {
  if (_registered) return;
  cytoscape.use(fcose);
  cytoscape.use(expandCollapse);
  _registered = true;
}

// marca nós cíclicos (borda vermelha) e arestas internas a um ciclo (vermelho tracejado):
// aresta é de ciclo quando produtor e consumidor estão no MESMO cluster cíclico (ciclo_id>0).
function markCycles(cy: cytoscape.Core) {
  cy.nodes("[kind = 'egp']").forEach((n) => { n.toggleClass("ciclo", (Number(n.data("ciclo_id")) || 0) > 0); });
  cy.edges().forEach((e) => {
    const s = Number(e.source().data("ciclo_id")) || 0;
    const t = Number(e.target().data("ciclo_id")) || 0;
    e.toggleClass("cycle", s > 0 && s === t);
  });
}

const egpEl = (n: LineageNode, root: string | null, withParent: boolean, mesOf: Map<string, number>): cytoscape.ElementDefinition => {
  const area = n.area || "—";
  const mt = mesOf.get(n.projeto);
  const ciclo = Number(n.ciclo_id) || 0;
  const data: Record<string, unknown> = {
    id: n.projeto, kind: "egp", area, color: areaColor(area),
    label: nodeLabel(n.projeto, mt, ciclo),
    mes: mt != null ? `M${mt}` : "—", indi: indiOf(n), ninputs: n.n_inputs, noutputs: n.n_outputs,
    isroot: n.projeto === root, ciclo_id: ciclo,
  };
  if (withParent) data.parent = AREA_PREFIX + area;
  return { group: "nodes", data };
};
const areaElDef = (area: string, count: number): cytoscape.ElementDefinition => ({
  group: "nodes",
  data: { id: AREA_PREFIX + area, kind: "area", area, count, color: areaColor(area), label: `${area} · ${count}` },
});
const edgeElDef = (e: LineageEdge): cytoscape.ElementDefinition => ({
  group: "edges",
  data: { id: `${e.from}=>${e.to}`, source: e.from, target: e.to, via: e.via || "" },
});

export function LineageView() {
  const elRef = useRef<HTMLDivElement>(null);
  const cyRef = useRef<cytoscape.Core | null>(null);
  const ecRef = useRef<any>(null);
  const rootRef = useRef<string | null>(null);
  const dirRef = useRef<Dir>("both");
  const depsRef = useRef(true);
  const modeRef = useRef<Mode>("bulk");
  const expandedRef = useRef<Set<string>>(new Set());

  const [mode, setMode] = useState<Mode>("bulk");
  const [dir, setDir] = useState<Dir>("both");
  const [deps, setDeps] = useState(true);
  const [scopeIndi, setScopeIndi] = useState(false);
  const [areas, setAreas] = useState<AreaStat[]>([]);
  const [area, setArea] = useState("");
  const [egps, setEgps] = useState<LineageNode[]>([]);
  const [egp, setEgp] = useState("");
  const [info, setInfo] = useState("carregando…");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [tip, setTip] = useState<{ x: number; y: number; lines: string[] } | null>(null);

  const { mesOf } = useMesPlan();
  const mesOfRef = useRef(mesOf);
  useEffect(() => { mesOfRef.current = mesOf; applyMes(cyRef.current, mesOf); }, [mesOf]);

  const renderPayload = useCallback((p: LineagePayload, root: string | null, grouped: boolean) => {
    const cy = cyRef.current, ec = ecRef.current;
    if (!cy) return;
    rootRef.current = root;
    const ids = new Set(p.nodes.map((n) => n.projeto));
    const edges = p.edges.filter((e) => ids.has(e.from) && ids.has(e.to));
    cy.elements().remove();
    if (grouped) {
      const byArea = new Map<string, number>();
      for (const n of p.nodes) { const a = n.area || "—"; byArea.set(a, (byArea.get(a) || 0) + 1); }
      const els: cytoscape.ElementDefinition[] = [];
      for (const [a, c] of byArea) els.push(areaElDef(a, c));
      for (const n of p.nodes) els.push(egpEl(n, root, true, mesOfRef.current));
      for (const e of edges) els.push(edgeElDef(e));
      cy.add(els);
      ec?.collapseAll();
      const nAreas = byArea.size;
      setInfo(`${p.nodes.length} EGPs em ${nAreas} área${nAreas > 1 ? "s" : ""} · ${edges.length} vínculos${p.capped ? " · ⚠ truncado" : ""}`);
    } else {
      cy.add([...p.nodes.map((n) => egpEl(n, root, false, mesOfRef.current)), ...edges.map(edgeElDef)]);
      cy.layout(FCOSE as unknown as cytoscape.LayoutOptions).run();
      setInfo(`${p.nodes.length} EGPs · ${edges.length} vínculos${p.capped ? " · ⚠ truncado" : ""}`);
    }
    markCycles(cy);
    setTimeout(() => cy.fit(undefined, 45), 650);
  }, []);

  const run = useCallback(async (fn: () => Promise<void>) => {
    setBusy(true); setErr(null);
    try { await fn(); } catch (e) { setErr(String(e)); } finally { setBusy(false); }
  }, []);

  const loadBulk = useCallback((a: string, si: boolean) => run(async () => {
    const params: { area?: string; scope?: string; mode?: string; deps?: boolean } = { deps: depsRef.current };
    if (a) params.area = a;
    if (si) params.scope = "indi";
    if (!a && !si) params.mode = "all";
    expandedRef.current = new Set();
    renderPayload(await api.lineageGraph(params), null, true);
  }), [run, renderPayload]);

  const loadRoot = useCallback((proj: string) => run(async () => {
    setEgp(proj);
    const p = await api.lineageNeighbors(proj, dirRef.current);
    if (!p.nodes.some((n) => n.projeto === proj)) {
      const s = await api.lineageSearch(proj, "", "", 1);
      if (s.rows[0]) p.nodes.push(s.rows[0]);
    }
    expandedRef.current = new Set([proj + dirRef.current]);
    renderPayload(p, proj, false);
  }), [run, renderPayload]);

  const expandNode = useCallback(async (proj: string) => {
    const cy = cyRef.current; if (!cy) return;
    const k = proj + dirRef.current;
    if (expandedRef.current.has(k)) return;
    expandedRef.current.add(k);
    try {
      const p = await api.lineageNeighbors(proj, dirRef.current);
      const have = new Set(cy.nodes().map((n) => n.id()));
      const newNodes = p.nodes.filter((n) => !have.has(n.projeto)).map((n) => egpEl(n, rootRef.current, false, mesOfRef.current));
      const present = new Set([...have, ...p.nodes.map((n) => n.projeto)]);
      const newEdges = p.edges
        .filter((e) => present.has(e.from) && present.has(e.to))
        .map(edgeElDef)
        .filter((el) => cy.getElementById(String(el.data.id)).empty());
      cy.add([...newNodes, ...newEdges]);
      markCycles(cy);
      cy.layout(FCOSE as unknown as cytoscape.LayoutOptions).run();
      const nEgp = cy.nodes().filter((n) => n.data("kind") === "egp").length;
      setInfo(`${nEgp} EGPs · ${cy.edges().length} vínculos`);
    } catch (e) { setErr(String(e)); }
  }, []);

  // monta a instância Cytoscape uma vez e abre na visão colapsada por área.
  useEffect(() => {
    ensureExt();
    if (!elRef.current) return;
    const cy = cytoscape({
      container: elRef.current, elements: [], style: STYLE,
      minZoom: 0.04, maxZoom: 3, boxSelectionEnabled: false, pixelRatio: 1,
    });
    cyRef.current = cy;
    ecRef.current = (cy as any).expandCollapse(EC_OPTS);

    cy.on("dbltap", "node", (evt) => {
      const n = evt.target;
      if (modeRef.current === "egp" && n.data("kind") === "egp") expandNode(n.id());
    });
    cy.on("tap", "node", (evt) => {
      const n = evt.target, ec = ecRef.current;
      if (!ec) return;
      if (ec.isExpandable(n)) ec.expand(n);
      else if (ec.isCollapsible(n)) ec.collapse(n);
    });
    cy.on("mouseover", "node[kind = 'egp']", (evt) => evt.target.connectedEdges().addClass("hl"));
    cy.on("mouseout", "node[kind = 'egp']", () => cy.edges().removeClass("hl"));
    const showTip = (evt: any) => {
      const t = evt.target, rp = evt.renderedPosition || { x: 0, y: 0 };
      let lines: string[];
      if (t.isEdge()) {
        const via = t.data("via");
        lines = ["via: " + (via ? via : "(sem tabela mapeada)")];
      } else if (t.data("kind") === "area") {
        lines = [String(t.data("area")), `${t.data("count")} EGPs · clique para abrir/fechar`];
      } else {
        lines = [t.id(), `Área: ${t.data("area")}`, `Mês: ${t.data("mes")}`,
          `escopo Indicium: ${t.data("indi") ? "sim" : "não"}`,
          `inputs: ${t.data("ninputs")} · outputs: ${t.data("noutputs")}`];
      }
      setTip({ x: rp.x + 14, y: rp.y + 14, lines });
    };
    cy.on("mouseover", "node, edge", showTip);
    cy.on("mouseout", "node, edge", () => setTip(null));
    cy.on("pan zoom drag", () => setTip(null));

    api.lineageAreas().then((r) => setAreas(r.rows)).catch(() => {});
    loadBulk("", false);
    return () => { cy.destroy(); cyRef.current = null; ecRef.current = null; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // dropdown de EGPs filtrado por área (modo Por EGP)
  useEffect(() => {
    if (mode !== "egp") return;
    api.lineageSearch("", scopeIndi ? "indi" : "", area, 5000).then((r) => setEgps(r.rows)).catch(() => setEgps([]));
  }, [area, scopeIndi, mode]);

  const onMode = (m: Mode) => {
    setMode(m); modeRef.current = m;
    if (m === "bulk") loadBulk(area, scopeIndi);
    else { cyRef.current?.elements().remove(); rootRef.current = null; setEgp(""); setInfo("escolha um EGP para focar"); }
  };
  const onArea = (a: string) => { setArea(a); if (modeRef.current === "bulk") loadBulk(a, scopeIndi); };
  const onScope = (si: boolean) => { setScopeIndi(si); if (modeRef.current === "bulk") loadBulk(area, si); };
  const toggleDeps = (v: boolean) => { setDeps(v); depsRef.current = v; if (modeRef.current === "bulk") loadBulk(area, scopeIndi); };
  const changeDir = (d: Dir) => { setDir(d); dirRef.current = d; if (modeRef.current === "egp" && rootRef.current) loadRoot(rootRef.current); };

  return (
    <div className="lineage">
      <div className="lin-bar">
        <select value={mode} onChange={(e) => onMode(e.target.value as Mode)} title="modo">
          <option value="bulk">Conjunto (colapsado por área)</option>
          <option value="egp">Por EGP (foco)</option>
        </select>

        <select value={area} onChange={(e) => onArea(e.target.value)} title="área">
          <option value="">todas as áreas</option>
          {areas.map((a) => (
            <option key={a.area} value={a.area}>{a.area} ({scopeIndi ? `${a.n_indi} indi` : a.n})</option>
          ))}
        </select>

        <select value={scopeIndi ? "indi" : "all"} onChange={(e) => onScope(e.target.value === "indi")} title="escopo">
          <option value="all">escopo: todos</option>
          <option value="indi">escopo: só Indicium</option>
        </select>

        {mode === "egp" && (
          <select className="egp-dd" value={egp} onChange={(e) => e.target.value && loadRoot(e.target.value)} title="EGP">
            <option value="">{egps.length ? `escolha um EGP (${egps.length})…` : "carregando…"}</option>
            {egps.map((n) => (
              <option key={n.projeto} value={n.projeto}>{shortName(n.projeto)}{indiOf(n) ? " ◆" : ""}</option>
            ))}
          </select>
        )}

        {mode === "egp" && (
          <div className="seg">
            <button className={dir === "up" ? "on" : ""} onClick={() => changeDir("up")}>⬅ depende de</button>
            <button className={dir === "both" ? "on" : ""} onClick={() => changeDir("both")}>ambos</button>
            <button className={dir === "down" ? "on" : ""} onClick={() => changeDir("down")}>alimenta ➡</button>
          </div>
        )}

        {mode === "bulk" && (
          <>
            <label className="chk">
              <input type="checkbox" checked={deps} onChange={(e) => toggleDeps(e.target.checked)} />
              incluir deps externas
            </label>
            <button className="ghost" onClick={() => ecRef.current?.expandAll()}>Abrir áreas</button>
            <button className="ghost" onClick={() => ecRef.current?.collapseAll()}>Fechar áreas</button>
          </>
        )}

        <button className="ghost" onClick={() => cyRef.current?.fit(undefined, 45)}>Enquadrar</button>
        <span className="info">{busy ? "carregando…" : info}</span>
      </div>
      <div className="lin-hint">
        {mode === "bulk"
          ? "Clique numa área para abrir/fechar seus EGPs · cor = área · ◆ borda escura = Indicium · 🔴 borda/aresta vermelha = dependência cíclica · seta = produtor → consumidor"
          : "Duplo-clique num nó expande 1 nível · borda amarela = nó focado · 🔴 borda/aresta vermelha = ciclo · seta = produtor → consumidor · hover na aresta mostra as tabelas"}
      </div>
      {err && <div className="error">{err}</div>}
      <div className="lin-stage">
        <div ref={elRef} className="lin-canvas" />
        {tip && (
          <div className="lin-tip" style={{ left: tip.x, top: tip.y }}>
            {tip.lines.map((l, i) => <div key={i} className={i === 0 ? "t0" : ""}>{l}</div>)}
          </div>
        )}
      </div>
    </div>
  );
}
