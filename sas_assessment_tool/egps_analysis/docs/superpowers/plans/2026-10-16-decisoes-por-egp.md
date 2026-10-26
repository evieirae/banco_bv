# Decisões por EGP (`src/egps_decisoes.csv`) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** remover duplicata e renomear EGP passam a ser uma linha versionada, com motivo, que o orquestrador e o publish aplicam na leitura do corpus. Assim o publish para de desfazer essas decisões.

**Architecture:** um módulo puro, `egps_analysis/egp_decisoes.py`, lê `src/egps_decisoes.csv` e devolve o corpus filtrado: sem os excluídos e com o nome publicado. O orquestrador gera os CSVs 01–08 a partir desse corpus. O publish usa o mesmo corpus nos três leitores que vão direto ao `text_egps/` (libmap, NON_CREATOR, LOC), aplica o renome ao `indi_231`, corta do escopo os outputs marcados e recusa CSVs gerados sem as decisões. Decisão órfã ou incoerente para o processo antes de qualquer escrita.

**Tech Stack:** Python 3.12 (stdlib: `csv`, `dataclasses`), pytest. Nada novo no `requirements.txt`.

---

## Contexto (decisão Q10 de 16/10/2026)

- **Por que existe.** O orquestrador lê `text_egps/` inteiro e o publish é full replace nas tabelas do corpus. Toda decisão tomada direto no banco volta no publish seguinte. Medido em prod em 16/10 (só leitura):
  - as **11 duplicatas** removidas à mão em agosto e setembro estavam **todas de volta**, cada uma com 1 nó e de 1 a 36 pares;
  - o renome do `Cobranças__CPF_Contrato` (v1 → `__v2`, D013) era refeito à mão depois de cada publish, com `reaplica_rename_cpf_contrato_pos_publish.py`: 5 vezes na auditoria (31/08, 18/09, 02/10, 13/10 e 14/10).
- **Decisão do usuário** (rodada Q10–Q14): arquivo versionado lido pelo **orquestrador** (opção b), numa branch à parte saindo da develop, antes da 2b. Assim o publish por CLI de prod já sai certo. A 2b herda o arquivo: ele vai no pacote, e a trava da Q12 o confere.
- **Carga inicial** (14 linhas). O CSV da revisão de 21/09 se perdeu; a carga saiu de `sas_pipeline_audit` com `campo='remocao'` em prod:
  - as 10 remoções auditadas;
  - o `Jurídico__1351-SAS_v20201209_V2`, removido em 18/08 sem auditoria (memória `egps-duplicados-cross-area-sem-trava`);
  - as 3 linhas do CPF: excluir o `__v2` pequeno, renomear o v1 e tirar do escopo os 4 outputs `CARNEIRO.BASE_3040_*`.
  - Os 13 EGPs citados existem em `text_egps/`, com stem igual ao `PROJECT:`.
- **Limite conhecido (fica para a 2b).** O `recompute_escopo` do app (`app/backend/main.py:4333`) refaz `escopo_indi` de `sas_egp_outputs` e `sas_outputs_monitor` a cada edição de escopo na tela, e o app não lê este arquivo. Por isso o corte dos 4 `BASE_3040` dura até a próxima edição de escopo. É o comportamento de hoje, só que sem o script manual. Na 2b, o pacote leva o arquivo, o app o guarda (Q12) e o recompute passa a respeitar o corte.

## Convenções

- **Worktree da branch** `feat/egp-decisions-file` (criada de `origin/develop` em `3e6ab7d8`):
  - `W` = `/tmp/claude-1000/-home-lucasmuller-ind-bv-sas-assessment-tool/c576032b-5e2b-4b43-835c-3ecb0c933eb9/scratchpad/q10`
- **Python:** o venv do checkout principal, porque o worktree não tem venv.
  - `PY` = `/home/lucasmuller_ind/bv/sas_assessment_tool/egps_analysis/venv/bin/python`
- **Scripts de comparação:** ficam fora do repo.
  - `S` = `/tmp/claude-1000/-home-lucasmuller-ind-bv-sas-assessment-tool/c576032b-5e2b-4b43-835c-3ecb0c933eb9/scratchpad/q10-saidas`
- Nos comandos, substitua `W`, `PY` e `S` pelo caminho literal. Um comando por chamada, sem `&&`, `;` nem heredoc.
- **Git:**
  - sempre `/usr/bin/git -C <W> ...`;
  - commits em português, **sem** `Co-Authored-By`;
  - commit e push só com pedido do usuário. Até lá, o passo "Commit" de cada task vira só o `git add` (stage), e as mensagens ficam prontas para quando ele pedir.
- **Preview do dry-run:** o publish em dry-run reescreve `egps_analysis/docs/analises/publish_databricks.preview.sql`, que é versionado. Depois de cada dry-run, restaure com `/usr/bin/git -C <W> checkout -- egps_analysis/docs/analises/publish_databricks.preview.sql`.
- **Escritas no Databricks** (dev ou prod) **só com consentimento explícito do usuário em cada vez** (Task 7).

## Mapa de arquivos

| Arquivo | O quê |
|---|---|
| `egps_analysis/egp_decisoes.py` (novo) | Lê e valida o CSV; `Decisoes.nome()`, `nomes_proibidos()`, `output_no_escopo()`; `aplica_ao_corpus()` devolve os `.txt` que entram, com o nome publicado. |
| `egps_analysis/test_egp_decisoes.py` (novo) | Testes do módulo, do arquivo versionado e dos dois pontos do publish. |
| `egps_analysis/src/egps_decisoes.csv` (novo) | As 14 decisões. |
| `egps_analysis/orchestrator_inventory.py` | `main()` e `gerar_arestas_arquivo()` iteram o corpus filtrado. |
| `egps_analysis/publish_to_databricks.py` | Os leitores do corpus recebem o corpus filtrado; `indi_231` renomeado; guarda de CSV velho; corte dos outputs; `main()` aborta antes de escrever. |
| `egps_analysis/01…06, 08 *.csv` | Regenerados com as decisões (Task 5). |
| `egps_analysis/docs/PIPELINE_INVENTARIO_MIGRACAO_SAS.md`, `CLAUDE.md`, `docs/analises/reaplica_rename_cpf_contrato_pos_publish.py`, `rename_cpf_contrato_v1_para_v2.py`, `repara_escopo_indi_cpf_contrato.py` | Documentação e avisos de obsoleto (Task 6). |
| `bitbucket-pipelines.yml` | `test_egp_decisoes.py` no gate de testes do CI (Task 6, Step 3b). |

---

### Task 1: Módulo `egp_decisoes.py`

**Files:**
- Create: `egps_analysis/egp_decisoes.py`
- Test: `egps_analysis/test_egp_decisoes.py`

- [ ] **Step 1: Escreva os testes**

`egps_analysis/test_egp_decisoes.py`:

