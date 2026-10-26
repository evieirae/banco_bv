# -*- coding: utf-8 -*-
"""Versões novas de EGP enviadas pelo cliente — comparação com o antecessor.

A ABA dedicada foi aposentada (spec §5, ticket 11): o sucessor é linha da aba EGPs e a
comparação virou seção do detalhe do EGP. O MÓDULO fica — ele é a única fonte da
comparação, que não existe em nenhum outro lugar.

Backend READ-ONLY sobre tabelas próprias (sas_egp_atualizados / _inputs / _outputs),
carregadas exclusivamente pelo script local egps_analysis/publish_egps_atualizados.py.
Isolamento é de ESCRITA, não de leitura (docs/adr/0001): este módulo nunca escreve em
tabela alguma; a partir do ticket 03 ele LÊ sas_inputs_monitor (JOIN vivo) para a
disponibilidade dos inputs. Com a aposentadoria ele voltou a ser read-only puro: o funil
próprio (sas_egp_atualizados_pipeline/_audit) era o único ponto de escrita e saiu junto
com a tela — as duas tabelas ficam como registro histórico, sem serem lidas pelo app.

Sem criação de tabela aqui: quem cria é o script local. Tabela ausente = lista vazia,
não erro (o app pode subir num schema onde nenhuma versão foi publicada ainda).

Registrado em main.py via register(app, run_sql, fq) — padrão de módulo irmão sem
APIRouter, seguindo o main.py (endpoints @app.get diretos).
"""

import re
import sys
from decimal import Decimal, ROUND_HALF_UP

import dialeto

# Colunas expostas na LISTA (uma linha por EGP = versão recebida mais recente).
# O detalhe (inputs/outputs/histórico) chega no ticket 03/05.
_COLS_LISTA = (
    "versao_id, egp_key, nome, area, egp_original, n_antecessores, confianca_par, "
    "quadrante, valor, esforco, razao, n_vetos, autor_ultimo_save, data_ultimo_save, "
    "data_recebimento, status_troca"
)

_INT = ("n_antecessores", "n_vetos", "n_versoes", "n_inputs", "n_disp", "n_novos")
_FLOAT = ("valor", "esforco", "razao", "pct", "overlap_tasks")


def _tipa(row: dict) -> dict:
    """StatementExecution devolve tudo string; converte os numéricos da lista."""
    for c in _INT:
        if row.get(c) is not None:
            try:
                row[c] = int(row[c])
            except (TypeError, ValueError):
                pass
    for c in _FLOAT:
        if row.get(c) is not None:
            try:
                row[c] = float(row[c])
            except (TypeError, ValueError):
                pass
    return row


def _tabela_ausente(exc, nome_tabela: str) -> bool:
    """A tabela ausente é a DESTA aba (= nada publicado ainda), não outra qualquer.

    Antes bastava o erro citar TABLE_OR_VIEW_NOT_FOUND para a aba renderizar "nada
    publicado": se sas_inputs_monitor ou sas_egp_inputs (tabelas CORE do corpus, não
    desta aba) sumissem ou fossem renomeadas, o usuário via uma aba vazia em vez de
    um erro — e nada ia para o log. "CANNOT BE FOUND" também casava mensagens de
    função/schema não encontrados."""
    msg = str(getattr(exc, "detail", exc) or "").upper()
    if "TABLE_OR_VIEW_NOT_FOUND" not in msg and "CANNOT BE FOUND" not in msg:
        return False
    return nome_tabela.split(".")[-1].upper() in msg


# --- versões recebidas que ainda não entraram no corpus (spec §5, "O buraco que A abre")
#
# Entre a chegada do arquivo (etapa 0) e a entrada no corpus (etapa 2) o sucessor não
# existe em superfície nenhuma. O contador que o mantém visível é DERIVADO: diferença
# entre as versões publicadas aqui e os projetos do grafo, calculada na hora. Nada é
# gravado — por isso ele zera sozinho quando o pipeline roda e some sozinho quando a
# versão é descartada (§2, "Descarte" = a linha sai da aba), sem limpeza manual.
_ATU = "__ATU"

