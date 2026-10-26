#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Gera a linhagem visual interativa (HTML, vis-network) dos EGPs priorizados pela
Indicium, a partir da aba 'Extração Bruta oficial' da planilha de Controle.

Escopo = linhas com `EGP Indicium? == 'Sim'` (222 projetos).
Grafo bipartido: Tabela/arquivo de ENTRADA  ->  EGP.
  - EGP: caixa, cor por ÁREA.
  - Input: ponto, cor por Modernizada? (Não=vermelho / Sim=verde / Sanitizado=amarelo),
           tamanho por nº de EGPs que consomem (fan-out).

Saídas (em docs/analises/):
  - lineage_indicium.html           grafo interativo, self-contained (CDN vis-network)
  - indicium_inputs_distintos.csv   inputs distintos não modernizados + nº de EGPs + origem
  - indicium_scope_222_projetos.csv lista de projetos do escopo (área)

Uso (do root do projeto, com venv ativo):
  python egps_analysis/docs/analises/build_lineage.py "[SAS] 1. Pré-Working - Controle e Validação (2).xlsx"
"""
import sys, os, json, csv, collections
import openpyxl

XLSX = sys.argv[1] if len(sys.argv) > 1 else "[SAS] 1. Pré-Working - Controle e Validação (2).xlsx"
OUTDIR = os.path.join("egps_analysis", "docs", "analises")
TAB = "Extração Bruta oficial"
INPUT_CATS = {"table_in", "file_in", "libname_in", "script_in"}

# ---------- paleta por área ----------
AREA_COLORS = {
    "Cobrança": "#4e79a7", "Riscos": "#e15759", "Jurídico": "#76b7b2",
    "Atacado": "#59a14f", "Finanças": "#edc948", "Operações": "#b07aa1",
    "Banco Relacional": "#ff9da7", "Seguros": "#9c755f",
}
DEFAULT_AREA = "#bab0ac"
MOD_COLORS = {"Não": "#e15759", "Sim": "#59a14f", "Sanitizado": "#edc948", "Ruído": "#777777"}


def n(v):
    return str(v).strip() if v is not None else ""


def load_scope():
    wb = openpyxl.load_workbook(XLSX, read_only=True, data_only=True)
    ws = wb[TAB]
    it = ws.iter_rows(values_only=True)
    hdr = next(it)
    idx = {str(h).strip(): i for i, h in enumerate(hdr) if h not in (None, "")}

    def g(r, name):
        i = idx.get(name)
        return r[i] if (i is not None and i < len(r)) else None

    rows = []
    for r in it:
        if all(v in (None, "") for v in r):
            continue
        if n(g(r, "EGP Indicium?")) != "Sim":
            continue
        cat = n(g(r, "category"))
        if cat not in INPUT_CATS:
            continue
        rows.append({
            "project": n(g(r, "project")),
            "area": n(g(r, "area")) or "(sem área)",
            "artifact": n(g(r, "artifact")),
            "cat": cat,
            "mod": n(g(r, "Modernizada?")) or "Não",
            "src": n(g(r, "source_type")),
        })
    wb.close()
    return [r for r in rows if r["project"] and r["artifact"]]


def build():
    rows = load_scope()
    # ----- agregações -----
    projects = {}                      # project -> area
    art_meta = {}                      # art_key -> dict(label, cats set, mods set, srcs set)
    art_to_egps = collections.defaultdict(set)
    edges = {}                         # (art_key, project) -> dict(cat,mod)
    for r in rows:
        pj, area = r["project"], r["area"]
        projects.setdefault(pj, area)
        ak = r["artifact"].upper()
        m = art_meta.setdefault(ak, {"label": r["artifact"], "cats": set(), "mods": set(), "srcs": set()})
        m["cats"].add(r["cat"]); m["mods"].add(r["mod"]); m["srcs"].add(r["src"])
        art_to_egps[ak].add(pj)
        edges[(ak, pj)] = {"cat": r["cat"], "mod": r["mod"]}

    def art_cat(ak):
        cats = art_meta[ak]["cats"]
        for c in ("table_in", "file_in", "libname_in", "script_in"):
            if c in cats:
                return c
        return "table_in"

    def is_noise(ak):
        # placeholders de macro / metadados SAS — não são alvos de ingestão
        if art_cat(ak) != "table_in":
            return False
        if ak.startswith(("WORK.", "DICTIONARY.", "SASHELP.", "SASUSER.")):
            return True
        if "{" in ak or "}" in ak or "&" in ak:
            return True
        if ak.endswith((".SAS7", ".SAS7BDAT")):
            return True
        return False

    def art_mod(ak):
        # estrito: verde se disponível em BQ em qualquer EGP; vermelho só se NUNCA modernizada
        if is_noise(ak):
            return "Ruído"
        mods = art_meta[ak]["mods"]
        if "Sim" in mods:
            return "Sim"
        if "Sanitizado" in mods:
            return "Sanitizado"
        return "Não"

    # ----- nós -----
    nodes = []
    for pj, area in sorted(projects.items()):
        nodes.append({
            "id": "E::" + pj, "label": pj, "kind": "egp", "area": area,
            "color": AREA_COLORS.get(area, DEFAULT_AREA),
            "shape": "box", "deg": 0,
            "title": f"EGP: {pj}\\nÁrea: {area}",
        })
    for ak, egs in art_to_egps.items():
        mod = art_mod(ak); cat = art_cat(ak); deg = len(egs)
        srcs = ", ".join(sorted(s for s in art_meta[ak]["srcs"] if s))
        nodes.append({
            "id": "T::" + ak, "label": art_meta[ak]["label"], "kind": "input",
            "cat": cat, "mod": mod, "deg": deg,
            "color": MOD_COLORS.get(mod, "#bab0ac"),
            "shape": "dot", "size": min(8 + deg * 1.6, 46),
            "title": f"{art_meta[ak]['label']}\\nCategoria: {cat}\\nModernizada?: {mod}\\nOrigem: {srcs}\\nConsumida por {deg} EGP(s)",
        })

    edge_list = [{"from": "T::" + ak, "to": "E::" + pj, "cat": e["cat"], "mod": e["mod"]}
                 for (ak, pj), e in edges.items()]

    # degree dos EGPs (nº de inputs distintos)
    egp_deg = collections.Counter()
    for (ak, pj) in edges:
        egp_deg[pj] += 1
    for nd in nodes:
        if nd["kind"] == "egp":
            nd["deg"] = egp_deg.get(nd["label"], 0)
            nd["size"] = min(10 + nd["deg"] * 0.6, 40)

    os.makedirs(OUTDIR, exist_ok=True)

    # ----- CSV de inputs distintos não modernizados -----
    with open(os.path.join(OUTDIR, "indicium_inputs_distintos.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["artifact", "categoria", "modernizada", "source_types", "qtd_egps", "egps"])
        for ak in sorted(art_to_egps, key=lambda k: -len(art_to_egps[k])):
            if art_mod(ak) != "Não":
                continue
            w.writerow([art_meta[ak]["label"], art_cat(ak), art_mod(ak),
                        " | ".join(sorted(s for s in art_meta[ak]["srcs"] if s)),
                        len(art_to_egps[ak]), " | ".join(sorted(art_to_egps[ak]))])

    # ----- métricas para o painel -----
    areas = collections.Counter(projects.values())
    stats = {
        "n_egps": len(projects),
        "n_inputs": len(art_to_egps),
        "n_edges": len(edge_list),
        "n_nao": sum(1 for ak in art_to_egps if art_mod(ak) == "Não"),
        "n_sim": sum(1 for ak in art_to_egps if art_mod(ak) == "Sim"),
        "n_san": sum(1 for ak in art_to_egps if art_mod(ak) == "Sanitizado"),
        "n_ruido": sum(1 for ak in art_to_egps if art_mod(ak) == "Ruído"),
        "n_shared": sum(1 for ak in art_to_egps if len(art_to_egps[ak]) >= 2),
        "areas": dict(areas),
    }
    html = render_html(nodes, edge_list, stats)
    out = os.path.join(OUTDIR, "lineage_indicium.html")
    with open(out, "w", encoding="utf-8") as f:
        f.write(html)
    print("nós:", len(nodes), "| arestas:", len(edge_list))
    print("escrito:", out)
    print("escrito:", os.path.join(OUTDIR, "indicium_inputs_distintos.csv"))


def render_html(nodes, edges, stats):
    nodes_json = json.dumps(nodes, ensure_ascii=False)
    edges_json = json.dumps(edges, ensure_ascii=False)
    stats_json = json.dumps(stats, ensure_ascii=False)
    area_colors_json = json.dumps(AREA_COLORS, ensure_ascii=False)
    return TEMPLATE.replace("__NODES__", nodes_json)\
                   .replace("__EDGES__", edges_json)\
                   .replace("__STATS__", stats_json)\
                   .replace("__AREACOLORS__", area_colors_json)


TEMPLATE = r"""<!DOCTYPE html>
<html lang="pt-br">
<head>
<meta charset="utf-8"/>
<title>Linhagem EGPs priorizados — Indicium</title>
<script src="https://unpkg.com/vis-network@9.1.6/standalone/umd/vis-network.min.js"></script>
<style>
  :root{--bg:#1d1f23;--panel:#26292e;--ink:#e8e8e8;--mut:#9aa0a6;}
  *{box-sizing:border-box;font-family:Segoe UI,Roboto,Helvetica,Arial,sans-serif;}
  html,body{margin:0;height:100%;background:var(--bg);color:var(--ink);}
  #wrap{display:flex;height:100vh;}
  #side{width:320px;flex:0 0 320px;background:var(--panel);padding:14px;overflow:auto;border-right:1px solid #000;}
  #net{flex:1;height:100%;}
  h1{font-size:15px;margin:0 0 4px;} h2{font-size:12px;color:var(--mut);text-transform:uppercase;letter-spacing:.5px;margin:16px 0 6px;}
  .stat{font-size:12px;line-height:1.5;}
  .stat b{font-size:15px;color:#fff;}
  label{font-size:12px;display:flex;align-items:center;gap:6px;margin:3px 0;cursor:pointer;}
  .sw{width:11px;height:11px;border-radius:3px;display:inline-block;flex:0 0 11px;}
  input[type=text]{width:100%;padding:6px;border-radius:5px;border:1px solid #444;background:#1a1c20;color:var(--ink);}
  button{background:#3a3f46;color:var(--ink);border:1px solid #4a4f56;border-radius:5px;padding:5px 8px;font-size:12px;cursor:pointer;margin:2px 0;}
  button:hover{background:#474d55;}
  .leg{font-size:11px;color:var(--mut);margin-top:2px;}
  .row{display:flex;gap:6px;flex-wrap:wrap;}
  hr{border:none;border-top:1px solid #3a3f46;margin:12px 0;}
  .pill{font-size:11px;background:#1a1c20;border:1px solid #3a3f46;border-radius:10px;padding:1px 7px;}
</style>
</head>
<body>
<div id="wrap">
  <div id="side">
    <h1>Linhagem — EGPs Indicium</h1>
    <div class="leg">Tabela/arquivo de entrada → EGP. Aba <i>Extração Bruta oficial</i>.</div>

    <h2>Resumo</h2>
    <div class="stat" id="stats"></div>

    <h2>Busca</h2>
    <input type="text" id="search" placeholder="nó (EGP ou tabela)…"/>

    <h2>Mostrar inputs</h2>
    <label><input type="checkbox" id="onlyShared" checked/> só compartilhados (≥2 EGPs)</label>
    <div class="leg" id="sharedNote"></div>

    <h2>Modernização</h2>
    <label><input type="checkbox" class="mod" value="Não" checked/><span class="sw" style="background:#e15759"></span> Não modernizado (ingerir)</label>
    <label><input type="checkbox" class="mod" value="Sanitizado" checked/><span class="sw" style="background:#edc948"></span> Sanitizado</label>
    <label><input type="checkbox" class="mod" value="Sim" checked/><span class="sw" style="background:#59a14f"></span> Já em BigQuery</label>
    <label><input type="checkbox" class="mod" value="Ruído"/><span class="sw" style="background:#777"></span> Ruído (placeholder/metadado SAS)</label>

    <h2>Categoria</h2>
    <label><input type="checkbox" class="cat" value="table_in" checked/> tabelas (table_in)</label>
    <label><input type="checkbox" class="cat" value="file_in" checked/> arquivos (file_in)</label>
    <label><input type="checkbox" class="cat" value="libname_in" checked/> libs (libname_in)</label>
    <label><input type="checkbox" class="cat" value="script_in" checked/> scripts (script_in)</label>

    <h2>Áreas</h2>
    <div id="areas"></div>

    <hr/>
    <div class="row">
      <button id="apply">Aplicar filtros</button>
      <button id="fit">Enquadrar</button>
      <button id="physics">Pausar física</button>
    </div>
    <div class="leg" id="visible"></div>
  </div>
  <div id="net"></div>
</div>
<script>
const ALL_NODES = __NODES__;
const ALL_EDGES = __EDGES__;
const STATS = __STATS__;
const AREA_COLORS = __AREACOLORS__;

document.getElementById('stats').innerHTML =
  `<b>${STATS.n_egps}</b> EGPs · <b>${STATS.n_inputs}</b> inputs distintos<br>`+
  `<span class="sw" style="background:#e15759"></span> ${STATS.n_nao} a ingerir &nbsp; `+
  `<span class="sw" style="background:#edc948"></span> ${STATS.n_san} sanit. &nbsp; `+
  `<span class="sw" style="background:#59a14f"></span> ${STATS.n_sim} em BQ &nbsp; `+
  `<span class="sw" style="background:#777"></span> ${STATS.n_ruido} ruído<br>`+
  `${STATS.n_shared} inputs compartilhados (≥2 EGPs) · ${STATS.n_edges} arestas`;
document.getElementById('sharedNote').textContent =
  `${STATS.n_shared} compartilhados vs ${STATS.n_inputs-STATS.n_shared} usados por 1 só EGP.`;

// área checkboxes
const areasDiv = document.getElementById('areas');
Object.entries(STATS.areas).sort((a,b)=>b[1]-a[1]).forEach(([a,c])=>{
  const col = AREA_COLORS[a] || '#bab0ac';
  const l = document.createElement('label');
  l.innerHTML = `<input type="checkbox" class="area" value="${a}" checked/>`+
                `<span class="sw" style="background:${col}"></span>${a} <span class="pill">${c}</span>`;
  areasDiv.appendChild(l);
});

const container = document.getElementById('net');
const nodes = new vis.DataSet();
const edges = new vis.DataSet();
const network = new vis.Network(container, {nodes, edges}, {
  nodes:{font:{color:'#e8e8e8',size:13},borderWidth:1},
  edges:{color:{color:'#555',highlight:'#fff'},width:0.5,smooth:false,arrows:{to:{enabled:true,scaleFactor:0.4}}},
  physics:{stabilization:{iterations:120},barnesHut:{gravitationalConstant:-9000,springLength:120,springConstant:0.02,avoidOverlap:0.2}},
  interaction:{hover:true,tooltipDelay:120,navigationButtons:true,keyboard:true},
});

function getChecked(cls){return [...document.querySelectorAll('.'+cls+':checked')].map(e=>e.value);}

function apply(){
  const mods=new Set(getChecked('mod'));
  const cats=new Set(getChecked('cat'));
  const areas=new Set(getChecked('area'));
  const onlyShared=document.getElementById('onlyShared').checked;

  // 1. inputs que passam nos filtros
  const keepInput=new Set();
  for(const nd of ALL_NODES){
    if(nd.kind!=='input') continue;
    if(!mods.has(nd.mod)) continue;
    if(!cats.has(nd.cat)) continue;
    if(onlyShared && nd.deg<2) continue;
    keepInput.add(nd.id);
  }
  // 2. arestas válidas só p/ EGPs de área selecionada e inputs mantidos
  const egpArea={}; ALL_NODES.forEach(n=>{if(n.kind==='egp')egpArea[n.id]=n.area;});
  const keepEgp=new Set(); const useEdges=[];
  for(const e of ALL_EDGES){
    if(!keepInput.has(e.from)) continue;
    if(!areas.has(egpArea[e.to])) continue;
    useEdges.push(e); keepEgp.add(e.to);
  }
  // 3. só inputs que ainda têm ao menos uma aresta visível
  const inputWithEdge=new Set(useEdges.map(e=>e.from));
  const vn=[], ve=[];
  for(const nd of ALL_NODES){
    if(nd.kind==='egp' && keepEgp.has(nd.id)) vn.push(nd);
    else if(nd.kind==='input' && inputWithEdge.has(nd.id)) vn.push(nd);
  }
  const inMod={}; ALL_NODES.forEach(n=>{if(n.kind==='input')inMod[n.id]=n.mod;});
  useEdges.forEach((e,i)=>{const m=inMod[e.from];
    ve.push({id:'e'+i,from:e.from,to:e.to,
      color:{color: m==='Não'?'#7a3a3b': m==='Sanitizado'?'#7a6f2f': m==='Ruído'?'#444':'#3a5a36'}});});
  nodes.clear(); edges.clear(); nodes.add(vn); edges.add(ve);
  document.getElementById('visible').textContent=`Visível: ${vn.length} nós · ${ve.length} arestas`;
}

document.getElementById('apply').onclick=apply;
document.getElementById('fit').onclick=()=>network.fit({animation:true});
let phys=true;
document.getElementById('physics').onclick=function(){phys=!phys;network.setOptions({physics:phys});this.textContent=phys?'Pausar física':'Retomar física';};
document.getElementById('onlyShared').onchange=apply;
document.querySelectorAll('.mod,.cat,.area').forEach(c=>c.onchange=apply);
document.getElementById('search').addEventListener('keydown',e=>{
  if(e.key!=='Enter')return; const q=e.target.value.trim().toUpperCase(); if(!q)return;
  const hit=nodes.get().find(n=>(n.label||'').toUpperCase().includes(q));
  if(hit){network.selectNodes([hit.id]);network.focus(hit.id,{scale:1.2,animation:true});}
});
apply();
</script>
</body>
</html>
"""

if __name__ == "__main__":
    build()