```python
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Decisões por EGP (src/egps_decisoes.csv): o que o corpus não sabe e o publish desfazia.

Medido em 16/10/2026: as 11 duplicatas removidas à mão estavam todas de volta em prod, e o
renome do CPF_Contrato era refeito à mão a cada publish. Estes testes travam as duas
promessas do módulo: a decisão vale na leitura do corpus, e decisão que não se aplica
(órfã, conflitante) para o processo em vez de sumir.

Roda como:
    egps_analysis/venv/bin/python -m pytest egps_analysis/test_egp_decisoes.py -q
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import egp_decisoes as dec  # noqa: E402

CAB = "egp_key,acao,alvo,motivo,data,quem\n"


def _csv(tmp_path, linhas, cab=CAB):
    p = tmp_path / "egps_decisoes.csv"
    p.write_text(cab + "".join(linhas), encoding="utf-8")
    return str(p)


def _corpus(tmp_path, arquivos):
    """arquivos = {stem: projeto do cabeçalho}"""
    d = tmp_path / "text_egps"
    d.mkdir()
    for stem, projeto in arquivos.items():
        (d / f"{stem}.txt").write_text(
            f"PROJECT: {projeto}\nLINES_OF_CODE: 10\nEND_METADATA\ncorpo\n", encoding="utf-8")
    return str(d)


# ---------------------------------------------------------------- carrega

def test_arquivo_ausente_para_o_processo(tmp_path):
    with pytest.raises(dec.DecisaoInvalida, match="não existe"):
        dec.carrega(str(tmp_path / "nao_existe.csv"))


def test_cabecalho_errado_para_o_processo(tmp_path):
    path = _csv(tmp_path, [], cab="egp,acao\n")
    with pytest.raises(dec.DecisaoInvalida, match="cabeçalho"):
        dec.carrega(path)


def test_excluir_e_renomear(tmp_path):
    path = _csv(tmp_path, [
        "A__dup,excluir,,duplicata de A__orig,2026-09-21,x\n",
        "A__v1,renomear,A__v2,D013,2026-08-24,x\n",
    ])
    d = dec.carrega(path)
    assert d.nome("A__dup") is None
    assert d.nome("A__v1") == "A__v2"
    assert d.nome("A__outro") == "A__outro"
    assert d.nomes_proibidos() == {"A__dup", "A__v1"}


def test_cpf_alvo_do_renome_e_o_nome_do_excluido(tmp_path):
    """O caso real: o `__v2` pequeno sai e o v1 passa a se chamar `__v2`. O nome `__v2`
    sai das proibições, porque é o nome que o v1 publica."""
    path = _csv(tmp_path, [
        "C__CPF__v2,excluir,,outro projeto,2026-08-24,x\n",
        "C__CPF,renomear,C__CPF__v2,D013,2026-08-24,x\n",
    ])
    d = dec.carrega(path)
    assert d.nome("C__CPF__v2") is None
    assert d.nome("C__CPF") == "C__CPF__v2"
    assert d.nomes_proibidos() == {"C__CPF"}


@pytest.mark.parametrize("linhas,trecho", [
    (["A,excluir,,,2026-01-01,x\n"], "sem motivo"),
    (["A,excluir,B,m,2026-01-01,x\n"], "não leva alvo"),
    (["A,renomear,,m,2026-01-01,x\n"], "renomear sem alvo"),
    (["A,tirar_output_do_escopo,,m,2026-01-01,x\n"], "sem alvo"),
    (["A,apagar,,m,2026-01-01,x\n"], "desconhecida"),
    ([",excluir,,m,2026-01-01,x\n"], "egp_key vazio"),
    (["A,excluir,,m,2026-01-01,x\n", "A,excluir,,m,2026-01-01,x\n"], "excluído duas vezes"),
    (["A,renomear,B,m,2026-01-01,x\n", "A,renomear,C,m,2026-01-01,x\n"], "renomeado duas vezes"),
    (["A,excluir,,m,2026-01-01,x\n", "A,renomear,B,m,2026-01-01,x\n"], "excluído e renomeado"),
    (["A,excluir,,m,2026-01-01,x\n", "A,tirar_output_do_escopo,LIB.T,m,2026-01-01,x\n"],
     "EGP excluído"),
    (["A,renomear,Z,m,2026-01-01,x\n", "B,renomear,Z,m,2026-01-01,x\n"], "mais de um renome"),
    (["A,excluir,,duplicata de X, revisão,2026-09-21,x\n"], "colunas a mais"),
    (["A,renomear,A,m,2026-01-01,x\n"], "próprio nome"),
    (["A,renomear,B,m,2026-01-01,x\n", "B,renomear,C,m,2026-01-01,x\n"], "o alvo também é renomeado"),
    (['A,excluir,,"duplicata, revisão,2026-09-21,x\n', "B,excluir,,m,2026-09-21,x\n"],
     "aspas sem fechar"),
])
def test_arquivo_incoerente_para_o_processo(tmp_path, linhas, trecho):
    with pytest.raises(dec.DecisaoInvalida, match=trecho):
        dec.carrega(_csv(tmp_path, linhas))


def test_arquivo_fora_de_utf8_para_o_processo(tmp_path):
    p = tmp_path / "egps_decisoes.csv"
    p.write_bytes((CAB + "A,excluir,,revisão,2026-01-01,x\n").encode("cp1252"))
    with pytest.raises(dec.DecisaoInvalida, match="não é UTF-8"):
        dec.carrega(str(p))


def test_erro_aponta_a_linha_fisica(tmp_path):
    """Linha em branco no meio não desloca o número que a mensagem mostra."""
    with pytest.raises(dec.DecisaoInvalida, match=r"linha 3 \(A\): sem motivo"):
        dec.carrega(_csv(tmp_path, ["\n", "A,excluir,,,2026-01-01,x\n"]))


def test_arquivo_salvo_com_bom_e_aceito(tmp_path):
    """Excel salva CSV UTF-8 com BOM; o cabeçalho tem de casar mesmo assim."""
    d = dec.carrega(_csv(tmp_path, ["A,excluir,,duplicata,2026-01-01,x\n"], cab="\ufeff" + CAB))
    assert d.nome("A") is None


def test_output_fora_do_escopo_vale_pelo_nome_publicado(tmp_path):
    """A decisão cita o nome do corpus; o publish pergunta pelo nome já renomeado."""
    path = _csv(tmp_path, [
        "C__CPF,renomear,C__CPF__v2,D013,2026-08-24,x\n",
        "C__CPF,tirar_output_do_escopo,CARNEIRO.BASE_3040,D013,2026-08-24,x\n",
    ])
    d = dec.carrega(path)
    assert d.output_no_escopo("C__CPF__v2", "CARNEIRO.BASE_3040_202509") is False
    assert d.output_no_escopo("C__CPF__v2", "carneiro.base_3040_202510") is False
    assert d.output_no_escopo("C__CPF__v2", "CARNEIRO.OUTRA") is True
    assert d.output_no_escopo("C__OUTRO", "CARNEIRO.BASE_3040_202509") is True
    assert d.outputs_fora() == {"C__CPF__v2": ("CARNEIRO.BASE_3040",)}


# ---------------------------------------------------------------- aplica_ao_corpus

def test_cabecalho_vale_o_ultimo_project_como_no_orquestrador(tmp_path):
    """parse_txt_metadata do orquestrador fica com o último PROJECT: antes do END_METADATA;
    o nome publicado tem de ser o mesmo, senão a decisão e o relatório falam de EGPs diferentes."""
    d = tmp_path / "text_egps"
    d.mkdir()
    (d / "X.txt").write_text("PROJECT: X_velho\nPROJECT: X\nEND_METADATA\nPROJECT: Y\n",
                             encoding="utf-8")
    assert dec.projeto_do_cabecalho(str(d / "X.txt")) == "X"


def test_corpus_sai_sem_excluido_e_com_renome(tmp_path):
    txt = _corpus(tmp_path, {"C__CPF": "C__CPF", "C__CPF__v2": "C__CPF__v2",
                             "A__dup": "A__dup", "A__orig": "A__orig"})
    d = dec.carrega(_csv(tmp_path, [
        "C__CPF__v2,excluir,,outro projeto,2026-08-24,x\n",
        "C__CPF,renomear,C__CPF__v2,D013,2026-08-24,x\n",
        "A__dup,excluir,,duplicata,2026-09-21,x\n",
    ]))
    saida = dec.aplica_ao_corpus(txt, d)
    assert [(os.path.basename(a.caminho), a.stem, a.projeto) for a in saida] == [
        ("A__orig.txt", "A__orig", "A__orig"),
        ("C__CPF.txt", "C__CPF__v2", "C__CPF__v2"),
    ]


def test_parte_de_projeto_multiarquivo_e_excluida_junto(tmp_path):
    """Exclusão é pelo PROJECT: do cabeçalho, então pega todas as partes do projeto."""
    txt = _corpus(tmp_path, {"R__proj__01": "R__proj", "R__proj__02": "R__proj", "R__x": "R__x"})
    d = dec.carrega(_csv(tmp_path, ["R__proj,excluir,,teste,2026-01-01,x\n"]))
    assert [a.projeto for a in dec.aplica_ao_corpus(txt, d)] == ["R__x"]


@pytest.mark.parametrize("linha", [
    "A__dupp,excluir,,duplicata,2026-09-21,x\n",
    "A__v11,renomear,A__v2,D013,2026-08-24,x\n",
    "A__v11,tirar_output_do_escopo,LIB.T,D013,2026-08-24,x\n",
])
def test_decisao_orfa_para_o_processo(tmp_path, linha):
    """Erro de digitação ou .txt apagado: a decisão não se aplicaria e a duplicata (ou o
    renome) voltaria calada. Vale para as três ações."""
    txt = _corpus(tmp_path, {"A__orig": "A__orig"})
    d = dec.carrega(_csv(tmp_path, [linha]))
    with pytest.raises(dec.DecisaoInvalida, match="não está no corpus"):
        dec.aplica_ao_corpus(txt, d)


def test_renome_para_nome_de_egp_mantido_para_o_processo(tmp_path):
    """O orquestrador une projetos de mesmo nome: o renome juntaria dois EGPs em silêncio."""
    txt = _corpus(tmp_path, {"A": "A", "B": "B"})
    d = dec.carrega(_csv(tmp_path, ["A,renomear,B,m,2026-01-01,x\n"]))
    with pytest.raises(dec.DecisaoInvalida, match="já existe um EGP B"):
        dec.aplica_ao_corpus(txt, d)


def test_renome_para_stem_de_txt_mantido_para_o_processo(tmp_path):
    """Os leitores do publish chaveados por stem juntariam os dois .txt."""
    txt = _corpus(tmp_path, {"03-X": "SAS_UC4__03-X", "A": "A"})
    d = dec.carrega(_csv(tmp_path, ["A,renomear,03-X,m,2026-01-01,x\n"]))
    with pytest.raises(dec.DecisaoInvalida, match="já existe um EGP 03-X"):
        dec.aplica_ao_corpus(txt, d)


def test_renome_de_egp_com_stem_diferente_do_projeto_para_o_processo(tmp_path):
    """Os leitores por stem não saberiam o nome novo: só renomeia EGP cujo .txt tem o nome do projeto."""
    txt = _corpus(tmp_path, {"R__proj__01": "R__proj"})
    d = dec.carrega(_csv(tmp_path, ["R__proj,renomear,R__novo,m,2026-01-01,x\n"]))
    with pytest.raises(dec.DecisaoInvalida, match="mesmo nome do projeto"):
        dec.aplica_ao_corpus(txt, d)
```

- [ ] **Step 2: Rode e veja falhar**

Run: `PY -m pytest W/egps_analysis/test_egp_decisoes.py -q -p no:cacheprovider`
Expected: erro de coleta `ModuleNotFoundError: No module named 'egp_decisoes'`.