# A taxonomia "Situação" da aba morreu com ela (§5, "O que sai") — ficou o Tipo de vínculo
# (Atualizado/Substituído/Unificado, em sas_egp_pipeline). Mas dois dos valores da Situação
# NÃO são tipo de vínculo: eles dizem que a comparação não pôde ser feita. Descartá-los
# junto faria um arquivo cuja extração falhou parecer normal — que é exatamente o bug que
# "Falha na extração" já causou uma vez aqui (sem branch própria, caía no default e
# aparecia como "Atualizado" verde, implicando seguro trocar). Viram PENDÊNCIA.
PENDENCIA_POR_QUADRANTE = {
    "Par não resolvido": "pareamento não resolvido",
    "Falha na extração": "falha na extração",
}


def pendencia_de(quadrante) -> str | None:
    return PENDENCIA_POR_QUADRANTE.get((quadrante or "").strip())


def _digitos(v) -> str:
    return re.sub(r"\D", "", str(v or ""))


def chave_prevista(egp_key: str, data_recebimento) -> str:
    """Chave que a versão terá ao virar projeto do corpus: `Área__nome__ATU<data>`.

    O sufixo é obrigatório na régua de nomeação (spec §2, etapa 2) porque 12 versões têm
    nome IDÊNTICO ao antecessor — e o antecessor já é projeto do corpus. Casar pela chave
    `Área__nome` pura daria "já entrou" no minuto zero para essas 12, que nunca chegariam
    a aparecer no contador."""
    return f"{egp_key}{_ATU}{_digitos(data_recebimento)}"


# ANCORADO no fim da chave, e com a data obrigatória. `_ATU in projeto` casa também
# `Cobranças__ATUALIZACAO BASE PROJURIS` e `Riscos__ATUALIZACAO_PROJURIS V10`, que não são
# versão de nada — medido em 01/10/2026: 3 falsos positivos em 21 casamentos por substring.
_RE_SUFIXO_ATU = re.compile(r"__ATU\d{8}$")


def eh_chave_atu(projeto: str) -> bool:
    """O projeto nasceu de uma versão recebida, pela régua de nomeação (§2, etapa 2)?

    Serve ao universo do contador "no corpus, sem vínculo": a tabela de chegada
    (`sas_egp_atualizados`) não conhece EGP que entrou por fora dela — pela skill, por
    carga manual — e esses somem exatamente como o ticket 23 descreve."""
    return bool(_RE_SUFIXO_ATU.search(projeto or ""))


def _id_atu(projeto: str):
    """(chave base, data em dígitos) de um projeto do corpus nascido de versão recebida.

    A data entra normalizada porque a etapa 2 ainda não está implementada e a grafia do
    sufixo (`2026-09-24` ou `20260924`) ainda não está decidida — mas ela entra: casar só
    pelo prefixo `egp_key__ATU` faria a entrada da v2 cobrir a v3 recém-chegada, que
    sumiria de vista sem ter entrado no corpus nem sido descartada."""
    if _ATU not in projeto:
        return None
    base, _, suf = projeto.rpartition(_ATU)
    return base, _digitos(suf)


def pendentes_de_corpus(versoes, projetos):
    """As versões recebidas que ainda não viraram projeto do corpus, na ordem de chegada.

    O grão é a VERSÃO, não a egp_key: a lista da aba mostra só a mais recente de cada
    egp_key (rn = 1), e herdar esse recorte faria uma versão que nunca entrou sumir do
    contador no dia em que a seguinte chegasse — um terceiro desfecho, invisível.

    Casamento estrito de propósito: versão que entrou no corpus com outra grafia continua
    contada (falso positivo, visível e corrigível) em vez de sumir em silêncio."""
    no_corpus = {k for k in (_id_atu((p or "").strip()) for p in projetos) if k}
    rows = [_linha(v) for v in versoes
            if ((v.get("egp_key") or "").strip(),
                _digitos(v.get("data_recebimento"))) not in no_corpus]
    rows.sort(key=_ordem)
    return rows


