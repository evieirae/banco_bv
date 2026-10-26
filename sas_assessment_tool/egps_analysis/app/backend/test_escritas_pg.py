# -*- coding: utf-8 -*-
"""Escritas no Postgres (Fase 2, ADR 0005): o espelho vira a fonte, e cada rota de escrita
grava no legado pelas views compat, com o papel app_escrita.

O app roda de verdade, em modo Postgres, num subprocesso: FQ e as tabelas T_* são fixadas no
import do main, então o modo não troca dentro do processo do pytest. O banco é um só para o
módulo e cada teste grava em chaves próprias, com três estados que são do banco inteiro: o
snapshot da priorização (linha única id='current' — o teste do GET apaga antes de ler, para
não depender da ordem), o contador diário da fragilidade (uma linha por dia) e o recálculo do
escopo, que regrava escopo_indi e o funil de todos (nenhum outro teste confere esses campos)."""
import datetime
import json
import os
import pathlib
import re
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from zoneinfo import ZoneInfo

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from db import migra  # noqa: E402
from sync import sintetico  # noqa: E402
from sync.espelho_tabelas import TABELAS  # noqa: E402

DSN = os.environ.get("PG_TEST_DSN")
if not DSN and os.environ.get("PG_TEST_OBRIGATORIO") == "1":
    raise RuntimeError("PG_TEST_OBRIGATORIO=1 mas PG_TEST_DSN não foi definido")
pytestmark = pytest.mark.skipif(not DSN, reason="sem PG_TEST_DSN")
APP = pathlib.Path(__file__).resolve().parent.parent
ADMIN = "admin.teste@indicium.ai"
# Instante gravado em coluna texto: o formato do Spark, sem fuso ('2026-10-15 19:27:07.090031').
INSTANTE_TEXTO = re.compile(r"\d{4}-\d\d-\d\d \d\d:\d\d:\d\d(\.\d{1,6})?")


@pytest.fixture(scope="module")
def banco():
    import psycopg
    nome = "t_escr_" + uuid.uuid4().hex[:8]
    with psycopg.connect(DSN, autocommit=True) as c:
        c.execute(f"CREATE DATABASE {nome} TEMPLATE template0 LC_COLLATE 'C'")
    try:
        dsn = f"{DSN.rpartition('/')[0]}/{nome}"
        migra.aplica(dsn, saida=lambda *_: None)
        with psycopg.connect(dsn) as c:   # a massa do ensaio: 300 inputs, 40 EGPs, 26 no escopo
            sintetico.carrega_sintetico(c)
        with psycopg.connect(dsn, autocommit=True) as c:
            c.execute("SELECT set_config('app.usuario', %s, false)", (ADMIN,))
            c.execute("INSERT INTO cadastro.usuario (email, nome, papel) VALUES (%s, 'Admin Teste', 'admin')",
                      (ADMIN,))
        yield dsn
    finally:
        with psycopg.connect(DSN, autocommit=True) as c:
            c.execute(f"DROP DATABASE {nome} WITH (FORCE)")


def _porta_livre():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def app(banco, tmp_path_factory):
    porta = _porta_livre()
    log = tmp_path_factory.mktemp("app") / "app.log"
    # A porta vai nas duas variáveis: DATABRICKS_APP_PORT tem precedência no main. A rotina de
    # consulta fica desligada (é do Databricks e subiria uma thread no servidor).
    env = {**os.environ, "DB_BACKEND": "postgres", "PG_DSN": banco, "PUBLISH_SCHEMA": "compat",
           "IDENTIDADE": "dev", "DEV_USUARIO": ADMIN, "PG_PAPEL": "app_escrita",
           "SOMENTE_LEITURA": "0", "APP_PORT": str(porta), "DATABRICKS_APP_PORT": str(porta),
           "CONSULTA_SNAPSHOT": "0", "FAMILIAS_SAFRA": "1"}
    with open(log, "w", encoding="utf-8") as saida:
        proc = subprocess.Popen([sys.executable, "backend/main.py"], cwd=APP, env=env,
                                stdout=saida, stderr=subprocess.STDOUT)
    try:
        base = f"http://127.0.0.1:{porta}"
        for _ in range(150):
            try:
                urllib.request.urlopen(base + "/api/health", timeout=1)
                break
            except OSError:
                if proc.poll() is not None:
                    raise RuntimeError("o app não subiu:\n" + log.read_text(encoding="utf-8"))
                time.sleep(0.2)
        else:
            proc.kill()
            proc.wait()
            raise RuntimeError("o app não respondeu em 30 s:\n" + log.read_text(encoding="utf-8"))
        yield base
    finally:
        proc.terminate()
        try:
            proc.wait(10)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()


