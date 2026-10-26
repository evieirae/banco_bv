# -*- coding: utf-8 -*-
"""Linhas das tabelas de CONSULTA (sas_consulta_egp / sas_consulta_input) — ADR 0004.

O agente de consulta (Genie, aba Perguntas) lê o que o app MOSTRA sem recalcular nada: o
backend grava, em linhas, o resultado das mesmas funções que servem as telas. Este módulo
é a parte pura — sem DB e sem FastAPI, no padrão de vinculos.py/sanitizacao.py: recebe o
que o main.py já calculou e devolve (a) as linhas e (b) a conferência de paridade contra
os números das telas. Regra de ouro: NENHUMA régua nova mora aqui; se uma coluna precisa
de lógica, a lógica é a da tela, chamada no main.py e passada pronta.

Paridade: cada total de tela tem de ser reproduzido pela soma das colunas `conta_*`. Se
não for, `confere()` devolve as divergências e o main.py NÃO grava — tabela que diz um
número que a tela não diz é pior que tabela velha (falha barulhenta, não silenciosa).
"""

TERMINAIS_EGP = ("Migrado", "Despriorizado e Contabilizado")   # BANDS + Migrado do proj_funnel

# (coluna, tipo SQL) — a ordem é a do INSERT. Mudou aqui, mude a DDL junto (main.py usa isto).
COLUNAS_EGP = [
    ("projeto", "STRING"), ("area", "STRING"), ("responsavel", "STRING"), ("responsavel_bv", "STRING"),
    ("classe_linha_base", "STRING"), ("na_linha_base", "BOOLEAN"), ("no_recorte", "BOOLEAN"),
    ("tipo", "STRING"), ("dep_nivel", "INT"), ("depende_de", "STRING"), ("e_dependencia_de", "STRING"),
    ("ex_dependencia", "BOOLEAN"), ("ex_motivo", "STRING"),
    ("extra", "BOOLEAN"), ("extra_motivo", "STRING"), ("casca", "BOOLEAN"),
    ("vinculo_tipo", "STRING"), ("sucessor", "STRING"), ("antecessores", "STRING"),
    ("etapa_gravada", "STRING"), ("status_gravado", "STRING"),
    ("etapa_exibida", "STRING"), ("status_exibido", "STRING"), ("status_contagem", "STRING"),
    ("bloqueado_dep", "BOOLEAN"), ("deps_despriorizadas", "STRING"),
    ("n_inputs", "INT"), ("n_faltam", "INT"), ("n_sem_fonte", "INT"),
    ("conta_total_egps", "BOOLEAN"), ("conta_funil_migracao", "BOOLEAN"),
    ("conta_funil_migracao_deps", "BOOLEAN"), ("conta_funil_migracao_extras", "BOOLEAN"),
    ("conta_migrado", "BOOLEAN"), ("aparece_gestao", "BOOLEAN"), ("mes_priorizacao", "INT"),
    ("calculado_em", "TIMESTAMP"),
]
COLUNAS_INPUT = [
    ("chave", "STRING"), ("nome", "STRING"), ("categoria", "STRING"), ("origem", "STRING"),
    ("familia", "BOOLEAN"), ("n_safras", "INT"), ("safras", "STRING"), ("responsavel", "STRING"),
    ("etapa_efetiva", "STRING"), ("status_efetivo", "STRING"), ("sanitizado_derivado", "BOOLEAN"),
    ("resolvido", "BOOLEAN"), ("a_ingerir", "BOOLEAN"),
    ("vinculo_ativo", "BOOLEAN"), ("so_de_ex_dependencia", "BOOLEAN"),
    ("de_extra", "BOOLEAN"), ("so_de_extra", "BOOLEAN"), ("balde", "STRING"),
    ("conta_total_inputs", "BOOLEAN"), ("conta_funil_ingestao", "BOOLEAN"),
    ("conta_funil_ingestao_deps", "BOOLEAN"), ("conta_funil_ingestao_extras", "BOOLEAN"),
    ("aparece_gestao", "BOOLEAN"), ("egps_no_recorte", "STRING"),
    ("calculado_em", "TIMESTAMP"),
]
BALDES_CONTADOS = ("escopo", "dependencia", "extra")


def _lista(v):
    return ", ".join(sorted(str(x) for x in v if x)) or None


def _sem_vazio(linha):
    """Texto vazio vira NULL. O app grava etapa/responsável vazios como '' e as telas tratam
    os dois igual; quem consulta por SQL escreve `IS NULL` e deixava passar o '' — medido no
    agente em 07/10/2026: 15 EGPs sem etapa contados como "ativos"."""
    return {k: (None if isinstance(v, str) and not v.strip() else v) for k, v in linha.items()}