- [ ] **Step 3: Escreva o módulo**

`egps_analysis/egp_decisoes.py`:

```python
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
```

- [ ] **Step 4: Rode e veja passar**

Run: `PY -m pytest W/egps_analysis/test_egp_decisoes.py -q -p no:cacheprovider`
Expected: `32 passed`.

- [ ] **Step 5: Commit**

```bash
/usr/bin/git -C W add egps_analysis/egp_decisoes.py egps_analysis/test_egp_decisoes.py
/usr/bin/git -C W commit -m "feat(egps): módulo de decisões por EGP aplicadas na leitura do corpus"
```

---

### Task 2: As 14 decisões em `src/egps_decisoes.csv`

**Files:**
- Create: `egps_analysis/src/egps_decisoes.csv`
- Test: `egps_analysis/test_egp_decisoes.py` (acrescentar no fim)

- [ ] **Step 1: Acrescente o teste do arquivo versionado** no fim de `test_egp_decisoes.py`:

```python
# ---------------------------------------------------------------- o arquivo versionado

def test_arquivo_versionado_bate_com_o_corpus_versionado():
    """O src/egps_decisoes.csv do repo carrega e se aplica ao text_egps/ do repo."""
    base = os.path.dirname(os.path.abspath(__file__))
    d = dec.carrega()
    saida = dec.aplica_ao_corpus(os.path.join(base, "text_egps"), d)
    projetos = {a.projeto for a in saida}
    assert "Cobranças__CPF_Contrato" not in projetos
    assert "Cobranças__CPF_Contrato__v2" in projetos
    assert "Cobranças__Envio SMS - Pagamentos - Cartão Amigável__v2" not in projetos
    assert "Cobranças__Envio SMS - Pagamentos - Cartão Amigável" in projetos
```

- [ ] **Step 2: Rode e veja falhar**

Run: `PY -m pytest W/egps_analysis/test_egp_decisoes.py -q -p no:cacheprovider`
Expected: 1 failed, com `DecisaoInvalida: .../src/egps_decisoes.csv não existe`.

- [ ] **Step 3: Escreva o arquivo** `egps_analysis/src/egps_decisoes.csv` (UTF-8, sem BOM):

```csv
egp_key,acao,alvo,motivo,data,quem
Cobranças__CPF_Contrato__v2,excluir,,"Outro projeto com o mesmo nome (similaridade 0,025); o nome __v2 passa para o v1 (D013 em docs/analises/RELATORIO_VERSOES_EGPS_2026-08-13.md)",2026-08-24,lucas.muller@indicium.tech
Cobranças__CPF_Contrato,renomear,Cobranças__CPF_Contrato__v2,O v1 é migrado sem a base 3040 com o nome v2 (D013),2026-08-24,lucas.muller@indicium.tech
Cobranças__CPF_Contrato,tirar_output_do_escopo,CARNEIRO.BASE_3040,v2 = v1 sem a base 3040: os outputs BASE_3040 não entram na migração (D013),2026-08-24,lucas.muller@indicium.tech
Cobranças__Envio SMS - Pagamentos - Cartão Amigável__v2,excluir,,Duplicata byte-idêntica de Cobranças__Envio SMS - Pagamentos - Cartão Amigável; o consumidor foi re-apontado para o original,2026-08-10,lucas.muller@indicium.tech
Teste EGPs__Consignado_PF_INSS v7 2,excluir,,Duplicata byte a byte (sha256 igual); revisão de duplicados do escopo de 21/09,2026-09-21,lucas.muller@indicium.tech
Cobranças__PROJECT_LINHAS_QIKVIEW_V5_RPA (1),excluir,,Duplicata byte a byte (sha256 igual); revisão de duplicados do escopo de 21/09,2026-09-21,lucas.muller@indicium.tech
Teste EGPs__CobrancaAcima120dias_v15_GCP 2,excluir,,Duplicata byte a byte (sha256 igual); revisão de duplicados do escopo de 21/09,2026-09-21,lucas.muller@indicium.tech
Teste EGPs__ativa 2,excluir,,Duplicata byte a byte (sha256 igual); revisão de duplicados do escopo de 21/09,2026-09-21,lucas.muller@indicium.tech
Cartões__Processo de bonificação - taxas_v35 (2),excluir,,Duplicata byte a byte (sha256 igual); revisão de duplicados do escopo de 21/09,2026-09-21,lucas.muller@indicium.tech
Cobranças__COLCHAO_ACORDO_CL__v2,excluir,,Duplicata byte a byte (sha256 igual); revisão de duplicados do escopo de 21/09,2026-09-21,lucas.muller@indicium.tech
Riscos__SAS_IQ_V001,excluir,,Duplicata byte a byte (sha256 igual); revisão de duplicados do escopo de 21/09,2026-09-21,lucas.muller@indicium.tech
Finanças__Gastos_PE,excluir,,Duplicata byte a byte (sha256 igual); revisão de duplicados do escopo de 21/09,2026-09-21,lucas.muller@indicium.tech
Cobranças__Rastreador_v8_corr_tb_taylor,excluir,,"Código idêntico ao Cobranças__Rastreador_v8_corr_tb_taylor_vf, fora do escopo e das dependências (revisão de duplicados, grupo G9)",2026-09-22,lucas.muller@indicium.tech
Jurídico__1351-SAS_v20201209_V2,excluir,,"Gêmeo entre áreas de Riscos__1351-SAS_v20201209_V2, que é o canônico (linha em sas_escopo, jira UDAA-4837) e alimenta os mesmos 4 EGPs de Cobranças",2026-08-18,lucas.muller@indicium.tech
```

- [ ] **Step 4: Rode e veja passar**

Run: `PY -m pytest W/egps_analysis/test_egp_decisoes.py -q -p no:cacheprovider`
Expected: `33 passed`.

- [ ] **Step 5: Commit**

```bash
/usr/bin/git -C W add egps_analysis/src/egps_decisoes.csv egps_analysis/test_egp_decisoes.py
/usr/bin/git -C W commit -m "feat(egps): as 14 decisões por EGP (11 duplicatas e o CPF_Contrato) no arquivo versionado"
```

---

### Task 3: O orquestrador lê o corpus pelas decisões

**Files:**
- Modify: `egps_analysis/orchestrator_inventory.py` (imports; constantes perto da linha 57; `main()` perto das linhas 772 e 853; `gerar_arestas_arquivo()` perto das linhas 1490 e 1500)

- [ ] **Step 1: Import.** Logo depois de `from libname_resolver import parse_libmap_from_txt`, acrescente:

```python
import egp_decisoes
```

- [ ] **Step 2: Constante.** Troque

```python
MODERN_OVERRIDE_CSV_PATH = r'./src/inputs_modernizados.csv'
REPMAP_XLSX_PATH = r'./src/RepMap.xlsx'
```

por

```python
MODERN_OVERRIDE_CSV_PATH = r'./src/inputs_modernizados.csv'
# Decisões por EGP (excluir duplicata, renomear): valem na leitura do corpus, antes de
# qualquer relatório. Ver egp_decisoes.py.
DECISOES_CSV_PATH = r'./src/egps_decisoes.csv'
REPMAP_XLSX_PATH = r'./src/RepMap.xlsx'
```

- [ ] **Step 3: Listagem do corpus em `main()`.** Troque

```python
    txt_files = sorted(f for f in os.listdir(INPUT_FOLDER) if f.lower().endswith('.txt'))
    if not txt_files:
        print(f"Nenhum arquivo .txt encontrado em '{INPUT_FOLDER}'.")
        return

    print(f"🔍 Analisando {len(txt_files)} projetos...")
```

por

```python
    try:
        decisoes = egp_decisoes.carrega(DECISOES_CSV_PATH)
        corpus = egp_decisoes.aplica_ao_corpus(INPUT_FOLDER, decisoes)
    except egp_decisoes.DecisaoInvalida as e:
        print(f"\n❌ ABORTADO: {e}")
        sys.exit(2)
    if not corpus:
        print(f"Nenhum arquivo .txt encontrado em '{INPUT_FOLDER}'.")
        return

    print(f"🔍 Analisando {len(corpus)} projetos...")
    print(f"  decisões por EGP: {len(decisoes.excluidos)} excluídos, "
          f"{len(decisoes.renomes)} renomeados ({DECISOES_CSV_PATH})")
```

- [ ] **Step 4: Laço dos `.txt` em `main()`.** Troque

```python
    for filename in txt_files:
        filepath = os.path.join(INPUT_FOLDER, filename)
        p_data = parse_txt_metadata(filepath)
        p_data['libmap'] = parse_libmap_from_txt(filepath)
```

por

```python
    for arq in corpus:
        filepath = arq.caminho
        filename = os.path.basename(filepath)
        p_data = parse_txt_metadata(filepath)
        p_data['project'] = arq.projeto  # nome publicado (egp_decisoes)
        p_data['libmap'] = parse_libmap_from_txt(filepath)
```

- [ ] **Step 5: Relatório 08.** Troque a chamada `n8, d8 = gerar_arestas_arquivo()` por `n8, d8 = gerar_arestas_arquivo(corpus)`. Na função, troque

