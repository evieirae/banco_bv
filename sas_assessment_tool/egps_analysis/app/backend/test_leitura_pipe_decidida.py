#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Trava estrutural: toda leitura de etapa/status do funil tem de DECLARAR a decisão.

O defeito que gerou este arquivo não nasceu de erro de raciocínio. `anexa_vinculo()` — a
derivação que aplica a etapa espelhada e o status `Desatualizado` (spec §3.2) — existia num
lugar só, e **nada avisava** quando uma sexta superfície passava a ler
`etapa_migracao`/`status_migracao` crus. A aba EGPs e o Resumo então discordavam sobre a
etapa do mesmo antecessor, em silêncio, até alguém conferir na mão.

As duas respostas são legítimas e nenhuma é o default:

* **derivado** — a superfície mostra o ANDAMENTO do trabalho (funis do Resumo, drawers,
  Gestão, coluna Etapa da Priorização). Aqui a etapa é a do sucessor e o status é
  `Desatualizado`.
* **real** — a superfície pergunta pelo ESTADO GRAVADO de gestão, ou escreve nele: quem
  está despriorizado (`_egps_fora_backlog`), o critério 189 dos denominadores
  (`_ex_deps_contab` e companhia), o PATCH, a DDL, a cópia do §3.3.11.

Então a regra é: cada leitura escreve, ali do lado, qual das duas escolheu e por quê.

    # pipe-etapa-status: real — <porquê>
    # pipe-etapa-status: derivado — <porquê>

Precedente do formato: test_chunks_sem_truncar.py (varre o fonte atrás de um padrão
proibido). A diferença é que aqui não existe padrão proibido — existe decisão obrigatória.

Offline: só lê e parseia o fonte, não abre conexão nenhuma.
"""
import ast
import pathlib
import re

import pytest

ALVO = pathlib.Path(__file__).resolve().parent / "main.py"

# As colunas do funil de MIGRAÇÃO em sas_egp_pipeline. O funil de "progresso"
# (etapa_progresso/status_progresso) fica de fora: não tem vínculo nem derivação.
COLUNAS = ("etapa_migracao", "status_migracao")

MARCADOR = re.compile(r"#\s*pipe-etapa-status:\s*(real|derivado)\b")


def _linhas_de_docstring(tree):
    """Linhas ocupadas por docstrings — elas CITAM as colunas sem ler nada."""
    fora = set()
    for no in ast.walk(tree):
        corpo = getattr(no, "body", None)
        if not isinstance(corpo, list) or not corpo:
            continue
        p = corpo[0]
        if (isinstance(p, ast.Expr) and isinstance(p.value, ast.Constant)
                and isinstance(p.value.value, str)):
            fora.update(range(p.lineno, (p.end_lineno or p.lineno) + 1))
    return fora


def _stmts(tree):
    return [n for n in ast.walk(tree)
            if isinstance(n, ast.stmt) and getattr(n, "end_lineno", None)]


def _janela(stmts, linha):
    """(inicio, fim) das linhas em que a decisão desta leitura pode estar escrita.

    Do fim do comando ANTERIOR até a própria linha da leitura — ou seja, o bloco de
    comentário que encosta neste comando, mais um comentário de fim de linha. Deliberado:
    uma leitura NOVA colada numa já decidida cai fora da janela da vizinha (o comentário
    dela fica antes do comando anterior) e o teste cobra a decisão dela também.
    """
    dentro = [n for n in stmts if n.lineno <= linha <= (n.end_lineno or n.lineno)]
    alvo = max(dentro, key=lambda n: (n.lineno, -(n.end_lineno or n.lineno)))
    antes = [n.end_lineno for n in stmts if (n.end_lineno or n.lineno) < alvo.lineno]
    return (max(antes) + 1 if antes else 1), linha


def leituras_sem_decisao(src):
    """[(linha, texto)] das leituras que não declaram derivado|real."""
    linhas = src.splitlines()
    tree = ast.parse(src)
    docs = _linhas_de_docstring(tree)
    stmts = _stmts(tree)
    faltando = []
    for i, texto in enumerate(linhas, start=1):
        if not any(c in texto for c in COLUNAS):
            continue
        if i in docs or texto.lstrip().startswith("#"):
            continue                      # comentário/docstring: cita, não lê
        ini, fim = _janela(stmts, i)
        if not any(MARCADOR.search(linhas[j - 1]) for j in range(ini, fim + 1)):
            faltando.append((i, texto.strip()))
    return faltando


def test_toda_leitura_do_funil_declara_derivado_ou_real():
    pendentes = leituras_sem_decisao(ALVO.read_text(encoding="utf-8"))
    assert not pendentes, (
        "leitura de etapa/status de sas_egp_pipeline sem decisão declarada — escreva "
        "`# pipe-etapa-status: real — <porquê>` ou `# pipe-etapa-status: derivado — "
        "<porquê>` junto dela (ver o cabeçalho deste arquivo):\n"
        + "\n".join(f"  main.py:{n}: {t}" for n, t in pendentes))


def test_a_trava_pega_uma_leitura_nova_sem_decisao():
    """Prova que o teste acima FALHA quando alguém adiciona uma leitura crua.

    Sem isto a trava poderia estar sempre verde por engano (regex que nunca casa, janela
    larga demais) e ninguém notaria até o defeito voltar.
    """
    src = ALVO.read_text(encoding="utf-8")
    base = [t for _n, t in leituras_sem_decisao(src)]

    # 1) leitura nova, em função nova: tem de ser pega
    nova = src + (
        "\n\ndef _superficie_nova_sem_decisao():\n"
        "    return run_sql(f\"SELECT projeto, etapa_migracao FROM {T_PIPE}\")\n")
    assert any("_superficie_nova_sem_decisao" in linha or "etapa_migracao FROM" in linha
               for _n, linha in leituras_sem_decisao(nova))

    # 2) leitura nova COLADA numa já decidida: o comentário da vizinha não a cobre
    alvo = "    return _cache_lineage((\"fora_backlog\",), _p)"
    assert alvo in src
    crua = "    _outra = run_sql(f\"SELECT projeto, status_migracao FROM {T_PIPE}\")\n"
    colada = src.replace(alvo, crua + alvo, 1)
    assert any("_outra" in linha for _n, linha in leituras_sem_decisao(colada))

    # 3) a MESMA leitura, com a decisão declarada, passa — e nada MAIS é cobrado
    decidida = src.replace(
        alvo, "    # pipe-etapa-status: real — porque sim.\n" + crua + alvo, 1)
    # compara os TEXTOS (as linhas abaixo do trecho inserido deslocam de número)
    assert [t for _n, t in leituras_sem_decisao(decidida)] == base


@pytest.mark.parametrize("marcador", ["real", "derivado"])
def test_as_duas_decisoes_existem_no_codigo(marcador):
    """Guarda contra a trava virar carimbo: se um dos dois lados sumir, é sinal de que
    alguém derivou tudo (quebrando o denominador e quem está despriorizado) ou de que a
    derivação voltou a existir num lugar só."""
    src = ALVO.read_text(encoding="utf-8")
    assert re.search(rf"#\s*pipe-etapa-status:\s*{marcador}\b", src)