def conta_no_coorte_migrado(etapa_exibida, status_contagem, stages, fantasmas):
    """Mesma régua do proj_funnel: só entra no "X/Y migrados" quem está no coorte (etapa
    exibida conhecida e não fantasma) e tem status de contagem terminal."""
    if not etapa_exibida or etapa_exibida in fantasmas or etapa_exibida not in stages:
        return False
    return (status_contagem or "A Iniciar") in TERMINAIS_EGP


def linhas_egp(readiness, linha_base, pipe_real, frontier, extras_recorte, gestao_ids,
               mes_por_projeto, stages, fantasmas, calculado_em):
    """Uma linha por EGP da aba EGPs (readiness `indi_deps`: Recorte + Ex-dependências +
    Linha de base fora do recorte). `linha_base`={projeto: classe}; `pipe_real`={projeto:
    (etapa, status)} gravados; `mes_por_projeto` do plano já podado."""
    dependentes = {}
    for r in readiness:
        for d in r.get("deps") or []:
            dependentes.setdefault(d.get("projeto"), set()).add(r["projeto"])
    out = []
    for r in readiness:
        p = r["projeto"]
        classe = linha_base.get(p)
        et_real, st_real = pipe_real.get(p, (None, None))
        st_cont = r.get("status_contagem")
        out.append(_sem_vazio({
            "projeto": p, "area": r.get("area"), "responsavel": r.get("responsavel"),
            "responsavel_bv": r.get("responsavel_bv"),
            "classe_linha_base": classe, "na_linha_base": classe is not None,
            "no_recorte": p in frontier, "tipo": r.get("tipo"), "dep_nivel": r.get("dep_nivel"),
            "depende_de": _lista(d.get("projeto") for d in (r.get("deps") or [])),
            "e_dependencia_de": _lista(dependentes.get(p, ())),
            "ex_dependencia": bool(r.get("ex_dependencia")), "ex_motivo": r.get("ex_motivo"),
            "extra": bool(r.get("e_extra")), "extra_motivo": r.get("extra_motivo"),
            "casca": r.get("extra_motivo") == "casca",
            "vinculo_tipo": r.get("vinculo_tipo"), "sucessor": r.get("sucessor"),
            "antecessores": _lista(a.get("projeto") for a in (r.get("antecessores") or [])),
            "etapa_gravada": et_real, "status_gravado": st_real,
            "etapa_exibida": r.get("etapa"), "status_exibido": r.get("status"),
            "status_contagem": st_cont,
            "bloqueado_dep": bool(r.get("bloqueado_dep")),
            "deps_despriorizadas": _lista(r.get("deps_despriorizadas") or ()),
            "n_inputs": r.get("n_inputs"), "n_faltam": r.get("n_faltam"),
            "n_sem_fonte": r.get("n_sem_fonte"),
            "conta_total_egps": classe is not None,
            "conta_funil_migracao": classe == "base",
            "conta_funil_migracao_deps": classe is not None,
            "conta_funil_migracao_extras": p in extras_recorte,
            "conta_migrado": conta_no_coorte_migrado(r.get("etapa"), st_cont, stages, fantasmas),
            "aparece_gestao": p in gestao_ids,
            "mes_priorizacao": mes_por_projeto.get(p),
            "calculado_em": calculado_em,
        }))
    return out