```python
def gerar_arestas_arquivo():
    """Arestas EGP→EGP via arquivo exportado/importado, casadas por esqueleto de
    macro (macro_file_refs). Níveis: 1 = dir resolvido igual + esqueleto confiável;
    2 = esqueleto confiável, dir irresolvível em ≥1 lado; 3 = esqueleto genérico
    (guarda anti-REGRAS). Dirs resolvidos e CONFLITANTES nunca casam (cópias em
    pastas distintas são arquivos distintos). Fan-out >10 rebaixa p/ nível 3;
    >200 descarta o esqueleto (degenerado). 100% aditivo: só escreve o 08."""
    import glob as _glob
    from macro_file_refs import file_refs_de_arquivo

    outs_por_skel, ins_por_skel = defaultdict(list), defaultdict(list)
    for path in sorted(_glob.glob(os.path.join(INPUT_FOLDER, '*.txt'))):
        projeto = os.path.splitext(os.path.basename(path))[0]
```

por

```python
def gerar_arestas_arquivo(corpus):
    """Arestas EGP→EGP via arquivo exportado/importado, casadas por esqueleto de
    macro (macro_file_refs). Níveis: 1 = dir resolvido igual + esqueleto confiável;
    2 = esqueleto confiável, dir irresolvível em ≥1 lado; 3 = esqueleto genérico
    (guarda anti-REGRAS). Dirs resolvidos e CONFLITANTES nunca casam (cópias em
    pastas distintas são arquivos distintos). Fan-out >10 rebaixa p/ nível 3;
    >200 descarta o esqueleto (degenerado). 100% aditivo: só escreve o 08.
    `corpus` = egp_decisoes.aplica_ao_corpus (já sem os excluídos)."""
    from macro_file_refs import file_refs_de_arquivo

    outs_por_skel, ins_por_skel = defaultdict(list), defaultdict(list)
    for arq in corpus:
        path, projeto = arq.caminho, arq.stem
```

- [ ] **Step 6: Prova de neutralidade** (sem decisões, os relatórios não mudam nada):
  1. Reescreva `egps_analysis/src/egps_decisoes.csv` só com o cabeçalho (`egp_key,acao,alvo,motivo,data,quem`).
  2. Rode `env -C W/egps_analysis PY orchestrator_inventory.py`. Expected: `Analisando 1817 projetos...` e `decisões por EGP: 0 excluídos, 0 renomeados`.
  3. Rode `/usr/bin/git -C W status --short`. Expected: só `M egps_analysis/orchestrator_inventory.py` e `M egps_analysis/src/egps_decisoes.csv`. Nenhum CSV 01–08 muda: medido no rascunho, os sete saem iguais byte a byte aos da develop.
  4. Restaure o arquivo: `/usr/bin/git -C W checkout -- egps_analysis/src/egps_decisoes.csv`.

- [ ] **Step 7: Prova de recusa.** Troque `Riscos__SAS_IQ_V001` por `Riscos__SAS_IQ_V00X` no CSV e rode o orquestrador. Expected: exit 2 com `❌ ABORTADO: decisões incoerentes com o corpus: … Riscos__SAS_IQ_V00X: não está no corpus`. Restaure o CSV com `git checkout --` como no Step 6.

- [ ] **Step 8: Suíte**

Run: `PY -m pytest W/egps_analysis --ignore=W/egps_analysis/app -q -p no:cacheprovider`
Expected: `164 passed` (131 da develop + 33).

- [ ] **Step 9: Commit** (só o código; os CSVs regenerados entram na Task 5)

```bash
/usr/bin/git -C W add egps_analysis/orchestrator_inventory.py
/usr/bin/git -C W commit -m "feat(egps): orquestrador lê o corpus já com as decisões por EGP"
```

---

### Task 4: O publish aplica as decisões

**Files:**
- Modify: `egps_analysis/publish_to_databricks.py`
- Test: `egps_analysis/test_egp_decisoes.py` (acrescentar antes da seção do arquivo versionado)

O publish lê o corpus direto em três lugares, todos chaveados por nome: libmap e NON_CREATOR pelo stem, LOC pelo `PROJECT:`. Sem o corpus filtrado, o v1 do CPF (publicado como `__v2`) leria os libnames e o LOC do `__v2` pequeno descartado. O `indi_231` cita o CPF pelo nome antigo (linha 48).

- [ ] **Step 1: Testes.** Antes de `# ---------------------------------------------------------------- o arquivo versionado`, acrescente:

```python
# ---------------------------------------------------------------- no publish

def test_publish_le_o_corpus_pelo_nome_publicado(tmp_path):
    """O LOC do v1 vai para o nome novo e o do `__v2` pequeno descartado não entra. Antes, o nó
    `__v2` mostrava o LOC do arquivo pequeno (106 em vez de 1114)."""
    import publish_to_databricks as pub
    txt = tmp_path / "text_egps"
    txt.mkdir()
    for stem, loc in (("C__CPF", 1114), ("C__CPF__v2", 106)):
        (txt / f"{stem}.txt").write_text(
            f"PROJECT: {stem}\nLINES_OF_CODE: {loc}\nEND_METADATA\n", encoding="utf-8")
    d = dec.carrega(_csv(tmp_path, [
        "C__CPF__v2,excluir,,outro projeto,2026-08-24,x\n",
        "C__CPF,renomear,C__CPF__v2,D013,2026-08-24,x\n",
    ]))
    assert pub.build_loc_tasks(dec.aplica_ao_corpus(str(txt), d)) == {"C__CPF__v2": (1114, 0)}


def test_publish_nome_da_lista_indicium(tmp_path):
    """indi_231 cita o CPF pelo nome antigo (linha 48); quem editar a linha para o nome que o
    app mostra também passa. EGP excluído na lista Indicium é contradição: para."""
    import publish_to_databricks as pub
    d = dec.carrega(_csv(tmp_path, [
        "C__CPF__v2,excluir,,outro projeto,2026-08-24,x\n",
        "C__CPF,renomear,C__CPF__v2,D013,2026-08-24,x\n",
        "A__dup,excluir,,duplicata,2026-09-21,x\n",
    ]))
    assert pub._nome_indi("A__orig", d) == "A__orig"
    assert pub._nome_indi("C__CPF", d) == "C__CPF__v2"
    assert pub._nome_indi("C__CPF__v2", d) == "C__CPF__v2"
    with pytest.raises(dec.DecisaoInvalida, match="lista Indicium"):
        pub._nome_indi("A__dup", d)


def test_publish_recusa_prefixo_de_output_que_nao_acha_nada(tmp_path):
    """Prefixo digitado errado deixaria os outputs no escopo calado: é decisão que não se
    aplica, então para."""
    import publish_to_databricks as pub
    egp_out = {("C__CPF__v2", "CARNEIRO.BASE_3040_202509"):
               {"projeto": "C__CPF__v2", "artifact": "CARNEIRO.BASE_3040_202509"}}
    errado = dec.carrega(_csv(tmp_path, [
        "C__CPF__v2,tirar_output_do_escopo,CARNEIRO.BASE3040,D013,2026-08-24,x\n"]))
    with pytest.raises(dec.DecisaoInvalida,
                       match="nenhum output de C__CPF__v2 começa com CARNEIRO.BASE3040"):
        pub._confere_outputs_fora(errado, egp_out)
    certo = dec.carrega(_csv(tmp_path, [
        "C__CPF__v2,tirar_output_do_escopo,carneiro.base_3040,D013,2026-08-24,x\n"]))
    pub._confere_outputs_fora(certo, egp_out)  # caixa diferente casa; não levanta


CAB06 = "project,artifact,category,area,path,status_validacao,source_type\n"
DEC_CPF = ("egp_key,acao,alvo,motivo,data,quem\n"
           "C__CPF__v2,excluir,,outro projeto,2026-08-24,x\n"
           "C__CPF,renomear,C__CPF__v2,D013,2026-08-24,x\n"
           "C__CPF,tirar_output_do_escopo,CARNEIRO.BASE_3040,D013,2026-08-24,x\n")


def _publish_sobre_fixture(tmp_path, monkeypatch, linhas_06):
    """build() do publish sobre corpus e CSVs mínimos, sem banco: as constantes de caminho
    apontam para tmp_path. O v1 do CPF tem LOC 50 e marca INFO_CONTA como só-contribuição; o
    `__v2` pequeno tem LOC 7."""
    import publish_to_databricks as pub
    txt = tmp_path / "text_egps"
    txt.mkdir()
    (txt / "C__CPF.txt").write_text(
        "PROJECT: C__CPF\nLINES_OF_CODE: 50\nNON_CREATOR_OUTPUTS: CARNEIRO.INFO_CONTA\n"
        "END_METADATA\n", encoding="utf-8")
    (txt / "C__CPF__v2.txt").write_text(
        "PROJECT: C__CPF__v2\nLINES_OF_CODE: 7\nEND_METADATA\n", encoding="utf-8")
    (tmp_path / "dec.csv").write_text(DEC_CPF, encoding="utf-8")
    (tmp_path / "06.csv").write_text(CAB06 + "".join(
        f"{p},{a},{c},Cobranças,,,\n" for p, a, c in linhas_06), encoding="utf-8")
    (tmp_path / "03.csv").write_text("alvo,dep,via,n_produtores\n", encoding="utf-8")
    (tmp_path / "indi.csv").write_text(
        "egp_dor1,area,status_extracao,project_no_06 / observacao\n"
        "cpf,Cobrança,exato,C__CPF\n", encoding="utf-8")
    for nome, val in (("TXT_DIR", str(txt)), ("DECISOES", str(tmp_path / "dec.csv")),
                      ("R06", str(tmp_path / "06.csv")), ("R03", str(tmp_path / "03.csv")),
                      ("R04", str(tmp_path / "nao.csv")), ("INDI", str(tmp_path / "indi.csv")),
                      ("EGPS_CASCA", str(tmp_path / "nao.csv"))):
        monkeypatch.setattr(pub, nome, val)
    return pub


def test_build_aplica_as_decisoes(tmp_path, monkeypatch):
    pub = _publish_sobre_fixture(tmp_path, monkeypatch, [
        ("C__CPF__v2", "CARNEIRO.BASE_3040_202509", "table_out"),
        ("C__CPF__v2", "CARNEIRO.INFO_CONTA", "table_out"),
        ("C__CPF__v2", "LIB.ENTRADA", "table_in"),
    ])
    data = pub.build()
    no = {r["projeto"]: r for r in data["nodes"]}
    assert no["C__CPF__v2"]["loc"] == 50
    assert no["C__CPF__v2"]["escopo_indi"] is True
    out = {r["chave_canonica"]: r["escopo_indi"] for r in data["outputs"]}
    assert out == {"CARNEIRO.BASE_3040_202509": False, "CARNEIRO.INFO_CONTA": True}
    eo = {r["artifact"]: r for r in data["egp_outputs"]}
    assert {a: r["escopo_indi"] for a, r in eo.items()} == {
        "CARNEIRO.BASE_3040_202509": False, "CARNEIRO.INFO_CONTA": True}
    assert eo["CARNEIRO.INFO_CONTA"]["apenas_contribui"] is True
    assert [r["projeto"] for r in data["indicium"]] == ["C__CPF__v2"]


def test_build_recusa_csv_gerado_sem_as_decisoes(tmp_path, monkeypatch):
    pub = _publish_sobre_fixture(tmp_path, monkeypatch, [
        ("C__CPF", "CARNEIRO.BASE_3040_202509", "table_out")])
    with pytest.raises(dec.DecisaoInvalida, match="rode o orchestrator_inventory.py"):
        pub.build()


def test_build_recusa_prefixo_sem_output(tmp_path, monkeypatch):
    pub = _publish_sobre_fixture(tmp_path, monkeypatch, [
        ("C__CPF__v2", "CARNEIRO.INFO_CONTA", "table_out")])
    with pytest.raises(dec.DecisaoInvalida, match="nenhum output de C__CPF__v2"):
        pub.build()


def test_build_recusa_indi_231_com_o_mesmo_egp_por_dois_nomes(tmp_path, monkeypatch):
    """Nome antigo e nome publicado na lista Indicium viram o mesmo EGP: o escopo seria
    semeado duas vezes e o funil contaria o EGP em dobro, sem aviso."""
    pub = _publish_sobre_fixture(tmp_path, monkeypatch, [
        ("C__CPF__v2", "CARNEIRO.BASE_3040_202509", "table_out")])
    (tmp_path / "indi.csv").write_text(
        "egp_dor1,area,status_extracao,project_no_06 / observacao\n"
        "cpf,Cobrança,exato,C__CPF\n"
        "cpf_novo,Cobrança,exato,C__CPF__v2\n", encoding="utf-8")
    with pytest.raises(dec.DecisaoInvalida, match="cita o mesmo EGP por dois nomes"):
        pub.build()
```

