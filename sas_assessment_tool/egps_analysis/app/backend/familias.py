#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Regra canônica de FAMÍLIA DE SAFRAS — a unidade de input do app.

Uma "safra" é uma carga datada da mesma tabela lógica (`GRIMALDI.CARGA_MASSIFICADOS_202506`);
a "família" é o conjunto delas e é o que conta como 1 input, recebe estado de trabalho e vira
pedido de ingestão ao BV (ingestão de família = UMA tabela particionada no destino). Porquê e
alternativas rejeitadas: docs/adr/0002-familia-de-safras-como-unidade-de-input.md.

Três invariantes que este módulo carrega (não "simplificar" sem ler o ADR):

1. **Só `categoria='tabela'` colapsa.** `arquivo`/`script` passam intactos porque o app não
   publica caminho físico para eles (`paths_fisicos` vazio em 100%): sem path, `EXCECOES.CSV`
   juntaria 154 membros sem evidência de serem o mesmo arquivo. Mesma lógica de "guardar onde
   a chave é fraca" que o publish já aplica no bloco de `.sas7bdat`.
2. **Família exige ≥2 membros.** Artefato datado sem irmão continua sendo ele mesmo — é o que
   protege tabela legítima com ano no nome (`CORP.HISTORICO_2016`). Isso é decisão de CORPUS,
   não de nome: `familia_candidata()` é pura; quem aplica a guarda é `resolve()`.
3. **Identidade não depende do filtro.** A contagem de membros roda sobre o corpus INTEIRO,
   nunca sobre o recorte em tela — senão a mesma tabela seria "família" no escopo base e
   "input solto" no escopo Indicium. Mesmo princípio da identidade por (path, membro) da
   linhagem (ver CLAUDE.md §Decisões de design).

Duas formas equivalentes da mesma regra, testadas em `test_familias.py`:
  - `familia_candidata()` (Python) — agregação em memória, escrita, testes;
  - `familia_efetiva_sql()` (expressão SQL) — `COUNT(DISTINCT ...)` no warehouse.
