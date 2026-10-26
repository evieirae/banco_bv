import os, collections
from databricks.sdk import WorkspaceClient

WID = os.environ.get("DATABRICKS_WAREHOUSE_ID", "5922c26f81f1bbdd")
FQ = "bv_dev_db.monitoramento_sas"
w = WorkspaceClient()

import time
def q(sql):
    r = w.statement_execution.execute_statement(warehouse_id=WID, statement=sql, wait_timeout="50s")
    while r.status and r.status.state.value in ("PENDING", "RUNNING"):
        time.sleep(2); r = w.statement_execution.get_statement(r.statement_id)
    if r.status and r.status.state.value != "SUCCEEDED":
        raise RuntimeError(f"{r.status.state.value}: {r.status.error}")
    cols = [c.name for c in r.manifest.schema.columns]
    data = r.result.data_array or []
    return [dict(zip(cols, row)) for row in data]

# pull raw
edges = q(f"SELECT projeto_alvo, depende_do FROM {FQ}.sas_lineage_edges")
nodes = q(f"SELECT projeto, escopo_indi FROM {FQ}.sas_lineage_nodes")
egpin = q(f"SELECT projeto, chave_canonica, categoria, modernizada_auto FROM {FQ}.sas_egp_inputs")

indi = {n["projeto"] for n in nodes if str(n["escopo_indi"]).lower() == "true"}
print(f"nodes={len(nodes)} | escopo Indicium={len(indi)} | edges={len(edges)} | egp_inputs={len(egpin)}")

# adjacency: alvo -> set(depende_do)
dep_of = collections.defaultdict(set)
for e in edges:
    a, d = e["projeto_alvo"], e["depende_do"]
    if a and d and a != d:
        dep_of[a].add(d)

# direct deps of indi scope
direct = set()
for a in indi:
    direct |= dep_of.get(a, set())

# transitive deps (closure) of indi scope
trans = set()
stack = list(direct)
while stack:
    p = stack.pop()
    if p in trans:
        continue
    trans.add(p)
    for nxt in dep_of.get(p, set()):
        if nxt not in trans:
            stack.append(nxt)

# inputs per projeto
proj_inputs = collections.defaultdict(set)          # projeto -> set(chave)
proj_inputs_aing = collections.defaultdict(set)     # projeto -> set(chave) a ingerir
chave_cat = {}
for r in egpin:
    proj_inputs[r["projeto"]].add(r["chave_canonica"])
    chave_cat[r["chave_canonica"]] = r["categoria"]
    if r["modernizada_auto"] == "A ingerir":
        proj_inputs_aing[r["projeto"]].add(r["chave_canonica"])

# inputs of the 229 themselves (for "novo" calc)
indi_inputs = set()
for p in indi:
    indi_inputs |= proj_inputs.get(p, set())

def summarize(label, dep_set):
    in_scope = dep_set & indi
    out_scope = dep_set - indi
    all_in = set(); aing = set()
    for p in dep_set:
        all_in |= proj_inputs.get(p, set())
        aing |= proj_inputs_aing.get(p, set())
    out_in = set()
    for p in out_scope:
        out_in |= proj_inputs.get(p, set())
    novo = all_in - indi_inputs            # inputs que NÃO aparecem em nenhum dos 229
    tabs = {c for c in all_in if chave_cat.get(c) == "tabela"}
    print(f"\n=== {label} ===")
    print(f"  EGPs dependência: {len(dep_set)}  (dentro do escopo={len(in_scope)} | fora do escopo={len(out_scope)})")
    print(f"  inputs distintos (todas as deps):          {len(all_in)}")
    print(f"    └ a ingerir:                             {len(aing)}")
    print(f"    └ tabelas (subconjunto table_in):        {len(tabs)}")
    print(f"  inputs distintos só das deps FORA escopo:  {len(out_in)}")
    print(f"  inputs NOVOS (não presentes nos 229):      {len(novo)}")

summarize("DEPENDÊNCIAS DIRETAS do escopo Indicium", direct)
summarize("DEPENDÊNCIAS TRANSITIVAS (toda a cadeia)", trans)
print(f"\n[ref] inputs distintos dos próprios 229 = {len(indi_inputs)}")