- [ ] **Step 2: Rode e veja falhar**

Run: `PY -m pytest W/egps_analysis/test_egp_decisoes.py -q -p no:cacheprovider`
Expected: 7 failed. O LOC falha porque `build_loc_tasks` recebe `txt_dir` e trata a lista como caminho (`TypeError`); `_nome_indi` e `_confere_outputs_fora` ainda não existem (`AttributeError`); os quatro testes do `build()` falham no `monkeypatch.setattr(pub, "DECISOES", …)`, porque a constante ainda não existe.

- [ ] **Step 3: Imports e constante.** Em `publish_to_databricks.py`:
  - **Import:** remova `import glob`; ele fica órfão depois do Step 4.
  - **Módulo:** antes de `import identidade_guard`, acrescente:

```python
import egp_decisoes         # excluir duplicata / renomear EGP (src/egps_decisoes.csv)
```

  - **Constante:** logo depois de `EGPS_CASCA = os.path.join(BASE, "src", "egps_casca.csv")`, acrescente:

```python
# Decisões por EGP (egp_decisoes.py): o orquestrador já gera os CSVs com elas; aqui valem para
# o que o publish lê direto do corpus (libmap, NON_CREATOR, LOC) e do indi_231.
DECISOES = os.path.join(BASE, "src", "egps_decisoes.csv")
```

- [ ] **Step 4: Os três leitores do corpus recebem o corpus filtrado.**

  (a) Em `build_project_libmap`: a assinatura vira `def build_project_libmap(corpus):`. No fim da docstring, depois de `(cobertura medida: ~63% dos stems têm libname de disco próprio).`, acrescente o parágrafo:

```python

    `corpus` = egp_decisoes.aplica_ao_corpus: sem os excluídos e com o stem já renomeado
    (sem isso o v1 do CPF_Contrato, publicado como `__v2`, leria os libnames do `__v2`
    pequeno descartado).
```

  Troque também o laço

```python
    for fp in glob.glob(os.path.join(txt_dir, "*.txt")):
        stem = os.path.basename(fp)[:-4]
        stem_lib[stem] = libname_resolver.parse_libmap_from_txt(fp)
```

  por

```python
    for arq in corpus:
        stem_lib[arq.stem] = libname_resolver.parse_libmap_from_txt(arq.caminho)
```

  (b) Em `build_non_creator_map`: a assinatura vira `def build_non_creator_map(corpus):`, e a docstring vira

```python
    """projeto (stem do .txt, já renomeado) -> {canon(artefato)} da linha NON_CREATOR_OUTPUTS.
    Outputs que o EGP só apensa/atualiza (regra do criador). Txt sem a linha
    (corpus antigo) -> ausente do mapa: conservador, ninguém vira contribuinte.
    `corpus` = egp_decisoes.aplica_ao_corpus."""
```

  As duas primeiras linhas do laço

```python
    for fp in glob.glob(os.path.join(txt_dir, "*.txt")):
        stem = os.path.basename(fp)[:-4]
```

  viram

```python
    for arq in corpus:
        fp, stem = arq.caminho, arq.stem
```

  (c) Em `build_loc_tasks`: a assinatura vira `def build_loc_tasks(corpus):`. A primeira frase da docstring passa a dizer `stem do arquivo — já renomeado por egp_decisoes.aplica_ao_corpus) -> (LINES_OF_CODE somado, …`. Troque

```python
    for fp in glob.glob(os.path.join(txt_dir, "*.txt")):
        proj, loc, tasks = None, 0, 0
        try:
            with open(fp, encoding="utf-8", errors="ignore") as f:
                for line in f:
                    if line.startswith("END_METADATA"):
                        break
                    if line.startswith("PROJECT:"):
                        proj = line.split(":", 1)[1].strip()
                    elif line.startswith("LINES_OF_CODE:"):
```

  por

```python
    for arq in corpus:
        fp, proj, loc, tasks = arq.caminho, arq.projeto, 0, 0
        try:
            with open(fp, encoding="utf-8", errors="ignore") as f:
                for line in f:
                    if line.startswith("END_METADATA"):
                        break
                    if line.startswith("LINES_OF_CODE:"):
```

  Apague também as duas linhas `if not proj:` / `continue` depois do `except OSError`. O projeto agora vem sempre do corpus, então elas viraram código morto desta mudança.

- [ ] **Step 5: `build()`.** Logo antes de `def build(choices=None):`, acrescente:

```python
def _nome_indi(projeto, decisoes):
    """Nome publicado de um projeto do indi_231 (o CPF_Contrato está lá pelo nome antigo; quem
    editar a linha para o nome que o app mostra também passa). Um EGP da lista Indicium que as
    decisões excluem é contradição, não detalhe: para."""
    if projeto in decisoes.renomes.values():  # já é o nome publicado de um renome
        return projeto
    novo = decisoes.nome(projeto)
    if novo is None:
        raise egp_decisoes.DecisaoInvalida(
            f"{projeto} está na lista Indicium (indi_231) e foi excluído em {DECISOES}; "
            f"decida qual dos dois vale")
    return novo


def _confere_outputs_fora(decisoes, egp_out):
    """tirar_output_do_escopo cujo prefixo não acha nenhum output do EGP é decisão que não se
    aplica (prefixo digitado errado): para, em vez de deixar os outputs no escopo calado."""
    for proj, prefixos in decisoes.outputs_fora().items():
        arts = [(er["artifact"] or "").upper() for er in egp_out.values() if er["projeto"] == proj]
        for prefixo in prefixos:
            if not any(a.startswith(prefixo) for a in arts):
                raise egp_decisoes.DecisaoInvalida(
                    f"tirar_output_do_escopo: nenhum output de {proj} começa com {prefixo} "
                    f"({DECISOES})")
```

  Em seguida, faça estas trocas dentro de `build()`:

  - As duas primeiras linhas

```python
    indi = load_indi_projects()
    proj_dor1_area = load_indi_project_areas()
```

    viram

