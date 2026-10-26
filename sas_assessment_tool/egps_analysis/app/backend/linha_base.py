# -*- coding: utf-8 -*-
"""Linha de base CONGELADA dos EGPs — decisão da gestão, 29/09/2026.

O total de EGPs **deixa de ser calculado** e passa a ser uma LISTA de 193 projetos,
versionada em `egps_analysis/src/linha_base_congelada_2026-09-29.csv` (colunas
`projeto,classe`). Quem não está na lista é `extra`, **inclusive o que o grafo
classificaria como dependência**: o que entrou no corpus depois do congelamento conta à
parte, num contador próprio.

Congelado nos dois lados: quem SAI do escopo continua no denominador. `Despriorizado e
Contabilizado` já contava por desenho; remoção e dedup deixam de mexer no número. O
progresso passa a ser medido contra um total que nunca muda.

**Só o DENOMINADOR é congelado.** Congelado é *quais* projetos contam e a *classe* de cada
um. Etapa, status, funis, barras, coorte, migrados, inputs e fila continuam sendo
derivados do estado atual a cada leitura, como hoje: é "X de 193", com o 193 parado e o X
se mexendo o tempo todo.

Módulo de DADO, não de runtime: a lista é lida do arquivo versionado (como o publish lê
`src/egps_casca.csv`), e **arquivo ausente explode** em vez de virar lista vazia — sem a
linha de base o total seria um número inventado, e um zero silencioso é pior do que um 500.

A data está no NOME do arquivo de propósito: trocar a linha de base exige arquivo novo e
uma mudança em `ARQUIVO` — ato deliberado, nunca efeito colateral de um republish.
"""
import csv
import io
import os

# Classes gravadas no CSV. `extra` NÃO é classe: extra é quem está FORA desta lista.
CLASSES = ("base", "dependencia", "ex_dependencia")

ARQUIVO = "linha_base_congelada_2026-09-29.csv"
# AO LADO DO MÓDULO, de propósito (corrigido 29/09 depois de um 500 em produção do app
# dev): o deploy sincroniza apenas `egps_analysis/app/`, então qualquer caminho que suba
# para fora daí existe em desenvolvimento e SOME no app publicado. O guard de falha
# barulhenta funcionou — a aba EGPs deu 500 em vez de inventar um total —, mas o arquivo
# precisa viajar junto. Travado por test_linha_base.py::test_arquivo_vive_dentro_do_deploy.
CAMINHO = os.path.join(os.path.dirname(os.path.abspath(__file__)), ARQUIVO)


class LinhaBaseAusente(RuntimeError):
    """O arquivo da linha de base não existe/não pôde ser lido."""


class LinhaBaseInvalida(ValueError):
    """O arquivo existe mas não descreve uma linha de base utilizável."""


def parse(texto):
    """CSV (texto) -> {projeto: classe}. Puro, e recusa tudo que faria o total mentir:
    classe desconhecida, projeto repetido e lista vazia."""
    mapa = {}
    for i, r in enumerate(csv.DictReader(io.StringIO(texto)), start=2):
        projeto = (r.get("projeto") or "").strip()
        classe = (r.get("classe") or "").strip()
        if not projeto:
            continue
        if classe not in CLASSES:
            raise LinhaBaseInvalida(
                f"linha {i}: classe {classe!r} desconhecida (esperado: {', '.join(CLASSES)})")
        if projeto in mapa:
            raise LinhaBaseInvalida(f"linha {i}: projeto {projeto!r} repetido")
        mapa[projeto] = classe
    if not mapa:
        raise LinhaBaseInvalida("linha de base vazia — o total de EGPs seria zero")
    return mapa


_cache = {}


def carrega(caminho=None):
    """Lê a linha de base do arquivo versionado. Cacheado por caminho (é dado imutável).

    Falha BARULHENTA: arquivo ausente/ilegível vira LinhaBaseAusente. Nunca devolve {}."""
    caminho = caminho or CAMINHO
    if caminho not in _cache:
        try:
            with open(caminho, encoding="utf-8") as f:
                texto = f.read()
        except OSError as e:
            raise LinhaBaseAusente(
                f"linha de base congelada não encontrada em {caminho}: {e}") from e
        _cache[caminho] = parse(texto)
    return _cache[caminho]


def limpa_cache():
    _cache.clear()


def projetos(mapa):
    """Os projetos da linha de base — o conjunto que decide quem CONTA."""
    return set(mapa or {})


def por_classe(mapa):
    """{classe: {projetos}} — a decomposição vem da classe GRAVADA, nunca do grafo vivo."""
    out = {c: set() for c in CLASSES}
    for projeto, classe in (mapa or {}).items():
        out[classe].add(projeto)
    return out


def decomposicao(mapa):
    """{classe: quantidade} — o que a tela mostra como base / dependências / ex."""
    return {c: len(v) for c, v in por_classe(mapa).items()}


def total(mapa):
    """O denominador. É o tamanho da lista, não uma soma de contagens vivas."""
    return len(mapa or {})