Divergir as duas é bug: há teste pinado no mesmo conjunto de casos.
"""
import json
import os
import re

import dialeto

CATEGORIA_COLAPSAVEL = "tabela"
# SAFRA EM ARQUIVO (02/10/2026). A invariante 1 acima excluía `arquivo` porque o app não
# publicava caminho físico para ele — sem path, `EXCECOES.CSV` juntaria membros sem
# evidência de serem o mesmo arquivo. Essa premissa MUDOU: medido em prod em 02/10, 73%
# dos 4.420 inputs `arquivo` têm `paths_fisicos` preenchido.
#
# E o risco que ela temia é real: das 145 famílias que o nome sozinho formaria, 64 (694
# membros) abrangem 2+ diretórios — inclusive `EXCECOES.CSV`, com 258 membros em 2 pastas.
# Colapsar por nome juntaria arquivos distintos.
#
# Por isso a chave do arquivo é (DIRETÓRIO, padrão), não o padrão sozinho: mesma pasta +
# mesmo nome sem a data = mesma ingestão diária. Sem path, NÃO colapsa — ausência de
# evidência não vira evidência. Medido: 76 famílias, 635 membros -> 76 unidades (-559
# inputs no corpus), e os 237 membros sem path seguem intactos.
CATEGORIA_ARQUIVO = "arquivo"

# Token de data, delimitado por '_' ou '-' à esquerda e por fim-de-nome, delimitador ou '.'
# à direita. `[0-9]` em vez de `\d` para a expressão ser literalmente a mesma em Python e no
# regex Java do Databricks (sem escape de barra).
#
# Os formatos vieram de duas fontes: os três primeiros do corpus (2026-09) e os demais da
# branch `feat/vintage_analysis` (Guilherme, 2026-09), cuja régua pegava 487 tabelas que esta
# não pegava — e nenhuma no sentido contrário. Mês em português é o caso mais comum
# (`SEGUROS.RECLAMACOES_ICATU_ABR25`, 15 irmãos) e não tinha como sair de um regex só numérico.
#
# NÃO adotamos dois pedaços da régua dela, de propósito: `strip_schema` (remover o `LIB.`)
# faria falso-merge, porque mesmo nome em lib/path diferente são tabelas DIFERENTES — é a
# razão de a linhagem ser por (path, membro); e o eixo de VERSÃO (`_v2`, dígito final) não é
# safra: duas versões não são partições do mesmo dado, e colapsá-las esconderia trabalho.
#
# Ordem da alternância importa: do mais específico para o mais genérico, senão o ano solto
# casa primeiro e o lookahead derruba o match inteiro.
# MAIÚSCULA e sem flag de caixa: as duas formas da regra recebem o artefato em `upper()`,
# e apoiar-se em `re.I` no Python fazia o SQL (que não tem flag) NÃO casar mês em português —
# 174 divergências de paridade em 10.451 linhas, medidas antes de corrigir. Padrão em caixa
# alta é literalmente o mesmo nos dois motores.
_MES_PT = (r"(?:JAN(?:EIRO)?|FEV(?:EREIRO)?|MAR(?:CO|ÇO)?|ABR(?:IL)?|MAI(?:O)?|JUN(?:HO)?"
           r"|JUL(?:HO)?|AGO(?:STO)?|SET(?:EMBRO)?|OUT(?:UBRO)?|NOV(?:EMBRO)?|DEZ(?:EMBRO)?)")
_DATA = (
    r"(?:"
    r"1[0-9]{12}"                                                      # epoch em ms
    r"|20[0-9]{2}_(?:0[1-9]|1[0-2])_(?:0[1-9]|[12][0-9]|3[01])"  # YYYY_MM_DD
    r"|20[0-9]{2}(?:0[1-9]|1[0-2])(?:0[1-9]|[12][0-9]|3[01])"   # YYYYMMDD
    r"|(?:0[1-9]|[12][0-9]|3[01])(?:0[1-9]|1[0-2])20[0-9]{2}"   # DDMMYYYY
    r"|20[0-9]{2}[.](?:0[1-9]|1[0-2])"                          # YYYY.MM
    r"|20[0-9]{2}(?:0[1-9]|1[0-2])"                             # YYYYMM
    r"|(?:0[1-9]|[12][0-9]|3[01])(?:0[1-9]|1[0-2])[0-9]{2}"            # DDMMYY
    r"|(?:0[1-9]|[12][0-9]|3[01])" + _MES_PT + r"[0-9]{2}"             # 29JAN26
    r"|" + _MES_PT + r"_?[0-9]{2}"                                     # ABR25, ABRIL_25
    r"|20[0-9]{2}"                                              # YYYY (ano solto)
    r"|(?:0[1-9]|1[0-2])[0-9]{2}"                                      # MMYY
    r")"
)
# À direita: fim, '_'/'-', ou '.' NÃO seguido de dígito. O ponto entrou porque
# `ALVESDS.EMP_8_20260305._GCP` e `BRUNO.CARTEIRA_202601._BRUNO` são safra e ficavam de fora;
# o "não seguido de dígito" preserva a decisão pinada em `ATIVOS.ATIVOS_ENCART_23_202509.30`,
# onde o `.30` é sufixo numérico (parte/versão) e o nome inteiro é outra tabela.
# '.' nunca entra no delimitador da ESQUERDA: ali ele separa o libname.
_TOKEN = r"[_-]" + _DATA + r"(?=$|[_-]|[.](?![0-9]))"
TOKEN_SAFRA = re.compile(_TOKEN)
_SO_TOKEN = re.compile(r"^" + _DATA + r"$")

OVERRIDES_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                              "familias_overrides.json")


# ---------------------------------------------------------------- regra (pura)

def diretorio_de(paths):
    """Diretório do PRIMEIRO caminho de `paths_fisicos` (lista separada por ' | '), em
    caixa alta. Vazio = sem evidência de localização, e aí o arquivo não colapsa.

    O PRIMEIRO, não o menor nem o ordenado: é o que a forma SQL consegue reproduzir com
    `element_at(split(...), 1)` sem ordenar, e as duas formas têm de dar a mesma chave (ver o cabeçalho
    do módulo). Arquivo em 2 pastas fica com a chave da 1ª — conservador: no máximo deixa
    de juntar, nunca junta errado."""
    p = (paths or "").split(" | ")[0].strip()
    if not p:
        return ""
    for sep in ("/", "\\"):
        if sep in p:
            return p.rsplit(sep, 1)[0].upper()
    return ""


def familia_candidata(artifact, categoria=CATEGORIA_COLAPSAVEL, paths=None):
    """Chave de família CANDIDATA (antes da guarda dos ≥2 membros e dos overrides).

    Remove todos os tokens de data do nome: `ALVESDS.EMP_8_20250124_GCP` -> `ALVESDS.EMP_8_GCP`.
    Categoria não colapsável, nome vazio ou nome que virou vazio devolvem o artefato como está
    (nunca devolve string vazia — chave vazia colapsaria inputs sem relação nenhuma).
    """
    a = (artifact or "").strip().upper()
    if not a:
        return a
    if categoria == CATEGORIA_COLAPSAVEL:
        f = TOKEN_SAFRA.sub("", a)
        return f or a
    if categoria == CATEGORIA_ARQUIVO:
        f = TOKEN_SAFRA.sub("", a)
        d = diretorio_de(paths)
        # só arquivo DATADO e COM diretório conhecido vira família; o resto passa intacto,
        # para a chave de um artefato solitário continuar 1:1 com ele (ver _fam_sql_egp).
        if f == a or not f or not d:
            return a
        return f"{d}|{f}"
    return a


def nome_com_marcador(artifact, categoria=CATEGORIA_COLAPSAVEL, marcador="{SAFRA}"):
    """Nome do artefato com o token de data trocado pelo MARCADOR, preservando a posição.

    `GRIMALDI.CARGA_MASSIFICADOS_202506` -> `GRIMALDI.CARGA_MASSIFICADOS_{SAFRA}`;
    `ALVESDS.EMP_8_20250124_GCP` -> `ALVESDS.EMP_8_{SAFRA}_GCP` (data no meio do nome).

    Serve a EXIBIÇÃO: a chave de família (`familia_candidata`) remove o token, então perde
    onde a data estava — daí o template ser derivado de um MEMBRO, não da chave. O separador
    original (`_` ou `-`) é mantido. Nome sem token volta inalterado.

    Vale para `arquivo` também (02/10/2026): a chave dele carrega o DIRETÓRIO
    (`/PASTA|EXCECOES.CSV`), que é identidade, não nome — mostrar isso na tabela seria
    ilegível. Aqui sai `EXCECOES_{SAFRA}.CSV` e o diretório fica no tooltip, que já exibe
    a chave crua (`InputsTable.tsx`: "chave: ${r.artifact}").
    """
    a = (artifact or "").strip().upper()
    if not a or categoria not in (CATEGORIA_COLAPSAVEL, CATEGORIA_ARQUIVO):
        return a
    return TOKEN_SAFRA.sub(lambda m: m.group(0)[0] + marcador, a)


def safras_no_nome(artifact):
    """Tokens de data presentes no nome, na ordem — insumo da profundidade (tickets 07/08).

    Só os tokens: `GRIMALDI.CARGA_MASSIFICADOS_202506` -> ['202506'].
    """
    a = (artifact or "").strip().upper()
    return [m.group(0)[1:] for m in TOKEN_SAFRA.finditer(a)]


_MESES_PT = {"JAN": 1, "FEV": 2, "MAR": 3, "ABR": 4, "MAI": 5, "JUN": 6,
             "JUL": 7, "AGO": 8, "SET": 9, "OUT": 10, "NOV": 11, "DEZ": 12}


def safra_ym(safra):
    """(ano, mês) de um token de safra; None quando o token não carrega mês.

    `'202506'`/`'20250612'` -> (2025, 6); `'ABR25'` -> (2025, 4); `'0124'` -> (2024, 1);
    `'110226'` (DDMMYY) -> (2026, 2); `'2025'` (ano solto) -> None.

    Ambiguidade de 6 e 8 dígitos: o prefixo `20` NÃO decide sozinho, porque o **dia 20**
    produz exatamente o mesmo prefixo que o ano (`200125` é 20/01/25, não ano 2001 mês 25).
    Quem desempata é o mês: só vale a leitura YYYYMM(DD) se o mês dela existir.
    """
    s = (safra or "").strip().upper()
    if not _SO_TOKEN.match(s):
        return None
    dig = s.replace(".", "")
    if dig.isdigit():
        n = len(dig)
        if n == 13:                                        # epoch em ms
            import datetime
            d = datetime.datetime.utcfromtimestamp(int(dig) / 1000)
            return (d.year, d.month)
        # `_DATA` só aceita ano `20xx` — daí o teste ser `== "20"` e não `in ("19","20")`:
        # o "19" ali nunca podia ser ano, só servia para fazer o dia 19 ser lido como um.
        if n in (6, 8):
            if n == 8:
                ymd = (int(dig[:4]), int(dig[4:6]))              # YYYYMMDD
                dmy = (int(dig[4:]), int(dig[2:4]))              # DDMMYYYY
            else:
                ymd = (int(dig[:4]), int(dig[4:6]))              # YYYYMM
                dmy = (2000 + int(dig[4:6]), int(dig[2:4]))      # DDMMYY
            # YYYYMM tem preferência quando as duas leituras dão mês possível
            # (`200112` é tanto 2001-12 quanto 20/01/12) — é o formato dominante
            # no corpus e era o que a versão anterior já escolhia.
            if dig[:2] == "20" and 1 <= ymd[1] <= 12:
                return ymd
            return dmy if 1 <= dmy[1] <= 12 else None
        if n == 4:
            if dig[:2] == "20":                                 # ano solto (2025)
                return None
            return (2000 + int(dig[2:]), int(dig[:2]))          # MMYY
        return None
    # mês em português: ABR25, ABRIL_25, 29JAN26
    m = re.search(r"([A-Z]{3})[A-Z]*_?([0-9]{2})$", s)
    if m and m.group(1) in _MESES_PT:
        return (2000 + int(m.group(2)), _MESES_PT[m.group(1)])
    return None


# ---------------------------------------------------------------- overrides

class OverridesInvalidos(ValueError):
    """Arquivo de exceções malformado — falha ALTA no import/carga, nunca silenciosa."""


def carrega_overrides(path=None):
    """Lê e valida `familias_overrides.json`; ausente = sem exceções.

    Formato:
      {"juntar":  [{"familia": "LIB.NOME", "membros": ["LIB.NOME_A", ...], "motivo": "..."}],
       "separar": [{"artefato": "LIB.NOME_202401", "motivo": "..."}]}

    `juntar` força artefatos numa família que a regra separou; `separar` mantém um artefato
    sozinho, fora de qualquer família. `motivo` é obrigatório — exceção sem porquê é exceção
    que ninguém revisa depois.
    """
    p = path or OVERRIDES_PATH
    if not os.path.exists(p):
        return {"juntar": {}, "separar": set(), "familias_forcadas": {}}
    try:
        with open(p, encoding="utf-8") as f:
            raw = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        raise OverridesInvalidos(f"{p}: não deu para ler/parsear ({e})")
    if not isinstance(raw, dict):
        raise OverridesInvalidos(f"{p}: raiz deve ser objeto")

    juntar, separar, forcadas = {}, set(), {}
    for i, ent in enumerate(raw.get("juntar") or []):
        fam = (ent.get("familia") or "").strip().upper()
        membros = [(m or "").strip().upper() for m in (ent.get("membros") or [])]
        membros = [m for m in membros if m]
        if not fam:
            raise OverridesInvalidos(f"{p}: juntar[{i}] sem 'familia'")
        # Um membro basta: o uso comum é redirecionar UM nome órfão para uma família que a
        # regra já montou (nome que perdeu a data para uma macro — `PAGOS_CYBER_&DAT_EXEC.`
        # extraído como `PERF_CL.PAGOS_CYBER_` — ou para um curinga `..._:`). Exigir um
        # segundo membro obrigaria a fixar aqui o nome de uma safra qualquer, e um re-key do
        # pipeline derrubaria a carga inteira dos overrides (strict=True) por um motivo que
        # nada tem a ver com a exceção. Zero membros, esse sim, é entrada sem efeito.
        if not membros:
            raise OverridesInvalidos(f"{p}: juntar[{i}] ({fam}) sem nenhum membro")
        if not (ent.get("motivo") or "").strip():
            raise OverridesInvalidos(f"{p}: juntar[{i}] ({fam}) sem 'motivo'")
        for m in membros:
            if m in juntar and juntar[m] != fam:
                raise OverridesInvalidos(f"{p}: {m} forçado em duas famílias ({juntar[m]}, {fam})")
            juntar[m] = fam
        forcadas[fam] = sorted(set(membros) | set(forcadas.get(fam, ())))
    for i, ent in enumerate(raw.get("separar") or []):
        art = (ent.get("artefato") or "").strip().upper()
        if not art:
            raise OverridesInvalidos(f"{p}: separar[{i}] sem 'artefato'")
        if not (ent.get("motivo") or "").strip():
            raise OverridesInvalidos(f"{p}: separar[{i}] ({art}) sem 'motivo'")
        separar.add(art)
    conflito = separar & set(juntar)
    if conflito:
        raise OverridesInvalidos(f"{p}: {sorted(conflito)} em 'juntar' e 'separar' ao mesmo tempo")
    return {"juntar": juntar, "separar": separar, "familias_forcadas": forcadas}


# ---------------------------------------------------------------- resolução (corpus)

def resolve(rows, artifact_key="artifact", categoria_key="categoria", overrides=None,
            strict=True, paths_key="paths_fisicos"):
    """Aplica regra + guarda dos ≥2 membros + overrides sobre o CORPUS INTEIRO.

    `rows` = todas as linhas não-órfãs do monitor (não o recorte em tela — invariante 3).
    Devolve {"chave": {(categoria, ARTEFATO): chave_efetiva},
             "membros": {(categoria, chave_efetiva): [ARTEFATO, ...]}}.
    A chave efetiva de quem não tem irmão é o próprio artefato, então todo consumidor pode
    agrupar por ela sem tratar caso especial.

    `strict` faz override que aponta para artefato inexistente levantar — é o que impede o
    arquivo de exceções de apodrecer em silêncio depois de um re-key do pipeline.

    `paths_key` traz o caminho físico da LINHA, que é o que permite a safra em ARQUIVO
    colapsar por (diretório, padrão). A chave do mapa segue `(categoria, ARTEFATO)` porque
    o par é único no monitor (medido em 02/10/2026: 0 duplicatas em 12.855 linhas) — então
    o diretório sai da própria linha e nenhum consumidor precisa mudar.
    """
    ov = overrides if overrides is not None else carrega_overrides()
    juntar, separar = ov["juntar"], ov["separar"]

    itens = []       # [(categoria, ARTEFATO, candidata)]
    vistos = set()
    for r in rows:
        art = (r.get(artifact_key) or "").strip().upper()
        cat = (r.get(categoria_key) or "").strip()
        if not art or (cat, art) in vistos:
            continue
        vistos.add((cat, art))
        if art in separar:
            cand = art                                  # fora de qualquer família
        elif art in juntar:
            cand = juntar[art]                           # família forçada
        else:
            cand = familia_candidata(art, cat, r.get(paths_key))
        itens.append((cat, art, cand))

    if strict:
        conhecidos = {a for _, a, _ in itens}
        orfas = sorted((set(juntar) | separar) - conhecidos)
        if orfas:
            raise OverridesInvalidos(
                "overrides apontam para artefatos que não existem no corpus: "
                + ", ".join(orfas[:10]) + (" …" if len(orfas) > 10 else ""))

    n_membros = {}
    for cat, _art, cand in itens:
        n_membros[(cat, cand)] = n_membros.get((cat, cand), 0) + 1

    chave, membros = {}, {}
    for cat, art, cand in itens:
        # guarda dos ≥2: candidata com um único membro não é família (mas família FORÇADA
        # por override vale, mesmo que o corpus só tenha um membro dela no momento)
        eff = cand if (n_membros[(cat, cand)] > 1 or art in juntar) else art
        chave[(cat, art)] = eff
        membros.setdefault((cat, eff), []).append(art)
    for k in membros:
        membros[k].sort()
    return {"chave": chave, "membros": membros}


def e_familia(membros_map, categoria, chave):
    """True se a chave efetiva agrupa mais de um artefato (i.e. é família, não input solto)."""
    return len(membros_map.get((categoria, chave), ())) > 1


# ---------------------------------------------------------------- forma SQL

def _lit(s):
    return dialeto.lit(s)


def familia_candidata_sql(art="artifact", cat="categoria", paths="''", overrides=None):
    """Expressão SQL da chave CANDIDATA — espelho de `familia_candidata()` + overrides.

    Os overrides entram como CASE (o arquivo é curado e pequeno), senão as contagens do
    warehouse discordariam da agregação em memória justamente nas exceções.

    `paths` é a EXPRESSÃO do caminho físico (ver `diretorio_de`). O default é `''` — sem
    evidência — de propósito: há chamador sem a coluna no escopo (a auditoria lê
    `sas_inputs_audit`, que não tem `paths_fisicos`), e ali o certo é arquivo NÃO colapsar.
    Default apontando para um nome de coluna quebraria essas queries em runtime.
    """
    ov = overrides if overrides is not None else carrega_overrides()
    up = f"upper({art})"
    regra = (f"coalesce(nullif(regexp_replace({up}, {_lit(_TOKEN)}, ''), ''), {up})")
    # SAFRA EM ARQUIVO: espelho de `diretorio_de()` + a regra do candidato. `element_at(.., 1)`
    # pega o PRIMEIRO caminho, igual ao Python, nos dois bancos (`split(x)[0]` não roda no
    # Postgres, onde o índice começa em 1 e função não aceita colchete); `regexp_replace` tira
    # o nome do arquivo e o separador final. `{regra} <> {up}` é o "só datado colapsa";
    # diretório vazio não colapsa.
    prim = f"element_at(split({paths}, ' [|] '), 1)"
    _nao_sep = "'[^/" + "\\\\" * 2 + "]*$'"
    _sep_fim = "'[/" + "\\\\" * 2 + "]$'"
    dir_ = f"upper(regexp_replace(regexp_replace({prim}, {_nao_sep}, ''), {_sep_fim}, ''))"
    base = (f"CASE WHEN {cat} = {_lit(CATEGORIA_COLAPSAVEL)} THEN {regra} "
            f"WHEN {cat} = {_lit(CATEGORIA_ARQUIVO)} AND {regra} <> {up} "
            f"AND {dir_} <> '' AND {prim} <> '' "
            f"THEN concat({dir_}, '|', {regra}) "
            f"ELSE {up} END")
    casos = []
    for art_ov, fam in sorted(ov["juntar"].items()):
        casos.append(f"WHEN {up} = {_lit(art_ov)} THEN {_lit(fam)}")
    for art_ov in sorted(ov["separar"]):
        casos.append(f"WHEN {up} = {_lit(art_ov)} THEN {up}")
    if not casos:
        return base
    return "CASE " + " ".join(casos) + f" ELSE {base} END"


def familia_efetiva_sql(art="artifact", cat="categoria", paths="''", overrides=None):
    """Expressão SQL da chave EFETIVA: candidata, ou o próprio artefato se não tiver irmão.

    A guarda dos ≥2 membros é janela sobre o corpus inteiro — use esta expressão em SELECT
    que NÃO filtre linhas (filtre depois, num CTE externo), senão a janela conta membros do
    recorte e quebra a invariante 3.
    """
    cand = familia_candidata_sql(art, cat, paths, overrides)
    return (f"CASE WHEN count(*) OVER (PARTITION BY {cat}, {cand}) > 1 "
            f"THEN {cand} ELSE upper({art}) END")
