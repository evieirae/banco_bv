#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Decisões humanas por EGP que o corpus não carrega (`src/egps_decisoes.csv`).

O orquestrador lê `text_egps/` inteiro e o publish regrava as tabelas do corpus a cada
rodada, então uma decisão tomada direto no banco morre no publish seguinte. Medido em
16/10/2026: as 11 duplicatas removidas à mão entre agosto e setembro estavam todas de volta
em prod, e o renome do CPF_Contrato (D013) era refeito à mão depois de cada publish.

A decisão mora neste arquivo versionado, com o motivo, e vale na LEITURA do corpus, antes de
qualquer relatório: o orquestrador e o publish chamam `carrega` e `aplica_ao_corpus`.

Colunas: egp_key, acao, alvo, motivo, data, quem.
  egp_key  nome do EGP no corpus: o PROJECT: do cabeçalho do .txt.
  acao     excluir                o EGP sai do inventário (duplicata, cópia de teste).
           renomear               o EGP entra com o nome `alvo`.
           tirar_output_do_escopo os outputs do EGP cujo artefato começa com `alvo` ficam
                                  fora do escopo Indicium (escopo_indi=false).

Qualquer incoerência para o processo (DecisaoInvalida): seguir em frente com uma decisão que
não se aplica é a falha silenciosa que este arquivo existe para impedir.
"""
import csv
import os
from dataclasses import dataclass

ACOES = ("excluir", "renomear", "tirar_output_do_escopo")
COLUNAS = ["egp_key", "acao", "alvo", "motivo", "data", "quem"]
PADRAO = os.path.join(os.path.dirname(os.path.abspath(__file__)), "src", "egps_decisoes.csv")


class DecisaoInvalida(ValueError):
    """Arquivo de decisões incoerente sozinho ou com o corpus."""


@dataclass(frozen=True)
class ArquivoDoCorpus:
    caminho: str
    stem: str     # nome do .txt sem extensão, já renomeado
    projeto: str  # PROJECT: do cabeçalho, já renomeado


class Decisoes:
    def __init__(self, excluidos, renomes, outputs_fora):
        self.excluidos = frozenset(excluidos)
        self.renomes = dict(renomes)  # nome no corpus -> nome publicado
        self._chaves_fora = frozenset(outputs_fora)
        # chave = nome PUBLICADO: quem pergunta (o publish) já trabalha com o nome renomeado
        self._outputs_fora = {self.nome(k): tuple(p.upper() for p in v)
                              for k, v in outputs_fora.items()}

    def chaves(self):
        """Nomes do corpus que alguma decisão cita."""
        return set(self.excluidos) | set(self.renomes) | set(self._chaves_fora)

    def nome(self, projeto):
        """Nome publicado do EGP do corpus; None se ele foi excluído."""
        if projeto in self.excluidos:
            return None
        return self.renomes.get(projeto, projeto)

    def nomes_proibidos(self):
        """Nomes do corpus que não podem aparecer num relatório gerado COM as decisões:
        excluídos e origens de renome, menos os que voltam como alvo de um renome (o CPF
        `__v2` pequeno é excluído, mas `__v2` é o nome que o v1 passa a ter)."""
        return (set(self.excluidos) | set(self.renomes)) - set(self.renomes.values())

    def outputs_fora(self):
        """{nome publicado: prefixos (maiúsculos)}: quem aplica confere se cada um achou output."""
        return dict(self._outputs_fora)

    def output_no_escopo(self, projeto, artefato):
        """False se uma decisão tira este output (do EGP já renomeado) do escopo."""
        return not (artefato or "").upper().startswith(self._outputs_fora.get(projeto, ()))


def carrega(path=PADRAO):
    if not os.path.exists(path):
        raise DecisaoInvalida(
            f"{path} não existe. Sem ele, as duplicatas removidas e o renome do "
            f"CPF_Contrato voltam no próximo publish.")
    problemas, linhas = [], []
    try:
        # utf-8-sig: Excel salva CSV UTF-8 com BOM, e o cabeçalho tem de casar mesmo assim
        with open(path, newline="", encoding="utf-8-sig") as f:
            leitor = csv.DictReader(f)
            if leitor.fieldnames != COLUNAS:
                raise DecisaoInvalida(f"{path}: cabeçalho {leitor.fieldnames}, esperado {COLUNAS}")
            for r in leitor:
                if None in r:  # vírgula sem aspas no motivo: o csv põe o excesso sob a chave None
                    problemas.append(f"linha {leitor.line_num}: colunas a mais "
                                     f"(vírgula sem aspas no motivo?)")
                    continue
                if any("\n" in v for v in r.values() if v):  # aspas sem fechar engolem as linhas seguintes
                    problemas.append(f"linha {leitor.line_num}: quebra de linha dentro de um "
                                     f"campo (aspas sem fechar?)")
                    continue
                linhas.append((leitor.line_num, {k: (v or "").strip() for k, v in r.items()}))
    except UnicodeDecodeError as e:
        raise DecisaoInvalida(f"{path}: não é UTF-8 ({e})") from e

    excluidos, renomes, fora = set(), {}, {}
    for i, r in linhas:
        chave, acao, alvo = r["egp_key"], r["acao"], r["alvo"]
        if not chave:
            problemas.append(f"linha {i}: egp_key vazio")
            continue
        if not r["motivo"]:
            problemas.append(f"linha {i} ({chave}): sem motivo")
        if acao == "excluir":
            if alvo:
                problemas.append(f"linha {i} ({chave}): excluir não leva alvo")
            if chave in excluidos:
                problemas.append(f"linha {i} ({chave}): excluído duas vezes")
            excluidos.add(chave)
        elif acao == "renomear":
            if not alvo:
                problemas.append(f"linha {i} ({chave}): renomear sem alvo")
            elif chave in renomes:
                problemas.append(f"linha {i} ({chave}): renomeado duas vezes")
            else:
                renomes[chave] = alvo
        elif acao == "tirar_output_do_escopo":
            if not alvo:
                problemas.append(f"linha {i} ({chave}): tirar_output_do_escopo sem alvo")
            else:
                fora.setdefault(chave, []).append(alvo)
        else:
            problemas.append(f"linha {i} ({chave}): ação '{acao}' desconhecida "
                             f"(use {', '.join(ACOES)})")

    for chave in sorted(excluidos & set(renomes)):
        problemas.append(f"{chave}: excluído e renomeado ao mesmo tempo")
    for chave in sorted(excluidos & set(fora)):
        problemas.append(f"{chave}: tira output do escopo de um EGP excluído")
    for chave, alvo in sorted(renomes.items()):
        if alvo == chave:
            problemas.append(f"{chave}: renomeado para o próprio nome")
        elif alvo in renomes:
            # cadeia (A->B, B->C) ou troca (A<->B): nome() deixaria de ser estável e a troca
            # zeraria nomes_proibidos(), desligando a recusa de CSV velho no publish
            problemas.append(f"{chave} -> {alvo}: o alvo também é renomeado "
                             f"(cadeia ou troca de nomes)")
    alvos = list(renomes.values())
    for alvo in sorted({a for a in alvos if alvos.count(a) > 1}):
        problemas.append(f"{alvo}: alvo de mais de um renome")
    if problemas:
        raise DecisaoInvalida(f"{path}:\n  " + "\n  ".join(problemas))

    return Decisoes(excluidos, renomes, fora)


def projeto_do_cabecalho(caminho):
    """O último PROJECT: antes do END_METADATA (como o parse_txt_metadata do orquestrador);
    "UNKNOWN" sem ele."""
    projeto = "UNKNOWN"
    with open(caminho, encoding="utf-8", errors="ignore") as f:
        for linha in f:
            if "END_METADATA" in linha:
                break
            linha = linha.strip()
            if linha.startswith("PROJECT:"):
                projeto = linha.split("PROJECT:", 1)[1].strip()
    return projeto


def aplica_ao_corpus(txt_dir, decisoes):
    """Os .txt do corpus que entram, com o nome publicado. Confere as decisões contra o
    corpus antes: chave que não existe é decisão órfã (erro de digitação ou .txt apagado),
    e renome para um nome que outro EGP mantido já usa juntaria os dois em silêncio (o
    orquestrador une projetos de mesmo nome)."""
    lidos = []
    for nome in sorted(os.listdir(txt_dir)):
        if nome.lower().endswith(".txt"):
            caminho = os.path.join(txt_dir, nome)
            lidos.append((caminho, nome[:-4], projeto_do_cabecalho(caminho)))
    no_corpus = {p for _, _, p in lidos}

    problemas = []
    for chave in sorted(decisoes.chaves() - no_corpus):
        problemas.append(f"{chave}: não está no corpus ({txt_dir}); remova a decisão "
                         f"ou restaure o .txt")
    mantidos = no_corpus - decisoes.excluidos - set(decisoes.renomes)
    # o nome novo também vira stem, e os leitores do publish chaveados por stem juntariam os dois
    stems_mantidos = {stem for _, stem, projeto in lidos if projeto in mantidos}
    for origem, alvo in sorted(decisoes.renomes.items()):
        if alvo in mantidos or alvo in stems_mantidos:
            problemas.append(f"{origem} -> {alvo}: já existe um EGP {alvo} mantido no "
                             f"corpus (nome ou .txt); exclua-o ou escolha outro nome")
    for _, stem, projeto in lidos:
        if projeto in decisoes.renomes and stem != projeto:
            problemas.append(f"{projeto}: renomear só vale para EGP de um .txt com o mesmo "
                             f"nome do projeto (este vem de {stem}.txt)")
    if problemas:
        raise DecisaoInvalida("decisões incoerentes com o corpus:\n  " + "\n  ".join(problemas))

    saida = []
    for caminho, stem, projeto in lidos:
        novo = decisoes.nome(projeto)
        if novo is None:
            continue
        saida.append(ArquivoDoCorpus(caminho, novo if projeto in decisoes.renomes else stem, novo))
    return saida
