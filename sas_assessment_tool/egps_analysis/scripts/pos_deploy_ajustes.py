#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Replica em PROD os ajustes de classificação feitos no ambiente de validação.

## Por que existe

A branch `feature/updated-egps-unification` foi validada num schema descartável
(`monitoramento_sas_atualizados_dev`). Além do CÓDIGO, ela produziu **decisões de gestão**
que são dado, não deploy: 23 vínculos antecessor→sucessor, a declaração do `ROI` como EGP
novo e dois acertos de etapa/status. Prod tem **zero** vínculos — nada disso viaja no
`databricks sync`.

Reconstruir essa lista à mão depois seria frágil, então o script **lê do ambiente de
origem** em vez de carregar a lista no código. A única coisa escrita à mão são os dois
acertos de pipeline, que são julgamento e por isso ficam explícitos e revisáveis abaixo.

## Como aplica

Pelo ENDPOINT (`egp_pipeline`), nunca por SQL: as guardas do §3.2.7 e a cópia do §3.3.11
moram no PATCH, e migrar vínculo por UPDATE cru já reintroduziu o bug do ticket 07 uma vez.
Só `_require_gestao` é neutralizado — é gate de UI, não regra de negócio.

Idempotente: o que já está igual no destino é pulado. Dry-run por padrão.

## Pré-requisito DURO