def _linha(v) -> dict:
    return {
        "versao_id": v.get("versao_id"),
        "egp_key": (v.get("egp_key") or "").strip(),
        "nome": v.get("nome"),
        "area": v.get("area"),
        "data_recebimento": v.get("data_recebimento"),
        "egp_original": v.get("egp_original"),
        "chave_prevista": chave_prevista((v.get("egp_key") or "").strip(),
                                         v.get("data_recebimento")),
        "pendencia": pendencia_de(v.get("quadrante")),
    }


def _ordem(r):
    return (r["data_recebimento"] or "", r["egp_key"] or "")


def pendencias_fora(versoes, ja_listadas):
    """Versões com pendência que NÃO estão na lista de aguardando (= já entraram no corpus).

    Entrar no corpus resolve o "aguardando", não a pendência: a comparação continua sem ter
    rodado. Sair das duas listas de uma vez devolveria o silêncio que o contador existe para
    quebrar. Quem ainda aguarda não se repete aqui — já aparece lá, com o selo.
    """
    rows = [_linha(v) for v in versoes
            if pendencia_de(v.get("quadrante")) and v.get("versao_id") not in ja_listadas]
    rows.sort(key=_ordem)
    return rows


def register(app, run_sql, fq: str, modern_expr: str, http_exc, enrich_contexto,
             familia_por_chave=None, on_write=None, ator=lambda: "current_user()",
             agora="current_timestamp()"):
    """modern_expr: predicado SQL de "input resolvido" do main (_modern), renderizado
    sobre os aliases i (sas_inputs_monitor) e ma (agregado de modernizada_auto por
    chave). http_exc: classe HTTPException do FastAPI. enrich_contexto:
    _enrich_egp_contexto do main — funil + recorte (indi/dep/ex/fora) dos antecessores,
    com os MESMOS conjuntos das abas EGPs/Inputs (fecho cacheado por geração).
    familia_por_chave: _familia_por_chave do main — {chave física -> chave de família},
    para o link do input apontar para a linha que a aba Inputs exibe (FAMILIAS_SAFRA=1).
    Ausente (ou flag desligada) => nenhum remapeamento, o link usa a chave física.
    on_write: chamado depois de cada escrita bem-sucedida — no main, `_bump_gen`. O
    payload de /api/egp-readiness (cacheado por geração lá) lê tipo_vinculo daqui; sem
    o gancho, o rótulo ficava velho por até 5 min, inclusive para quem acabou de clicar.
    ator / agora: quem e quando gravam (Fase 2, ADR 0005). `ator` é um chamável sem
    argumento que devolve a expressão SQL do autor; é avaliado a cada escrita, porque
    depende do usuário da requisição (no main, `_ator`, que lê o ContextVar do e-mail).
    `agora` é uma string SQL fixa (no main, `AGORA`). O padrão dos dois é o SQL do
    Databricks."""
    t_main = f"{fq}.sas_egp_atualizados"
    t_in = f"{fq}.sas_egp_atualizados_inputs"
    t_out = f"{fq}.sas_egp_atualizados_outputs"
    t_mon = f"{fq}.sas_inputs_monitor"
    t_egp = f"{fq}.sas_egp_inputs"
    t_nd = f"{fq}.sas_lineage_nodes"
    t_egp_pipe = f"{fq}.sas_egp_pipeline"   # funil de MIGRAÇÃO do corpus (pré-working do antecessor)
    # PONTE (ver o PATCH lá embaixo): tabelas do funil próprio da aba aposentada. Só o
    # tipo_vinculo ainda é escrito aqui; etapa/status/responsável morreram com a aba.
    t_pipe = f"{fq}.sas_egp_atualizados_pipeline"
    t_aud = f"{fq}.sas_egp_atualizados_audit"
    _TIPOS_VINCULO = ("atualizacao", "substituicao", "agrupamento")

    # modernizada_auto vive no grão (EGP do corpus × input); para um input da versão
    # recebida agregamos: alguma ocorrência 'Disponível' vale como auto-modernizado.
    _ma = (f"(SELECT chave_canonica, max(CASE WHEN modernizada_auto = 'Disponível' "
           f"THEN 'Disponível' END) AS auto FROM {t_egp} GROUP BY chave_canonica)")

    # Disponível "vivo": casa no corpus e o monitor diz resolvido; fora do corpus, vale a
    # situação congelada na carga (híbrido do grilling Q12 / ADR 0001).
    _disp_vivo = (f"CASE WHEN i.chave_canonica IS NOT NULL THEN ({modern_expr}) "
                  f"ELSE v.situacao_no_recebimento = 'disponivel' END")

    _prontidao = f"""
        (SELECT v.versao_id,
                count(*) AS n_inputs,
                sum(CASE WHEN {_disp_vivo} THEN 1 ELSE 0 END) AS n_disp,
                sum(CASE WHEN v.novo THEN 1 ELSE 0 END) AS n_novos
         FROM {t_in} v
         LEFT JOIN {t_mon} i ON v.chave_canonica = i.chave_canonica
         LEFT JOIN {_ma} ma ON ma.chave_canonica = v.chave_canonica
         GROUP BY v.versao_id)
    """

    # Estado do(s) antecessor(es), anexado vivo a cada versão via _enrich_egp_contexto
    # do main (fonte única, mesma das abas EGPs/Inputs): etapa/status do funil de
    # migração + `recorte` (indi = escopo direto · dep = dependência transitiva · ex ·
    # fora). O fecho transitivo é cacheado por geração no main (_cache_lineage), então
    # anexar na LISTA é barato — e o recorte sustenta o seletor "Indicium + dependências"
    # da aba. Falha do enrich = antecessores sem estado (badge não aparece), nunca 500.
    def _split_ants(v):
        return [a.strip() for a in (v or "").split(" + ") if a.strip()]

    def _anexa_antecessores(rows):
        nomes = sorted({a for r in rows for a in _split_ants(r.get("egp_original"))})
        est = {}
        pw = {}
        if nomes:
            ctx = [{"projeto": a} for a in nomes]
            try:
                enrich_contexto(ctx)
                est = {c["projeto"]: c for c in ctx}
            except Exception as e:
                # Degradar sem 500 é deliberado (a aba é read-only), mas SEM log a
                # falha era invisível: todo antecessor fica sem etapa/status/recorte,
                # e "sem badge" é visualmente idêntico a "antecessor fora do funil" —
                # que é justamente o estado que sugere que a troca é segura.
                print(f"[egps-atualizados] enrich_contexto falhou "
                      f"({type(e).__name__}: {e}); antecessores ficam sem estado",
                      file=sys.stderr)
                est = {}
            # Preworking do(s) antecessor(es), vindo do funil de MIGRAÇÃO (sas_egp_pipeline)
            # — leitura best-effort, mesmo espírito do enrich acima: um antecessor sem linha
            # no pipeline (nunca chegou lá) fica sem badge, não derruba a lista.
            try:
                nomes_in = ", ".join(_sql_str(a) for a in nomes)
                pw = {r["projeto"]: r for r in (run_sql(
                    f"SELECT projeto, preworking_preenchido, preworking_data "
                    f"FROM {t_egp_pipe} WHERE projeto IN ({nomes_in})") or [])}
            except Exception as e:
                print(f"[egps-atualizados] leitura de preworking do antecessor falhou "
                      f"({type(e).__name__}: {e})", file=sys.stderr)
                pw = {}
        for r in rows:
            r["antecessores"] = [{
                "projeto": a,
                "etapa": (est.get(a) or {}).get("etapa"),
                "status": (est.get(a) or {}).get("status"),
                "recorte": (est.get(a) or {}).get("escopo"),
                "preworking": (str((pw.get(a) or {}).get("preworking_preenchido")).lower() == "true")
                    if a in pw else None,
                "preworking_data": (pw.get(a) or {}).get("preworking_data"),
            } for a in _split_ants(r.get("egp_original"))]

    @app.get("/api/egps-atualizados")
    def egps_atualizados_lista():
        """Uma linha por egp_key (a versão recebida mais recente).

        Sem a aba, sobra como CATÁLOGO: alimenta a busca do AtualizadoLinkButton (vincular
        um EGP do corpus à versão recebida) no detalhe do EGP."""
        sql = f"""
            SELECT m.*, coalesce(p.n_inputs, 0) AS n_inputs,
                   coalesce(p.n_disp, 0) AS n_disp,
                   coalesce(p.n_novos, 0) AS n_novos,
                   CASE WHEN coalesce(p.n_inputs, 0) = 0 THEN 100.0
                        ELSE round(100.0 * p.n_disp / p.n_inputs, 1) END AS pct
            FROM (
                SELECT {_COLS_LISTA}, n_versoes FROM (
                    SELECT {_COLS_LISTA},
                           COUNT(*) OVER (PARTITION BY egp_key) AS n_versoes,
                           ROW_NUMBER() OVER (
                               PARTITION BY egp_key
                               ORDER BY data_recebimento DESC, publicado_em DESC) AS rn
                    FROM {t_main}
                ) WHERE rn = 1
            ) m
            LEFT JOIN {_prontidao} p ON p.versao_id = m.versao_id
            ORDER BY m.area NULLS FIRST, m.nome NULLS FIRST
        """
        try:
            rows = run_sql(sql) or []
        except Exception as e:
            if _tabela_ausente(e, t_main):
                return {"rows": [], "sem_tabela": True}
            # Qualquer outra tabela ausente (sas_inputs_monitor, sas_egp_inputs...) é
            # problema real de schema, não "aba ainda vazia" — sobe e fica no log.
            print(f"[egps-atualizados] lista falhou ({type(e).__name__}: {e})",
                  file=sys.stderr)
            raise
        rows = [_tipa(r) for r in rows]
        _anexa_antecessores(rows)
        return {"rows": rows, "sem_tabela": False}

    @app.get("/api/egps-atualizados/aguardando-corpus")
    def egps_atualizados_aguardando_corpus():
        """Versões recebidas que ainda não viraram projeto do corpus (spec §5).

        A guarda que repõe o que a aba dedicada fazia, agora que ela foi aposentada: sem
        ela, "chegou versão nova" vira um fato que ninguém vê. TODAS as versões, não só
        a mais recente por egp_key — ver pendentes_de_corpus().

        Carrega também as PENDÊNCIAS (pareamento não resolvido / falha na extração): elas
        não têm equivalente no Tipo de vínculo e sumiriam com a taxonomia "Situação".
        `n_pendencias` conta a versão UMA vez, esteja ela em `rows` (com o selo) ou em
        `pendencias` (já entrou no corpus, mas a comparação segue sem ter rodado)."""
        try:
            versoes = run_sql(
                f"SELECT versao_id, egp_key, nome, area, data_recebimento, egp_original, "
                f"quadrante FROM {t_main}") or []
        except Exception as e:
            if _tabela_ausente(e, t_main):
                return {"rows": [], "n": 0, "pendencias": [], "n_pendencias": 0,
                        "sem_tabela": True}
            print(f"[egps-atualizados] aguardando-corpus falhou "
                  f"({type(e).__name__}: {e})", file=sys.stderr)
            raise
        # Só os projetos que PODEM ter nascido de uma versão recebida: o corpus tem
        # ~1.400 nós e o casamento exato acontece em Python, então o LIKE é um
        # superconjunto barato — não a regra (ela está em _id_atu).
        projetos = [r.get("projeto") or "" for r in run_sql(
            f"SELECT projeto FROM {t_nd} WHERE projeto LIKE '%ATU%'") or []]
        rows = pendentes_de_corpus(versoes, projetos)
        pend = pendencias_fora(versoes, {r["versao_id"] for r in rows})
        n_pend = sum(1 for r in rows if r["pendencia"]) + len(pend)
        return {"rows": rows, "n": len(rows), "pendencias": pend,
                "n_pendencias": n_pend, "sem_tabela": False}

    @app.patch("/api/egp-atualizado-pipeline")
    def egp_atualizado_tipo_vinculo(payload: dict):
        """PONTE TEMPORÁRIA — classifica o `tipo_vinculo` da troca (grão `egp_key`).

        ## Por que isto existe depois de a aba ter sido aposentada

        O ticket 11 aposentou a aba EGPs Atualizados e, com ela, este endpoint — que
        gravava etapa/status/responsável/responsavel_bv/tipo_vinculo no funil PRÓPRIO
        (`sas_egp_atualizados_pipeline`, paralelo ao `sas_egp_pipeline` do corpus).

        Acontece que o merge chegou em prod ANTES do publish que leva os sucessores ao
        corpus. Medido em 01/10/2026: prod tem 0 vínculos no eixo unificado
        (`sas_egp_pipeline.egp_vinculo_tipo`) e os 3 sucessores não estão em
        `sas_lineage_nodes` — então criar o vínculo certo lá é IMPOSSÍVEL hoje (o
        `PATCH /api/egp-pipeline` recusa com 404). E a classificação está em uso: a
        última escrita é de 01/10, por outra pessoa do time.

        Sem esta ponte, o deploy tiraria uma capacidade que alguém usou no mesmo dia,
        sem substituto disponível.

        ## O que mudou em relação ao endpoint original

        Aceita **só** `tipo_vinculo`. Mandar etapa/status/responsável é 400, não silêncio:
        o funil paralelo continua morto e ninguém volta a registrar progresso em dois
        lugares — que é exatamente o que a unificação veio desfazer.

        ## Quando apagar

        Quando `sas_egp_pipeline.egp_vinculo_tipo` tiver os 3 registros em prod
        (`PERF_AMIGAVEL_202603_GCP_v7-RPA`, `ACORDO_AMIGAVEL_v1_RPA`,
        `PERF_REVISIONAIS_RPA`). Aí o eixo unificado responde a mesma pergunta e isto
        aqui vira dívida. Ver ticket 17 e docs/analises/vinculos_a_recriar_prod_*.md.
        """
        egp_key = (payload.get("egp_key") or "").strip()
        if not egp_key:
            raise http_exc(400, "egp_key obrigatório")
        # Recusa ALTA para os campos que morreram com a aba: aceitar e ignorar faria o
        # front achar que salvou. Quem edita etapa/status agora é o funil do corpus.
        mortos = [c for c in ("etapa", "status", "responsavel", "responsavel_bv")
                  if c in payload]
        if mortos:
            raise http_exc(400, f"{', '.join(mortos)}: o funil próprio da aba EGPs "
                                "Atualizados foi aposentado (ticket 11) — use o funil de "
                                "migração do EGP. Aqui só se grava tipo_vinculo.")
        if "tipo_vinculo" not in payload:
            raise http_exc(400, "nada a gravar (tipo_vinculo)")
        tv = (payload.get("tipo_vinculo") or "").strip()
        if tv and tv not in _TIPOS_VINCULO:
            raise http_exc(400, f"tipo_vinculo deve ser um de {_TIPOS_VINCULO}")
        # não criar funil para chave arbitrária
        if not run_sql(f"SELECT 1 FROM {t_main} WHERE egp_key = {_sql_str(egp_key)} LIMIT 1"):
            raise http_exc(404, "EGP atualizado não encontrado")

        cur = run_sql(f"SELECT tipo_vinculo FROM {t_pipe} "
                      f"WHERE egp_key = {_sql_str(egp_key)}") or []
        old = (cur[0].get("tipo_vinculo") if cur else None) or ""
        # AUDITORIA ANTES DA ESCRITA (mantido do original, 2026-09): com o MERGE primeiro,
        # um INSERT de auditoria que falhasse deixava a mudança gravada e sem histórico — e
        # o retry lia `old` já com o valor novo, pulava a auditoria e respondia ok:true.
        # Invertido, o pior caso é uma linha de histórico de mudança que não pegou: visível,
        # e o request falha alto.
        if old != tv:
            run_sql(f"INSERT INTO {t_aud} (id, egp_key, campo, valor_antigo, valor_novo, "
                    f"autor, ts) SELECT uuid(), {_sql_str(egp_key)}, 'tipo_vinculo', "
                    f"{_sql_str(old) if old else 'NULL'}, "
                    f"{_sql_str(tv) if tv else 'NULL'}, {ator()}, {agora}",
                    want_rows=False)
        # MERGE, não DELETE+INSERT (mantido do original): o par deixava uma janela em que a
        # linha já tinha sido apagada e a nova ainda não existia; um timeout do warehouse
        # entre as duas apagava etapa/status que o usuário tinha digitado. O UPDATE SET toca
        # SÓ tipo_vinculo — as outras colunas seguem como estão, intocadas.
        run_sql(
            f"MERGE INTO {t_pipe} t USING (SELECT {_sql_str(egp_key)} AS egp_key, "
            f"{_sql_str(tv) if tv else 'CAST(NULL AS STRING)'} AS tipo_vinculo) s "
            f"ON t.egp_key = s.egp_key "
            f"WHEN MATCHED THEN UPDATE SET tipo_vinculo = s.tipo_vinculo, "
            f"updated_by = {ator()}, updated_at = {agora} "
            f"WHEN NOT MATCHED THEN INSERT (egp_key, tipo_vinculo, updated_by, updated_at) "
            f"VALUES (s.egp_key, s.tipo_vinculo, {ator()}, {agora})",
            want_rows=False)
        if on_write is not None:
            on_write()
        return {"ok": True, "egp_key": egp_key, "tipo_vinculo": tv or None}

    @app.get("/api/egp-atualizado")
    def egp_atualizado_detalhe(versao_id: str):
        vid = versao_id
        vids = _sql_str(vid)
        versao = run_sql(f"SELECT * FROM {t_main} WHERE versao_id = {vids}") or []
        if not versao:
            raise http_exc(404, "versão recebida não encontrada")
        inputs = run_sql(f"""
            SELECT v.chave_canonica, v.artefato, v.categoria, v.source,
                   v.situacao_no_recebimento, v.novo,
                   (i.chave_canonica IS NOT NULL) AS no_corpus,
                   CASE WHEN {_disp_vivo} THEN true ELSE false END AS disponivel_vivo,
                   i.etapa AS etapa_corpus, i.status AS status_corpus,
                   i.origem AS origem_corpus, i.qtd_projetos
            FROM {t_in} v
            LEFT JOIN {t_mon} i ON v.chave_canonica = i.chave_canonica
            LEFT JOIN {_ma} ma ON ma.chave_canonica = v.chave_canonica
            WHERE v.versao_id = {vids}
            ORDER BY v.categoria NULLS FIRST, v.artefato NULLS FIRST
        """) or []
        outputs = run_sql(f"""
            SELECT chave_canonica, artefato, situacao, novo, removido,
                   n_consumidores_externos, padrao,
                   coalesce(categoria, 'tabela') AS categoria
            FROM {t_out} WHERE versao_id = {vids}
            ORDER BY removido DESC NULLS LAST, situacao NULLS FIRST, artefato NULLS FIRST
        """) or []
        v = _tipa(versao[0])
        _anexa_antecessores([v])
        # Histórico: TODAS as versões recebidas da mesma egp_key (append-only; a lista
        # principal mostra só a mais recente — aqui o usuário navega pelas anteriores).
        historico = run_sql(f"""
            SELECT versao_id, data_recebimento, data_ultimo_save, quadrante,
                   status_troca, arquivo_hash, publicado_em
            FROM {t_main} WHERE egp_key = {_sql_str(v.get('egp_key'))}
            ORDER BY data_recebimento DESC, publicado_em DESC
        """) or []
        _fam = familia_por_chave() if familia_por_chave else {}
        for r in inputs:
            r["chave_familia"] = _fam.get(r.get("chave_canonica"))
            for b in ("novo", "no_corpus", "disponivel_vivo"):
                r[b] = str(r.get(b)).lower() == "true" if r.get(b) is not None else None
            if r.get("qtd_projetos") is not None:
                try:
                    r["qtd_projetos"] = int(r["qtd_projetos"])
                except (TypeError, ValueError):
                    pass
        # Prontidão do detalhe: `versao` vem de um SELECT * cru em t_main, que NÃO tem
        # pct/n_disp/n_inputs (só a LISTA calcula isso via join com _prontidao). Calcula
        # aqui em cima de `inputs` (já buscado, já com disponivel_vivo coerced p/ bool)
        # em vez de repetir o join — mesma fórmula de _prontidao/egps_atualizados_lista.
        # Sem isto a linha "Prontidão" do modal de detalhe mostrava sempre
        # "undefined% (undefined/undefined inputs resolvidos)".
        # round() do Python é bancário (6.25 -> 6.2); o round() do Spark, usado na
        # LISTA, é HALF_UP (6.25 -> 6.3). Sem o Decimal a mesma versão mostrava pct
        # diferente na tabela e no modal (16 inputs / 1 resolvido: 6.2 vs 6.3).
        n_inputs = len(inputs)
        n_disp = sum(1 for r in inputs if r.get("disponivel_vivo"))
        v["n_inputs"] = n_inputs
        v["n_disp"] = n_disp
        v["pct"] = 100.0 if n_inputs == 0 else float(
            (Decimal(100 * n_disp) / Decimal(n_inputs)).quantize(
                Decimal("0.1"), rounding=ROUND_HALF_UP))
        for r in outputs:
            for b in ("novo", "removido", "padrao"):
                r[b] = str(r.get(b)).lower() == "true" if r.get(b) is not None else None
            if r.get("n_consumidores_externos") is not None:
                try:
                    r["n_consumidores_externos"] = int(r["n_consumidores_externos"])
                except (TypeError, ValueError):
                    pass
        return {"versao": v, "inputs": inputs, "outputs": outputs,
                "historico": historico,
                "mais_recente": bool(historico) and historico[0]["versao_id"] == vid}


def _sql_str(v: str) -> str:
    # Aspa escapada com \' e NÃO com '' : no Spark SQL `'O''Brien'` é lido como DOIS
    # literais adjacentes concatenados ("O" + "Brien"), então o apóstrofo some em
    # silêncio — não dá erro, grava o texto errado. Verificado no warehouse:
    #   SELECT 'O''Brien'  -> OBrien      (errado)
    #   SELECT 'O\'Brien'  -> O'Brien     (certo)
    # A contrabarra é escapada ANTES da aspa, senão a barra introduzida por \' seria
    # duplicada. Não confundir com sas_quote() em egps_extractor.py: aquilo gera código
    # SAS, onde '' É o escape correto.
    return dialeto.lit(v)
