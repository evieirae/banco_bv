#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Levantamento das safras de CARNEIRO.BASE_3040: quem lê, quem cria, e qual a ação.

ORIGEM DOS DADOS (importa): a ESTRUTURA (quem lê / quem cria) vem da extração vigente
em `text_egps/`, NÃO do publish. Motivo, verificado em 2026-08-24: o inventário de
produção atribui leitura e escrita de BASE_3040 a `Cobranças__CPF_Contrato__v2`, mas o
`__v2` de hoje é um stub de 179 linhas sem uma única referência à tabela; quem lê e
escreve é o `Cobranças__CPF_Contrato` (1.486 linhas). O publish também registra leituras
em `Fechamento_Contabil_RPDD_3040` que não existem mais no texto. Construir a
classificação sobre o publish produz recomendação errada (foi o que aconteceu na 1ª
versão deste script). Do painel vem só `etapa`/`status`, que é dado humano.

Classificação (mesma do estudo de 2026-08-13, restrita à família BASE_3040_<D>):

  auto_mesmo_run             o próprio leitor CRIA a mesma chave      -> sanitizar/desvincular
  auto_safra_irma            o leitor cria OUTRA safra da família     -> backfill único
  outro_egp_cria             outro EGP cria a mesma chave             -> ref() do produtor
  outro_egp_cria_safra_irma  outro EGP cria outra safra da família    -> backfill + ref()
  membro_dinamico            chave com &macro não resolvida           -> resolver antes de decidir
  ingestao                   ninguém na família cria                  -> ingerir de fato

Uso:
  cd egps_analysis
  venv/bin/python3 docs/analises/levantamento_base_3040.py \
      --profile bv --warehouse-id 5922c26f81f1bbdd