O sucessor tem de existir em `sas_lineage_nodes` do destino. Em 30/09 prod tinha 1.229 nós
e o ambiente 1.270 — **rode o publish do corpus ANTES**, senão o endpoint recusa com 404
(corretamente). O script lista quem falta e não tenta.
"""
import argparse
import json
import os
import sys
from unittest.mock import patch

# Acertos de ETAPA/STATUS feitos à mão no ambiente — julgamento da gestão, não derivável.
# Ficam aqui explícitos porque copiar etapa/status em massa da origem sobrescreveria o
# estado VIVO de prod, que é justamente o que não se quer tocar.
PIPELINE = [
    # (projeto, campo, valor, porquê)
    ("Cobranças__Reneg_Remunerav3", "status", "",
     "o Migrado estava no antecessor mas era do _RPA (decisão de 29/09); limpar é o que a "
     "própria guarda do app pede antes de vincular"),
    ("Cobranças__Reneg_Remunerav3_RPA", "etapa", "Migrado",
     "é ele que foi migrado e formalizado ao BV em 25/09"),
    ("Cobranças__Reneg_Remunerav3_RPA", "status", "Migrado", "idem"),
]
CONFIGS = ["egps_novos"]        # ex_deps_manuais já está igual nos dois


def _mod(schema):
    for m in ("main", "vinculos", "linha_base", "familias", "sanitizacao", "input_state"):
        sys.modules.pop(m, None)
    os.environ["PUBLISH_SCHEMA"] = schema
    import importlib
    return importlib.import_module("main")


def le_origem(schema):
    m = _mod(schema)
    vin = [(r["projeto"], r["egp_vinculo_tipo"], r["egp_sucessor"]) for r in m.run_sql(
        f"SELECT projeto, egp_vinculo_tipo, egp_sucessor FROM {m.T_PIPE} "
        f"WHERE coalesce(egp_sucessor, '') <> '' ORDER BY projeto")]
    cfg = {r["chave"]: r["valor"] for r in m.run_sql(
        f"SELECT chave, valor FROM {m.T_CFG} WHERE chave IN "
        f"({', '.join(m.sql_lit(c) for c in CONFIGS)})")}
    return vin, cfg


def aplica(destino, vin, cfg, aplicar):
    m = _mod(destino)
    nos = {r["projeto"] for r in m.run_sql(f"SELECT projeto FROM {m.T_ND}")}
    atual = {r["projeto"]: (r.get("egp_vinculo_tipo"), r.get("egp_sucessor"))
             for r in m.run_sql(f"SELECT projeto, egp_vinculo_tipo, egp_sucessor FROM {m.T_PIPE}")}
    faltam = [(a, t, s) for a, t, s in vin if s not in nos or a not in nos]
    iguais = [(a, t, s) for a, t, s in vin if atual.get(a) == (t, s)]
    fazer = [x for x in vin if x not in faltam and x not in iguais]
    print(f"\n=== vínculos — {m.CATALOG}.{m.SCHEMA}")
    print(f"   já iguais no destino : {len(iguais)}")
    print(f"   a aplicar            : {len(fazer)}")
    print(f"   BLOQUEADOS (fora do corpus do destino): {len(faltam)}")
    for a, t, s in faltam:
        qual = "antecessor" if a not in nos else "sucessor"
        print(f"      falta o {qual}: {(a if a not in nos else s)}")
    if faltam:
        print("   -> rode o publish do corpus antes; o endpoint recusaria com 404.")
    if not aplicar:
        for a, t, s in fazer:
            print(f"   [dry] {a[:52]:52} --{t}--> {s[:44]}")
    else:
        with patch.object(m, "_require_gestao", lambda *a, **k: None):
            for a, t, s in fazer:
                try:
                    m.egp_pipeline(m.EgpPipe(projeto=a, funil="migracao",
                                             egp_vinculo_tipo=t, egp_sucessor=s))
                    print(f"   OK   {a[:52]:52} --{t}--> {s[:44]}")
                except Exception as e:
                    print(f"   ERRO {a[:52]}: {getattr(e, 'detail', e)}")
            for projeto, campo, valor, _por in PIPELINE:
                if projeto not in nos:
                    print(f"   -- {projeto}: fora do corpus, pulado"); continue
                try:
                    m.egp_pipeline(m.EgpPipe(projeto=projeto, funil="migracao", **{campo: valor}))
                    print(f"   OK   {projeto[:52]:52} {campo}={valor!r}")
                except Exception as e:
                    print(f"   ERRO {projeto[:52]} {campo}: {getattr(e, 'detail', e)}")
    print(f"\n=== config")
    for chave, valor in sorted(cfg.items()):
        tem = m.run_sql(f"SELECT valor FROM {m.T_CFG} WHERE chave = {m.sql_lit(chave)}")
        if tem and tem[0]["valor"] == valor:
            print(f"   já igual: {chave} = {valor}"); continue
        print(f"   {'aplicar' if aplicar else '[dry]'}: {chave} = {valor}")
        if aplicar:
            m.run_sql(
                f"MERGE INTO {m.T_CFG} t USING (SELECT {m.sql_lit(chave)} AS chave) s "
                f"ON t.chave = s.chave WHEN MATCHED THEN UPDATE SET t.valor = {m.sql_lit(valor)}, "
                f"t.updated_by = current_user(), t.updated_at = cast(current_timestamp() AS STRING) "
                f"WHEN NOT MATCHED THEN INSERT (chave, valor, updated_by, updated_at) VALUES "
                f"({m.sql_lit(chave)}, {m.sql_lit(valor)}, current_user(), "
                f"cast(current_timestamp() AS STRING))", want_rows=False)
    return len(faltam)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--origem", default="monitoramento_sas_atualizados_dev")
    ap.add_argument("--destino", default="monitoramento_sas")
    ap.add_argument("--aplica", action="store_true", help="sem isto, so mostra o plano")
    a = ap.parse_args()
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                    "..", "app", "backend"))
    os.environ.setdefault("FAMILIAS_SAFRA", "1")
    vin, cfg = le_origem(a.origem)
    print(f"origem {a.origem}: {len(vin)} vínculo(s), config {sorted(cfg)}")
    faltam = aplica(a.destino, vin, cfg, a.aplica)
    print(f"\n{'APLICADO' if a.aplica else 'DRY-RUN — nada foi escrito'}")
    return 1 if faltam else 0


if __name__ == "__main__":
    sys.exit(main())