```python
    decisoes = egp_decisoes.carrega(DECISOES)
    corpus = egp_decisoes.aplica_ao_corpus(TXT_DIR, decisoes)
    # dois nomes do indi_231 (o antigo e o publicado) no mesmo EGP semeariam o escopo duas vezes
    fontes = collections.defaultdict(set)
    for p in load_indi_projects():
        fontes[_nome_indi(p, decisoes)].add(p)
    duplos = {k: sorted(v) for k, v in fontes.items() if len(v) > 1}
    if duplos:
        raise egp_decisoes.DecisaoInvalida(
            f"indi_231 cita o mesmo EGP por dois nomes (renome em {DECISOES}): {duplos}")
    indi = set(fontes)
    proj_dor1_area = {_nome_indi(p, decisoes): a for p, a in load_indi_project_areas().items()}
```

  - `build_project_libmap()` vira `build_project_libmap(corpus)`, `build_non_creator_map()` vira `build_non_creator_map(corpus)` e `build_loc_tasks()` vira `build_loc_tasks(corpus)`.
  - **Guarda de CSV velho.** Logo depois de `all_projs = set(proj_area) | {a for a, _ in edges} | {d for _, d in edges}`, acrescente:

```python
    # 06/03 gerados sem as decisões (orquestrador antigo, outro checkout) trazem de volta o
    # que elas tiram. Para aqui, antes de qualquer escrita.
    velhos = decisoes.nomes_proibidos() & all_projs
    if velhos:
        raise egp_decisoes.DecisaoInvalida(
            f"os CSVs do orquestrador trazem EGPs que {DECISOES} exclui ou renomeia "
            f"({', '.join(sorted(velhos)[:5])}): rode o orchestrator_inventory.py de novo")
    _confere_outputs_fora(decisoes, egp_out)
```

  - **`out_rows`.** Troque `"escopo_indi": bool(prods & indi),` por

```python
            # tirar_output_do_escopo (egp_decisoes): o par (EGP, output) cortado não conta
            "escopo_indi": any(p in indi and decisoes.output_no_escopo(p, orec["artifact"])
                               for p in prods),
```

  - **`egp_out_rows`.** Troque `"escopo_indi": er["projeto"] in indi,` por

```python
        "escopo_indi": er["projeto"] in indi
                       and decisoes.output_no_escopo(er["projeto"], er["artifact"]),
```

    Use o bloco de `egp_out_rows`, o que tem `"apenas_contribui"`. Os outros dois blocos com `er["projeto"] in indi` (`egp_inputs_rows`) ficam como estão.
  - **Retorno.** No dicionário devolvido, troque `"funil": funil_rows, "indicium": load_indi_full(),` por

```python
            "funil": funil_rows,
            "indicium": [{**r, "projeto": _nome_indi(r["projeto"], decisoes)}
                         for r in load_indi_full()],
```

- [ ] **Step 6: `main()` aborta antes de escrever.** Troque `data = build(choices)` por

```python
    try:
        data = build(choices)
    except egp_decisoes.DecisaoInvalida as e:
        print(f"\n❌ ABORTADO antes de escrever: {e}", file=sys.stderr)
        sys.exit(2)
```

- [ ] **Step 7: Rode os testes**

Run: `PY -m pytest W/egps_analysis --ignore=W/egps_analysis/app -q -p no:cacheprovider`
Expected: `171 passed` (131 + 40).

- [ ] **Step 8: Prova da guarda de CSV velho.** Os CSVs da branch ainda são os da develop, gerados sem as decisões.

Run: `PY W/egps_analysis/publish_to_databricks.py`
Expected: exit 2 e, no stderr, `❌ ABORTADO antes de escrever: os CSVs do orquestrador trazem EGPs que … exclui ou renomeia (Cartões__Processo de bonificação - taxas_v35 (2), Cobranças__COLCHAO_ACORDO_CL__v2, Cobranças__CPF_Contrato, …): rode o orchestrator_inventory.py de novo`. Nada é escrito, nem o preview.

- [ ] **Step 9: Commit**

```bash
/usr/bin/git -C W add egps_analysis/publish_to_databricks.py egps_analysis/test_egp_decisoes.py
/usr/bin/git -C W commit -m "feat(egps): publish aplica as decisões por EGP e recusa CSV gerado sem elas"
```

---

### Task 5: Regenerar os CSVs com as decisões e medir o efeito

**Files:**
- Modify (regenerados): `egps_analysis/01_prioridade_ingestao.csv` … `06_prontidao_tabela.csv` e `08_arestas_arquivo.csv`

- [ ] **Step 1: Guarde os CSVs da develop para comparar.** Comandos, um por vez:
  1. `mkdir -p S/develop`
  2. `cp W/egps_analysis/01_prioridade_ingestao.csv W/egps_analysis/02_entregaveis_marts.csv W/egps_analysis/03_matriz_dependencias.csv W/egps_analysis/04_ondas_de_migracao.csv W/egps_analysis/05_prontidao_egp.csv W/egps_analysis/06_prontidao_tabela.csv W/egps_analysis/08_arestas_arquivo.csv S/develop/`
  3. `cp W/egps_analysis/src/egps_decisoes.csv S/`

- [ ] **Step 2: Rode o orquestrador**

Run: `env -C W/egps_analysis PY orchestrator_inventory.py`
Expected:
- `Analisando 1805 projetos...` e `decisões por EGP: 12 excluídos, 1 renomeados`;
- `Linhagem por path: +205 arestas recuperadas`;
- 08 com `186 pares`.

- [ ] **Step 3: Compare relatório a relatório.** Crie `S/compara.py`:

```python
"""Compara os relatórios do orquestrador com e sem as decisões por EGP.

Uso: python compara.py <dir_sem> <dir_com> <egps_decisoes.csv>
Para cada relatório: linhas que saem e que entram (multiconjunto), e quais delas NÃO citam
nenhum dos EGPs das decisões (o efeito colateral que precisa de explicação).
"""
import collections
import csv
import sys

sem, com, dec = sys.argv[1], sys.argv[2], sys.argv[3]
with open(dec, newline="", encoding="utf-8") as f:
    nomes = set()
    for r in csv.DictReader(f):
        nomes.add(r["egp_key"])
        if r["alvo"] and r["acao"] == "renomear":
            nomes.add(r["alvo"])

RELS = ["01_prioridade_ingestao.csv", "02_entregaveis_marts.csv", "03_matriz_dependencias.csv",
        "04_ondas_de_migracao.csv", "05_prontidao_egp.csv", "06_prontidao_tabela.csv",
        "08_arestas_arquivo.csv"]


def linhas(path):
    with open(path, newline="", encoding="utf-8-sig") as f:
        return [tuple(r) for r in csv.reader(f)]


for rel in RELS:
    a, b = linhas(f"{sem}/{rel}"), linhas(f"{com}/{rel}")
    ca, cb = collections.Counter(a[1:]), collections.Counter(b[1:])
    saem, entram = ca - cb, cb - ca
    cita = lambda row: any(n in c for c in row for n in nomes)
    saem_outros = [r for r in saem.elements() if not cita(r)]
    entram_outros = [r for r in entram.elements() if not cita(r)]
    print(f"\n== {rel}: {len(a) - 1} -> {len(b) - 1} linhas | saem {sum(saem.values())} "
          f"(sem citar decisão: {len(saem_outros)}) | entram {sum(entram.values())} "
          f"(sem citar decisão: {len(entram_outros)})")
    for r in saem_outros[:6]:
        print("   - ", r[:6])
    for r in entram_outros[:6]:
        print("   + ", r[:6])
```

Run: `PY -I S/compara.py S/develop W/egps_analysis S/egps_decisoes.csv`
Expected (medido no rascunho):

| relatório | linhas | linhas que mudam sem citar um EGP das decisões |
|---|---|---|
| 01 | 8.889 → 8.889 | 115 entram: só contagens de consumidores (ex.: `TBCONTRATO` 162 → 161) |
| 02 | 48.678 → 48.246 | 0 |
| 03 | 2.705 → 2.632 | 49: só `n_produtores` uma unidade menor, porque a cópia deixa de contar como produtor (ex.: `NPS_NEW.BA_ESTOQUE_NPSENVIO_CARTAO` 2 → 1) |
| 04, 05 | 1.320 → 1.308 | 0 |
| 06 | 86.219 → 85.510 | 0 |
| 08 | 187 → 186 | 0 |

Qualquer linha fora disso é efeito colateral não previsto. Pare e investigue.

- [ ] **Step 4: Compare o build do publish com o da develop.** Crie `S/dump_build.py`:

```python
"""Roda o build() do publish de um checkout e grava o resultado em JSON (sem conectar).

Uso: python dump_build.py <dir egps_analysis> <saida.json>
"""
import json
import sys

sys.path.insert(0, sys.argv[1])
import publish_to_databricks as pub  # noqa: E402

data = pub.build()
with open(sys.argv[2], "w", encoding="utf-8") as f:
    json.dump(data, f, ensure_ascii=False, default=lambda o: sorted(o) if isinstance(o, set) else str(o))
print({k: len(v) for k, v in data.items() if hasattr(v, "__len__")})
```

e `S/compara_build.py`:

```python
"""Compara o build() do publish na develop com o build() com as decisões.

Uso: python compara_build.py <develop.json> <novo.json>
Para cada tabela: linhas que saem/entram por chave e campos que mudam nas linhas comuns.
O CPF_Contrato é comparado pelo nome antigo (develop) contra o novo (com decisões).
"""
import collections
import json
import sys

dev, novo = (json.load(open(p, encoding="utf-8")) for p in sys.argv[1:3])
VELHO, NOVO = "Cobranças__CPF_Contrato", "Cobranças__CPF_Contrato__v2"

CHAVES = {
    "nodes": ("projeto",),
    "inputs": ("chave_canonica",),
    "outputs": ("chave_canonica",),
    "egp_inputs": ("projeto", "chave_canonica"),
    "egp_outputs": ("projeto", "chave_canonica"),
    "resumo": ("chave_canonica",),
}


def chave(tab, r, lado):
    k = tuple(r[c] for c in CHAVES[tab])
    if lado == "dev" and tab in ("nodes", "egp_inputs", "egp_outputs"):
        if k[0] == NOVO:
            return None  # o __v2 pequeno da develop, excluído no novo
        if k[0] == VELHO:
            k = (NOVO,) + k[1:]
    return k


for tab in CHAVES:
    a = {chave(tab, r, "dev"): r for r in dev[tab]}
    a.pop(None, None)
    b = {chave(tab, r, "novo"): r for r in novo[tab]}
    saem, entram = set(a) - set(b), set(b) - set(a)
    campos = collections.Counter()
    exemplos = collections.defaultdict(list)
    for k in set(a) & set(b):
        for c in a[k]:
            if c in ("projeto",):
                continue
            if a[k][c] != b[k].get(c):
                campos[c] += 1
                if len(exemplos[c]) < 3:
                    exemplos[c].append((k, a[k][c], b[k].get(c)))
    print(f"\n== {tab}: {len(a)} -> {len(b)} | saem {len(saem)} | entram {len(entram)}")
    if tab == "nodes":
        print("   saem:", sorted(k[0] for k in saem))
        print("   entram:", sorted(k[0] for k in entram))
    for c, n in campos.most_common():
        print(f"   campo {c}: {n} linhas mudam; ex.: {exemplos[c]}")
```

O build da develop roda num worktree descartável da develop. Comandos, um por vez:
1. `/usr/bin/git -C W worktree add --detach S/develop-wt origin/develop`
2. `PY -I S/dump_build.py S/develop-wt/egps_analysis S/build_develop.json`
3. `PY -I S/dump_build.py W/egps_analysis S/build_novo.json`
4. `PY -I S/compara_build.py S/build_develop.json S/build_novo.json`
5. `/usr/bin/git -C W worktree remove --force S/develop-wt`

Expected (medido no rascunho):
- **`nodes` 1.303 → 1.292:**
  - saem exatamente os 11 duplicados;
  - o CPF passa a `__v2` sem nenhum outro campo mudar (LOC, escopo, ciclo);
  - mudam só `n_egps_consumidores` (41 nós) e os indicadores de intermediário (4 nós: a cópia deixava de ser consumidora).
- **`inputs` 10.664 → 10.664:**
  - nenhum input some (toda cópia é lida também pelo original);
  - mudam `qtd_projetos` (186) e `areas` (66: "Teste EGPs" sai de onde só a cópia lia).
- **`outputs` 3.862 → 3.862:** mudam produtores, criadores e consumidores, e `escopo_indi` dos 4 `CARNEIRO.BASE_3040_*` (true → false).
- **`egp_inputs`:** 24.213 → 24.003.
- **`egp_outputs`:** 4.831 → 4.788, e os 4 `BASE_3040` do `__v2` com `escopo_indi` true → false.
- **`resumo`:** 11.112 → 11.112, sem mudança de campo.

- [ ] **Step 5: Dry-run do publish passa**

Run: `PY W/egps_analysis/publish_to_databricks.py`
Expected: termina com `[dry-run] rode com --apply …`, sem `ABORTADO`. Depois, restaure o preview: `/usr/bin/git -C W checkout -- egps_analysis/docs/analises/publish_databricks.preview.sql`.

- [ ] **Step 6: Suíte**

Run: `PY -m pytest W/egps_analysis --ignore=W/egps_analysis/app -q -p no:cacheprovider`
Expected: `171 passed`.

- [ ] **Step 7: Commit**

```bash
/usr/bin/git -C W add egps_analysis/01_prioridade_ingestao.csv egps_analysis/02_entregaveis_marts.csv egps_analysis/03_matriz_dependencias.csv egps_analysis/04_ondas_de_migracao.csv egps_analysis/05_prontidao_egp.csv egps_analysis/06_prontidao_tabela.csv egps_analysis/08_arestas_arquivo.csv
/usr/bin/git -C W commit -m "chore(egps): relatórios regenerados sem as 11 duplicatas e com o CPF_Contrato como __v2"
```

---

### Task 6: Documentação

**Files:**
- Modify: `egps_analysis/docs/PIPELINE_INVENTARIO_MIGRACAO_SAS.md` (seção do `orchestrator_inventory.py`, nova seção depois de `src/RepMap.xlsx`, tabela "Referência rápida")
- Modify: `CLAUDE.md` (raiz, "Decisões de design & armadilhas")
- Modify: `egps_analysis/docs/analises/reaplica_rename_cpf_contrato_pos_publish.py` (docstring)
- Add: este plano

- [ ] **Step 1: Pipeline doc.** O doc está em português de Portugal: mantenha "ficheiro" e "secção" e escreva do mesmo jeito.

  (a) Na seção `### orchestrator_inventory.py`, antes do item **CLI:**, acrescente:

```markdown
- **Decisões por EGP:** `src/egps_decisoes.csv` (obrigatório) é aplicado **na leitura** do corpus, antes de qualquer relatório: EGP excluído não entra, EGP renomeado entra com o nome novo. Decisão órfã ou incoerente aborta o script (código 2). Ver a secção `src/egps_decisoes.csv` abaixo.
```

  (b) Depois da tabela de `### src/RepMap.xlsx` e do `---` que a fecha, acrescente:

```markdown
### `src/egps_decisoes.csv`

Decisões humanas por EGP que o corpus (`text_egps/`) não carrega. O publish regrava as tabelas do corpus a cada rodada, então apagar ou renomear um EGP direto no banco **não dura**: em 16/10/2026 as 11 duplicatas removidas à mão em agosto e setembro estavam todas de volta em prod. Remover duplicata ou renomear EGP é uma linha **aqui**, com o motivo; o `.txt` continua no corpus. Lido por `orchestrator_inventory.py` e `publish_to_databricks.py` (módulo `egp_decisoes.py`).

| Coluna | Significado |
|--------|-------------|
| `egp_key` | Nome do EGP no corpus: o `PROJECT:` do cabeçalho do `.txt`. |
| `acao` | `excluir` (sai do inventário), `renomear` (entra com o nome `alvo`) ou `tirar_output_do_escopo` (outputs cujo artefato começa com `alvo` ficam com `escopo_indi=false`). |
| `alvo` | Nome novo (`renomear`) ou prefixo do artefato (`tirar_output_do_escopo`); vazio em `excluir`. |
| `motivo` | Obrigatório. O porquê da decisão, com a referência (relatório, revisão, jira). |
| `data`, `quem` | Quando e por quem a decisão foi tomada. |

Decisão que cita EGP ausente do corpus, renome para um nome (ou `.txt`) que outro EGP mantido já usa e renome de EGP cujo `.txt` não tem o nome do projeto **param** o orquestrador e o publish, antes de qualquer escrita. O publish recusa ainda os CSVs do orquestrador gerados sem as decisões e o prefixo de `tirar_output_do_escopo` que não acha nenhum output. A recusa de CSV velho só vale num sentido: **retirar** uma decisão também exige rodar o orquestrador de novo, senão o publish segue sem aquele EGP até a próxima rodada. O corte de outputs dura até a próxima edição de escopo na tela do app, que recalcula a flag sem ler este ficheiro (fica para a Fase 2b da migração para a AWS).

---
```

  (c) Na tabela "Referência rápida: ficheiros × scripts", depois da linha do `src/RepMap.xlsx`:

```markdown
| `src/egps_decisoes.csv` | *(decisão humana, versionada)* | `orchestrator_inventory.py`, `publish_to_databricks.py` |
```

- [ ] **Step 2: `CLAUDE.md` da raiz.** O texto do arquivo está em inglês. Em "Decisões de design & armadilhas", logo antes do item **The extractor excludes `*dtm.json`**, acrescente:

```markdown
- **Removing a duplicate EGP or renaming one is a line in `egps_analysis/src/egps_decisoes.csv`, never a DELETE/UPDATE in the database.** The publish rewrites the corpus tables every run, so database-only fixes come back (measured 16/10/2026: all 11 hand-removed duplicates were back in prod). The orchestrator and the publish apply the file while reading the corpus and refuse orphan or conflicting decisions. → `egps_analysis/egp_decisoes.py`, `docs/PIPELINE_INVENTARIO_MIGRACAO_SAS.md` §`src/egps_decisoes.csv`.
```

- [ ] **Step 3: Script do CPF obsoleto.** No começo da docstring de `reaplica_rename_cpf_contrato_pos_publish.py`, antes de `Manutenção recorrente prevista no AVISO CRÍTICO…`, acrescente:

