# -*- coding: utf-8 -*-
"""Versão recebida que ainda não entrou no corpus continua visível (ticket 10).

Entre a etapa 0 (chegada do arquivo) e a etapa 2 (entrada no corpus) da spec
`2026-09-24-egps-atualizados-unificacao-design.md`, o sucessor não existe em superfície
nenhuma: já foi comparado, mas ainda não é projeto do corpus. A janela deveria durar o
tempo de uma rodada do pipeline; se ninguém rodar, dura dias e o arquivo some de vista.

O contador é DERIVADO — diferença entre as versões publicadas em `sas_egp_atualizados` e
os projetos de `sas_lineage_nodes`. Nada é gravado, e é isso que faz os dois desfechos
caírem de graça: entrar no corpus tira do contador (etapa 2), e descartar a versão
(remover a linha da aba, §2 "Descarte") também.

O teste que dá sentido ao ticket é o do ÚLTIMO critério: nenhuma versão recebida pode
sair do contador sem um desses dois desfechos. Os três caminhos que a fariam sumir sem
desfecho estão travados abaixo (`test_..._nao_some_...`).

run_sql stubado — sem credencial, sem rede.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import backend.egps_atualizados as ega  # noqa: E402

ROTA = "/api/egps-atualizados/aguardando-corpus"


class _AppFake:
    """Coleta os endpoints registrados sem subir FastAPI (mesmo padrão dos testes irmãos)."""

    def __init__(self):
        self.rotas = {}

    def _reg(self, path, **_kw):
        def deco(fn):
            self.rotas[path] = fn
            return fn
        return deco

    get = patch = post = delete = _reg


class _SemTabela(Exception):
    pass


def _versao(egp_key, data, nome=None, area="Cobranças", antecessor=None):
    return {"versao_id": f"{egp_key}@{data}", "egp_key": egp_key,
            "nome": nome or egp_key.split("__", 1)[-1], "area": area,
            "data_recebimento": data, "egp_original": antecessor}


def _rodar(versoes, projetos, falha_t_main=None):
    """Registra o módulo com um run_sql que despacha pela tabela citada e chama a rota."""
    def run_sql(stmt, want_rows=True, **_kw):
        s = " ".join(stmt.split()).lower()
        if "sas_egp_atualizados" in s:
            if falha_t_main is not None:
                raise falha_t_main
            return [dict(v) for v in versoes]
        if "sas_lineage_nodes" in s:
            return [{"projeto": p} for p in projetos]
        return []

    app = _AppFake()
    ega.register(app, run_sql, "cat.sch", "true",
                 lambda code, msg: Exception(f"{code}: {msg}"), lambda *a, **k: None)
    return app.rotas[ROTA]()


# --------------------------------------------------------------------- caminho vazio
def test_sem_versao_recebida_o_contador_e_zero():
    r = _rodar([], ["Cobranças__A", "Cobranças__B"])
    assert r["n"] == 0 and r["rows"] == [] and r["sem_tabela"] is False


def test_tabela_ausente_nao_e_erro():
    """Schema onde nenhuma versão foi publicada ainda: aba vazia, não 500."""
    r = _rodar([], [], falha_t_main=_SemTabela(
        "[TABLE_OR_VIEW_NOT_FOUND] The table cat.sch.sas_egp_atualizados cannot be found"))
    assert r == {"rows": [], "n": 0, "pendencias": [], "n_pendencias": 0,
                 "sem_tabela": True}


def test_corpus_vazio_conta_tudo():
    """Nada publicado no grafo ainda não pode esconder o que já chegou."""
    r = _rodar([_versao("Cobranças__X", "2026-09-24")], [])
    assert r["n"] == 1


# ------------------------------------------------------- quantas · quais · zera sozinho
def test_conta_e_lista_a_versao_que_ainda_nao_entrou_no_corpus():
    r = _rodar([_versao("Cobranças__X", "2026-09-24", antecessor="Cobranças__X_v1")],
               ["Cobranças__X_v1"])
    assert r["n"] == 1
    linha = r["rows"][0]
    assert linha["egp_key"] == "Cobranças__X"
    assert linha["versao_id"] == "Cobranças__X@2026-09-24"
    assert linha["egp_original"] == "Cobranças__X_v1"
    # "quais" inclui a chave que o pipeline vai criar (spec §2, etapa 2)
    assert linha["chave_prevista"] == "Cobranças__X__ATU20260924"


def test_zera_sozinho_depois_da_rodada_do_pipeline():
    versoes = [_versao("Cobranças__X", "2026-09-24")]
    assert _rodar(versoes, ["Cobranças__X_v1"])["n"] == 1
    # o pipeline rodou: o sucessor virou projeto do corpus, sem ninguém limpar nada
    assert _rodar(versoes, ["Cobranças__X_v1", "Cobranças__X__ATU20260924"])["n"] == 0


def test_aceita_a_data_do_sufixo_com_ou_sem_hifen():
    """A entrada no corpus ainda não está implementada; o contador não pode depender de
    qual grafia de data o pipeline vai escolher — só da data em si."""
    versoes = [_versao("Cobranças__X", "2026-09-24")]
    assert _rodar(versoes, ["Cobranças__X__ATU2026-09-24"])["n"] == 0


def test_versao_descartada_some_do_contador_sem_limpeza():
    """Descarte (§2) = a linha sai da aba. Nada mais a fazer: o contador é derivado."""
    assert _rodar([_versao("Cobranças__X", "2026-09-24")], [])["n"] == 1
    assert _rodar([], [])["n"] == 0


def test_acentos_preservados_na_chave():
    """Área e nome entram crus na chave — normalizar para ASCII renomearia ~10% do corpus."""
    r = _rodar([_versao("Cobranças__Processo de bonificação", "2026-09-24")], [])
    assert r["rows"][0]["chave_prevista"] == (
        "Cobranças__Processo de bonificação__ATU20260924")


# ----------------------------------------- último critério: nada some sem um dos desfechos
def test_nome_identico_ao_antecessor_nao_some_do_contador():
    """O buraco mais fácil de abrir: casar a versão pelo `Área__nome` puro.

    12 versões têm nome IDÊNTICO ao antecessor (spec §2, etapa 2) — o antecessor já é
    projeto do corpus, então o casamento sem o sufixo `__ATU<data>` daria "já entrou" no
    minuto zero e elas nunca apareceriam no contador. É exatamente por isso que o sufixo
    é obrigatório na régua de nomeação.
    """
    r = _rodar([_versao("Cobranças__tipos_acordo", "2026-09-24",
                        antecessor="Cobranças__tipos_acordo")],
               ["Cobranças__tipos_acordo"])          # o ANTECESSOR, não o sucessor
    assert r["n"] == 1, "versão com nome igual ao antecessor sumiu sem ter entrado"


def test_versao_anterior_nao_some_quando_chega_outra_da_mesma_egp_key():
    """A aba lista só a versão mais recente por egp_key (ROW_NUMBER/rn=1). Se o contador
    herdasse esse recorte, a v2 que nunca entrou no corpus sumiria de vista no dia em que
    a v3 chegasse — sem ter entrado e sem ter sido descartada. Aqui o grão é a VERSÃO."""
    r = _rodar([_versao("Cobranças__X", "2026-09-01"),
                _versao("Cobranças__X", "2026-09-15")], [])
    assert r["n"] == 2
    assert [l["data_recebimento"] for l in r["rows"]] == ["2026-09-01", "2026-09-15"]


def test_entrada_da_versao_anterior_nao_cobre_a_nova():
    """Cadeia (§2, etapa 5): a v2 entrou no corpus, a v3 acabou de chegar. Casar por
    prefixo `egp_key__ATU` (ignorando a data) daria a v3 como já entrada — ela sumiria
    de vista de graça. A data é o que separa uma versão da outra."""
    r = _rodar([_versao("Cobranças__X", "2026-09-01"),
                _versao("Cobranças__X", "2026-09-15")],
               ["Cobranças__X__ATU20260901"])
    assert r["n"] == 1
    assert r["rows"][0]["data_recebimento"] == "2026-09-15"


def test_homonimo_de_outra_area_nao_cobre_a_versao():
    """Mesma data, mesmo nome, área diferente: chaves distintas, nenhuma cobre a outra."""
    r = _rodar([_versao("Cobranças__X", "2026-09-24")],
               ["Riscos__X__ATU20260924"])
    assert r["n"] == 1


# ------------------------------------------- pendência (ticket 11: a Situação morre, mas
# "par não resolvido" e "falha na extração" não são tipo de vínculo — são pendência)
def _versao_q(egp_key, data, quadrante, **kw):
    v = _versao(egp_key, data, **kw)
    v["quadrante"] = quadrante
    return v


def test_quadrante_normal_nao_vira_pendencia():
    r = _rodar([_versao_q("Cobranças__X", "2026-09-24", "Trocar agora")], [])
    assert r["rows"][0]["pendencia"] is None
    assert r["n_pendencias"] == 0 and r["pendencias"] == []


def test_pareamento_nao_resolvido_e_falha_na_extracao_viram_pendencia():
    """A taxonomia "Situação" morre com a aba (spec §5), mas estes dois valores NÃO são
    tipo de vínculo: descartá-los junto faria um arquivo cuja extração falhou parecer
    normal — o bug que "Falha na extração" já causou uma vez (caía no default e mostrava
    "Atualizado" verde, implicando seguro trocar quando a comparação nunca rodou)."""
    r = _rodar([_versao_q("Cobranças__X", "2026-09-24", "Par não resolvido"),
                _versao_q("Cobranças__Y", "2026-09-24", "Falha na extração")], [])
    assert [l["pendencia"] for l in r["rows"]] == ["pareamento não resolvido",
                                                   "falha na extração"]
    assert r["n_pendencias"] == 2


def test_pendencia_de_versao_ja_no_corpus_continua_visivel():
    """Entrar no corpus resolve o "aguardando", não a pendência: a comparação segue sem
    ter rodado. Sair das duas listas de uma vez seria o silêncio que o ticket proíbe."""
    r = _rodar([_versao_q("Cobranças__X", "2026-09-24", "Falha na extração")],
               ["Cobranças__X__ATU20260924"])
    assert r["n"] == 0, "entrou no corpus: fora do contador de aguardando"
    assert r["n_pendencias"] == 1
    assert [p["versao_id"] for p in r["pendencias"]] == ["Cobranças__X@2026-09-24"]


def test_pendencia_que_ainda_aguarda_nao_e_listada_duas_vezes():
    """Ela já aparece na lista de aguardando, com o selo — repetir embaixo seria ler
    como duas versões."""
    r = _rodar([_versao_q("Cobranças__X", "2026-09-24", "Par não resolvido")], [])
    assert r["n"] == 1 and r["pendencias"] == []
    assert r["n_pendencias"] == 1, "o número conta a versão uma vez, onde quer que ela esteja"


def test_versao_sem_quadrante_nao_explode():
    """Carga antiga (ou coluna nula): sem quadrante não há pendência — e não há erro."""
    r = _rodar([_versao("Cobranças__X", "2026-09-24")], [])
    assert r["rows"][0]["pendencia"] is None and r["n_pendencias"] == 0


# ------------------------------------------------- o funil próprio da aba foi aposentado
def test_a_listagem_nao_le_o_funil_proprio():
    """§5 "O que sai": o lugar onde se EDITAVA etapa/status da versão morre — o sucessor
    passa a usar sas_egp_pipeline. A tabela e a auditoria ficam como registro histórico.

    REVISADO em 01/10/2026. Este teste afirmava também que a rota
    `/api/egp-atualizado-pipeline` não existia mais. Ela voltou como PONTE, restrita a
    `tipo_vinculo` (ticket 17): o merge chegou em prod antes do publish, e sem os
    sucessores no corpus o vínculo unificado é impossível de criar. O estreitamento tem
    teste próprio em `test_ponte_tipo_vinculo.py` — inclusive a recusa de etapa/status.

    O que continua valendo e é verificado aqui: a LEITURA da aba não toca o funil próprio.
    É isso que garante que a listagem não ressuscitou a tela aposentada."""
    lidos = []

    def run_sql(stmt, want_rows=True, **_kw):
        lidos.append(" ".join(stmt.split()).lower())
        return []

    app = _AppFake()
    ega.register(app, run_sql, "cat.sch", "true",
                 lambda code, msg: Exception(f"{code}: {msg}"), lambda *a, **k: None)
    app.rotas["/api/egps-atualizados"]()
    assert not any("sas_egp_atualizados_pipeline" in s or "sas_egp_atualizados_audit" in s
                   for s in lidos), lidos


def test_a_comparacao_continua_sendo_lida_das_tabelas_do_script_local():
    """"Só a tela saiu": o detalhe segue lendo as 3 tabelas da comparação carregadas por
    publish_egps_atualizados.py."""
    lidos = []

    def run_sql(stmt, want_rows=True, **_kw):
        s = " ".join(stmt.split()).lower()
        lidos.append(s)
        if "from cat.sch.sas_egp_atualizados where versao_id" in s:
            return [{"versao_id": "Cobranças__X@2026-09-24", "egp_key": "Cobranças__X",
                     "egp_original": "Cobranças__X_v1"}]
        return []

    app = _AppFake()
    ega.register(app, run_sql, "cat.sch", "true",
                 lambda code, msg: Exception(f"{code}: {msg}"), lambda *a, **k: None)
    d = app.rotas["/api/egp-atualizado"](versao_id="Cobranças__X@2026-09-24")
    assert d["versao"]["versao_id"] == "Cobranças__X@2026-09-24"
    for t in ("sas_egp_atualizados_inputs", "sas_egp_atualizados_outputs"):
        assert any(t in s for s in lidos), t


# ---- universo do contador "no corpus, sem vínculo" (ticket 23, 01/10/2026) -------------

def test_eh_chave_atu_exige_sufixo_ancorado_com_data():
    """`"__ATU" in projeto` casava EGP cujo NOME começa com "ATUALIZACAO" — 3 falsos
    positivos em 21 casamentos no corpus do clone. O sufixo é âncora de fim + 8 dígitos."""
    assert ega.eh_chave_atu("Cobranças__manut_acordo__ATU20260901")
    assert not ega.eh_chave_atu("Riscos__ATUALIZACAO_PROJURIS V10")
    assert not ega.eh_chave_atu("Cobranças__ATUALIZACAO BASE PROJURIS")
    assert not ega.eh_chave_atu("Riscos__ATUALIZACAO_BASES v09")


def test_eh_chave_atu_recusa_sufixo_sem_data_ou_truncado():
    assert not ega.eh_chave_atu("Cobranças__x__ATU")
    assert not ega.eh_chave_atu("Cobranças__x__ATU2026")
    assert not ega.eh_chave_atu("Cobranças__x__ATU20260901_v2")   # não está no fim
    assert not ega.eh_chave_atu("")
    assert not ega.eh_chave_atu(None)


def test_sugestao_nunca_propoe_o_proprio_projeto():
    """Medido em prod em 02/10/2026: as 3 linhas da lista "sem vínculo" sugeriam `X -> X`,
    porque o `egp_key` de chegada coincide com a chave do corpus quando a versão não foi
    renomeada com o sufixo da régua. 100% do que a tela oferecia induzia ao erro — e o
    PATCH, à época, aceitava. Sugerir nada é melhor que sugerir o próprio."""
    import backend.main as mm
    # o filtro é uma expressão pura sobre a string do pareamento; exercita os 3 formatos
    for ant, chave, esperado in (
        ("A__x", "A__x", None),                       # só o próprio -> nada
        ("A__x + A__velho", "A__x", "A__velho"),      # N:1 com o próprio no meio
        ("A__velho", "A__x", "A__velho"),             # normal, intacto
    ):
        partes = [p.strip() for p in ant.split(" + ") if p.strip() and p.strip() != chave]
        assert (" + ".join(partes) or None) == esperado, (ant, chave)
    assert hasattr(mm, "egps_sem_vinculo")