def chama(app, metodo, rota, corpo=None):
    """(status, json ou texto do erro)."""
    dados = None if corpo is None else json.dumps(corpo).encode()
    req = urllib.request.Request(app + rota, data=dados, method=metodo,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            return r.status, json.loads(r.read() or b"null")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")


def linhas(banco, sql, params=None):
    import psycopg
    with psycopg.connect(banco) as c:
        return c.execute(sql, params).fetchall()


def grava(banco, sql, params=None):
    import psycopg
    with psycopg.connect(banco, autocommit=True) as c:
        c.execute(sql, params)


# ------------------------------------------------------------------ papel do app
# Gravadas pelo backend mas que não migram: sas_egp_prioridades (spec: rotas sem tela) e as
# da rotina de consulta (só Databricks; somem na virada — gravadas via variável `tabela`).
NAO_MIGRAM = {"sas_egp_prioridades"}


def _tabelas_que_o_backend_grava():
    main = (APP / "backend" / "main.py").read_text(encoding="utf-8")
    atu = (APP / "backend" / "egps_atualizados.py").read_text(encoding="utf-8")
    mapa = dict(re.findall(r'^(T_[A-Z0-9_]+) = f"\{FQ\}\.(sas_[a-z0-9_]+)"', main, re.M))
    mapa.update(re.findall(r'^\s+(t_[a-z_]+) = f"\{fq\}\.(sas_[a-z0-9_]+)"', atu, re.M))
    alvos, sem_mapa = set(), set()
    for fonte in (main, atu):
        for nome in re.findall(r"(?:INSERT INTO|UPDATE|MERGE INTO|DELETE FROM)\s+\{([A-Za-z_][A-Za-z0-9_]*)\}", fonte):
            (alvos.add(mapa[nome]) if nome in mapa else sem_mapa.add(nome))
        alvos |= set(re.findall(r"(?:INSERT INTO|UPDATE|MERGE INTO|DELETE FROM)\s+\{FQ\}\.(sas_[a-z0-9_]+)", fonte))
    # `tabela` é a rotina de consulta (INSERT INTO {tabela}_dia, ao lado do INSERT OVERWRITE),
    # que sai no 2c; qualquer outro nome é escrita que este teste não sabe a que tabela vai.
    assert sem_mapa <= {"tabela"}, f"escrita em tabela que o teste não resolve: {sorted(sem_mapa - {'tabela'})}"
    return alvos - NAO_MIGRAM


def test_app_escrita_grava_exatamente_o_que_o_backend_grava(banco):
    """Menos que isso quebra uma rota na hora de gravar; mais que isso deixa o app gravar no
    que é só do publish (arestas da linhagem, versão e I/O dos EGPs atualizados, alias,
    métricas, resumo por projeto). Varre o banco inteiro, não só as views compat: um GRANT
    amplo no legado também acusa."""
    grava_app = _tabelas_que_o_backend_grava()
    assert len(grava_app) >= 30                  # o padrão ainda acha as escritas (sanidade)
    assert grava_app <= set(TABELAS), sorted(grava_app - set(TABELAS))
    com_privilegio = {n for (n,) in linhas(banco, """
        SELECT nsp.nspname || '.' || c.relname FROM pg_class c JOIN pg_namespace nsp ON nsp.oid = c.relnamespace
        WHERE nsp.nspname NOT IN ('pg_catalog', 'information_schema') AND c.relkind IN ('r', 'v', 'p', 'f', 'm')
          AND (has_table_privilege('app_escrita', c.oid, 'INSERT') OR has_table_privilege('app_escrita', c.oid, 'UPDATE')
               OR has_table_privilege('app_escrita', c.oid, 'DELETE'))""")}
    assert com_privilegio == {f"compat.{t}" for t in grava_app}, (sorted(com_privilegio), sorted(grava_app))


# ------------------------------------------------------------------ Gestão: cadastros
def test_responsavel_bv_cria_e_edita_com_autoria(app, banco):
    st, r = chama(app, "POST", "/api/responsaveis-bv", {"nome": "Fulana Responsável", "subarea": "Cobrança"})
    assert st == 200, r
    st, r = chama(app, "POST", "/api/responsaveis-bv", {"nome": "Fulana Responsável", "ativo": False})
    assert st == 200, r
    (row,) = linhas(banco, "SELECT nome, subarea, ativo, created_by, updated_by, created_at, updated_at "
                           "FROM legado.sas_responsaveis_bv WHERE nome = 'Fulana Responsável'")
    assert row[:5] == ("Fulana Responsável", "Cobrança", False, ADMIN, ADMIN)
    assert INSTANTE_TEXTO.fullmatch(row[5]) and INSTANTE_TEXTO.fullmatch(row[6]), row


def test_analista_cria_desativa_e_canoniza_o_email(app, banco):
    st, r = chama(app, "POST", "/api/analistas", {"email": "Ana.Teste@indicium.tech", "nome": "Ana Teste"})
    assert st == 200 and r["email"] == "ana.teste@indicium.ai", r
    email = "ana.teste@indicium.ai"
    st, r = chama(app, "DELETE", f"/api/analistas/{email}")
    assert st == 200, r
    (row,) = linhas(banco, "SELECT nome, ativo, created_by, updated_by, created_at, updated_at "
                           "FROM legado.sas_analistas WHERE email = 'ana.teste@indicium.ai'")
    assert row[:4] == ("Ana Teste", False, ADMIN, ADMIN), row
    assert INSTANTE_TEXTO.fullmatch(row[4]) and INSTANTE_TEXTO.fullmatch(row[5]), row


# ------------------------------------------------------------------ Inputs
def test_input_grava_campo_humano_e_audita(app, banco):
    chave = "tabela::LIB0.TAB_0000"
    st, r = chama(app, "PATCH", "/api/inputs", {"chave_canonica": chave, "responsavel": "Fulano",
                                                "observacao": "conferido"})
    assert st == 200 and r["responsavel"] == "Fulano", r
    (row,) = linhas(banco, "SELECT responsavel, observacao, updated_by, updated_at FROM legado.sas_inputs_monitor "
                           "WHERE chave_canonica = %s", (chave,))
    assert row[:3] == ("Fulano", "conferido", ADMIN) and row[3] is not None, row
    aud = linhas(banco, "SELECT campo, valor_novo, updated_by, updated_at IS NOT NULL FROM legado.sas_inputs_audit "
                        "WHERE chave_canonica = %s ORDER BY campo", (chave,))
    assert aud == [("observacao", "conferido", ADMIN, True), ("responsavel", "Fulano", ADMIN, True)], aud


def test_preworking_grava_checklist(app, banco):
    chave = "arquivo::ARQ_0001.CSV"
    st, r = chama(app, "PATCH", "/api/inputs/preworking", {"chave_canonica": chave, "frequencia": "Diária",
                                                           "recebido": "true", "data_recebimento": "2026-10-01"})
    assert st == 200, r
    (row,) = linhas(banco, "SELECT frequencia, recebido, data_recebimento, updated_by, updated_at "
                           "FROM legado.sas_inputs_preworking WHERE chave_canonica = %s", (chave,))
    assert row[:4] == ("Diária", "true", "2026-10-01", ADMIN) and INSTANTE_TEXTO.fullmatch(row[4]), row
    aud = linhas(banco, "SELECT campo, valor_novo, updated_by, updated_at IS NOT NULL FROM legado.sas_inputs_audit "
                        "WHERE chave_canonica = %s ORDER BY campo", (chave,))
    assert aud == [("preworking.data_recebimento", "2026-10-01", ADMIN, True),
                   ("preworking.frequencia", "Diária", ADMIN, True),
                   ("preworking.recebido", "true", ADMIN, True)], aud


def test_familia_ingestao_grava_e_audita(app, banco):
    st, r = chama(app, "PATCH", "/api/familia-ingestao", {"categoria": "tabela", "familia": "LIB1.TAB",
                                                          "desde": "202601", "ingerida_em": "2026-10-01"})
    assert st == 200, r
    (row,) = linhas(banco, "SELECT desde, ingerida_em, updated_by FROM legado.sas_familia_ingestao "
                           "WHERE categoria = 'tabela' AND familia = 'LIB1.TAB'")
    assert row == ("202601", "2026-10-01", ADMIN), row
    aud = linhas(banco, "SELECT campo, valor_antigo, valor_novo, ator, ts IS NOT NULL "
                        "FROM legado.sas_familia_ingestao_audit WHERE familia = 'LIB1.TAB'")
    assert aud == [("desde", "", "202601", ADMIN, True)], aud


# ------------------------------------------------------------------ EGPs
EGP = "Cobranças__EGP_TREINO_000"


def _um_input_do(banco, projeto):
    return linhas(banco, "SELECT chave_canonica FROM legado.sas_egp_inputs WHERE projeto = %s "
                         "ORDER BY chave_canonica LIMIT 1", (projeto,))[0][0]


def test_pipeline_do_egp_grava_campos_e_audita(app, banco):
    st, r = chama(app, "PATCH", "/api/egp-pipeline", {"projeto": EGP, "responsavel": "Fulano", "jira_id": "BV-123"})
    assert st == 200, r
    (row,) = linhas(banco, "SELECT responsavel, jira_id, updated_by, updated_at FROM legado.sas_egp_pipeline "
                           "WHERE projeto = %s", (EGP,))
    assert row[:3] == ("Fulano", "BV-123", ADMIN) and INSTANTE_TEXTO.fullmatch(row[3]), row
    aud = linhas(banco, "SELECT campo, ator, ts FROM legado.sas_pipeline_audit WHERE projeto = %s", (EGP,))
    assert {"responsavel", "jira_id"} <= {a[0] for a in aud}, aud
    assert all(a[1] == ADMIN and INSTANTE_TEXTO.fullmatch(a[2]) for a in aud), aud


def test_vinculo_copia_o_trabalho_para_o_sucessor(app, banco):
    antigo, sucessor = "Riscos__EGP_TREINO_001", "Jurídico__EGP_TREINO_002"
    assert chama(app, "PATCH", "/api/egp-pipeline", {"projeto": antigo, "responsavel": "Beltrano"})[0] == 200
    st, r = chama(app, "PATCH", "/api/egp-pipeline", {"projeto": antigo, "egp_vinculo_tipo": "Substituído",
                                                      "egp_sucessor": sucessor})
    assert st == 200, r
    (v,) = linhas(banco, "SELECT egp_vinculo_tipo, egp_sucessor FROM legado.sas_egp_pipeline WHERE projeto = %s",
                  (antigo,))
    assert v == ("Substituído", sucessor), v
    (s,) = linhas(banco, "SELECT responsavel, updated_by FROM legado.sas_egp_pipeline WHERE projeto = %s", (sucessor,))
    assert s == ("Beltrano", ADMIN), s


def test_leitura_dispensada_do_input_no_egp(app, banco):
    chave = _um_input_do(banco, EGP)
    st, r = chama(app, "PATCH", "/api/egp-input-link", {"projeto": EGP, "chave_canonica": chave, "link_broken": True})
    assert st == 200, r
    (row,) = linhas(banco, "SELECT link_broken, updated_by FROM legado.sas_egp_input_link "
                           "WHERE projeto = %s AND chave_canonica = %s", (EGP, chave))
    assert row == (True, ADMIN), row
    aud = linhas(banco, "SELECT chave_canonica, campo, ator, ts IS NOT NULL FROM legado.sas_egp_input_link_audit "
                        "WHERE projeto = %s", (EGP,))
    assert aud == [(chave, "link_broken", ADMIN, True)], aud


def test_periodo_da_familia_no_egp(app, banco):
    st, r = chama(app, "PATCH", "/api/familia-periodo", {"projeto": EGP, "categoria": "tabela", "familia": "LIB2.TAB",
                                                         "tipo": "desde", "valor": "202601"})
    assert st == 200, r
    (row,) = linhas(banco, "SELECT tipo, valor, updated_by FROM legado.sas_egp_input_periodo "
                           "WHERE projeto = %s AND familia = 'LIB2.TAB'", (EGP,))
    assert row == ("desde", "202601", ADMIN), row
    aud = linhas(banco, "SELECT campo, valor_novo, ator, ts IS NOT NULL FROM legado.sas_egp_input_periodo_audit "
                        "WHERE projeto = %s", (EGP,))
    assert aud == [("periodo", "desde:202601", ADMIN, True)], aud


def test_ainda_e_dependencia_grava_por_par_e_audita(app, banco):
    produtor = "Riscos__EGP_TREINO_007"
    consumidor, chave, art = linhas(banco, "SELECT e.projeto, e.chave_canonica, i.artifact FROM legado.sas_egp_inputs e "
                                           "JOIN legado.sas_inputs_monitor i USING (chave_canonica) "
                                           "WHERE e.projeto <> %s AND i.categoria = 'tabela' ORDER BY 1, 2 LIMIT 1",
                                    (produtor,))[0]
    grava(banco, "INSERT INTO legado.sas_lineage_edges (projeto_alvo, depende_do, via_tabelas) VALUES (%s, %s, %s)",
          (consumidor, produtor, art))
    st, r = chama(app, "PATCH", "/api/egp-dep-mantida", {"produtor": produtor, "mantida": True, "motivo": "falta coluna"})
    assert st == 200 and r["fan_out"]["alteracoes"] == 1, r
    (row,) = linhas(banco, "SELECT motivo, updated_by FROM legado.sas_egp_dep_mantida "
                           "WHERE projeto = %s AND chave_canonica = %s", (consumidor, chave))
    assert row == ("falta coluna", ADMIN), row
    aud = linhas(banco, "SELECT chave_canonica, campo, valor_antigo, valor_novo, ator, ts IS NOT NULL "
                        "FROM legado.sas_egp_dep_mantida_audit WHERE projeto = %s", (consumidor,))
    assert aud == [(chave, "dep_mantida", "false", "true", ADMIN, True)], aud


def test_egp_novo_declarado_vai_para_a_config(app, banco):
    st, r = chama(app, "PATCH", "/api/egps-novos", {"projeto": "Jurídico__EGP_TREINO_029", "acao": "declarar"})
    assert st == 200, r
    (row,) = linhas(banco, "SELECT valor, updated_by, updated_at FROM legado.sas_app_config WHERE chave = 'egps_novos'")
    assert "Jurídico__EGP_TREINO_029" in row[0] and row[1] == ADMIN and INSTANTE_TEXTO.fullmatch(row[2]), row
    (aud,) = linhas(banco, "SELECT valor_novo, ator, ts FROM legado.sas_pipeline_audit "
                           "WHERE projeto = '(config)' AND campo = 'egps_novos'")
    assert "Jurídico__EGP_TREINO_029" in aud[0] and aud[1] == ADMIN and INSTANTE_TEXTO.fullmatch(aud[2]), aud


def test_egp_atualizado_grava_tipo_de_vinculo_e_audita(app, banco):
    grava(banco, "INSERT INTO legado.sas_egp_atualizados (versao_id, egp_key, nome, area) "
                 "VALUES ('v1', 'Riscos__EGP_NOVO', 'EGP NOVO', 'Riscos')")
    st, r = chama(app, "PATCH", "/api/egp-atualizado-pipeline", {"egp_key": "Riscos__EGP_NOVO",
                                                                 "tipo_vinculo": "substituicao"})
    assert st == 200, r
    (row,) = linhas(banco, "SELECT tipo_vinculo, updated_by FROM legado.sas_egp_atualizados_pipeline "
                           "WHERE egp_key = 'Riscos__EGP_NOVO'")
    assert row == ("substituicao", ADMIN), row
    (aud,) = linhas(banco, "SELECT campo, valor_novo, autor, length(id), ts IS NOT NULL "
                           "FROM legado.sas_egp_atualizados_audit WHERE egp_key = 'Riscos__EGP_NOVO'")
    assert aud == ("tipo_vinculo", "substituicao", ADMIN, 36, True), aud


# ------------------------------------------------------------------ Outputs
def test_pipeline_do_output(app, banco):
    st, r = chama(app, "PATCH", "/api/output-pipeline", {"chave_canonica": "tabela::SAIDA.X", "recebido": True,
                                                         "recebido_data": "2026-10-01"})
    assert st == 200, r
    (row,) = linhas(banco, "SELECT recebido, recebido_data, updated_by, updated_at FROM legado.sas_outputs_pipeline "
                           "WHERE chave_canonica = 'tabela::SAIDA.X'")
    assert row[:3] == ("true", "2026-10-01", ADMIN) and INSTANTE_TEXTO.fullmatch(row[3]), row


def test_produtor_escolhido_grava_e_apaga(app, banco):
    chave = "tabela::SAIDA.Y"
    for p in ("Cobranças__EGP_TREINO_003", "Riscos__EGP_TREINO_004"):
        grava(banco, "INSERT INTO legado.sas_egp_outputs (projeto, area, chave_canonica, artifact, categoria) "
                     "VALUES (%s, %s, %s, 'SAIDA.Y', 'tabela')", (p, p.split("__")[0], chave))
    grava(banco, "INSERT INTO legado.sas_outputs_monitor (chave_canonica, artifact, categoria, qtd_produtores) "
                 "VALUES (%s, 'SAIDA.Y', 'tabela', 2)", (chave,))
    st, r = chama(app, "POST", "/api/output-producer", {"chave_canonica": chave,
                                                        "projeto_escolhido": "Riscos__EGP_TREINO_004"})
    assert st == 200, r
    (row,) = linhas(banco, "SELECT projeto_escolhido, chosen_by, chosen_at FROM legado.sas_output_producer_choice "
                           "WHERE chave_canonica = %s", (chave,))
    assert row[:2] == ("Riscos__EGP_TREINO_004", ADMIN) and INSTANTE_TEXTO.fullmatch(row[2]), row
    st, r = chama(app, "DELETE", "/api/output-producer?chave=" + urllib.parse.quote(chave))
    assert st == 200, r
    assert linhas(banco, "SELECT count(*) FROM legado.sas_output_producer_choice WHERE chave_canonica = %s",
                  (chave,))[0][0] == 0


# ------------------------------------------------------------------ Escopo
def test_escopo_inclui_desativa_e_reativa_recalculando(app, banco):
    projeto = "Riscos__EGP_TREINO_028"
    assert linhas(banco, "SELECT escopo_indi FROM legado.sas_lineage_nodes WHERE projeto = %s", (projeto,)) == [(False,)]
    st, r = chama(app, "POST", "/api/escopo", {"egp_dor1": "EGP_TREINO_028", "area": "Riscos", "projeto": projeto})
    assert st == 200, r
    (rid, por, em) = linhas(banco, "SELECT id, created_by, created_at FROM legado.sas_escopo WHERE projeto = %s",
                            (projeto,))[0]
    assert por == ADMIN and INSTANTE_TEXTO.fullmatch(em), (por, em)
    assert linhas(banco, "SELECT escopo_indi FROM legado.sas_lineage_nodes WHERE projeto = %s", (projeto,)) == [(True,)]
    assert chama(app, "DELETE", f"/api/escopo/{rid}")[0] == 200
    assert linhas(banco, "SELECT escopo_indi FROM legado.sas_lineage_nodes WHERE projeto = %s", (projeto,)) == [(False,)]
    assert chama(app, "POST", f"/api/escopo/{rid}/ativar")[0] == 200
    assert linhas(banco, "SELECT escopo_indi FROM legado.sas_lineage_nodes WHERE projeto = %s", (projeto,)) == [(True,)]
    aud = linhas(banco, "SELECT acao, ator, ts FROM legado.sas_escopo_audit WHERE projeto = %s ORDER BY ts", (projeto,))
    assert [a[:2] for a in aud] == [("add", ADMIN), ("desativar", ADMIN), ("reativar", ADMIN)], aud
    assert all(INSTANTE_TEXTO.fullmatch(a[2]) for a in aud), aud


# ------------------------------------------------------------------ escritas dentro de GET
# Na Fase 1 a AWS só lia e quem gravava era o Databricks; com a escrita ligada (Fase 2) as
# duas voltam a valer também no Postgres — senão a série diária e a semente param na virada.
def test_get_da_fragilidade_grava_o_contador_do_dia(app, banco):
    st, r = chama(app, "GET", "/api/inputs/fragilidade")
    assert st == 200, r
    assert linhas(banco, "SELECT count(*) FROM legado.sas_app_config WHERE chave LIKE 'san_contadores::%'")[0][0] == 1


def test_get_da_priorizacao_sem_snapshot_grava_a_semente(app, banco):
    grava(banco, "DELETE FROM legado.sas_priorizacao_snapshot")   # sem snapshot, qualquer que seja a ordem
    st, r = chama(app, "GET", "/api/priorizacao")
    assert st == 200, r
    assert linhas(banco, "SELECT saved_by FROM legado.sas_priorizacao_snapshot WHERE id = 'current'") == [("auto",)]


# ------------------------------------------------------------------ Priorização
def test_snapshot_da_priorizacao(app, banco):
    fixado = "Riscos__EGP_TREINO_010"
    st, r = chama(app, "POST", "/api/priorizacao/snapshot", {"pins": {fixado: 3}, "capacidade": 5})
    assert st == 200, r
    (row,) = linhas(banco, "SELECT capacidade, saved_by, saved_at FROM legado.sas_priorizacao_snapshot "
                           "WHERE id = 'current'")
    assert row[:2] == (5, ADMIN) and INSTANTE_TEXTO.fullmatch(row[2]), row
    (pin,) = linhas(banco, "SELECT mes_prioridade, updated_by, updated_at FROM legado.sas_egp_pipeline "
                           "WHERE projeto = %s", (fixado,))
    assert pin[:2] == (3, ADMIN) and INSTANTE_TEXTO.fullmatch(pin[2]), pin
    (cap,) = linhas(banco, "SELECT valor, updated_by, updated_at FROM legado.sas_app_config "
                           "WHERE chave = 'prio_capacidade'")
    assert cap[:2] == ("5", ADMIN) and INSTANTE_TEXTO.fullmatch(cap[2]), cap
    aud = linhas(banco, "SELECT projeto, campo, valor_novo, ator, ts FROM legado.sas_pipeline_audit "
                        "WHERE (projeto = '(config)' AND campo IN ('capacidade_mes', 'priorizacao_snapshot')) "
                        "OR (projeto = %s AND campo = 'mes_prioridade') ORDER BY campo", (fixado,))
    assert [a[:2] for a in aud] == [("(config)", "capacidade_mes"), (fixado, "mes_prioridade"),
                                    ("(config)", "priorizacao_snapshot")], aud
    assert aud[0][2] == "5" and aud[1][2] == "3" and INSTANTE_TEXTO.fullmatch(aud[2][2]), aud   # a hora do snapshot
    assert all(a[3] == ADMIN and INSTANTE_TEXTO.fullmatch(a[4]) for a in aud), aud


# ------------------------------------------------------------------ Gestão
def test_gestao_status_comentario(app, banco):
    st, r = chama(app, "POST", "/api/gestao/status", {"entity": "egp", "id": EGP, "autor": "Fulano", "texto": "andando"})
    assert st == 200, r
    (row,) = linhas(banco, "SELECT autor, criado_por, texto, ts FROM legado.sas_gestao_status "
                           "WHERE entity_id = %s AND texto = 'andando'", (EGP,))
    assert row[:3] == ("Fulano", ADMIN, "andando") and INSTANTE_TEXTO.fullmatch(row[3]), row


def test_gestao_com_bv_grava_hoje_e_apaga(app, banco):
    def hoje_sp():
        return datetime.datetime.now(ZoneInfo("America/Sao_Paulo")).date().isoformat()

    antes = hoje_sp()
    st, r = chama(app, "POST", "/api/gestao/bv", {"entity": "egp", "id": EGP, "comBv": True})
    depois = hoje_sp()
    assert st == 200, r
    (bid, data, autor, ts) = linhas(banco, "SELECT id, data, autor, ts FROM legado.sas_gestao_bv WHERE entity_id = %s",
                                    (EGP,))[0]
    # sem data no corpo, vale HOJE em São Paulo (o dia pode virar durante a chamada)
    assert data in (antes, depois) and autor == ADMIN and INSTANTE_TEXTO.fullmatch(ts), (data, antes, autor, ts)
    assert chama(app, "DELETE", f"/api/gestao/bv?id={bid}")[0] == 200
    assert linhas(banco, "SELECT count(*) FROM legado.sas_gestao_bv WHERE id = %s", (bid,))[0][0] == 0
    aud = linhas(banco, "SELECT valor_antigo, valor_novo, ator, ts FROM legado.sas_pipeline_audit "
                        "WHERE projeto = %s AND campo = 'ComBV' ORDER BY ts", (EGP,))
    assert [a[:3] for a in aud] == [("-", "Com BV", ADMIN), ("Com BV", "DELETADO", ADMIN)], aud
    assert all(INSTANTE_TEXTO.fullmatch(a[3]) for a in aud), aud


def test_gestao_revisao_e_datas(app, banco):
    assert chama(app, "POST", "/api/gestao/revisao", {"id": EGP, "delta": 1})[0] == 200
    assert chama(app, "PATCH", "/api/gestao/datas", {"entity": "egp", "id": EGP, "campo": "inicio",
                                                     "valor": "2026-10-01"})[0] == 200
    (rev,) = linhas(banco, "SELECT contador, updated_by, updated_at FROM legado.sas_gestao_revisao "
                           "WHERE entity_id = %s", (EGP,))
    assert rev[:2] == (1, ADMIN) and INSTANTE_TEXTO.fullmatch(rev[2]), rev
    (dat,) = linhas(banco, "SELECT inicio, updated_by, updated_at FROM legado.sas_gestao_datas "
                           "WHERE entity_id = %s", (EGP,))
    assert dat[:2] == ("2026-10-01", ADMIN) and INSTANTE_TEXTO.fullmatch(dat[2]), dat
    aud = linhas(banco, "SELECT campo, valor_antigo, valor_novo, ator, ts FROM legado.sas_pipeline_audit "
                        "WHERE projeto = %s AND campo IN ('RevisaoRegras', 'inicio') ORDER BY campo", (EGP,))
    assert [a[:4] for a in aud] == [("RevisaoRegras", "0", "1", ADMIN), ("inicio", "", "2026-10-01", ADMIN)], aud
    assert all(INSTANTE_TEXTO.fullmatch(a[4]) for a in aud), aud