```text
OBSOLETO: o renome e o corte dos outputs BASE_3040 vêm de `src/egps_decisoes.csv`, que o
orquestrador e o publish aplicam na leitura do corpus. Depois de um publish com o arquivo,
`Cobranças__CPF_Contrato` não existe mais nas tabelas derivadas, e a guarda abaixo aborta
este script ("Não há o que renomear") sem escrever nada. Fica no repo como registro.

```

- [ ] **Step 3b: Ajustes da revisão final** (pedidos pela revisão do conjunto):
  1. **CI:** em `bitbucket-pipelines.yml`, no `python -m pytest` da suíte da raiz, inclua `test_egp_decisoes.py` depois de `test_chunks_sem_truncar.py`. Sem isso nenhuma das travas roda no gate. O step já dispara com mudança em `egps_analysis/**`.
  2. **`publish_to_databricks.py`:**
     - Na docstring do módulo, a lista "Origem (local)" ganha, depois do `indi_231` (que passa a terminar em `·`):
       `text_egps/ (libnames, NON_CREATOR, LOC) e src/egps_decisoes.csv (decisões por EGP, ver egp_decisoes.py).`
     - O comentário da constante `DECISOES` passa a terminar em:
       `… e do indi_231, cortam do escopo os outputs marcados, e o build() recusa CSV gerado sem elas.`
  3. **`docs/analises/rename_cpf_contrato_v1_para_v2.py`:** antes de `⚠️ AVISO CRÍTICO — RISCO DE RE-KEY NO REPUBLISH`, acrescente:
     `RESOLVIDO em 16/10/2026: o renome agora mora em src/egps_decisoes.csv, que o orquestrador e o publish aplicam na leitura do corpus. O aviso abaixo fica como registro do porquê.`
  4. **`docs/analises/repara_escopo_indi_cpf_contrato.py`:** depois da primeira linha da docstring, acrescente:
     `Desde 16/10/2026 o renome vem de src/egps_decisoes.csv e o publish já grava o nó como __v2 antes do recompute; o re-key pós-publish descrito abaixo não roda mais. Segue útil só para CONFERIR se as duas contagens do Resumo batem.`

- [ ] **Step 4: Commit**

```bash
/usr/bin/git -C W add bitbucket-pipelines.yml egps_analysis/publish_to_databricks.py egps_analysis/docs/analises/rename_cpf_contrato_v1_para_v2.py egps_analysis/docs/analises/repara_escopo_indi_cpf_contrato.py
/usr/bin/git -C W add egps_analysis/docs/PIPELINE_INVENTARIO_MIGRACAO_SAS.md CLAUDE.md egps_analysis/docs/analises/reaplica_rename_cpf_contrato_pos_publish.py egps_analysis/docs/superpowers/plans/2026-10-16-decisoes-por-egp.md
/usr/bin/git -C W commit -m "docs(egps): decisões por EGP no pipeline e no CLAUDE.md; script do CPF fica obsoleto"
```

---

### Task 7: Entrega e publish (cada escrita só com consentimento)

- [ ] **Step 1: Push** (só com pedido do usuário):

```bash
/usr/bin/git -C W push -u origin feat/egp-decisions-file
```

  O usuário abre a PR para a `develop` pelo link que o push imprime. O merge roda só o step de testes do CI (`egps_analysis/**`); o deploy do app dev exige mudança em `egps_analysis/app/**`, que esta branch não tem. Nada muda no banco: só o publish escreve.

- [ ] **Step 2: Publish no dev do Databricks** (`monitoramento_sas_dev`, o schema padrão), **só com consentimento**:

```bash
PY W/egps_analysis/publish_to_databricks.py --apply --profile bv --warehouse-id 5922c26f81f1bbdd
```

  Conferir no app dev:
  - os 11 duplicados sumiram da aba EGPs;
  - o CPF aparece só como `Cobranças__CPF_Contrato__v2`, com o perfil grande (≈ 1.114 LOC, 13 tasks);
  - Resumo e card batem.
  - A cópia do Cartão Amigável (`…Cartão Amigável__v2`) tem linha própria em `sas_egp_pipeline`, editada por engano em 28/09 (etapa Pré-conversão, status A Iniciar). O original segue Concluído. Veja se a cópia aparece em alguma tela. Se aparecer, leve ao usuário a proposta de apagar a linha da cópia. É uma escrita, então só com consentimento.

- [ ] **Step 3: Pré-checagem de prod, só leitura** (o estado das tabelas de apoio de prod difere do dev: a cópia do Cartão voltou e foi editada só em prod):
  1. **Checkout:** publique de um checkout igual à `develop` depois do merge (ou de W, se a develop não andou). O publish é full replace a partir do corpus local.
  2. **Linhas de apoio que citam os 12 nomes excluídos e o nome antigo do CPF**, em `bv_dev_db.monitoramento_sas`:
     - `sas_escopo` (linhas ativas);
     - `sas_egp_pipeline`;
     - `sas_gestao_status` e `sas_gestao_datas` (entidade EGP);
     - `sas_output_producer_choice.projeto_escolhido`;
     - `sas_egp_input_link`, `sas_egp_dep_mantida`, `sas_egp_input_periodo`, `sas_egp_prioridades`;
     - o JSON do `sas_priorizacao_snapshot`.

     Os riscos de deixar essas linhas:
     - Linha ativa em `sas_escopo` separa o card do Resumo (conta pelo `sas_escopo`) do funil (conta pelo grafo): o sintoma 195 × 194 de setembro.
     - Escolha de produtor apontando para EGP excluído é descartada calada pelo publish.
     - O snapshot da Priorização pode listar EGP sem nó.

     Leve a lista ao usuário antes do apply.
  3. **Build × prod de hoje**, não só × develop. Esperado:
     - menos 11 nós;
     - nenhum renome do CPF (o script de reaplicação já tinha posto o `__v2`);
     - os 4 `BASE_3040` passam de true para false em `sas_outputs_monitor` (o script só cortava `sas_egp_outputs`);
     - mudam as contagens de consumidores e produtores.

     Qualquer outra diferença indica que prod foi publicado de outro corpus ou código: pare.

- [ ] **Step 4: Publish em prod** (`monitoramento_sas`), **só com consentimento explícito**:

```bash
PY W/egps_analysis/publish_to_databricks.py --apply --schema monitoramento_sas --prod-confirm --profile bv --warehouse-id 5922c26f81f1bbdd
```

  Não rode mais o `reaplica_rename_cpf_contrato_pos_publish.py`. Se alguém rodar, a guarda dele aborta sem escrever. Confira em prod as mesmas coisas do dev, com uma consulta só de leitura: os 11 sem nó, o CPF só como `__v2`, os 4 `BASE_3040` com `escopo_indi=false` em `sas_egp_outputs` e em `sas_outputs_monitor`.

- [ ] **Step 5: Memória** (fora do repo): marque como resolvidas, apontando para `src/egps_decisoes.csv`, as notas `cpf-contrato-rekey-pos-publish`, `cartao-amigavel-v2-removido`, `egps-duplicados-escopo-revisao-2026-09` e `egps-duplicados-cross-area-sem-trava`. O limite do `recompute_escopo` com o `BASE_3040` fica registrado em `migracao-aws-app` (2b).

---

## Fora deste plano

- **O app respeitar o corte de outputs no `recompute_escopo`:** 2b. O app passa a guardar as decisões que chegam no pacote (Q12).
- **Os outros 33 grupos de gêmeos entre áreas** (`docs/analises/egps_duplicados_entre_areas_2026-08-12.csv`): cada um vira uma linha `excluir` quando for decidido. Este plano só registra o 1351, que já foi removido.
- **EGP reenviado com o nome de um excluído:** se o BV reenviar um EGP cujo `<pasta>__<nome>` é igual ao de um excluído (ex.: `Finanças__Gastos_PE`), o extrator sobrescreve o `.txt` e a decisão descarta o EGP novo sem aviso. Proteção forte: guardar o hash do `.txt` nas linhas `excluir` e recusar quando mudar. Proteção barata: uma linha na tabela do Passo 2 da skill `sobe-egp-atualizado`.
- **Recusa de CSV velho nos dois sentidos:** o publish poderia comparar os projetos do corpus filtrado com os do 05 (hoje 1.308 = 1.308), o que pegaria decisão retirada sem rodar o orquestrador e `.txt` novo sem rodar o orquestrador. Hoje é limite documentado.
- **Teste do libmap pelo nome renomeado** (`build_project_libmap`): nenhum teste prende a chave pelo stem renomeado (a mutação sobrevive); a medição da Task 5 mostra `paths_fisicos` correto. Um `LIBNAME` no fixture do v1 resolveria.
- **Resumo das decisões no dry-run do publish:** o orquestrador imprime quantos excluídos e renomeados; o publish não.
- **Scripts de análise que ainda leem o corpus cru:** `egps_analysis/_analise_intermediarios.py` (lista `oi.INPUT_FOLDER` direto, então conta os 12 excluídos e o nome antigo do CPF), `validate_macro_refs.py` e o `__main__` de `macro_file_refs.py`. Nenhum alimenta o pipeline; trocar para `egp_decisoes.aplica_ao_corpus` quando forem usados de novo.
- **Docstring de `docs/analises/overlay_egps_novos.py`:** ela diz que o publish reverte o lote Sanitizar/Desvincular e o overlay do %DESCOMPACTA, e o levantamento de 16/10 mostrou que não reverte. Fica anotado aqui; não é desta mudança.