def linhas_input(rows_deps, chaves_escopo_universo, rows_indi_universo, gestao_ids, egps_por_chave,
                 eff_etapa, eff_status, modern, aingerir, universo, calculado_em):
    """Uma linha por UNIDADE de input do dataset do Recorte (`indi_deps`), mesma partição da
    Visão geral. As funções de estado (eff_*, modern, aingerir, universo) são as do app,
    passadas prontas. `rows_indi_universo`={chave: linha} do dataset do ESCOPO já filtrado
    pelo universo: o funil de ingestão do escopo lê o estado de lá (a família agrega só as
    safras em vista, então o estado pode diferir do Recorte)."""
    no_uni = {r["chave_canonica"] for r in universo(rows_deps)}
    out = []
    for r in rows_deps:
        k = r["chave_canonica"]
        if r.get("ex_dependencia"):
            balde = "so_ex_dependencia"
        elif r.get("vinculo_ativo") is False:
            balde = "sem_vinculo_ativo"
        elif r.get("so_de_extra"):
            balde = "extra"
        elif k in chaves_escopo_universo:
            balde = "escopo"
        else:
            balde = "dependencia"
        st = eff_status(r)
        conta = k in no_uni and balde in BALDES_CONTADOS
        ri = rows_indi_universo.get(k)
        membros = [m for m in (r.get("membros") or []) if m != k]
        out.append(_sem_vazio({
            "chave": k, "nome": r.get("nome_exibicao") or r.get("artifact"),
            "categoria": r.get("categoria"), "origem": r.get("origem"),
            "familia": bool(membros), "n_safras": len(membros) or 1, "safras": _lista(membros),
            "responsavel": r.get("responsavel"),
            "etapa_efetiva": eff_etapa(r), "status_efetivo": st,
            "sanitizado_derivado": bool(r.get("sanitizado_derivado")),
            "resolvido": modern(r), "a_ingerir": conta and aingerir(r),
            "vinculo_ativo": r.get("vinculo_ativo") is not False,
            "so_de_ex_dependencia": bool(r.get("ex_dependencia")),
            "de_extra": bool(r.get("de_extra")), "so_de_extra": bool(r.get("so_de_extra")),
            "balde": balde, "conta_total_inputs": conta,
            "conta_funil_ingestao": (ri is not None and not ri.get("so_de_extra")
                                     and eff_status(ri) != "Sanitizado"),
            "conta_funil_ingestao_deps": conta and balde != "extra" and st != "Sanitizado",
            "conta_funil_ingestao_extras": conta and balde == "extra" and st != "Sanitizado",
            "aparece_gestao": k in gestao_ids,
            "egps_no_recorte": _lista(egps_por_chave.get(k, ())),
            "calculado_em": calculado_em,
        }))
    return out


def _n(linhas, col, **filtros):
    return sum(1 for r in linhas if r.get(col) and all(r.get(c) == v for c, v in filtros.items()))


def confere(egp, inp, landing, funis, n_gestao_egp, n_gestao_input):
    """[(o que, tela, tabela)] para cada total de tela que a soma das linhas não reproduz.
    Lista vazia = paridade. É o critério de gravação: divergiu, não grava."""
    pares = [
        ("total de EGPs (Resumo)", landing["total_egps"], _n(egp, "conta_total_egps")),
        ("EGPs no escopo (Resumo)", landing["egps_escopo"], _n(egp, "conta_funil_migracao")),
        ("dependências (Resumo)", landing["deps"], _n(egp, "na_linha_base", classe_linha_base="dependencia")),
        ("ex-dependências (Resumo)", landing["deps_ex"], _n(egp, "na_linha_base", classe_linha_base="ex_dependencia")),
        ("extras (Resumo)", landing["extras"], _n(egp, "conta_funil_migracao_extras")),
        ("funil migração: migrados", funis["migracao"]["migrados"],
         _n(egp, "conta_migrado", conta_funil_migracao=True)),
        ("funil migração +deps: migrados", funis["migracao_deps"]["migrados"],
         _n(egp, "conta_migrado", conta_funil_migracao_deps=True)),
        ("funil migração extras: migrados", funis["migracao_extras"]["migrados"],
         _n(egp, "conta_migrado", conta_funil_migracao_extras=True)),
        ("Gestão: EGPs", n_gestao_egp, _n(egp, "aparece_gestao")),
        ("inputs no escopo (Resumo)", landing["inputs_escopo"], _n(inp, "conta_total_inputs", balde="escopo")),
        ("inputs das dependências (Resumo)", landing["inputs_deps"], _n(inp, "conta_total_inputs", balde="dependencia")),
        ("inputs dos extras (Resumo)", landing["inputs_extras"], _n(inp, "conta_total_inputs", balde="extra")),
        ("total de inputs (Resumo)", landing["total_inputs"], _n(inp, "conta_total_inputs")),
        ("inputs a ingerir no escopo (Resumo)", landing["inputs_a_ingerir"], _n(inp, "a_ingerir", balde="escopo")),
        ("inputs a ingerir das dependências (Resumo)", landing["inputs_deps_a_ingerir"], _n(inp, "a_ingerir", balde="dependencia")),
        ("inputs a ingerir dos extras (Resumo)", landing["inputs_extras_a_ingerir"], _n(inp, "a_ingerir", balde="extra")),
        ("total não modernizados (Resumo)", landing["total_nao_modernizados"], _n(inp, "a_ingerir")),
        ("funil ingestão: total", funis["ingestao"]["total"], _n(inp, "conta_funil_ingestao")),
        ("funil ingestão +deps: total", funis["ingestao_deps"]["total"], _n(inp, "conta_funil_ingestao_deps")),
        ("funil ingestão extras: total", funis["ingestao_extras"]["total"], _n(inp, "conta_funil_ingestao_extras")),
        ("Gestão: inputs", n_gestao_input, _n(inp, "aparece_gestao")),
    ]
    return [(o, tela, tab) for o, tela, tab in pares if tela != tab]