"""
import argparse
import collections
import csv
import glob
import io
import os
import re
import time

BASE = os.path.dirname(os.path.abspath(__file__))
RAIZ = os.path.dirname(os.path.dirname(BASE))   # docs/analises -> docs -> egps_analysis
PREFIXO = "CARNEIRO.BASE_3040"

_TOKEN = r'CARNEIRO\.BASE_3040[A-Za-z0-9_&.]*'
_ESCRITA_RE = re.compile(r'(?:CREATE\s+TABLE|DATA)\s+(' + _TOKEN + r')', re.IGNORECASE)
_LEITURA_RE = re.compile(r'(?:FROM|SET|JOIN|MERGE)\s+(' + _TOKEN + r')', re.IGNORECASE)

_SAFRA_RE = re.compile(r'(?<!\d)(20\d{2})(0[1-9]|1[0-2])(0[1-9]|[12]\d|3[01])?(?!\d)')
_ANO_RE = re.compile(r'_(20\d{2})$')

ACOES = {
    "auto_safra_irma": "Backfill único do histórico (o próprio EGP gera a safra corrente)",
    "outro_egp_cria": "Sem ingestão: virar ref() do EGP produtor ao migrar",
    "outro_egp_cria_safra_irma": "Backfill único + ref() do produtor da safra corrente",
    "membro_dinamico": "Resolver a macro (&SAFRA/&DT_REF) antes de decidir — chave incompleta",
    "ingestao": "Ingerir de fato (nenhum EGP do corpus cria a família)",
}


def limpa(tok):
    return tok.strip().rstrip('.').upper()


def familia(art):
    """Tabela lógica sem a safra, em qualquer granularidade (dia, mês ou ano)."""
    return _ANO_RE.sub("_<D>", _SAFRA_RE.sub("<D>", art))


def dinamico(art):
    return '&' in art or art.endswith('_')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--catalog", default=os.environ.get("PUBLISH_CATALOG", "bv_dev_db"))
    ap.add_argument("--schema", default=os.environ.get("PUBLISH_SCHEMA", "monitoramento_sas"))
    ap.add_argument("--warehouse-id", default=os.environ.get("DATABRICKS_DEFAULT_WAREHOUSE_ID"))
    ap.add_argument("--profile", default=os.environ.get("DATABRICKS_CONFIG_PROFILE"))
    ap.add_argument("--date", default="2026-08-24")
    args = ap.parse_args()

    # ---------- estrutura: CABEÇALHO da extração vigente ----------
    # Fonte autoritativa: o extrator já resolve alias/libname, SET multi-dataset e a
    # regra do criador. Varrer o corpo com regex subconta leitores (um `SET` lista
    # vários datasets em linhas seguintes e só o 1º casa) — foi o erro da versão anterior.
    #   EXTERNAL INPUTS  = lê e NÃO cria (fila de ingestão)
    #   INTERNAL READS   = lê e cria (auto-produção; o extrator já tira da fila)
    #   PERMANENT OUTPUTS - NON_CREATOR_OUTPUTS = criador de fato
    def campo(txt, nome):
        m = re.search(r'^' + nome + r'[^:]*:(.*)$', txt, re.IGNORECASE | re.MULTILINE)
        if not m:
            return []
        itens = []
        for t in m.group(1).split(','):
            t = re.sub(r'\[[^\]]*\]', '', t).strip().upper()
            if t and t != '(NONE)' and t.startswith(PREFIXO):
                itens.append(t)
        return itens

    escreve = collections.defaultdict(set)
    le = collections.defaultdict(set)
    auto = collections.defaultdict(set)     # (art, egp) em que o EGP lê E cria
    externo = collections.defaultdict(set)  # (art, egp) em que o EGP só lê
    for path in sorted(glob.glob(os.path.join(RAIZ, "text_egps", "*.txt"))):
        txt = io.open(path, encoding="utf-8", errors="replace").read()
        if PREFIXO not in txt.upper():
            continue
        egp = os.path.basename(path)[:-4]
        cab = txt.partition("END_METADATA")[0]
        ext = campo(cab, "EXTERNAL INPUTS")
        itn = campo(cab, "INTERNAL READS")
        outs = set(campo(cab, "PERMANENT OUTPUTS")) - set(campo(cab, "NON_CREATOR_OUTPUTS"))
        for a in outs:
            escreve[a].add(egp)
        for a in ext:
            le[a].add(egp)
            externo[a].add(egp)
        for a in itn:
            le[a].add(egp)
            auto[a].add(egp)
            escreve[a].add(egp)   # INTERNAL READ implica que o próprio EGP cria

    cria_familia = collections.defaultdict(set)
    for art, projs in escreve.items():
        cria_familia[familia(art)] |= projs

    # ---------- status humano: painel ----------
    status = {}
    if args.warehouse_id:
        from databricks.sdk import WorkspaceClient
        from databricks.sdk.service.sql import StatementState, Disposition, Format
        w = WorkspaceClient(profile=args.profile) if args.profile else WorkspaceClient()
        fq = f"{args.catalog}.{args.schema}"
        resp = w.statement_execution.execute_statement(
            statement=f"SELECT upper(artifact) AS art, etapa, status, chave_canonica "
                      f"FROM {fq}.sas_inputs_monitor WHERE upper(artifact) LIKE '{PREFIXO}%'",
            warehouse_id=args.warehouse_id, wait_timeout="50s",
            disposition=Disposition.INLINE, format=Format.JSON_ARRAY,
            catalog=args.catalog, schema=args.schema)
        sid = resp.statement_id
        while resp.status and resp.status.state in (StatementState.PENDING, StatementState.RUNNING):
            time.sleep(2)
            resp = w.statement_execution.get_statement(statement_id=sid)
        if resp.status and resp.status.state == StatementState.SUCCEEDED and resp.result and resp.result.data_array:
            cols = [c.name for c in resp.manifest.schema.columns]
            for row in resp.result.data_array:
                r = dict(zip(cols, row))
                status[r["art"]] = r
    else:
        print("(sem --warehouse-id: etapa/status ficam em branco)")

    linhas = []
    for art in sorted(set(le) | set(escreve)):
        fam = familia(art)
        cri = escreve.get(art, set())
        cri_fam = cria_familia.get(fam, set())
        st = status.get(art, {})
        for leitor in sorted(le.get(art, set())):
            outros = sorted(le.get(art, set()) - {leitor})
            if dinamico(art):
                classe = "membro_dinamico"
            elif leitor in auto.get(art, set()) or leitor in cri:
                classe = "auto_mesmo_run"
            elif leitor in cri_fam:
                classe = "auto_safra_irma"
            elif cri:
                classe = "outro_egp_cria"
            elif cri_fam:
                classe = "outro_egp_cria_safra_irma"
            else:
                classe = "ingestao"
            if classe == "auto_mesmo_run":
                acao = ("Sanitizar (é o único leitor)" if not outros
                        else f"Desvincular só este par ({len(outros)} outro(s) leitor(es) dependem do dado)")
            else:
                acao = ACOES[classe]
            linhas.append({
                "input": art,
                "familia": fam,
                "egp_leitor": leitor,
                "classe": classe,
                "acao_recomendada": acao,
                "criador_da_mesma_chave": " | ".join(sorted(cri)) or "—",
                "criadores_da_familia": " | ".join(sorted(cri_fam)) or "—",
                "outros_leitores": " | ".join(outros) or "—",
                "qtd_leitores": len(le.get(art, set())),
                "etapa_atual_app": st.get("etapa") or "",
                "status_atual_app": st.get("status") or "",
                "no_painel": "sim" if art in status else "NÃO (só no texto)",
                "chave_canonica": st.get("chave_canonica") or f"tabela::{art}",
            })

    out = os.path.join(BASE, f"BV_Migracao_SAS_Levantamento_BASE_3040_{args.date}.csv")
    campos = ["input", "familia", "egp_leitor", "classe", "acao_recomendada",
              "criador_da_mesma_chave", "criadores_da_familia", "outros_leitores",
              "qtd_leitores", "etapa_atual_app", "status_atual_app", "no_painel",
              "chave_canonica"]
    with open(out, "w", newline="", encoding="utf-8-sig") as f:
        wtr = csv.DictWriter(f, fieldnames=campos, delimiter=";")
        wtr.writeheader()
        wtr.writerows(linhas)

    print(f"safras vistas na extração: {len(set(le) | set(escreve))}")
    print(f"  escritas por: {sorted({e for v in escreve.values() for e in v})}")
    print(f"pares (input x EGP leitor): {len(linhas)}\n")
    ct = collections.Counter(l["classe"] for l in linhas)
    inp = collections.defaultdict(set)
    for l in linhas:
        inp[l["classe"]].add(l["input"])
    print(f"{'classe':<28} {'pares':>6} {'inputs':>7}")
    for c, n in ct.most_common():
        print(f"{c:<28} {n:>6} {len(inp[c]):>7}")
    pend = [l for l in linhas if l["status_atual_app"] != "Sanitizado"
            and l["etapa_atual_app"] != "Modernizado"]
    print(f"\npares pendentes: {len(pend)} de {len(linhas)}")
    fora = {l["input"] for l in linhas if l["no_painel"] != "sim"}
    if fora:
        print(f"safras no texto mas SEM linha no painel: {len(fora)} -> {sorted(fora)}")
    print(f"CSV: {out}")


if __name__ == "__main__":
    main()
