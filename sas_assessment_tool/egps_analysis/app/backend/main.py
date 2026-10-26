#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Backend do app "Painel de Modernização SAS" (incremento 2 — monitoramento).

FastAPI servindo o bundle React (../static) + API JSON sobre as Delta tables
em <catalog>.<schema> (default bv_dev_db.monitoramento_sas). Consulta o SQL
Warehouse via databricks-sdk (StatementExecutionAPI). Dentro de um Databricks App,
autentica on-behalf-of-user: usa o token OAuth do usuário (header
X-Forwarded-Access-Token) por request; sem ele (dev local), cai no service
principal / profile do ambiente.

Endpoints:
  GET   /api/health
  GET   /api/me                       -> {user, papel}
  GET   /api/metrics?scope=indi|base  -> métricas do último snapshot
  GET   /api/inputs?...               -> linhas do monitor (filtros server-side)
  PATCH /api/inputs                   -> grava etapa/status/responsavel/observacao
"""
import os
import re
import time
import json
import functools
import hashlib
import uuid
import unicodedata
import contextvars
import datetime
import html
import threading
import urllib.parse
from concurrent.futures import Future, ThreadPoolExecutor

import anyio

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import egps_atualizados  # aba EGPs Atualizados (registrado antes do mount do SPA)
import dialeto  # banco em uso + literal (ADR 0005)
import db_pg     # execução no Postgres com o contrato do run_sql (ADR 0005)
import auth_alb  # e-mail do usuário a partir do JWT assinado pelo load balancer
import familias  # regra de família de safras (ticket 01)
import vinculos  # vínculo antecessor -> sucessor (spec 2026-09-24)
import linha_base  # lista CONGELADA de EGPs que contam (decisão 2026-09-29)
from priorizacao_logic import plan_months, resumo_counts
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.gzip import GZipMiddleware

from databricks.sdk import WorkspaceClient
from databricks.sdk.service.sql import StatementState, Disposition, Format
from prioridades_logic import STATUS_PRIO, valid_status, next_ordem, neighbor_swap

CATALOG = os.environ.get("PUBLISH_CATALOG", "bv_dev_db")
SCHEMA = os.environ.get("PUBLISH_SCHEMA", "monitoramento_sas")
WAREHOUSE_ID = os.environ.get("DATABRICKS_WAREHOUSE_ID") or os.environ.get("DATABRICKS_DEFAULT_WAREHOUSE_ID")
# Em produção (Databricks App) exigimos o token do usuário; sem ele NÃO caímos no
# service principal (evita escalonamento de privilégio). Em dev local fica desligado.
REQUIRE_OBO = os.environ.get("REQUIRE_OBO", "").strip().lower() in ("1", "true", "yes")
# App na AWS (ADR 0005). IDENTIDADE: obo = Databricks App (token do usuário); alb = login do
# Google feito pelo load balancer (cabeçalho assinado); dev = DEV_USUARIO fixo, SÓ local.
IDENTIDADE = os.environ.get("IDENTIDADE", "obo").strip().lower()
ALB_SIGNER = os.environ.get("ALB_SIGNER_ARN", "")
DEV_USUARIO = os.environ.get("DEV_USUARIO", "")
# Fase 1 na AWS: ninguém escreve (a fonte da verdade ainda é o Databricks).
SOMENTE_LEITURA = os.environ.get("SOMENTE_LEITURA", "").strip().lower() in ("1", "true", "yes")
# Família de safras (docs/adr/0002): ligada, TODA superfície de input passa a falar
# FAMÍLIA — 1 linha por família, contagem e estado por família, safra como evidência.
# Desligada, o app se comporta exatamente como antes: é a saída de emergência sem
# redeploy (variável de ambiente no app.yaml).
FAMILIAS_ON = os.environ.get("FAMILIAS_SAFRA", "").strip().lower() in ("1", "true", "yes")
PORT = int(os.environ.get("DATABRICKS_APP_PORT", os.environ.get("APP_PORT", "8000")))
HERE = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(os.path.dirname(HERE), "static")

# No Postgres não há catálogo: o app lê as views do schema `compat`, que imitam as tabelas
# Delta pelo nome (PUBLISH_SCHEMA=compat na AWS).
FQ = SCHEMA if dialeto.PG else f"{CATALOG}.{SCHEMA}"
T_IN = f"{FQ}.sas_inputs_monitor"
T_ND = f"{FQ}.sas_lineage_nodes"
T_ED = f"{FQ}.sas_lineage_edges"
T_MT = f"{FQ}.sas_pipeline_metrics"
T_EGP = f"{FQ}.sas_egp_inputs"
T_OUT = f"{FQ}.sas_outputs_monitor"
T_EGP_OUT = f"{FQ}.sas_egp_outputs"
T_AUD = f"{FQ}.sas_inputs_audit"
T_ANALISTAS = f"{FQ}.sas_analistas"
T_RESPBV = f"{FQ}.sas_responsaveis_bv"   # Responsável BV -> sub-área (nunca dropada pelo publish)
T_RES = f"{FQ}.sas_resumo_inputs"
T_RESP = f"{FQ}.sas_resumo_proj"
T_FUN = f"{FQ}.sas_funil_area"
T_ESC = f"{FQ}.sas_escopo"
# Único extra que mora em sas_escopo: a CASCA (§3.6.24). A linha dela existe só p/ o
# recompute_escopo() não apagar o escopo_indi — nunca p/ contar, então toda contagem que
# agrega sas_escopo direto no warehouse (funil por área, "EGPs no escopo") a exclui.
# coalesce porque `origem` é NULL nas linhas antigas e `NULL <> 'casca'` derrubaria a linha.
SQL_ESC_NAO_EXTRA = f"coalesce(origem, '') <> '{vinculos.ORIGEM_CASCA}'"
T_ESC_AUD = f"{FQ}.sas_escopo_audit"
T_PRIO = f"{FQ}.sas_egp_prioridades"
T_PRIO_SNAP = f"{FQ}.sas_priorizacao_snapshot"  # plano de priorização CONGELADO (1 linha id='current')
T_CHOICE = f"{FQ}.sas_output_producer_choice"
T_PIPE = f"{FQ}.sas_egp_pipeline"
T_ATU = f"{FQ}.sas_egp_atualizados"  # aba EGPs Atualizados (read-only aqui — ver egps_atualizados.py)
T_ATUP = f"{FQ}.sas_egp_atualizados_pipeline"  # funil da TROCA (tipo_vinculo etc.) — idem, read-only aqui
T_CFG = f"{FQ}.sas_app_config"      # config chave/valor do app (ex.: capacidade da priorização)
T_GST = f"{FQ}.sas_gestao_status"   # Gestão de EGPs/Inputs: status/comentários (nunca dropada)
T_GDT = f"{FQ}.sas_gestao_datas"    # Gestão: datas início/fim conversão/fim por entidade (nunca dropada)
T_GBV = f"{FQ}.sas_gestao_bv"       # Gestão: log append-only do switch "Com BV" (nunca dropada)
T_GRV = f"{FQ}.sas_gestao_revisao"  # Gestão: contador manual de EGPs devolvidos de PRD p/ DES (revisão de regras de negócio; nunca dropada)
T_PWK = f"{FQ}.sas_inputs_preworking"  # checklist manual de pré-working por input (nunca dropada)
T_OUT_PIPE = f"{FQ}.sas_outputs_pipeline"  # recebimento manual por output (chave_canonica, nunca dropada)
T_PIPE_AUD = f"{FQ}.sas_pipeline_audit"
T_LINK = f"{FQ}.sas_egp_input_link"           # per-(EGP, Input) link state (broken = counts as Sanitizado for that EGP only)
T_LINK_AUD = f"{FQ}.sas_egp_input_link_audit"  # audit trail for T_LINK writes
T_DEPM = f"{FQ}.sas_egp_dep_mantida"           # per-(EGP consumidor, Input) — "ainda dependo do PRODUTOR" (espelho do link_broken)
T_DEPM_AUD = f"{FQ}.sas_egp_dep_mantida_audit"  # audit trail for T_DEPM writes
T_PER = f"{FQ}.sas_egp_input_periodo"          # profundidade NECESSÁRIA por (EGP, família)
T_PER_AUD = f"{FQ}.sas_egp_input_periodo_audit"
T_ING = f"{FQ}.sas_familia_ingestao"           # profundidade INGERIDA por família (fato)
T_ING_AUD = f"{FQ}.sas_familia_ingestao_audit"

CATEGORIAS = ["tabela", "arquivo", "lib", "script"]
ORIGENS = ["BigQuery", "Transacional", "SAS/Local (externo)", "SAS/Local (dependência)", "Arquivo", "Script"]

# status_humano (legado, 5 valores) foi SUBSTITUÍDO por 2 colunas ortogonais em T_IN —
# etapa (funil de ingestão, PIPELINE_INPUT) + status (progresso na etapa, STATUS_INPUT) —
# espelhando o modelo já usado por sas_egp_pipeline (etapa_migracao/status_migracao). A
# coluna status_humano NUNCA é apagada/reescrita (fica congelada como histórico); ver
# scripts/migrate_input_status_split.py p/ o backfill único e PIPELINE_INPUT/STATUS_INPUT
# mais abaixo (perto de PIPELINE_PROJETO/STATUS_PROJETO) p/ o vocabulário.


# Estado efetivo do input (etapa/status/resolvido) mora em input_state.py, em duas formas
# pareadas: as geradoras de SQL abaixo (mesmos nomes de sempre) e as gêmeas em Python
# (py_*), usadas pela agregação por família em memória. Ver docs/adr/0002.
from input_state import (  # noqa: E402  (import depois das constantes de tabela, de propósito)
    _eff_etapa, _eff_status_input, _modern, _aingerir, _sanitizado,
    py_eff_etapa, py_eff_status, py_modern, py_aingerir,
)
# Sanitização DERIVADA do input (§3.4.18): lógica pura, sem DB — ver _sanitizacao_derivada.
import sanitizacao  # noqa: E402
# Linhas das tabelas de consulta do agente (ADR 0004): lógica pura — ver _consulta_calcula.
import consulta  # noqa: E402


def _ch_vinculo_ativo(egp_where):
    """Subquery SQL do UNIVERSO POR VÍNCULO — predicado ÚNICO dos contadores do app
    (landing/funis/resumo/cards da aba Inputs): chaves com ≥1 vínculo NÃO quebrado
    (sas_egp_input_link) com EGPs do recorte. `egp_where` filtra o alias `e` de
    sas_egp_inputs (ex.: "e.escopo_indi = true" ou "e.projeto IN (...)"). Input cujos
    vínculos estão TODOS quebrados sai das contagens em TODAS as superfícies (vínculo
    quebrado = resolvido; decisão 2026-07-30 — antes cada endpoint aplicava ou não o
    filtro e o Resumo divergia por 1 da aba Inputs). Callers garantem
    _ensure_link_tables() antes de executar a query."""
    return (f"(SELECT DISTINCT e.chave_canonica FROM {T_EGP} e "
            f"LEFT JOIN {T_LINK} l ON l.projeto = e.projeto "
            f"AND l.chave_canonica = e.chave_canonica "
            f"WHERE {egp_where} AND NOT coalesce(l.link_broken, false))")


# ---- pipelines de migração (funis da landing) ----
# 2 funis de projeto (single-pointer: cada EGP tem etapa+status por funil) + 1 de ingestão
# (derivado do status do input). Etapas ordenadas; última etapa = "concluído do funil".
PIPELINE_PROJETO = {
    "migracao": ["Projetos Habilitados", "Pré-Working + Outputs", "Conversão do Código",
                 "Validação em DES", "Aprv. PR + Validação Governança", "Implant. em PRD",
                 "Aplicação de Grant", "Validação da Área", "Migrado"],
}
# Etapas "phantom" (fora do funil, gravadas em etapa_migracao normalmente): fogem da
# ordem de PIPELINE_PROJETO["migracao"], não deslocam índices em _funnel_bars, e ficam
# fora do coorte de migração (não contam em migrados/total). Chave = etapa, valor = tom
# da UI (top_stats). Auditoria em sas_pipeline_audit preserva a transição normalmente.
#   - "Pré-conversão": EGP pode chegar aqui sem passar por "Conversão do Código" (pré-
#     conversão iniciada p/ destravar o funil enquanto BV atrasa a entrega de outputs).
#   - "Conversão pela Área" (2026-08): a conversão de código deste EGP NÃO é escopo da
#     Indicium — a própria área de negócio do BV converte. Só a ingestão dos inputs
#     (funil de INGESTÃO, independente) segue sendo acompanhada; o EGP não avança pelas
#     etapas de Conversão/Validação/Aprv. PR/Implantação/Grant/Validação da Área daqui.
# Por ser etapa (não status), continua puxando dependências normalmente — diferente de
# "Despriorizado e Contabilizado", que é status e aciona no_expand (_egps_fora_backlog).
PHANTOM_ETAPAS_MIGRACAO = {"Pré-conversão": "wip", "Conversão pela Área": "mut"}
# Etapas do funil de MIGRAÇÃO renomeadas em 24–25/08/2026 (scripts/rename_migracao_etapas.py).
# O rename mexeu só em sas_egp_pipeline: a trilha sas_pipeline_audit (campo='etapa') guarda os
# nomes ANTIGOS, e não é reescrita de propósito (histórico fiel). As contas de tempo leem a
# auditoria por _canon_etapa_rows. NÃO vale pro funil de INPUTS ("Pré-Working"/"Aplicação de
# Grant" têm outro sentido lá). Nova renomeação = nova linha aqui (e no script de rename).
ETAPAS_RENOMEADAS_MIGRACAO = {
    "Pré-Working": "Pré-Working + Outputs",
    "Aprv. PR": "Aprv. PR + Validação Governança",
    "Artefatos de GOV.": "Aplicação de Grant",
}


def _canon_etapa_rows(rows):
    """Mapeia etapa antiga -> atual em linhas de auditoria [{projeto, etapa, ts}, ...]
    ORDENADAS por (projeto, ts), e funde linhas CONSECUTIVAS do mesmo projeto que ficaram
    na mesma etapa após o mapa (mantém a 1ª entrada) — senão uma só permanência, que cruzou
    o rename, viraria 2 intervalos e inflaria `n`/derrubaria a média. Não altera `rows`."""
    out = []
    for r in rows:
        et = ETAPAS_RENOMEADAS_MIGRACAO.get(r.get("etapa"), r.get("etapa"))
        if out and out[-1]["projeto"] == r["projeto"] and out[-1]["etapa"] == et:
            continue
        out.append({**r, "etapa": et})
    return out
# "Removido" foi EXTINTO (2026-07): única saída de backlog é "Despriorizado e
# Contabilizado" (dados antigos migrados por UPDATE; auditoria preserva o histórico).
STATUS_PROJETO = ["A Iniciar", "Em Andamento", "Em espera", "Concluído", "Block",
                  "Despriorizado e Contabilizado", "Migrado"]
BANDS = {"Despriorizado e Contabilizado"}  # reflete em todas as colunas do funil
# "Em espera" (2026-10-01): EGP parado porque o responsável só avança 1 EGP por vez (não é
# bloqueio externo como "Block", nem falta de trabalho como "A Iniciar") — tempo neste
# status é EXCLUÍDO das métricas de tempo (_tempo_etapas/_analises_tempo, via
# _dias_uteis_segmentos) pra não superdimensionar o tempo real gasto no EGP.

# Funil de INGESTÃO dos inputs (etapa) + progresso dentro da etapa (status) — mesmo
# modelo do funil de migração acima, ver _eff_etapa/_eff_status_input. STATUS_INPUT
# reaproveita de propósito 4 das strings de STATUS_PROJETO (mesma paleta SEG no front:
# A Iniciar/Em Andamento/Concluído/Block) + "Sanitizado" (exceção terminal: input que
# pulou a esteira). Sanitizado segue a MESMA regra app-wide de "Sanitizado = removido do
# escopo" (ver README): fica de fora do funil de ingestão (bars/coorte/total/migrados),
# só aparece como contador informativo — não é uma banda, ao contrário do "Despriorizado
# e Contabilizado" dos EGPs.
#
# "Autoprodutor" (2026-08): exceção terminal IRMÃ de Sanitizado — input cujo próprio EGP
# consumidor também o CRIA (não só apensa), então não precisa de ingestão separada. Ao
# contrário de Sanitizado (exclui do universo — "não se aplica"), Autoprodutor CONTA COMO
# FEITO (soma no numerador e no denominador da prontidão — trabalho entregue por via
# alternativa). Ver _modern()/_autoprodutor_candidatos() e README §Autoprodutor.
PIPELINE_INPUT = ["A Receber", "Recebido", "Pré-Working", "Ingestão UAT", "PDI + GMUD",
                  "Ingestão PRD", "Aplicação de Grant", "Modernizado"]
STATUS_INPUT = ["A Iniciar", "Em Andamento", "Concluído", "Block", "Sanitizado", "Autoprodutor"]

# Checklist manual de pré-working (sas_inputs_preworking): campos preenchidos pelas áreas
# de negócio com o operacional necessário p/ configurar a ingestão de cada input. Espelha
# PREWORKING_* em frontend/src/pipeline.ts — mudou num, sincronize o outro.
PREWORKING_FREQUENCIA = ["Diária", "Semanal", "Quinzenal", "Mensal", "Sob demanda", "Carga única"]
PREWORKING_TIPO_CARGA = ["Full", "Incremental", "Full + Incremental"]
PREWORKING_POS_PROC = ["Mover", "Apagar", "Manter (nenhuma ação)"]
PREWORKING_DADOS_SENSIVEIS = ["Sim", "Não"]

# Jira ID: project key uppercase alfa/digit (começando com letra, ≥ 2 chars) + hífen +
# número. Ex: PROJ-123, ABC1-42, X1Y2-9. Ver
# https://stackoverflow.com/questions/19322669/regular-expression-for-a-jira-identifier.
JIRA_ID_RE = re.compile(r"^[A-Z][A-Z0-9]+-\d+$")


def _funnel_bars(stages, items):
    """Barras empilhadas. Despriorizado e Contabilizado = banda (todas as colunas);
    demais: j<i=Concluído, j==i=status, j>i=A Iniciar."""
    bars = []
    for j in range(len(stages)):
        seg = {}
        for i, st, w in items:
            if st in BANDS:
                k = st
            elif j < i:
                k = "Concluído"
            elif j == i:
                k = st
            else:
                k = "A Iniciar"
            seg[k] = seg.get(k, 0) + w
        bars.append({"etapa": stages[j], "seg": seg})
    return bars
READ_CAP = 20000

app = FastAPI(title="Painel de Modernização SAS")


@app.exception_handler(familias.OverridesInvalidos)
def _overrides_invalidos(request, exc):
    """`familias_overrides.json` malformado: falha ALTA, mas DIAGNOSTICÁVEL.

    A exceção é `ValueError`, então escapava de todo `except HTTPException` do app e caía
    como 500 genérico em qualquer rota que toque família — sem dizer que o culpado é um
    arquivo curado à mão, editável em segundos. Continua derrubando a request (degradar
    em silêncio daria agrupamento de família errado, que é pior), mas agora diz o quê."""
    print(f"[familias] overrides inválidos: {exc}", flush=True)
    return JSONResponse(
        status_code=500,
        content={"detail": f"familias_overrides.json inválido — corrija o arquivo e "
                           f"recarregue: {exc}"})


# --- Autenticação on-behalf-of-user (OBO) ---------------------------------
# Dentro do Databricks App, cada request traz o token OAuth do usuário no header
# X-Forwarded-Access-Token (escopos já habilitados no app). Falamos com o SQL
# Warehouse COMO O USUÁRIO usando esse token; sem ele (dev local), caímos no
# service principal / profile do ambiente. O token é exposto por um middleware
# ASGI puro — NÃO BaseHTTPMiddleware, que roda em outra task e não propaga o
# contextvar para o endpoint.
_user_token: contextvars.ContextVar = contextvars.ContextVar("obo_user_token", default=None)

# --- Cache em memória das leituras (linhagem, dataset do escopo, payload) ----
LINEAGE_CACHE_TTL = 300  # s — teto de staleness p/ escrita FORA do app (publish, scripts)
# NB: cache + invalidação são process-local. O app roda single-process (app.yaml); se escalar p/ múltiplos workers/réplicas, a invalidação de escopo precisaria de sinal compartilhado — o TTL limita a staleness nesse caso.
#
# Chave COMPARTILHADA entre usuários (2026-10-06). Antes a chave levava o hash do token
# OBO: N usuários pagavam N recomputações idênticas e cada rotação de token esfriava tudo.
# O schema não tem row filter nem column mask e os grants de leitura são por SCHEMA, sem
# grant por tabela (medido em 06/10/2026) — o dado servido é o mesmo para todo leitor. O
# que o token na chave protegia ("quem não lê o schema não recebe o dado") passa a ser
# checado por `_autoriza_leitura()` antes de qualquer hit: 1 statement OBO por token a cada
# _SESSAO_TTL. Se um dia entrar row filter/grant por tabela, a chave volta a precisar da
# identidade.
#
# Single-flight: requests concorrentes da mesma chave esperam o primeiro em vez de
# recalcular juntos (o prefetch dispara ~20 GETs que dependem do mesmo frontier).
_lineage_cache: dict = {}
_lineage_gen = 0
_cache_lock = threading.Lock()
_inflight: dict = {}
_CACHE_MAX = 256


def _evict(store, now):
    """Sob _cache_lock. Primeiro sai o que já não serve (expirado ou de geração velha); se
    ainda passar do teto, os que vencem antes. Antes era clear() total — ~8 usuários x ~29
    chaves esvaziavam o cache de todo mundo — e a varredura corria sem lock enquanto as
    threads do _parallel inseriam (RuntimeError: dictionary changed size)."""
    for k in [k for k, v in store.items() if v[0] <= now or v[2] != _lineage_gen]:
        del store[k]
    excesso = len(store) - _CACHE_MAX * 3 // 4
    if len(store) > _CACHE_MAX and excesso > 0:
        for k, _v in sorted(store.items(), key=lambda kv: kv[1][0])[:excesso]:
            del store[k]


def _cache_get(store, key, producer):
    """`key` de `store`; ausente, expirado ou de geração velha -> produz UMA vez.

    A geração é capturada ANTES do produce() e vai tanto na entrada quanto na chave do
    in-flight: um hit só vale se ela ainda é a vigente (fecha a corrida read-after-write)
    e quem chega depois de um bump nunca recebe — nem espera — um cálculo começado antes
    dele. Falha do produtor não entra no cache; quem estava esperando recebe a mesma
    exceção."""
    _autoriza_leitura()
    gen = _lineage_gen
    now = time.monotonic()
    voo = (id(store), key, gen)
    with _cache_lock:
        hit = store.get(key)
        if hit and hit[0] > now and hit[2] == gen:
            return hit[1]
        fut = _inflight.get(voo)
        dono = fut is None
        if dono:
            fut = _inflight[voo] = Future()
    if not dono:
        return fut.result()
    try:
        val = producer()
    except BaseException as e:
        with _cache_lock:
            _inflight.pop(voo, None)
        fut.set_exception(e)
        raise
    with _cache_lock:
        atual = store.get(key)
        if not (atual and atual[2] > gen):   # cálculo pré-bump não apaga o pós-bump
            store[key] = (now + LINEAGE_CACHE_TTL, val, gen)
        _inflight.pop(voo, None)
        if len(store) > _CACHE_MAX:
            _evict(store, now)
    fut.set_result(val)
    return val


def _cache_lineage(key_parts, producer):
    """Cache das leituras de linhagem/recorte. Invalidado por geração (_bump_gen) em toda
    mutação que as afeta; TTL limita o que muda fora do app (republish)."""
    return _cache_get(_lineage_cache, tuple(key_parts), producer)


# --- Cache em memória do DATASET DO ESCOPO (linhas de /api/inputs sem filtros) ---
# REUSA _lineage_gen (geração global) de propósito: o dataset de inputs depende das MESMAS
# tabelas-núcleo (T_IN.escopo_indi/etapa/status) que recompute_escopo já invalida; reusar
# faz recompute invalidar os dois caches de uma vez. Dict separado p/ não competir com a
# evicção por tamanho do _lineage_cache.
_scope_cache: dict = {}


def _cache_scope_dataset(scope, producer):
    """Cache do dataset COMPLETO de um scope (sem filtros texto/multiselect)."""
    return _cache_get(_scope_cache, (scope,), producer)

# --- Cache de PAYLOAD por endpoint (aba EGPs, detalhe de EGP, Gestão) ----------
# Invalidação: TODA mutação que afeta esses payloads bumpa a geração via _bump_gen().
_endpoint_cache: dict = {}


def _cache_endpoint(key_parts, producer):
    return _cache_get(_endpoint_cache, tuple(key_parts), producer)


def _bump_gen():
    """Invalida os caches derivados (linhagem/dataset/payload). Chamar em TODA mutação
    que afete leituras cacheadas — sob-invalidação quebra o contrato de freshness;
    sobre-invalidação só custa um re-query."""
    global _lineage_gen
    _lineage_gen += 1


# --- Sessão OBO: identidade, grupos e PROVA DE LEITURA, 1 query por token -----------
_SESSAO_TTL = 300  # s — mudança de grupo/grant reflete em até isso
_sessoes: dict = {}


def _verdade(v):
    return v is True or str(v).lower() == "true"


# E-mail do usuário quando o app roda na AWS (ADR 0005); o middleware preenche por request.
_usuario_email: contextvars.ContextVar = contextvars.ContextVar("usuario_email", default=None)


def _sessao_pg_de(email):
    """{user, papel, gestao, admin} de quem está ATIVO em cadastro.usuario, ou None.
    Cacheado por e-mail (mesmo TTL da sessão OBO): mudança de papel reflete em até 5 min."""
    now = time.monotonic()
    k = "pg:" + email
    with _cache_lock:
        hit = _sessoes.get(k)
        if hit and hit[0] > now:
            return hit[1]
    rows = run_sql("SELECT papel FROM cadastro.usuario WHERE ativo AND email = " + sql_lit(email))
    val = None
    if rows:
        p = rows[0]["papel"]
        val = {"user": email, "papel": p, "gestao": p in ("gestao", "admin"), "admin": p == "admin"}
    with _cache_lock:
        _sessoes[k] = (now + _SESSAO_TTL, val)
    return val


def _sessao():
    """{user, gestao, admin} do usuário OBO, numa query só, cacheado por token.

    O scalar subquery em sas_inputs_monitor é a PROVA DE LEITURA que autoriza servir o
    cache compartilhado: sem SELECT no schema, a query falha (403) e nada é servido. Antes
    eram 3 statements soltos e sem cache — current_user(), is_member de gestão, de admin —
    pagos em todo GET de cadastro e em toda mutação de gestão. Só sucesso é cacheado."""
    if dialeto.PG:
        email = _usuario_email.get()
        val = _sessao_pg_de(email) if email else None
        if val is None:
            raise HTTPException(403, "Sem acesso ao app — peça à gestão do projeto para cadastrar seu e-mail.")
        return val
    tok = _user_token.get()
    k = hashlib.sha256(tok.encode()).hexdigest()[:16] if tok else "sp"
    now = time.monotonic()
    with _cache_lock:
        hit = _sessoes.get(k)
        if hit and hit[0] > now:
            return hit[1]
    g = " OR ".join(f"is_account_group_member({sql_lit(x)}) OR is_member({sql_lit(x)})"
                    for x in GESTAO_GROUPS)
    a = " OR ".join(f"is_account_group_member({sql_lit(x)}) OR is_member({sql_lit(x)})"
                    for x in ADMIN_GROUPS)
    r = run_sql(f"SELECT current_user() AS u, ({g}) AS g, ({a}) AS a, "
                f"(SELECT count(*) FROM (SELECT 1 FROM {T_IN} LIMIT 1)) AS leitura")
    row = r[0] if r else {}
    val = {"user": row.get("u"), "gestao": _verdade(row.get("g")),
           "admin": _verdade(row.get("a"))}
    with _cache_lock:
        _sessoes[k] = (now + _SESSAO_TTL, val)
        if len(_sessoes) > _CACHE_MAX:
            for kk in [kk for kk, v in _sessoes.items() if v[0] <= now]:
                del _sessoes[kk]
    return val


def _autoriza_leitura():
    """Sem token (dev local / service principal) não há o que provar."""
    if _user_token.get():
        _sessao()


_PAR_MAX = 8  # teto de statements simultâneos por request (decisão 2026-08-27)


def _parallel(*thunks):
    """Executa callables INDEPENDENTES em threads, propagando o contexto do request
    (token OBO + acumulador [perf]) p/ cada uma. Retorna os resultados NA ORDEM dos
    thunks; exceção de qualquer thunk re-levanta no caller (mesma semântica do serial).
    Usar só p/ leituras sem dependência entre si — nunca p/ writes ordenados."""
    if len(thunks) == 1:
        return [thunks[0]()]
    with ThreadPoolExecutor(max_workers=min(_PAR_MAX, len(thunks))) as ex:
        futs = [ex.submit(contextvars.copy_context().run, t) for t in thunks]
        return [f.result() for f in futs]


# Phase 0 perf instrumentation (LOGGING-ONLY — não altera consulta/resultado/auth).
# _perf_req acumula por request (set no middleware, lido em run_sql) p/ medir o
# fan-out (N statements seriais por endpoint). _last_stmt_mono é global: mede o gap
# entre run_sql consecutivos — gap grande sugere cold-start/spin-up do warehouse.
_perf_req: contextvars.ContextVar = contextvars.ContextVar("perf_req", default=None)
_last_stmt_mono: float = 0.0


@functools.lru_cache(maxsize=1)
def _sp_client():
    """Service principal (dentro do app) ou profile/env (dev local)."""
    return WorkspaceClient()


_CLIENTE_TTL = 600  # s — teto de retenção do cliente (e do token dentro dele)
_clientes: dict = {}


def _user_client(token):
    """Cliente autenticado com o token OAuth do usuário (host herdado do SP).

    auth_type="pat" é obrigatório: dentro do Databricks App o ambiente já tem o OAuth
    do service principal (DATABRICKS_CLIENT_ID/SECRET); sem forçar o tipo, o SDK acha
    OAuth + PAT ao mesmo tempo e falha ("more than one authorization method").

    Reaproveitado POR TOKEN (2026-10-06). Criar um por statement não era barato: medido em
    prod, ~0,4 s (p50) de cada statement era só cliente novo + conexão TLS nova (218
    statements casados com system.query.history; benchmark local 1.551 vs 641 ms). O
    cliente fica preso ao PRÓPRIO token — revogação/expiração seguem refletindo na hora,
    porque o warehouse recusa o token, e token novo é chave nova. Teto de tempo e de
    quantidade p/ não reter credencial além do uso."""
    k = hashlib.sha256(token.encode()).hexdigest()
    now = time.monotonic()
    with _cache_lock:
        hit = _clientes.get(k)
        if hit and hit[0] > now:
            return hit[1]
    w = WorkspaceClient(host=_sp_client().config.host, token=token, auth_type="pat")
    with _cache_lock:
        _clientes[k] = (now + _CLIENTE_TTL, w)
        for kk in [kk for kk, v in _clientes.items() if v[0] <= now]:
            del _clientes[kk]
        if len(_clientes) > 64:
            del _clientes[min(_clientes, key=lambda kk: _clientes[kk][0])]
    return w


# Marca de execução da ROTINA de consulta (ADR 0004): só `_consulta_rotina()` a liga, na
# própria thread, e nenhum caminho de request a toca. É a ÚNICA forma de rodar leitura como
# service principal com REQUIRE_OBO ligado — a rotina não tem usuário (roda em segundo
# plano) e calcula o mesmo que as telas (o schema não tem filtro por linha nem máscara).
_rotina_sistema: contextvars.ContextVar = contextvars.ContextVar("rotina_sistema", default=False)
_ultimo_request_mono = 0.0   # último GET/POST em /api/* (o middleware atualiza)


def _client():
    tok = _user_token.get()
    if tok:
        return _user_client(tok)
    if _rotina_sistema.get():
        return _sp_client()
    # Sem token: em produção (REQUIRE_OBO) falha alto e claro em vez de cair no SP —
    # fecha o bypass de privilégio e pega eventual falha de propagação de contexto.
    if REQUIRE_OBO:
        raise HTTPException(401, "Autenticação de usuário ausente (X-Forwarded-Access-Token).")
    return _sp_client()


_LIVRES_PG = ("/api/health", "/api/me")
_METODOS_LEITURA = ("GET", "HEAD", "OPTIONS")


def _email_da_requisicao(scope):
    """E-mail na AWS. alb: cabeçalho assinado pelo load balancer (auth_alb confere assinatura
    e signer); dev: DEV_USUARIO, só para rodar local. None se não houver ou não valer."""
    if IDENTIDADE == "dev":
        return DEV_USUARIO.strip().lower() or None
    if IDENTIDADE != "alb":
        return None
    bruto = dict(scope.get("headers", [])).get(b"x-amzn-oidc-data", b"").decode("latin-1")
    try:
        return auth_alb.email_do_cabecalho(bruto, ALB_SIGNER)
    except auth_alb.IdentidadeInvalida as e:
        print(f"[auth] cabeçalho do ALB recusado: {e}", flush=True)
        return None


def _nega_acesso(email, metodo):
    """None = pode; (status, motivo) = recusa. ÚNICO lugar que decide acesso no Postgres:
    cadastro ativo, e nada de escrita para leitor nem com SOMENTE_LEITURA."""
    if not email:
        return 401, "Login ausente ou inválido — recarregue a página."
    s = _sessao_pg_de(email)
    if s is None:
        return 403, "Seu e-mail não tem acesso ao app — peça à gestão do projeto."
    if metodo not in _METODOS_LEITURA and (SOMENTE_LEITURA or s["papel"] == "leitor"):
        return 403, "Somente leitura."
    return None


# Página de login da AWS (IDENTIDADE=alb): autocontida, sem nada do bundle, que só é servido
# a quem já entrou. O botão leva a /login/google, o único caminho em que o load balancer
# força o login do Google; nos demais ele deixa passar (allow) e o app decide.
_PAGINA_LOGIN = """<!doctype html>
<html lang="pt-br">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Entrar · Painel de Modernização SAS</title>
<style>
:root{color-scheme:light dark;--fundo:#f6f7f9;--cartao:#fff;--texto:#1f2328;--suave:#59636e;--borda:#d0d7de}
@media (prefers-color-scheme:dark){:root{--fundo:#0d1117;--cartao:#161b22;--texto:#e6edf3;--suave:#9198a1;--borda:#30363d}}
*{box-sizing:border-box}
body{margin:0;min-height:100vh;display:grid;place-items:center;padding:16px;background:var(--fundo);color:var(--texto);font:16px/1.5 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
main{width:100%;max-width:380px;background:var(--cartao);border:1px solid var(--borda);border-radius:12px;padding:32px 28px;text-align:center}
h1{font-size:1.25rem;margin:0 0 24px}
a.google{display:inline-flex;align-items:center;gap:12px;padding:10px 20px;border:1px solid #747775;border-radius:999px;background:#fff;color:#1f1f1f;font-weight:500;text-decoration:none}
a.google:hover{background:#f2f2f2}
a.google:focus-visible{outline:2px solid #1a73e8;outline-offset:2px}
p{margin:20px 0 0;color:var(--suave);font-size:.85rem}
</style>
</head>
<body>
<main>
<h1>Painel de Modernização SAS</h1>
<a class="google" href="{link}"><svg width="18" height="18" viewBox="0 0 48 48" aria-hidden="true"><path fill="#EA4335" d="M24 9.5c3.54 0 6.71 1.22 9.21 3.6l6.85-6.85C35.9 2.38 30.47 0 24 0 14.62 0 6.51 5.38 2.56 13.22l7.98 6.19C12.43 13.72 17.74 9.5 24 9.5z"/><path fill="#4285F4" d="M46.98 24.55c0-1.57-.15-3.09-.38-4.55H24v9.02h12.94c-.58 2.96-2.26 5.48-4.78 7.18l7.73 6c4.51-4.18 7.09-10.36 7.09-17.65z"/><path fill="#FBBC05" d="M10.53 28.59c-.48-1.45-.76-2.99-.76-4.59s.27-3.14.76-4.59l-7.98-6.19C.92 16.46 0 20.12 0 24c0 3.88.92 7.54 2.56 10.78l7.97-6.19z"/><path fill="#34A853" d="M24 48c6.48 0 11.93-2.13 15.89-5.81l-7.73-6c-2.15 1.45-4.92 2.3-8.16 2.3-6.26 0-11.57-4.22-13.47-9.91l-7.98 6.19C6.51 42.62 14.62 48 24 48z"/></svg>Entrar com Google</a>
<p>O acesso depende do cadastro feito pela gestão do projeto.</p>
</main>
</body>
</html>
"""


def _volta_segura(volta):
    """Só caminho do próprio app. Nada de '//host', '/\\host', URL absoluta, espaço ou
    caractere de controle (o navegador apaga tab e quebra de linha: '/\\t/host' vira
    '//host') nem a própria página de login."""
    v = volta or ""
    if (not v.startswith("/") or v.startswith(("//", "/\\")) or any(ord(ch) < 0x21 for ch in v)
            or v == "/login" or v.startswith(("/login?", "/login/"))):
        return "/"
    return v


def _desvio_de_login(email, caminho, query):
    """Login na AWS (IDENTIDADE=alb). None = segue; senão, a resposta que substitui o pedido.
    Sem login só abrem /login e /api/health (health check do load balancer, que chega sem
    sessão); o resto vai para /login guardando o endereço, e a API responde 401."""
    volta = urllib.parse.parse_qs(query).get("volta", [""])[0]
    if caminho in ("/login", "/login/google"):
        if email:  # logado nunca vê a página de login: segue para onde ia
            return RedirectResponse(_volta_segura(volta), status_code=302)
        para_login = urllib.parse.quote(_volta_segura(volta), safe="")
        if caminho == "/login/google":  # chegou sem sessão (regra do ALB ausente): sem laço
            return RedirectResponse("/login?volta=" + para_login, status_code=302)
        link = html.escape("/login/google?volta=" + para_login)
        return HTMLResponse(_PAGINA_LOGIN.replace("{link}", link), headers={"Cache-Control": "no-store"})
    if email or caminho == "/api/health":
        return None
    if caminho.startswith("/api/"):
        return JSONResponse({"detail": "Login ausente ou expirado — entre de novo.", "entrar": "/login"},
                            status_code=401)
    destino = caminho + ("?" + query if query else "")
    return RedirectResponse("/login?volta=" + urllib.parse.quote(destino, safe=""), status_code=302)


class _OBOAuthMiddleware:
    """Middleware ASGI puro: lê X-Forwarded-Access-Token e o expõe via contextvar
    durante o request. Por rodar na mesma task do app, o valor propaga para os
    endpoints síncronos (o threadpool copia o contexto atual)."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        token = None
        for k, v in scope.get("headers", []):
            if k == b"x-forwarded-access-token" and v:
                token = v.decode("latin-1").strip() or None
                break
        reset = _user_token.set(token)
        email = _email_da_requisicao(scope) if dialeto.PG else None
        reset_email = _usuario_email.set(email)
        caminho = scope.get("path", "")
        if dialeto.PG and IDENTIDADE == "alb":
            desvio = _desvio_de_login(email, caminho, scope.get("query_string", b"").decode("latin-1"))
            if desvio is not None:
                _usuario_email.reset(reset_email)
                _user_token.reset(reset)
                await desvio(scope, receive, send)
                return
        if dialeto.PG and caminho.startswith("/api/") and caminho not in _LIVRES_PG:
            try:
                negado = await anyio.to_thread.run_sync(_nega_acesso, email, scope.get("method", "GET"))
            except HTTPException as e:  # banco fora do ar: fora dos handlers do FastAPI, viraria 500
                negado = (e.status_code, e.detail)
            if negado:
                _usuario_email.reset(reset_email)
                _user_token.reset(reset)
                await JSONResponse({"detail": negado[1]}, status_code=negado[0])(scope, receive, send)
                return
        if scope.get("path", "").startswith("/api/"):
            # a rotina de consulta só sonda mudança com o app em uso (warehouse acordado)
            global _ultimo_request_mono
            _ultimo_request_mono = time.monotonic()
        # Phase 0 perf: acumulador por request (rid curto) p/ medir fan-out de run_sql.
        _perf_rid = uuid.uuid4().hex[:8]
        perf_reset = _perf_req.set({"rid": _perf_rid, "n": 0, "total_ms": 0.0, "max_ms": 0.0})
        try:
            await self.app(scope, receive, send)
        finally:
            try:
                _acc = _perf_req.get()
                if _acc is not None:
                    print(
                        f"[perf] req rid={_acc['rid']} path={scope.get('path')} "
                        f"n={_acc['n']} total_ms={_acc['total_ms']:.0f} "
                        f"max_ms={_acc['max_ms']:.0f}",
                        flush=True)
            except Exception:
                pass
            _perf_req.reset(perf_reset)
            _usuario_email.reset(reset_email)
            _user_token.reset(reset)


app.add_middleware(_OBOAuthMiddleware)
# JSON de 1,5-1,8 MB (readiness base, inputs) ia cru. ASGI puro como o de cima: não
# interfere no contextvar do OBO. Nível 6: quase a taxa do 9 por uma fração da CPU.
app.add_middleware(GZipMiddleware, minimum_size=1024, compresslevel=6)


def sql_lit(v):
    # Dialeto do banco em uso (ADR 0005). No Spark a aspa vira \' — `'O''Brien'` lá são DOIS
    # literais concatenados e o apóstrofo some em silêncio (verificado no warehouse); no
    # Postgres o \' FECHA a string (injeção). As duas regras moram em dialeto.lit.
    return dialeto.lit(v)


# Quando e quem gravam, nos dois bancos (Fase 2, ADR 0005). No Databricks o SQL é o de sempre.
# Postgres: `localtimestamp` (timestamp sem fuso; a sessão está em UTC), que numa coluna texto
# sai no formato do Spark ('2026-10-15 19:27:07.090031') — current_timestamp levaria '+00'.
AGORA = "localtimestamp" if dialeto.PG else "current_timestamp()"


def _ator():
    """Quem grava, como expressão SQL. Databricks: current_user() — a consulta roda como o
    usuário (OBO). Postgres: o e-mail que o middleware conferiu (cabeçalho do ALB ou
    DEV_USUARIO), como literal; sem ele não há escrita."""
    if not dialeto.PG:
        return "current_user()"
    email = _usuario_email.get()
    if not email:
        raise HTTPException(401, "Login ausente ou inválido — recarregue a página.")
    return sql_lit(email)


def _lista_tem_algum(lista_sql, valores):
    """SQL: a lista em texto `lista_sql` ('a | b | c') tem algum dos `valores`, item a item e
    sem os espaços das pontas. Roda igual no Spark e no Postgres: sem lambda (`x -> trim(x)`)
    nem `array(...)`, que o Postgres não tem; `instr` e `regexp_replace` existem nos dois
    (no Postgres, em compat). `valores` não pode ser vazio."""
    norm = f"concat('|', regexp_replace(trim({lista_sql}), ' *[|] *', '|'), '|')"
    return "(" + " OR ".join(f"instr({norm}, {sql_lit('|' + v + '|')}) > 0" for v in valores) + ")"


def _sql_http_error(msg):
    """Mapeia falha de SQL/SDK para o status HTTP correto (permissão→403, token→401)."""
    low = (msg or "").lower()
    if any(p in low for p in ("permission denied", "permissiondenied", "not authorized",
                              "insufficient", "does not have", "access denied", "forbidden",
                              "no privilege", "unauthorized")):
        return HTTPException(403, "Sem permissão para este recurso — verifique os grants "
                                  "(USE/SELECT/MODIFY) no Unity Catalog e CAN USE no warehouse.")
    if any(p in low for p in ("invalid token", "token expired", "expired", "unauthenticated",
                              "invalid access token", "could not validate")):
        return HTTPException(401, "Sessão expirada — recarregue a página para reautenticar.")
    return HTTPException(502, f"Falha SQL: {msg}")


def _objeto_ausente(exc):
    """A falha é "tabela/coluna ainda não publicada" — o ÚNICO caso em que uma leitura
    pode virar vazio (app rodando antes do 1º publish, coluna que o publish novo ainda
    não criou). Timeout, 403 e 502 genérico NÃO: devolver vazio aí ia para o cache e
    mudava contagem em silêncio (despriorizado voltando a puxar dependência, aba EGPs
    sem etapa) — falha que sinaliza é melhor que número errado."""
    msg = str(getattr(exc, "detail", exc) or "").upper()
    return "TABLE_OR_VIEW_NOT_FOUND" in msg or "UNRESOLVED_COLUMN" in msg


def _materializa_linhas(w, sid, r):
    """Linhas de um statement SUCCEEDED, seguindo `next_chunk_index` até o fim.

    Com `disposition=INLINE` o PRIMEIRO chunk vem na resposta e o resto só sai pelo
    endpoint de chunk. Ler apenas `r.result.data_array` truncava em silêncio todo
    resultado que não coubesse num chunk: sem erro, sem aviso, e o app exibia um recorte
    do dado achando que era o todo — nas superfícies que carregam o dataset inteiro do
    escopo (~11k linhas) é exatamente o tamanho em que isso morde. O truncamento com esta
    mesma disposition já tinha sido observado neste repo; ver o laço equivalente em
    docs/analises/backup_overlays_prod.py."""
    cols = ([c.name for c in r.manifest.schema.columns]
            if (r.manifest and r.manifest.schema) else [])
    linhas, chunk = [], r.result
    while chunk is not None:
        linhas.extend(chunk.data_array or [])
        nxt = getattr(chunk, "next_chunk_index", None)
        if nxt is None:
            break
        chunk = w.statement_execution.get_statement_result_chunk_n(sid, nxt)
    return [dict(zip(cols, row)) for row in linhas]


def _run_pg(statement, want_rows, params):
    """run_sql no Postgres (ADR 0005). Mesma tradução de erro do Databricks: permissão -> 403,
    tabela/coluna ausente -> 502 com a marca que _objeto_ausente reconhece."""
    try:
        return db_pg.run(statement, want_rows, params, somente_leitura=SOMENTE_LEITURA)
    except db_pg.ErroSQL as e:
        print(f"[run_sql] PG: {e}", flush=True)
        raise _sql_http_error(str(e))


def run_sql(statement, want_rows=True, *, params=None):
    if dialeto.PG:
        return _run_pg(statement, want_rows, params)
    if params is not None:
        raise ValueError("params só existe no Postgres; no Databricks use sql_lit")
    if not WAREHOUSE_ID:
        raise HTTPException(500, "DATABRICKS_WAREHOUSE_ID não configurado.")
    w = _client()
    # Phase 0 perf: medir todo o execute+poll. gap_s = tempo desde o run_sql anterior
    # (global) — usado como heurística de cold-start. Nada aqui altera a consulta.
    global _last_stmt_mono
    _perf_t0 = time.monotonic()
    _perf_gap_s = (_perf_t0 - _last_stmt_mono) if _last_stmt_mono else 0.0
    poll_count = 0
    try:
        r = w.statement_execution.execute_statement(
            statement=statement, warehouse_id=WAREHOUSE_ID, wait_timeout="50s",
            disposition=Disposition.INLINE, format=Format.JSON_ARRAY,
            catalog=CATALOG, schema=SCHEMA)
        sid = r.statement_id
        while r.status and r.status.state in (StatementState.PENDING, StatementState.RUNNING):
            time.sleep(1)
            poll_count += 1
            r = w.statement_execution.get_statement(statement_id=sid)
    except HTTPException:
        raise
    except Exception as e:  # erros do SDK (auth/rede) — classifica por tipo/mensagem
        print(f"[run_sql] SDK error: {type(e).__name__}: {e}", flush=True)
        raise _sql_http_error(f"{type(e).__name__}: {e}")
    # Perf log: nunca pode quebrar a query — engole qualquer erro da instrumentação.
    try:
        _perf_ms = int((time.monotonic() - _perf_t0) * 1000)
        _perf_state = getattr(r.status, "state", None)
        _perf_state = _perf_state.value if hasattr(_perf_state, "value") else str(_perf_state)
        _perf_stmt_id = getattr(r, "statement_id", None)
        _perf_cold = _perf_gap_s > 300
        _perf_tag = " ".join(str(statement).split())[:60]
        _perf_acc = _perf_req.get()
        _perf_rid = _perf_acc.get("rid") if _perf_acc else "-"
        print(
            f"[perf] stmt rid={_perf_rid} ms={_perf_ms} polls={poll_count} "
            f"state={_perf_state} gap_s={_perf_gap_s:.1f} cold_suspect={_perf_cold} "
            f"stmt_id={_perf_stmt_id} tag={_perf_tag!r}",
            flush=True)
        _last_stmt_mono = time.monotonic()
        if _perf_acc is not None:
            _perf_acc["n"] += 1
            _perf_acc["total_ms"] += _perf_ms
            if _perf_ms > _perf_acc["max_ms"]:
                _perf_acc["max_ms"] = _perf_ms
    except Exception:
        pass
    if not r.status or r.status.state != StatementState.SUCCEEDED:
        msg = r.status.error.message if (r.status and r.status.error) else "erro desconhecido"
        print(f"[run_sql] SQL não-SUCCEEDED (state={getattr(r.status, 'state', None)}): {msg}", flush=True)
        raise _sql_http_error(msg)
    if not want_rows:
        return None
    return _materializa_linhas(w, sid, r)


def _run_sp(statement, want_rows=False):
    """SQL como o SERVICE PRINCIPAL do app (sem OBO). Uso restrito: seed/ensure de tabelas
    que QUALQUER usuário (mesmo read-only) precisa disparar no 1º load, sem depender do
    privilégio dele. NÃO usar p/ escritas atribuíveis (perde current_user())."""
    if dialeto.PG:
        return _run_pg(statement, want_rows, None)
    if not WAREHOUSE_ID:
        raise HTTPException(500, "DATABRICKS_WAREHOUSE_ID não configurado.")
    w = _sp_client()
    r = w.statement_execution.execute_statement(
        statement=statement, warehouse_id=WAREHOUSE_ID, wait_timeout="50s",
        disposition=Disposition.INLINE, format=Format.JSON_ARRAY, catalog=CATALOG, schema=SCHEMA)
    sid = r.statement_id
    while r.status and r.status.state in (StatementState.PENDING, StatementState.RUNNING):
        time.sleep(1)
        r = w.statement_execution.get_statement(statement_id=sid)
    if not r.status or r.status.state != StatementState.SUCCEEDED:
        msg = r.status.error.message if (r.status and r.status.error) else "erro desconhecido"
        raise RuntimeError(f"SP SQL falhou: {msg}")
    if not want_rows:
        return None
    return _materializa_linhas(w, sid, r)


@app.get("/api/health")
def health():
    return {"ok": True, "table": T_IN, "warehouse": bool(WAREHOUSE_ID)}


@app.get("/api/me")
def me():
    try:
        s = _sessao()
        # papel só existe no Postgres (ADR 0005); no Databricks a resposta segue {user}
        return {"user": s["user"], "papel": s["papel"]} if "papel" in s else {"user": s["user"]}
    except HTTPException:
        return {"user": None}


# --- Gestão: grupo bv_users + CRUD de analistas -----------------------------
GESTAO_GROUPS = ("bv_users", "bv_user")  # aceita ambos os nomes


def _is_gestao():
    """True se o usuário logado (OBO) pertence ao grupo de gestão. Checado via SQL
    (is_account_group_member/is_member) — roda COMO o usuário, sem exigir SCIM. Vem da
    _sessao() (1 query por token, cacheada)."""
    try:
        return _sessao()["gestao"]
    except HTTPException:
        return False


def _require_gestao():
    if not _is_gestao():
        raise HTTPException(403, "Restrito ao grupo de gestão (bv_users).")


ADMIN_GROUPS = ("bv_admins",)  # correção retroativa da validação BV (reescreve histórico)


def _is_admin():
    """True se o usuário logado (OBO) pertence a bv_admins. Mesmo mecanismo de _is_gestao
    (is_account_group_member/is_member via SQL, como o usuário — sem SCIM), via _sessao()."""
    try:
        return _sessao()["admin"]
    except HTTPException:
        return False


def _require_admin():
    if not _is_admin():
        raise HTTPException(403, "Restrito ao grupo de administração (bv_admins).")


@functools.lru_cache(maxsize=1)
def _migrate_analistas_cols():
    """Colunas do organograma (add-once por processo): organograma (aparece na aba Home) e
    papel (rótulo do cargo; o grupo é derivado dele no frontend)."""
    if dialeto.PG:  # no Postgres o schema vem das migrações (db/migrations), nunca do app
        return True
    for col, typ in (("organograma", "BOOLEAN"), ("papel", "STRING")):
        try:
            run_sql(f"SELECT {col} FROM {T_ANALISTAS} LIMIT 0")
        except HTTPException:
            run_sql(f"ALTER TABLE {T_ANALISTAS} ADD COLUMNS ({col} {typ})", want_rows=False)
    return True


# Espaços "invisíveis" que o Python e o JS classificam DIFERENTE: U+0085 (NEL) e U+001C-1F
# (separadores de registro) vêm de export de mainframe; U+200B (zero-width) e U+FEFF (BOM)
# vêm de CSV do Excel. Sem listá-los, `\s` do Python casa NEL/001C-1F e o do JS não, e o
# `trim()` do JS come o BOM e o `strip()` do Python não — a mesma pessoa viraria duas linhas
# no cadastro. Verificado por fuzz diferencial contra o JS (4k casos).
_ESPACOS_NOME_BV = re.compile(r"[\s\u0085\u001c-\u001f\u200b\ufeff]+")


def _norm_nome_bv(nome):
    r"""Chave canônica do Responsável BV. `sas_egp_pipeline.responsavel_bv` é texto livre
    digitado à mão, então caixa/acento/espaço duplo NÃO podem separar a mesma pessoa em
    duas sub-áreas. Regra replicada em frontend/src/subareas.ts (normNome) e em
    egps_analysis/scripts/seed_responsaveis_bv.py — mudou num, muda nos três (há teste
    diferencial das três em test_subarea_bv.py).

    Marca: filtra por CATEGORIA (Mn/Mc/Me = \p{M} do JS), não por `combining() != 0` —
    marcas de classe 0 (ex. tailandês U+0E31) são \p{M} mas têm combining 0, e as duas
    implementações discordariam nelas."""
    s = unicodedata.normalize("NFKD", (nome or "").lower())
    s = "".join(c for c in s if not unicodedata.category(c).startswith("M"))
    return _ESPACOS_NOME_BV.sub(" ", s).strip()


@functools.lru_cache(maxsize=1)   # 1x por processo — rodava CREATE em todo GET do prefetch
def _ensure_analistas_table():
    if dialeto.PG:  # no Postgres o schema vem das migrações (db/migrations), nunca do app
        return True
    run_sql(f"""CREATE TABLE IF NOT EXISTS {T_ANALISTAS} (email STRING, nome STRING,
  ativo BOOLEAN, created_by STRING, created_at STRING, updated_by STRING, updated_at STRING)
  USING DELTA""", want_rows=False)
    _migrate_analistas_cols()
    return True


@functools.lru_cache(maxsize=1)   # 1x por processo — rodava CREATE em todo GET do prefetch
def _ensure_responsaveis_bv_table():
    """Cadastro Responsável BV -> sub-área interna do cliente (Digital, MIS, Operações,
    Estratégia - cartões/rodas, Riscos). Fora do publish, como sas_analistas: o republish
    nunca a droparia, mas deixamos explícito porque ela guarda dado 100% humano."""
    if dialeto.PG:  # no Postgres o schema vem das migrações (db/migrations), nunca do app
        return True
    run_sql(f"""CREATE TABLE IF NOT EXISTS {T_RESPBV} (nome_key STRING, nome STRING,
  subarea STRING, ativo BOOLEAN, created_by STRING, created_at STRING,
  updated_by STRING, updated_at STRING) USING DELTA""", want_rows=False)
    return True


@app.get("/api/responsaveis-bv")
def responsaveis_bv_list(incluir_inativos: bool = False):
    """Cadastro de Responsáveis BV (fonte da sub-área em TODAS as abas e do datalist do
    campo Responsável BV). Leitura ABERTA de propósito: o filtro por sub-área precisa
    funcionar para qualquer usuário, não só para o grupo de gestão."""
    _ensure_responsaveis_bv_table()
    where = "" if incluir_inativos else "WHERE ativo IS NOT false"
    rows = run_sql(f"SELECT nome_key, nome, subarea, ativo FROM {T_RESPBV} {where} "
                   f"ORDER BY subarea NULLS FIRST, nome NULLS FIRST")
    return {"rows": rows, "is_gestao": _is_gestao()}


class ResponsavelBv(BaseModel):
    nome: str
    subarea: str | None = None
    ativo: bool | None = None


@app.post("/api/responsaveis-bv")
def responsaveis_bv_upsert(r: ResponsavelBv):
    """Cria/edita por nome_key. Upsert PARCIAL (coalesce): um toggle de ativo não apaga a
    sub-área. Restrito a bv_users."""
    _require_gestao()
    _ensure_responsaveis_bv_table()
    nome = (r.nome or "").strip()
    key = _norm_nome_bv(nome)
    if not key:
        raise HTTPException(400, "nome obrigatório")
    sub_upd = "NULL" if r.subarea is None else sql_lit(r.subarea.strip())
    sub_ins = "NULL" if r.subarea is None else sql_lit(r.subarea.strip())
    ativo_upd = "NULL" if r.ativo is None else str(bool(r.ativo)).lower()
    ativo_ins = "true" if r.ativo is None else str(bool(r.ativo)).lower()
    run_sql(
        f"MERGE INTO {T_RESPBV} t USING (SELECT {sql_lit(key)} AS nome_key) s "
        f"ON t.nome_key = s.nome_key "
        f"WHEN MATCHED THEN UPDATE SET nome = {sql_lit(nome)}, "
        f"subarea = coalesce({sub_upd}, t.subarea), "
        f"ativo = coalesce({ativo_upd}, t.ativo), "
        f"updated_by = {_ator()}, updated_at = cast({AGORA} AS STRING) "
        f"WHEN NOT MATCHED THEN INSERT (nome_key, nome, subarea, ativo, created_by, created_at, "
        f"updated_by, updated_at) VALUES ({sql_lit(key)}, {sql_lit(nome)}, {sub_ins}, {ativo_ins}, "
        f"{_ator()}, cast({AGORA} AS STRING), {_ator()}, "
        f"cast({AGORA} AS STRING))",
        want_rows=False)
    return {"ok": True, "nome_key": key, "nome": nome}


@functools.lru_cache(maxsize=1)
def _ensure_link_tables():
    """DDL bootstrap p/ o overlay de vínculo per-(EGP, Input). Duas tabelas persistentes,
    nunca dropadas pelo publish (padrão de T_CHOICE, T_PIPE): estado + auditoria. Executa
    uma vez por processo (lru_cache) — idempotente via CREATE IF NOT EXISTS."""
    if dialeto.PG:  # no Postgres o schema vem das migrações (db/migrations), nunca do app
        return True
    run_sql(f"""CREATE TABLE IF NOT EXISTS {T_LINK} (
      projeto STRING NOT NULL,
      chave_canonica STRING NOT NULL,
      link_broken BOOLEAN NOT NULL,
      updated_by STRING,
      updated_at TIMESTAMP
    ) USING DELTA""", want_rows=False)
    run_sql(f"""CREATE TABLE IF NOT EXISTS {T_LINK_AUD} (
      id STRING,
      projeto STRING,
      chave_canonica STRING,
      campo STRING,
      valor_antigo STRING,
      valor_novo STRING,
      ator STRING,
      ts TIMESTAMP
    ) USING DELTA""", want_rows=False)
    return True


@functools.lru_cache(maxsize=1)
def _ensure_dep_mantida_tables():
    """DDL bootstrap do overlay "a dependência CONTINUA viva" per-(EGP consumidor, Input).
    Mesmo padrão de T_LINK: estado + auditoria, persistentes, nunca dropadas pelo publish.

    É o ESPELHO do link_broken, na direção oposta. link_broken diz "este EGP não precisa
    deste input"; aqui o consumidor diz "eu ainda preciso do PRODUTOR deste input, mesmo
    com a tabela já no lake" — caso da ingestão parcial (carga única sem refresh, ou o
    consumidor lê do produtor algo que a tabela ingerida não cobre). Sem isto, a via conta
    como resolvida, a aresta morre e o produtor vira ex-dependência com o trabalho órfão.

    Tabela separada (e não uma 2ª coluna em T_LINK) de propósito: T_LINK tem a invariante
    "linha ausente ≡ linkado; só existem linhas para link_broken=true", e `_link_escreve`
    APAGA a linha ao restaurar — uma segunda flag ali seria apagada junto, em silêncio."""
    if dialeto.PG:  # no Postgres o schema vem das migrações (db/migrations), nunca do app
        return True
    run_sql(f"""CREATE TABLE IF NOT EXISTS {T_DEPM} (
      projeto STRING NOT NULL,
      chave_canonica STRING NOT NULL,
      motivo STRING,
      updated_by STRING,
      updated_at TIMESTAMP
    ) USING DELTA""", want_rows=False)
    run_sql(f"""CREATE TABLE IF NOT EXISTS {T_DEPM_AUD} (
      id STRING,
      projeto STRING,
      chave_canonica STRING,
      campo STRING,
      valor_antigo STRING,
      valor_novo STRING,
      ator STRING,
      ts TIMESTAMP
    ) USING DELTA""", want_rows=False)
    return True


def _deps_mantidas_rd(rd):
    """Pares (EGP consumidor, ARTIFACT upper) com a dependência mantida à mão. Recebe o
    leitor (`rd`) em vez de chamar run_sql, para servir tanto o app (OBO) quanto o caminho
    de Service Principal do _frontier_via — mesma regra, uma implementação.

    Guarda a chave por ARTIFACT porque é assim que a aresta declara a via (via_tabelas);
    a tabela grava chave_canonica (o grão do drawer), daí o join."""
    try:
        return {((r.get("projeto") or ""), (r.get("artifact") or "").strip().upper())
                for r in rd(f"SELECT d.projeto, i.artifact FROM {T_DEPM} d "
                            f"JOIN {T_IN} i ON i.chave_canonica = d.chave_canonica")
                if r.get("projeto") and (r.get("artifact") or "").strip()}
    except (HTTPException, RuntimeError) as e:
        if not _objeto_ausente(e):
            raise
        return set()


def _deps_mantidas():
    """Versão cacheada com a linhagem (invalida junto com o resto ao gravar)."""
    def _p():
        _ensure_dep_mantida_tables()
        return _deps_mantidas_rd(lambda sql: run_sql(sql))
    return _cache_lineage(("depsmantidas",), _p)


def _produtores_mantidos():
    """PRODUTORES que estão vivos porque algum consumidor apertou "ainda é dependência".
    Só serve à UI: é onde o botão precisa aparecer como ligado (para desfazer). Sem
    nenhum par mantido não custa query nenhuma."""
    def _p():
        mant = _deps_mantidas()
        if not mant:
            return set()
        out = set()
        for e in run_sql(f"SELECT projeto_alvo, depende_do, via_tabelas FROM {T_ED}"):
            a, d = e.get("projeto_alvo"), e.get("depende_do")
            if not a or not d or a == d:
                continue
            if any((a, t.strip().upper()) in mant
                   for t in (e.get("via_tabelas") or "").split("|") if t.strip()):
                out.add(d)
        return out
    return _cache_lineage(("prodmantidos",), _p)


@app.get("/api/analistas")
def analistas_list(incluir_inativos: bool = False):
    """Lista de analistas (fonte dos dropdowns de responsável E do organograma da Home).
    Aberta a qualquer usuário."""
    _ensure_analistas_table()
    where = "" if incluir_inativos else "WHERE ativo IS NOT false"
    rows = run_sql(f"SELECT email, nome, ativo, organograma, papel FROM {T_ANALISTAS} "
                   f"{where} ORDER BY nome, email")
    for r in rows:
        r["organograma"] = str(r.get("organograma")).lower() == "true"  # API devolve bool como string
    return {"rows": rows, "is_gestao": _is_gestao()}


def _canon_analista_email(email):
    """Email canônico de analista. Na Indicium a MESMA pessoa tem 2 sufixos
    (@indicium.tech e @indicium.ai) — o canônico é SEMPRE @indicium.ai (decisão
    2026-07); o local-part (nome.sobrenome) identifica a pessoa. Retorna
    (canônico, variante legada .tech p/ dedupe); legada = None fora da Indicium."""
    e = (email or "").strip().lower()
    if e.endswith("@indicium.tech"):
        e = e[:-len("@indicium.tech")] + "@indicium.ai"
    legado = (e[:-len("@indicium.ai")] + "@indicium.tech") if e.endswith("@indicium.ai") else None
    return e, legado


class Analista(BaseModel):
    email: str
    nome: str | None = None
    ativo: bool | None = None
    organograma: bool | None = None   # aparece na aba Home
    papel: str | None = None          # cargo (grupo derivado dele no frontend)


@app.post("/api/analistas")
def analistas_upsert(a: Analista):
    """Cria/edita analista (upsert por email). Restrito a bv_users."""
    _require_gestao()
    _ensure_analistas_table()
    email = (a.email or "").strip().lower()
    if not email or "@" not in email:
        raise HTTPException(400, "email inválido")
    email, legado = _canon_analista_email(email)
    if legado:
        # nome.sobrenome já cadastrado com o sufixo legado (.tech)? NUNCA duplica a
        # pessoa: migra a linha antiga para o canônico .ai (ou descarta a legada,
        # se o canônico já existe) e segue com o upsert normal.
        tem_canon = int(run_sql(f"SELECT count(*) AS n FROM {T_ANALISTAS} "
                                f"WHERE email = {sql_lit(email)}")[0]["n"])
        tem_leg = int(run_sql(f"SELECT count(*) AS n FROM {T_ANALISTAS} "
                              f"WHERE email = {sql_lit(legado)}")[0]["n"])
        if tem_leg and not tem_canon:
            run_sql(f"UPDATE {T_ANALISTAS} SET email = {sql_lit(email)}, "
                    f"updated_by = {_ator()}, updated_at = cast({AGORA} AS STRING) "
                    f"WHERE email = {sql_lit(legado)}", want_rows=False)
        elif tem_leg and tem_canon:
            run_sql(f"DELETE FROM {T_ANALISTAS} WHERE email = {sql_lit(legado)}", want_rows=False)
    # Upsert PARCIAL: campo ausente (None) no request NÃO é sobrescrito no UPDATE (coalesce
    # preserva o atual). Sem isto, um toggle de ativo/organograma/papel (que não manda nome)
    # zeraria o nome p/ o local-part do email e forçaria ativo=true.
    nome_ins = (a.nome or email.split("@")[0]).strip()
    nome_upd = "NULL" if a.nome is None else sql_lit(nome_ins)
    ativo_upd = "NULL" if a.ativo is None else str(bool(a.ativo)).lower()
    ativo_ins = "true" if a.ativo is None else str(bool(a.ativo)).lower()
    org_upd = "NULL" if a.organograma is None else str(bool(a.organograma)).lower()
    org_ins = "false" if a.organograma is None else str(bool(a.organograma)).lower()
    papel_lit = "NULL" if a.papel is None else sql_lit(a.papel.strip())
    run_sql(
        f"MERGE INTO {T_ANALISTAS} t USING (SELECT {sql_lit(email)} AS email) s ON t.email = s.email "
        f"WHEN MATCHED THEN UPDATE SET nome = coalesce({nome_upd}, t.nome), "
        f"ativo = coalesce({ativo_upd}, t.ativo), "
        f"organograma = coalesce({org_upd}, t.organograma), papel = coalesce({papel_lit}, t.papel), "
        f"updated_by = {_ator()}, updated_at = cast({AGORA} AS STRING) "
        f"WHEN NOT MATCHED THEN INSERT (email, nome, ativo, organograma, papel, created_by, created_at, updated_by, updated_at) "
        f"VALUES ({sql_lit(email)}, {sql_lit(nome_ins)}, {ativo_ins}, {org_ins}, {papel_lit}, {_ator()}, "
        f"cast({AGORA} AS STRING), {_ator()}, cast({AGORA} AS STRING))",
        want_rows=False)
    return {"ok": True, "email": email, "nome": nome_ins}


@app.delete("/api/analistas/{email}")
def analistas_delete(email: str):
    """Soft-delete (ativo=false) p/ não orfãozar atribuições. Restrito a bv_users."""
    _require_gestao()
    _ensure_analistas_table()
    e, _leg = _canon_analista_email((email or "").strip().lower())
    alvo = f"({sql_lit(e)}, {sql_lit(_leg)})" if _leg else f"({sql_lit(e)})"
    run_sql(f"UPDATE {T_ANALISTAS} SET ativo = false, updated_by = {_ator()}, "
            f"updated_at = cast({AGORA} AS STRING) WHERE email IN {alvo}", want_rows=False)
    return {"ok": True, "email": e}


@app.get("/api/metrics")
def metrics(scope: str = "indi", area: list[str] = Query(default=[])):
    _ensure_input_pipeline_cols()
    scope = "indi" if scope not in ("indi", "base") else scope
    # Cálculo AO VIVO do monitor (não do snapshot do publish) com status EFETIVO
    # (humano prevalece sobre o auto, igual ao Resumo) — assim editar um status reflete
    # nos cards imediatamente após a invalidação do React Query.
    conds = []
    if scope == "indi":
        conds.append("escopo_indi = true")
    if area:
        # areas é multivalorado (pipe-delimitado): "Cobranças | Crédito | Riscos".
        conds.append(f"areas IS NOT NULL AND {_lista_tem_algum('areas', area)}")
    where = (" WHERE " + " AND ".join(conds)) if conds else ""
    mod = _modern()
    rows = run_sql(
        f"SELECT count(*) AS inputs_distintos, "
        f"count_if(NOT ({mod})) AS inputs_a_ingerir, "
        f"count_if(origem IN ({sql_lit('SAS/Local (externo)')}, {sql_lit('SAS/Local (dependência)')})) AS total_saslocal, "
        f"count_if(origem = {sql_lit('Transacional')}) AS total_transacional, "
        f"count_if(origem IN ({sql_lit('Arquivo')}, {sql_lit('Script')})) AS total_arquivos_scripts, "
        f"count_if(origem = {sql_lit('BigQuery')}) AS total_bigquery, "
        f"count_if({mod}) AS total_modernizadas "
        f"FROM {T_IN}{where}")
    r = rows[0] if rows else {}
    keys = ("inputs_distintos", "inputs_a_ingerir", "total_saslocal", "total_transacional",
            "total_arquivos_scripts", "total_bigquery", "total_modernizadas")
    m = {k: int(r.get(k) or 0) for k in keys}
    inputs_distintos, total_modernizadas = m["inputs_distintos"], m["total_modernizadas"]
    m["pct_modernizado"] = round(100 * total_modernizadas / inputs_distintos, 1) if inputs_distintos else 0.0
    return m


# Kick-off da migração SAS (D0 do time). Base do eixo X do gráfico "Inputs recebidos".
KICKOFF = "2026-07-07"


def _serie_flag_familia(pwk_fam, membros, campo, campo_data):
    """Valor de uma flag do checklist para a FAMÍLIA.

    O que está gravado na chave da família manda (é onde `preworking_patch` grava hoje).
    Sem linha lá, a família só tem a flag quando TODAS as safras têm — mesmo roll-up do
    resto do app ("qualquer safra pendente segura a família") — e a data é a da ÚLTIMA,
    porque é quando a família inteira chegou lá."""
    if (pwk_fam.get(campo) or "") == "true":
        return {campo: "true", campo_data: pwk_fam.get(campo_data)}
    if membros and all((m.get(campo) or "") == "true" for m in membros):
        datas = [(m.get(campo_data) or "")[:10] for m in membros]
        return {campo: "true", campo_data: max(datas) if all(datas) else None}
    return {campo: None, campo_data: None}


def _serie_unidades(pwk_rows, san_date, pwk_familia):
    """Colapsa as linhas do universo (grão SAFRA) nas unidades que a série conta.

    Com FAMILIAS_ON, uma decisão de família é UMA decisão: sanitizar uma família de 47
    safras escreve 47 linhas de auditoria no mesmo instante (fan-out de `_patch_familia`),
    e a barra semanal subia 47 para algo que toda outra superfície conta como 1 — com
    `universo_total` citando ~2,4k ao lado de um Resumo dizendo ~1,4k.

    Duas consequências do grão antigo que somem aqui:
      - o `LEFT JOIN` do checklist é por chave de SAFRA, então a linha gravada na chave da
        família era invisível e família nenhuma contava em `recebidos`/`modernizados_bv`;
      - `san_date` por safra fazia a família aparecer na semana da PRIMEIRA safra
        sanitizada, não na semana em que ficou inteira resolvida.

    Regra única, herdada do ADR 0002: a família está num estado quando TODAS as safras
    estão, e a data é a da última a chegar lá. Devolve dicts no mesmo shape que o laço de
    classificação consome, com a data de sanitização já resolvida em `_san`."""
    if not FAMILIAS_ON:
        return [dict(r, _san=san_date.get(r["chave_canonica"])) for r in pwk_rows]
    mapa = _familias_corpus()["chave"]
    grupos, soltas = {}, []
    for r in pwk_rows:
        cat = (r.get("categoria") or "").strip()
        fam = mapa.get((cat, (r.get("artifact") or "").strip().upper()))
        if fam:
            grupos.setdefault((cat, fam), []).append(r)
        else:
            soltas.append(r)
    unidades = [dict(r, _san=san_date.get(r["chave_canonica"])) for r in soltas]
    for (cat, fam), membros in grupos.items():
        datas_san = [san_date.get(m["chave_canonica"]) for m in membros]
        unidades.append({
            "chave_canonica": _chave_familia(cat, fam),
            "eff_status": ("Sanitizado"
                           if all(m.get("eff_status") == "Sanitizado" for m in membros)
                           else None),
            "_san": max(datas_san) if all(datas_san) else None,
            **_serie_flag_familia(pwk_familia.get(_chave_familia(cat, fam)) or {}, membros,
                                  "modernizado_bv", "data_modernizado_bv"),
            **_serie_flag_familia(pwk_familia.get(_chave_familia(cat, fam)) or {}, membros,
                                  "recebido", "data_recebimento"),
        })
    return unidades


@app.get("/api/inputs-recebidos-serie")
def inputs_recebidos_serie():
    """TRÊS séries POR SEMANA desde o kick-off (2026-07-07), MUTUAMENTE EXCLUSIVAS: cada
    input soma em no máximo 1 das 3 (nunca nas duas), decidido por PRIORIDADE sobre o
    estado ATUAL efetivo — um input "no meio da esteira" (etapa Ingestão UAT/PDI + GMUD/
    Ingestão PRD/Aplicação de Grant, sem nenhuma das flags abaixo) não aparece em
    NENHUMA das 3 (aceito conscientemente — o funil completo vive no gráfico de
    ingestão, não aqui). Refatoração 2026-08 (era 2 séries sobrepostas — recebidos/
    desbloqueados por transição de etapa; ver git log p/ a versão anterior).

    1. `sanitizados` (prioridade mais alta): status ATUAL = 'Sanitizado' (_eff_status_input,
       qualquer etapa — mesma regra de _sanitizado() usada no resto do app). Data = 1º
       evento válido de STATUS→'Sanitizado' em `sas_inputs_audit` (T_AUD, campo='status'
       UNIDO ao legado campo='status_humano' com valor_novo IN ('Sanitizado','Sanitizada',
       'Descartada','Descartado') — mesmo mapeamento de STATUS_CASE em
       scripts/migrate_input_status_split.py). Única série com a regra de "evento válido":
       um evento de ETAPA p/ 'A Receber' (novo ou legado, traduzido) invalida qualquer
       marcação de Sanitizado anterior a ele — o válido é o 1º evento após o último reset
       (ou o 1º absoluto se nunca houve reset). Sem evento válido (reset sem novo evento
       depois, ou histórico não coberto pelo audit) → bucket `pré`.
    2. `modernizados_bv`: checkbox manual `modernizado_bv='true'` no checklist de
       pré-working (sas_inputs_preworking) — input que o BANCO já modernizou fora da
       nossa esteira, informado à parte pela área de negócio (NÃO é derivado de
       `modernizada_auto`: esse campo é sobrescrito a cada publish sem gravar quando
       virou 'Disponível', então não tem data confiável — ver PREWORKING_CAMPOS_BV).
       Data = `data_modernizado_bv` (campo direto, digitado 1x, SEM lógica de reset).
    3. `recebidos`: checkbox `recebido='true'` do checklist de pré-working, qualificado
       pela exclusão das 2 séries acima (senão um input sanitizado ou já modernizado pelo
       BV, mas que também passou pelo recebimento, contaria 2x). Data = `data_recebimento`
       (campo direto, SEM lógica de reset).

    Em qualquer série, flag=true mas data vazia (ainda não preenchida) → bucket `pré`
    (mesmo padrão do antigo "auto-modernizado sem audit"). Buckets de 7 dias ancorados no
    kick-off (uma terça): 07/07, 14/07, 21/07... Última barra = semana em curso (partial,
    fill dessaturado).

    Resposta também traz `sem_categoria` (quantos do universo não caem em NENHUMA das 3 —
    "no meio da esteira" ou ainda "A Receber", sem data p/ virar barra) e `universo_total`
    (tamanho do universo indi_deps hoje), pro front mostrar "quantos ainda faltam
    classificar" como estatística à parte (não é uma barra — não tem data associada).

    Universo = indi_deps de hoje (frontier)."""
    from datetime import date, timedelta
    kick = date.fromisoformat(KICKOFF)
    hoje = date.today()
    _ensure_input_pipeline_cols()
    _ensure_preworking_table()

    try:
        frontier = _frontier_egps("indi_deps", [])[0]
    except HTTPException:
        frontier = set()
    if frontier:
        _finl = ", ".join(sql_lit(p) for p in frontier)
        universe_where = (f"chave_canonica IN (SELECT DISTINCT chave_canonica FROM {T_EGP} "
                          f"WHERE projeto IN ({_finl}))")
    else:
        universe_where = "escopo_indi = true"  # fallback

    eff_st = _eff_status_input()
    # Mesmo mapeamento legado de sempre (ver comentário histórico em git blame) — só as
    # saídas 'A Receber' importam aqui (fonte do reset); as demais são inertes p/ este uso.
    LEGACY_ETAPA_CASE = (
        "CASE valor_novo "
        "WHEN 'A receber' THEN 'A Receber' WHEN 'A ingerir' THEN 'A Receber' "
        "WHEN 'Não recebido' THEN 'A Receber' "
        "WHEN 'Recebido' THEN 'Recebido' WHEN 'Em análise' THEN 'Recebido' "
        "WHEN 'Priorizado' THEN 'Recebido' "
        "WHEN 'Em ingestão' THEN 'Ingestão UAT' "
        "WHEN 'Modernizado' THEN 'Modernizado' WHEN 'Disponível' THEN 'Modernizado' "
        "WHEN 'Sanitizado' THEN 'Modernizado' WHEN 'Sanitizada' THEN 'Modernizado' "
        "WHEN 'Descartada' THEN 'Modernizado' WHEN 'Descartado' THEN 'Modernizado' "
        "ELSE NULL END")
    # Equivalente legado de STATUS='Sanitizado' (STATUS_CASE em migrate_input_status_split.py
    # — não confundir com LEGACY_ETAPA_CASE acima, que mapeia os MESMOS valores p/ ETAPA).
    LEGACY_STATUS_SANITIZADO_VALS = "'Sanitizado','Sanitizada','Descartada','Descartado'"
    try:
        san_rows = run_sql(
            # aud_et = eventos de ETAPA (fonte só do reset agora); aud_san = eventos de
            # STATUS→Sanitizado (novo + legado traduzido); san = 1º evento válido de
            # Sanitizado por input (após o último reset), 1 linha por chave_canonica.
            f"WITH aud_et AS (SELECT chave_canonica, updated_at, valor_novo AS nvo "
            f"    FROM {T_AUD} WHERE campo = 'etapa' AND {universe_where} "
            f"  UNION ALL "
            f"  SELECT chave_canonica, updated_at, {LEGACY_ETAPA_CASE} AS nvo "
            f"    FROM {T_AUD} WHERE campo = 'status_humano' AND {universe_where}), "
            f"reset AS (SELECT chave_canonica, max(updated_at) AS reset_at "
            f"  FROM aud_et WHERE nvo = 'A Receber' GROUP BY chave_canonica), "
            f"aud_san AS (SELECT chave_canonica, updated_at FROM {T_AUD} "
            f"    WHERE campo = 'status' AND valor_novo = 'Sanitizado' AND {universe_where} "
            f"  UNION ALL SELECT chave_canonica, updated_at FROM {T_AUD} "
            f"    WHERE campo = 'status_humano' AND valor_novo IN ({LEGACY_STATUS_SANITIZADO_VALS}) "
            f"    AND {universe_where}) "
            f"SELECT a.chave_canonica, date_format(min(a.updated_at), 'yyyy-MM-dd') AS dia "
            f"  FROM aud_san a LEFT JOIN reset r ON a.chave_canonica = r.chave_canonica "
            f"  WHERE (r.reset_at IS NULL OR a.updated_at > r.reset_at) "
            f"  GROUP BY a.chave_canonica")
    except HTTPException:
        san_rows = []
    san_date = {r["chave_canonica"]: r["dia"] for r in san_rows}

    # Estado atual de cada input do universo (status efetivo + os 2 campos manuais do
    # checklist de pré-working). `universe_where` isolado numa CTE de 1 tabela só (T_IN) —
    # T_PWK também tem coluna chave_canonica, então aplicar universe_where já com o LEFT
    # JOIN em escopo geraria referência ambígua em Spark.
    pwk_rows = run_sql(
        f"WITH universo AS (SELECT chave_canonica, categoria, artifact, {eff_st} AS eff_status "
        f"  FROM {T_IN} i WHERE {universe_where}) "
        f"SELECT u.chave_canonica, u.categoria, u.artifact, u.eff_status, p.modernizado_bv, "
        f"p.data_modernizado_bv, p.recebido, p.data_recebimento FROM universo u "
        f"LEFT JOIN {T_PWK} p ON p.chave_canonica = u.chave_canonica")

    # Checklist gravado NA chave da família: não sai do JOIN acima (que é por chave de
    # safra) e é onde `preworking_patch` grava. Tabela pequena, recorte por prefixo.
    pwk_familia = {}
    if FAMILIAS_ON:
        try:
            pwk_familia = {r["chave_canonica"]: r for r in run_sql(
                f"SELECT chave_canonica, modernizado_bv, data_modernizado_bv, recebido, "
                f"data_recebimento FROM {T_PWK} "
                f"WHERE chave_canonica LIKE {sql_lit(FAMILIA_PREFIX + '%')}")}
        except HTTPException:
            pwk_familia = {}

    unidades = _serie_unidades(pwk_rows, san_date, pwk_familia)

    by_day: dict[str, list[int]] = {}
    sem_categoria = 0

    def _bump(dia: str | None, idx: int):
        rec = by_day.setdefault(dia or "pre", [0, 0, 0])
        rec[idx] += 1

    for r in unidades:
        if r.get("eff_status") == "Sanitizado":
            _bump(r.get("_san"), 0)
        elif (r.get("modernizado_bv") or "") == "true":
            _bump((r.get("data_modernizado_bv") or "")[:10] or None, 1)
        elif (r.get("recebido") or "") == "true":
            _bump((r.get("data_recebimento") or "")[:10] or None, 2)
        else:
            # no meio da esteira (ou ainda "A Receber"), sem nenhuma das 3 flags -> não
            # conta em nenhuma coluna do gráfico. Reportado à parte (sem_categoria) pro
            # front mostrar "quantos ainda faltam classificar", já que não tem data p/
            # virar uma barra semanal.
            sem_categoria += 1

    kick_iso = kick.isoformat()
    pre = [sum(v[i] for k, v in by_day.items() if k == "pre" or k < kick_iso) for i in range(3)]
    out = [{"dia": "pre", "sanitizados": pre[0], "modernizados_bv": pre[1], "recebidos": pre[2]}]
    d = kick
    while d <= hoje:
        tot = [sum(by_day.get((d + timedelta(days=i)).isoformat(), [0, 0, 0])[j]
                   for i in range(7)) for j in range(3)]
        out.append({"dia": d.isoformat(), "sanitizados": tot[0], "modernizados_bv": tot[1],
                    "recebidos": tot[2]})
        d += timedelta(days=7)
    return {"rows": out, "kickoff": KICKOFF, "sem_categoria": sem_categoria,
            "universo_total": len(unidades)}


# area_principal (1 área/input, lastreada no frontier) vive em T_RES; trazemos por subquery
# correlacionada em chave_canonica. O max() é exigência do Spark (subquery escalar correlacionada
# precisa agregar) — como é 1:1 por chave, devolve o único valor. Exige alias `i` no T_IN dos
# SELECTs que usam INPUTS_COLS (as demais colunas resolvem p/ i sozinhas).
INPUTS_COLS = (
    "chave_canonica, artifact, categoria, origem, source_types, qtd_projetos, areas, "
    "escopo_indi, modernizada_auto, etapa, status, responsavel, observacao, orfao, "
    "paths_fisicos, n_paths_fisicos, "
    f"(SELECT max(r.area_principal) FROM {T_RES} r WHERE r.chave_canonica = i.chave_canonica) AS area_principal")

# Cap do load do dataset COMPLETO do escopo (caminho cacheado, sem filtros). Folgado
# bem acima do tamanho real (~11k hoje) p/ garantir que o conjunto cabe INTEIRO no cache
# — nunca truncar o escopo. Diferente do READ_CAP (cap dos caminhos filtrados/legados).
SCOPE_DATASET_CAP = 100000


# ---- sanitização DERIVADA do input (§3.4.15 e §3.4.18 da spec da unificação) ------
# Input cujos consumidores no recorte ativo são TODOS despriorizados (§3.4.18) ou TODOS
# antecessores de um vínculo (§3.4.15) não é fila de ingestão. A régua pura mora em
# sanitizacao.py; aqui só a query e o cache. As duas origens saem no MESMO dicionário, de
# propósito: quem conta não precisa saber de onde veio, e o motivo fica na linha.
# NADA é gravado: o conjunto é recalculado por geração de cache, então repriorizar um EGP
# ou desfazer um vínculo devolve os inputs à fila sozinho, no request seguinte.

def _sanitizacao_derivada():
    """{chave_canonica: motivo} dos inputs sanitizados por derivação.

    Duas origens, um conjunto só: consumidores todos despriorizados (§3.4.18) ou todos
    antecessores de um vínculo (§3.4.15).

    Consumidores = EGPs do recorte ATIVO (Indi ∪ deps) com vínculo NÃO quebrado — a
    exclusividade é medida contra o escopo ativo, não contra o corpus (§3.4.16). Um
    recorte ÚNICO (o mais largo) para o app inteiro, de propósito: por escopo, a MESMA
    chave sairia sanitizada na visão +deps e pendente na visão de escopo, na mesma página.

    Cacheado por geração como _egps_fora_backlog — todo PATCH de egp-pipeline bumpa a
    geração, e é o mesmo PATCH que grava o vínculo. Sem despriorizado E sem vínculo no
    recorte, ou sem grafo publicado, devolve {} sem custo de query."""
    def _p():
        try:
            frontier, _b = _frontier_egps("indi_deps", [])
        except HTTPException as e:
            if not _objeto_ausente(e):
                raise
            return {}                       # grafo ainda não publicado
        fora = _egps_fora_backlog()
        # Antecessores DENTRO do recorte: vínculo de EGP fora do recorte não resolve
        # input nenhum, e a interseção mantém honesto o short-circuit abaixo.
        ante = set(_vinculos_por_antecessor()) & set(frontier)
        if not frontier or not (fora or ante):
            return {}
        _ensure_link_tables()
        _ensure_input_pipeline_cols()
        fin = ", ".join(sql_lit(p) for p in frontier)
        # pendentes: `_aingerir` SEM overlay (é a entrada da derivação, não o resultado).
        # As duas leituras são independentes: 1 onda, não 2 rodadas.
        cons_rows, pend_rows = _parallel(
            lambda: run_sql(
                f"SELECT e.chave_canonica AS ch, e.projeto AS pj FROM {T_EGP} e "
                f"LEFT JOIN {T_LINK} l ON l.projeto = e.projeto "
                f"AND l.chave_canonica = e.chave_canonica "
                f"WHERE e.projeto IN ({fin}) AND NOT coalesce(l.link_broken, false)"),
            lambda: run_sql(f"SELECT chave_canonica FROM {T_IN} WHERE {_aingerir()}"))
        cons = {}
        for r in cons_rows:
            cons.setdefault(r.get("ch"), set()).add(r.get("pj"))
        pend = {r["chave_canonica"] for r in pend_rows}
        return sanitizacao.motivos_derivados(cons, fora, ante, pend)
    return _cache_lineage(("san_derivada",), _p)


# ---- o preço do §3.4.16: a fila pode crescer sozinha ------------------------------
# A exclusividade é medida contra o ESCOPO ATIVO, não contra o corpus — decisão
# consciente da gestão, ciente de que chaves voltam sozinhas. O aviso põe esse preço na
# tela ("N chaves estão fora da fila só porque M EGPs estão fora do escopo") em vez de
# deixá-lo implícito, e o rollup inverso responde a pergunta acionável: quem é o EGP
# que, se entrar, devolve 40 chaves. Medido em 24/09: até 73 chaves.
# Log DIÁRIO de contadores: o presente é sempre recalculado, então sem foto não há
# passado — e histórico não se reconstrói. Chave `san_contadores::<YYYY-MM-DD>` em
# sas_app_config, SÓ número, e NADA o lê de volta (ver _log_san_contadores).
SAN_LOG_CHAVE = "san_contadores"
# Saída de emergência do log, sem redeploy do resto: desligar NÃO muda nenhum número
# da fila (é o critério de aceite do ticket 15, e test_desligar_o_log_nao_muda_*).
# Na AWS em modo leitura (ADR 0005, Fase 1) quem grava o log é o app do Databricks; com a
# escrita ligada (Fase 2, o espelho é a fonte) o Postgres grava, senão a série para na virada.
_SAN_LOG_ON = (os.environ.get("SAN_LOG_DIARIO", "1").strip().lower() not in ("0", "false", "no")
               and not (dialeto.PG and SOMENTE_LEITURA))
_san_log_dia = None   # dia já gravado por ESTE processo (a escrita é idempotente por data)


def _fragilidade_sanitizacao():
    """{n_chaves, n_egps, chaves, por_egp} das chaves sanitizadas por derivação que
    dependem de EGPs FORA do recorte para continuar fora da fila.

    Consumidor no corpus mas fora do recorte ativo não entra na régua (§3.4.16): se ele
    entrar no escopo vira consumidor vivo e a chave volta à fila sozinha. Mesmo filtro
    de vínculo quebrado do conjunto derivado — par resolvido não devolve chave nenhuma.

    Cacheado por geração como o conjunto derivado (o mesmo bump invalida os dois). Sem
    grafo publicado, ou sem chave derivada, devolve a fragilidade vazia sem query."""
    def _p():
        motivos = _sanitizacao_derivada()
        try:
            frontier = _frontier_egps("indi_deps", [])[0]
        except HTTPException:
            return sanitizacao.fragilidade({}, {})   # sem grafo: nada a medir, nada a logar
        fora = {}
        if motivos:
            _ensure_link_tables()
            cin = ", ".join(sql_lit(c) for c in motivos)
            for r in run_sql(
                    f"SELECT e.chave_canonica AS ch, e.projeto AS pj FROM {T_EGP} e "
                    f"LEFT JOIN {T_LINK} l ON l.projeto = e.projeto "
                    f"AND l.chave_canonica = e.chave_canonica "
                    f"WHERE e.chave_canonica IN ({cin}) "
                    f"AND NOT coalesce(l.link_broken, false)"):
                if r.get("pj") and r.get("pj") not in frontier:
                    fora.setdefault(r.get("ch"), set()).add(r.get("pj"))
        frag = sanitizacao.fragilidade(motivos, fora)
        try:
            _log_san_contadores(motivos, frag["n_chaves"])
        except Exception as e:
            # O log é efeito colateral, nunca etapa: warehouse fora do ar não pode
            # mudar um número da fila. Falha aparece no stdout do app (Logs do
            # Databricks App), não na tela.
            print(f"[san] log diário falhou (ignorado): {e!r}", flush=True)
        return frag
    return _cache_lineage(("san_frageis",), _p)


def _log_san_contadores(motivos, n_frageis):
    """Uma linha por dia em sas_app_config: {data, n por origem, n_frageis}.

    **SÓ contador, NUNCA o estado derivado** — nenhuma chave entra (garantido em
    sanitizacao.contadores). Se o log virasse fonte de verdade em qualquer caminho, a
    reversibilidade morreria, e a reversibilidade é a razão de o desenho inteiro ser
    derivado. Por isso NADA neste módulo lê a chave `san_contadores::*`: a série existe
    só para quem for olhar o passado por fora do app.

    APPEND, idempotente por data: `WHEN NOT MATCHED THEN INSERT` e nada mais. A linha
    do dia é a PRIMEIRA foto do dia e não é reescrita — sobrescrever apagaria história,
    e é a mesma razão de `sas_app_config` (tabela viva da configuração da gestão) nunca
    ser dropada nem recriada aqui. Sem job novo: grava quando o dado é calculado."""
    global _san_log_dia
    if not _SAN_LOG_ON:
        return
    hoje = datetime.date.today().isoformat()      # um só: a chave e o payload não podem
    if _san_log_dia == hoje:
        # A linha do dia é a PRIMEIRA foto e o MERGE abaixo nunca a reescreve: repetir no
        # mesmo processo era CREATE + MERGE (~2-4 s) em todo miss de cache de um GET.
        return
    chave = f"{SAN_LOG_CHAVE}::{hoje}"            # divergir se o dia virar no meio
    valor = json.dumps(sanitizacao.contadores(motivos, n_frageis, hoje),
                       ensure_ascii=False, sort_keys=True)
    if not dialeto.PG:  # no Postgres o schema vem das migrações (db/migrations), nunca do app
        run_sql(f"CREATE TABLE IF NOT EXISTS {T_CFG} "
                f"(chave STRING, valor STRING, updated_by STRING, updated_at STRING)",
                want_rows=False)
    run_sql(
        f"MERGE INTO {T_CFG} t USING (SELECT {sql_lit(chave)} AS chave) s "
        f"ON t.chave = s.chave "
        f"WHEN NOT MATCHED THEN INSERT (chave, valor, updated_by, updated_at) VALUES "
        f"({sql_lit(chave)}, {sql_lit(valor)}, {_ator()}, "
        f"cast({AGORA} AS STRING))", want_rows=False)
    _san_log_dia = hoje   # só depois do MERGE: falha deixa a próxima leitura tentar de novo


def _san_derivada_sql(col="e.chave_canonica"):
    """Expressão SQL BOOLEAN da sanitização derivada, para o slot `lnk` das geradoras de
    input_state — o MESMO slot do vínculo quebrado, e pela mesma razão: o par
    (EGP, input) está resolvido sem que ninguém tenha gravado status. Sem chave derivada,
    'false' (a expressão some sem mudar nenhum plano de execução)."""
    chaves = _sanitizacao_derivada()
    if not chaves:
        return "false"
    return f"{col} IN ({', '.join(sql_lit(c) for c in chaves)})"


def _lnk_resolvido(col="e.chave_canonica"):
    """`lnk` completo dos pares (EGP, input): vínculo quebrado OU sanitizado por derivação.
    Substitui o literal "coalesce(l.link_broken, false)" nas queries que já fazem o LEFT
    JOIN em T_LINK. NÃO usar no _blocking (semântica downstream, intocada — ver
    _egps_fora_backlog)."""
    return f"(coalesce(l.link_broken, false) OR {_san_derivada_sql(col)})"


def _enrich_n_proj_ativos(rows):
    """Anota cada linha com `n_proj_ativos` — mesma semântica da coluna homônima no EGP
    detail: consumidores do input que estão em Indi ∪ deps, NÃO despriorizados E que NÃO
    quebraram o vínculo com o input. Cacheia junto com o escopo do dataset porque
    `_lineage_gen` bumpa em toda mudança que afeta esse cálculo (patch_input,
    set/clear_output_producer, escopo, patch_egp_input_link). No-op se `rows` vazio."""
    if not rows:
        return rows
    _ensure_link_tables()
    _fora = _egps_fora_backlog()
    try:
        _ativo_set = _frontier_egps("indi_deps", [])[0] - _fora
    except HTTPException:
        _ativo_set = set()
    _chaves = {r.get("chave_canonica") for r in rows if r.get("chave_canonica")}
    if not _ativo_set or not _chaves:
        for r in rows:
            r["n_proj_ativos"] = 0
        return rows
    _cin = ", ".join(sql_lit(c) for c in _chaves)
    _pin = ", ".join(sql_lit(p) for p in _ativo_set)
    counts = {r["chave_canonica"]: int(r["n"]) for r in run_sql(
        f"SELECT e.chave_canonica, count(DISTINCT e.projeto) AS n FROM {T_EGP} e "
        f"LEFT JOIN {T_LINK} l ON l.projeto = e.projeto AND l.chave_canonica = e.chave_canonica "
        f"WHERE e.chave_canonica IN ({_cin}) AND e.projeto IN ({_pin}) "
        f"AND NOT coalesce(l.link_broken, false) GROUP BY e.chave_canonica")}
    for r in rows:
        r["n_proj_ativos"] = counts.get(r.get("chave_canonica"), 0)
    return rows


def _enrich_vinculo_ativo(rows, egp_where):
    """Anota `vinculo_ativo` (bool Python → JSON bool): o input tem ≥1 vínculo NÃO
    quebrado com EGP do recorte — MESMO universo dos contadores do Resumo
    (_ch_vinculo_ativo). False = todos os vínculos quebrados: a linha segue visível na
    tabela (com aviso), mas o front a EXCLUI dos cards p/ bater com o Resumo. Difere de
    n_proj_ativos, que também desconta despriorizados (régua mais estrita — não serve
    p/ universo). Cacheado junto com o dataset (bump de _lineage_gen no PATCH de link)."""
    if not rows:
        return rows
    _ensure_link_tables()
    ativas = {r["chave_canonica"] for r in run_sql(
        f"SELECT chave_canonica FROM {_ch_vinculo_ativo(egp_where)} s")}
    for r in rows:
        r["vinculo_ativo"] = r.get("chave_canonica") in ativas
    return rows


def _enrich_autoprodutor(rows):
    """Anota `autoprodutor_candidato` (bool) e `autoprodutor_egp` (projeto candidato, ou
    None) — ver _autoprodutor_candidatos(). Cacheado junto com o dataset (mesma geração
    de _lineage_gen dos enriquecimentos acima)."""
    if not rows:
        return rows
    cand = _autoprodutor_candidatos()
    for r in rows:
        proj = cand.get(r.get("chave_canonica"))
        r["autoprodutor_candidato"] = proj is not None
        r["autoprodutor_egp"] = proj
    return rows


# --- Família de safras: corpus, consumidores e agregação -----------------------
# A safra deixou de ser unidade de trabalho (docs/adr/0002). Estes helpers colapsam as
# linhas do monitor (grão safra) em linhas de FAMÍLIA, sem tocar no banco: a chave da
# família só existe na resposta da API. O grafo (linhagem/produtor/bloqueio) continua no
# grão físico de propósito — família aqui é contagem, exibição e estado.
FAMILIA_PREFIX = "familia::"


def _chave_familia(categoria, familia):
    """Chave de transporte da família. Namespace PRÓPRIO (`familia::`) e não `categoria::`
    de propósito: nenhuma tabela do banco é chaveada por família (o estado mora nas safras,
    por fan-out — ver ADR 0002), então uma chave que vaze para uma escrita tem que ser
    reconhecível num grep, não passar por chave real."""
    return f"{FAMILIA_PREFIX}{categoria}::{familia}"


def _familias_corpus():
    """Mapa de famílias sobre o CORPUS INTEIRO (linhas não-órfãs), cacheado por geração.

    Corpus inteiro, nunca o recorte em tela: a guarda dos ≥2 membros é decisão de corpus —
    resolver sobre o filtro faria a mesma tabela ser "família" num escopo e "input solto"
    noutro (ver familias.py, invariante 3). `strict=False`: override apontando para
    artefato que sumiu não pode derrubar request de usuário; quem falha alto nisso é
    egps_analysis/scripts/verifica_familias.py, rodado no dev/CI."""
    def _p():
        # paths_fisicos entra porque a safra em ARQUIVO colapsa por (diretório, padrão)
        # — sem ele o arquivo não tem evidência e não vira família (ver familias.py).
        rows = run_sql(f"SELECT artifact, categoria, paths_fisicos FROM {T_IN} "
                       f"WHERE orfao = false")
        return familias.resolve(rows, strict=False)
    return _cache_lineage(("familias_corpus",), _p)


def _familia_por_chave():
    """{chave_canonica física -> chave da família}, corpus inteiro, cacheado por geração.

    Payloads chaveados pela tabela FÍSICA (auditoria em T_AUD, inputs de uma versão recebida)
    precisam apontar para a linha que a tela EXIBE — e com FAMILIAS_SAFRA=1 quem aparece na
    aba Inputs é a família. Sem este mapa o link cai numa chave de safra que não está na
    lista, e o usuário lê "não encontrado" como se o input tivesse sumido do corpus.

    Flag desligada => mapa vazio (a tela volta a exibir safra; remapear seria o mesmo erro
    ao contrário). Só entra quem é família no CORPUS (≥2 membros), igual ao resto.

    Não reusa _pwk_familia_de de propósito: aquela resolve um punhado de chaves por request
    (SELECT por bloco de 400); esta resolve o corpus de uma vez, uma vez por geração."""
    if not FAMILIAS_ON:
        return {}

    def _p():
        corpus = _familias_corpus()
        mapa, membros = corpus["chave"], corpus["membros"]
        out = {}
        for r in run_sql(f"SELECT chave_canonica, categoria, artifact FROM {T_IN} WHERE orfao = false"):
            cat = (r.get("categoria") or "").strip()
            art = (r.get("artifact") or "").strip().upper()
            eff = mapa.get((cat, art), art)
            if len(membros.get((cat, eff), ())) > 1:
                out[r["chave_canonica"]] = _chave_familia(cat, eff)
        return out
    return _cache_lineage(("familia_por_chave",), _p)


def _familia_egp_counts():
    """{(categoria, chave_efetiva): {"qtd": consumidores, "ativos": consumidores ativos}}.

    Consumidor é contado DISTINTO por família — somar `qtd_projetos` das safras inflaria
    (o mesmo EGP lê 47 safras da mesma tabela num `SET` só). "ativos" segue a régua de
    _enrich_n_proj_ativos: EGP em Indi ∪ deps, não despriorizado, vínculo não quebrado.
    Os 22k pares de sas_egp_inputs vêm de uma vez e a agregação é em memória, cacheada
    por geração — mais barato que uma query por família."""
    def _p():
        _ensure_link_tables()
        mapa = _familias_corpus()["chave"]
        try:
            ativos_egp = _frontier_egps("indi_deps", [])[0] - _egps_fora_backlog()
        except HTTPException:
            ativos_egp = set()
        pares = run_sql(
            f"SELECT e.categoria, e.artifact, e.projeto, "
            f"coalesce(l.link_broken, false) AS broken "
            f"FROM {T_EGP} e LEFT JOIN {T_LINK} l "
            f"ON l.projeto = e.projeto AND l.chave_canonica = e.chave_canonica")
        agg = {}
        for p in pares:
            cat = (p.get("categoria") or "").strip()
            art = (p.get("artifact") or "").strip().upper()
            pj = p.get("projeto")
            if not art or not pj:
                continue
            eff = mapa.get((cat, art), art)
            d = agg.setdefault((cat, eff), {"projetos": set(), "ativos": set()})
            d["projetos"].add(pj)
            if str(p.get("broken")).lower() != "true" and pj in ativos_egp:
                d["ativos"].add(pj)
        return {k: {"qtd": len(v["projetos"]), "ativos": len(v["ativos"])}
                for k, v in agg.items()}
    return _cache_lineage(("familia_egp_counts",), _p)


def _fam_sql_egp(art="coalesce(i.artifact, e.artifact)",
                 cat="coalesce(i.categoria, e.categoria)",
                 paths="i.paths_fisicos"):
    """Chave de família em SQL para as queries que juntam sas_egp_inputs (e) com o monitor (i).

    Usa o CANDIDATO (sem a janela dos ≥2 membros) de propósito: dois artefatos só caem no
    mesmo candidato se forem membros da mesma família, e o candidato de um artefato
    solitário é 1:1 com ele — logo `count(DISTINCT candidato)` JÁ é a contagem por família,
    sem window function. Isso é o que permite converter os contadores por EGP sem
    reescrever as queries em CTE.

    `paths` vem do MONITOR (`i`): os 5 chamadores desta função têm esse join. É ele que
    permite a safra em ARQUIVO colapsar por (diretório, padrão) — ver familias.py."""
    return familias.familia_candidata_sql(art, cat, paths)


def _uniao(vals, sep=" | "):
    """União ordenada de campos multi-valor das safras (areas, source_types, paths)."""
    out = set()
    for v in vals:
        for part in (v or "").split("|"):
            part = part.strip()
            if part:
                out.add(part)
    return sep.join(sorted(out))


def _moda(vals):
    """Valor mais frequente (empate: alfabético) — determinístico de propósito."""
    vals = [v for v in vals if v]
    if not vals:
        return None
    cont = {}
    for v in vals:
        cont[v] = cont.get(v, 0) + 1
    return sorted(cont.items(), key=lambda kv: (-kv[1], kv[0]))[0][0]


def _area_da_familia(vals):
    """Área principal da família: a moda das safras que TÊM área. "(sem área)" só quando
    nenhuma tem — a régua da área por input (_pick_area). Pela moda simples, as safras que
    só extra lê ("(sem área)") ganhavam da safra lida pela base, e a família ia para a
    linha "(sem área)" do Resumo (13 unidades em 14/10/2026)."""
    return _moda([v for v in vals if v != "(sem área)"]) or _moda(vals)


def _consenso(vals):
    """Único valor não-vazio se todos que têm valor concordam; senão None (estado misto)."""
    dis = {v for v in vals if (v or "").strip()}
    return dis.pop() if len(dis) == 1 else None


def _ord_etapa(etapa):
    try:
        return PIPELINE_INPUT.index(etapa)
    except ValueError:
        return -1


def _estado_familia(membros):
    """(etapa, status) EFETIVOS da família — roll-up do ADR 0002.

    Safra terminal não conta nem segura: a família fala pela safra PENDENTE menos avançada
    (é ela que falta ingerir). Sem nenhuma pendente, a família está resolvida e fala pela
    mais avançada — o que faz uma família toda Sanitizada aparecer como Sanitizada, e uma
    com 47 Sanitizadas + 11 vivas aparecer no ponto das 11."""
    pend = [m for m in membros if py_aingerir(m)]
    ordem = lambda m: (_ord_etapa(py_eff_etapa(m)), py_eff_etapa(m))  # noqa: E731
    alvo = min(pend, key=ordem) if pend else max(membros, key=ordem)
    etapa = py_eff_etapa(alvo)
    # Entre as safras NESSA etapa, o status mais frequente (empate alfabético) — mas só
    # entre as PENDENTES quando existem: `Sanitizado` é status, não etapa, então uma safra
    # sanitizada continua com py_eff_etapa "A Receber" e votava junto das vivas. Uma
    # família de 47 sanitizadas + 1 pendente saía com status "Sanitizado" (py_modern ->
    # True, some do universo a ingerir) enquanto reportava n_safras_pendentes=1 e
    # estado_misto=true na mesma linha. A etapa já fala pelas pendentes; o status também.
    votantes = pend if pend else membros
    status = _moda([py_eff_status(m) for m in votantes if py_eff_etapa(m) == etapa])
    return etapa, status


def _agrega_familias(rows):
    """Colapsa linhas de input (grão safra) em linhas de FAMÍLIA, preservando o shape que
    o frontend já consome (mesmos campos) + os campos novos da família.

    Roda DEPOIS dos _enrich_* (as anotações por safra são roladas para cima) e só no
    caminho sem filtros — o caminho filtrado continua no grão safra e se declara como tal
    em `grao`, porque agregar um recorte produziria "família parcial", que mente."""
    if not rows:
        return rows
    _corpus = _familias_corpus()
    mapa, mapa_membros = _corpus["chave"], _corpus["membros"]
    cnt = _familia_egp_counts()
    grupos = {}
    for r in rows:
        cat = (r.get("categoria") or "").strip()
        art = (r.get("artifact") or "").strip().upper()
        eff = mapa.get((cat, art), art)
        grupos.setdefault((cat, eff), []).append(r)

    out = []
    for (cat, eff), membros in grupos.items():
        # "é família?" é decidido pelo CORPUS, nunca pelo recorte em tela. Decidir pelo
        # recorte fazia a MESMA tabela ser linha de safra num escopo (onde só 1 safra
        # entrava) e linha de família noutro — identidade dependente do filtro, o erro
        # que familias.py proíbe na invariante 3. O sintoma era a subtração da landing
        # (inputs das deps) achar 2 chaves "novas" que eram a mesma família com chave
        # diferente nas duas visões.
        corpus_membros = mapa_membros.get((cat, eff), [])
        if len(corpus_membros) < 2:
            out.extend(membros)             # não é família no corpus: linha(s) física(s)
            continue
        etapa, status = _estado_familia(membros)
        # intervalo e tamanho descrevem a FAMÍLIA (corpus); etapa/status/pendentes
        # descrevem o que está NESTE recorte — é o recorte que está sendo contado.
        toks = [t for a in corpus_membros for t in familias.safras_no_nome(a)]
        ym = sorted(t for t in toks if familias.safra_ym(t))
        pend = [m for m in membros if py_aingerir(m)]
        estados = {(py_eff_etapa(m), py_eff_status(m)) for m in membros}
        origens = sorted({(m.get("origem") or "").strip() for m in membros if m.get("origem")})
        c = cnt.get((cat, eff), {})
        # Nome de EXIBIÇÃO: `..._{SAFRA}` na posição original da data. A chave (`eff`)
        # removeu o token, então o template vem dos MEMBROS. Membros podem discordar
        # quando a data aparece em posições distintas (`A_202505_B` e `A_B_202506` caem na
        # mesma chave `A_B`) — `_moda` resolve de forma determinística, para o rótulo não
        # alternar entre requests.
        # Membro SEM token (a tabela "corrente" convivendo com `..._2026`) produz template
        # sem marcador; ele não pode ganhar o rótulo, senão a família mais informativa
        # aparece com nome de input solto. Marcador tem precedência; `_moda` só desempata
        # entre os que marcam.
        _tpl = [familias.nome_com_marcador(m, cat) for m in corpus_membros]
        nome_exib = _moda([x for x in _tpl if "{SAFRA}" in x] or _tpl)
        out.append({
            "chave_canonica": _chave_familia(cat, eff),
            "artifact": eff,
            "nome_exibicao": nome_exib or eff,
            "categoria": cat,
            # --- campos da família (novos) ---
            "is_familia": True,
            "familia": eff,
            "n_safras": len(corpus_membros),
            "n_safras_no_recorte": len(membros),
            "n_safras_pendentes": len(pend),
            # intervalo em AAAAMM: a família pode misturar token mensal (202506) e diário
            # (20250612) e exibir os dois crus confundiria ("20240826-202506"). A ordenação
            # usa o token inteiro (consistente entre os formatos); o corte é só de exibição.
            "safra_min": ym[0][:6] if ym else None,
            "safra_max": ym[-1][:6] if ym else None,
            "safras_sem_mes": sum(1 for t in toks if not familias.safra_ym(t)),
            "estado_misto": len(estados) > 1,
            "membros": [m.get("chave_canonica") for m in membros if m.get("chave_canonica")],
            "origens": " | ".join(origens) if len(origens) > 1 else None,
            # --- campos existentes, rolados para cima ---
            "origem": _moda([m.get("origem") for m in membros]),
            "source_types": _uniao([m.get("source_types") for m in membros]),
            # consumidor é DISTINTO por família (somar as safras inflaria)
            # fallback (família ausente de sas_egp_inputs): o maior entre as safras —
            # nunca a soma, que contaria o mesmo EGP uma vez por safra
            "qtd_projetos": c.get("qtd") or max(
                int(m.get("qtd_projetos") or 0) for m in membros),
            "areas": _uniao([m.get("areas") for m in membros]),
            "area_principal": _area_da_familia([m.get("area_principal") for m in membros]),
            "escopo_indi": any(str(m.get("escopo_indi")).lower() == "true" for m in membros),
            # auto só vale para a família quando vale para TODAS as safras (mesma régua do
            # roll-up: uma safra pendente segura a família)
            "modernizada_auto": ("Disponível" if all(
                m.get("modernizada_auto") == "Disponível" for m in membros) else "A ingerir"),
            "etapa": etapa,
            "status": status,
            "responsavel": _consenso([m.get("responsavel") for m in membros]),
            "observacao": _consenso([m.get("observacao") for m in membros]),
            "orfao": False,
            "paths_fisicos": _uniao([m.get("paths_fisicos") for m in membros]),
            "n_paths_fisicos": len([p for p in _uniao(
                [m.get("paths_fisicos") for m in membros]).split(" | ") if p]),
            "n_proj_ativos": c.get("ativos", 0),
            "vinculo_ativo": any(m.get("vinculo_ativo") for m in membros),
            # só é ex-dependência se TODAS as safras forem (senão a família tem consumidor vivo)
            "ex_dependencia": all(m.get("ex_dependencia") for m in membros),
            # vínculo quebrado é por (EGP, safra) e só sobe para a família quando TODAS
            # estão quebradas: com `any`, uma safra desvinculada apagaria do drawer do
            # EGP o trabalho vivo das outras. Só o /api/egp traz este campo nas linhas.
            "link_broken": all(bool(m.get("link_broken")) for m in membros),
            "autoprodutor_candidato": any(m.get("autoprodutor_candidato") for m in membros),
            "autoprodutor_egp": next((m.get("autoprodutor_egp") for m in membros
                                      if m.get("autoprodutor_egp")), None),
        })
    out.sort(key=lambda r: (-int(r.get("qtd_projetos") or 0), r.get("artifact") or ""))
    return out


def _marca_safra(rows):
    """Anota `de_safra` em cada linha: o artefato pertence a uma família de safras?

    Marcador INFORMATIVO (alimenta o filtro "só safras" da aba Inputs); não é unidade de
    contagem e por isso roda nos DOIS estados da flag, sem mexer em total nenhum. Com
    FAMILIAS_SAFRA=1 a linha já é a família e `de_safra` == `is_familia`; desligada, cada
    safra datada vem marcada — é o que permite filtrar sem reimplementar o regex de data no
    frontend (a regra de nome vive só em familias.py).

    Mesma régua de identidade do `_agrega_familias`: família é decidida pelo CORPUS, então
    UMA safra sozinha no recorte continua marcada (invariante 3 de familias.py).
    """
    if not rows:
        return rows
    corpus = _familias_corpus()
    mapa, mapa_membros = corpus["chave"], corpus["membros"]
    for r in rows:
        cat = (r.get("categoria") or "").strip()
        art = (r.get("artifact") or "").strip().upper()
        eff = mapa.get((cat, art), art)          # linha de família já vem com art == eff
        r["de_safra"] = len(mapa_membros.get((cat, eff), ())) > 1
    return rows


def _chaves_por_extra():
    """(`lidas_por_extra`, `lidas_por_contavel`): as chaves de SAFRA que os EGPs `extra`
    do recorte leem, e as que o RESTO do recorte lê. Cacheado por geração.

    Dois conjuntos, e não um, porque a aba e o card respondem perguntas diferentes
    (decisão da gestão, 29/09/2026 — a régua anterior era "tudo junto", §3.4.13):

    - **de_extra** = a chave está em `lidas_por_extra`. É o FILTRO da aba Inputs: "o que a
      versão nova consome", inclusive o que a linha de base já lia. Medido em 29/09: 190
      unidades.
    - **so_de_extra** = está em `lidas_por_extra` e NÃO em `lidas_por_contavel`. É o que
      PARTICIONA os cards da Visão geral: 28 unidades. Contar as compartilhadas ali poria
      a mesma chave em dois grupos e o Total deixaria de fechar.

    Não dá para derivar `so_de_extra` de uma subtração feita aqui: uma família agrega
    várias safras, e a safra que o contável lê pode não ser a mesma que o extra lê — o
    rollup precisa dos dois conjuntos crus. Ver `_marca_extra`.

    Sem grafo publicado (ou sem extra algum) -> dois conjuntos vazios, e toda linha sai
    com os dois campos `False`."""
    def _p():
        try:
            frontier, _b = _frontier_egps("indi_deps", [])
        except HTTPException as e:
            if not _objeto_ausente(e):
                raise
            return set(), set()
        ex = _extras(frontier)
        if not ex:
            return set(), set()
        _ensure_link_tables()

        def _ch(projetos):
            inl = ", ".join(sql_lit(p) for p in projetos)
            return {r["chave_canonica"] for r in run_sql(
                f"SELECT chave_canonica FROM {_ch_vinculo_ativo(f'e.projeto IN ({inl})')} s")}

        outros = frontier - ex
        return _ch(ex), (_ch(outros) if outros else set())
    return _cache_lineage(("chaves_por_extra",), _p)


def _marca_extra(rows):
    """Anota `de_extra` e `so_de_extra` em cada linha — ver `_chaves_por_extra`.

    Roda DEPOIS da agregação por família, de propósito: a família é a união das safras, e
    basta uma safra lida por um EGP contável para a família inteira deixar de ser "só de
    extra". Feito antes, `_agrega_familias` teria de repetir essa regra no rollup."""
    if not rows:
        return rows
    de_extra, de_contavel = _chaves_por_extra()
    for r in rows:
        membros = r.get("membros") or [r.get("chave_canonica")]
        r["de_extra"] = any(k in de_extra for k in membros)
        r["so_de_extra"] = r["de_extra"] and not any(k in de_contavel for k in membros)
    return rows


def _dataset_escopo(scope, areas=()):
    """Dataset COMPLETO de inputs de um escopo, cacheado — a fonte única do grão servido.

    Extraído de /api/inputs para que o Resumo conte do MESMO conjunto que a aba Inputs
    mostra: com família ligada, contar por SQL em paralelo daria números que divergem da
    tela (família de origem mista cairia em dois buckets, e o total por bucket passaria do
    distinto). Divergência Resumo × Inputs já foi bug aqui antes — ver README.

    `scope`: "indi" (escopo Indicium) | "indi_deps" (fecho transitivo) | "base" (tudo).
    `areas` só recorta a BASE do fecho em indi_deps (os demais filtros são client-side).
    """
    areas = list(areas or [])
    if scope == "indi_deps":
        def _produce_deps():
            frontier, _b = _frontier_egps("indi_deps", areas)
            if not frontier:
                return []
            fin = ", ".join(sql_lit(p) for p in frontier)
            rows = _enrich_autoprodutor(_enrich_vinculo_ativo(_enrich_n_proj_ativos(run_sql(
                f"SELECT {INPUTS_COLS} FROM {T_IN} i WHERE chave_canonica IN "
                f"(SELECT DISTINCT chave_canonica FROM {T_EGP} WHERE projeto IN ({fin})) "
                f"ORDER BY qtd_projetos DESC NULLS LAST, artifact LIMIT {SCOPE_DATASET_CAP}")),
                f"e.projeto IN ({fin})"))
            # inputs consumidos EXCLUSIVAMENTE por ex-dependências: entram FLAGADOS
            # (ex_dependencia=True) — linha cinza + chip off-by-default no front; NUNCA
            # contam nos cards. Fora de todos os universos de contagem (decisões 4/5).
            ex = _ex_deps(frontier, _b)[0]
            if ex:
                exin = ", ".join(sql_lit(p) for p in ex)
                seen = {r["chave_canonica"] for r in rows}
                ex_rows = [r for r in run_sql(
                    f"SELECT {INPUTS_COLS} FROM {T_IN} i WHERE chave_canonica IN "
                    f"(SELECT DISTINCT chave_canonica FROM {T_EGP} WHERE projeto IN ({exin})) "
                    f"ORDER BY qtd_projetos DESC NULLS LAST, artifact LIMIT {SCOPE_DATASET_CAP}")
                    if r["chave_canonica"] not in seen]
                _enrich_autoprodutor(_enrich_vinculo_ativo(_enrich_n_proj_ativos(ex_rows), f"e.projeto IN ({exin})"))
                for r in ex_rows:
                    r["ex_dependencia"] = True
                rows = rows + ex_rows
            # sanitização derivada ANTES da agregação: os motivos são chaveados pela
            # safra, e é o status já sobrescrito que a família agrega (§3.4.18).
            sanitizacao.aplica_em_linhas(rows, _sanitizacao_derivada())
            # família de safras: colapsa DENTRO do produtor (o resultado agregado é o
            # que entra no cache do escopo) — ver _agrega_familias. `_marca_safra` e
            # `_marca_extra` rodam nos dois estados da flag: são marcadores de FILTRO,
            # não mudam contagem por si — quem parte os cards em grupos é a landing.
            return _marca_extra(_marca_safra(_agrega_familias(rows) if FAMILIAS_ON else rows))
        return _cache_scope_dataset("indi_deps:" + "|".join(sorted(areas)), _produce_deps)

    def _produce_scope():
        wsql = " WHERE escopo_indi = true" if scope == "indi" else ""
        ew = "e.escopo_indi = true" if scope == "indi" else "true"
        _rows = _enrich_autoprodutor(_enrich_vinculo_ativo(_enrich_n_proj_ativos(run_sql(
            f"SELECT {INPUTS_COLS} FROM {T_IN} i{wsql} "
            f"ORDER BY qtd_projetos DESC NULLS LAST, artifact LIMIT {SCOPE_DATASET_CAP}")), ew))
        sanitizacao.aplica_em_linhas(_rows, _sanitizacao_derivada())
        return _marca_extra(_marca_safra(_agrega_familias(_rows) if FAMILIAS_ON else _rows))
    return _cache_scope_dataset(scope, _produce_scope)


# ---- universo e blocos do Resumo contados no MESMO dataset da aba Inputs ----------
BUCKETS_RESUMO = ["BigQuery", "Arquivo", "Transacional", "SAS/Local"]


def _bucket_origem(origem):
    """Bucket de origem do Resumo, espelho do CASE de `origem_block` (i.origem AO VIVO).
    None = fora dos 4 buckets (ex.: libname_in), que o Resumo não conta por decisão."""
    if origem in ("SAS/Local (externo)", "SAS/Local (dependência)"):
        return "SAS/Local"
    if origem in ("Arquivo", "Script"):
        return "Arquivo"
    if origem in ("BigQuery", "Transacional"):
        return origem
    return None


def _universo_contagem(rows):
    """Linhas que contam: vínculo ativo no recorte e não-exclusivas de ex-dependência —
    mesmo universo de _ch_vinculo_ativo + decisões 4/5 (ver README §universo por vínculo)."""
    return [r for r in rows
            if r.get("vinculo_ativo") is not False and not r.get("ex_dependencia")]


def _origem_block_py(rows, modern_of=py_modern):
    """Tabela de origem do Resumo (total/modernizado/não) por bucket, em Python.
    Só os 4 buckets, como a versão SQL — o total é a soma deles, não do universo todo.
    `fora_das_origens` conta o que ficou de fora (o placeholder `casco::` dos unificados),
    que o card Total de Inputs conta — é a diferença entre os dois."""
    agg = {b: {"bucket": b, "total": 0, "modernizado": 0, "nao_modernizado": 0}
           for b in BUCKETS_RESUMO}
    fora = 0
    for r in _universo_contagem(rows):
        b = _bucket_origem(r.get("origem"))
        if not b:
            fora += 1
            continue
        agg[b]["total"] += 1
        agg[b]["modernizado" if modern_of(r) else "nao_modernizado"] += 1
    tot = {"total": 0, "modernizado": 0, "nao_modernizado": 0}
    for b in BUCKETS_RESUMO:
        for k in tot:
            tot[k] += agg[b][k]
    return {"rows": [agg[b] for b in BUCKETS_RESUMO], "total": tot, "fora_das_origens": fora}


def _ingest_rows_py(rows):
    """[{et, st, n}] para `ingest_funnel`, a partir do dataset do escopo — mesmo shape que
    a agregação SQL produzia, só que a unidade é a FAMÍLIA quando a flag está ligada."""
    agg = {}
    for r in _universo_contagem(rows):
        k = (py_eff_etapa(r), py_eff_status(r))
        agg[k] = agg.get(k, 0) + 1
    return [{"et": et, "st": st, "n": n} for (et, st), n in agg.items()]


def _nao_mod_area_py(rows, modern_of=py_modern, area_of=lambda r: r.get("area_principal")):
    """{área principal: nº não-modernizados}, mesma régua dos 4 buckets."""
    out = {}
    for r in _universo_contagem(rows):
        if not _bucket_origem(r.get("origem")) or modern_of(r):
            continue
        a = area_of(r)
        out[a] = out.get(a, 0) + 1
    return out


@app.get("/api/inputs")
def inputs(scope: str = "indi", categoria: list[str] = Query(default=[]),
           etapa: list[str] = Query(default=[]), status: list[str] = Query(default=[]),
           q: str = "", divergence: bool = False,
           origem: list[str] = Query(default=[]), area: list[str] = Query(default=[])):
    _ensure_input_pipeline_cols()
    # Caminhos CACHEADOS (dataset completo do escopo): é como o frontend chama — manda só
    # `scope` e filtra/ordena no cliente. O dataset vem de _dataset_escopo, compartilhado
    # com o Resumo para os dois nunca divergirem.
    #
    # indi_deps: a ÁREA recorta a BASE do fecho (server-side, entra na chave do cache);
    # os demais filtros seguem no cliente. Nos outros escopos, QUALQUER filtro — área
    # inclusive — cai no caminho filtrado por SQL abaixo (grão safra).
    if scope == "indi_deps":
        rows = _dataset_escopo("indi_deps", area)
        capped = len(rows) >= SCOPE_DATASET_CAP
        return {"total": len(rows), "returned": len(rows), "capped": capped, "rows": rows,
                "grao": "familia" if FAMILIAS_ON else "safra"}
    if not (categoria or origem or etapa or status or q or divergence or area):
        rows = _dataset_escopo(scope, [])
        capped = len(rows) >= SCOPE_DATASET_CAP
        return {"total": len(rows), "returned": len(rows), "capped": capped, "rows": rows,
                "grao": "familia" if FAMILIAS_ON else "safra"}
    where = []
    if scope == "indi":
        where.append("escopo_indi = true")
    if area:
        where.append(f"areas IS NOT NULL AND {_lista_tem_algum('areas', area)}")
    cats = [c for c in categoria if c in CATEGORIAS]
    if cats:
        where.append(f"categoria IN ({', '.join(sql_lit(c) for c in cats)})")
    ors = [o for o in origem if o in ORIGENS]
    if ors:
        where.append(f"origem IN ({', '.join(sql_lit(o) for o in ors)})")
    ets = [e for e in etapa if e in PIPELINE_INPUT]
    if ets:
        where.append(f"{_eff_etapa()} IN ({', '.join(sql_lit(e) for e in ets)})")
    sts = [s for s in status if s in STATUS_INPUT]
    if sts:
        where.append(f"{_eff_status_input()} IN ({', '.join(sql_lit(s) for s in sts)})")
    if q:
        # busca abrangente: cada termo (q.split) deve aparecer em ALGUMA coluna de dados
        # (AND entre termos, OR entre colunas). Blob via concat_ws (ignora NULLs no Spark).
        # Exclui de proposito responsavel/observacao. Colunas sao base de T_IN -> vai no WHERE.
        blob = ("concat_ws(' ', artifact, categoria, origem, areas, source_types, "
                "paths_fisicos, etapa, status)")
        for term in q.split():
            where.append(f"upper({blob}) LIKE upper({sql_lit('%' + term + '%')})")
    if divergence:
        # humano (etapa) discorda do auto sobre "modernizado" (só quando há etapa humana).
        # OR explícito em vez de boolean <> (compat. Databricks).
        m = _modern()
        where.append(f"(etapa IS NOT NULL AND etapa <> '' AND "
                     f"(({m} AND modernizada_auto <> 'Disponível') "
                     f"OR (NOT {m} AND modernizada_auto = 'Disponível')))")
    wsql = (" WHERE " + " AND ".join(where)) if where else ""
    total = run_sql(f"SELECT count(*) AS n FROM {T_IN}{wsql}")[0]["n"]
    rows = _enrich_autoprodutor(_enrich_vinculo_ativo(_enrich_n_proj_ativos(run_sql(
        f"SELECT {INPUTS_COLS} "
        f"FROM {T_IN} i{wsql} ORDER BY qtd_projetos DESC NULLS LAST, artifact LIMIT {READ_CAP}")),
        "e.escopo_indi = true" if scope == "indi" else "true"))
    sanitizacao.aplica_em_linhas(rows, _sanitizacao_derivada())
    # Caminho FILTRADO (legado): continua no grão SAFRA mesmo com a flag ligada, e se
    # declara em `grao`. Agregar um recorte produziria "família parcial" — número que
    # parece de família mas só viu as safras que passaram no filtro. O frontend não usa
    # este caminho (manda só `scope` e filtra no cliente); ver MonitorView.
    return {"total": int(total), "returned": len(rows), "capped": int(total) > READ_CAP,
            "rows": _marca_extra(_marca_safra(rows)), "grao": "safra"}


def _pipe_egp_map():
    """{projeto: (etapa, status)} GRAVADOS em sas_egp_pipeline — o funil de migração do
    EGP. Cacheado por geração (todo PATCH de egp-pipeline chama _bump_gen), então clicar
    input a input não vira 1 query por clique. Tabela ausente (antes do 1º PATCH/publish)
    -> mapa vazio, nunca derruba o endpoint.

    É a leitura CRUA: quem EXIBE andamento usa `_pipe_exibido()`, que aplica o vínculo em
    cima deste mapa. Ver o registro de decisões em test_leitura_pipe_decidida.py."""
    def _p():
        try:
            # pipe-etapa-status: real — esta é a leitura crua que ALIMENTA a derivação;
            # derivar aqui dentro deixaria `_pipe_exibido()` sem o valor gravado do
            # sucessor (a etapa espelhada sai dele) e a derivação viraria circular.
            return {r.get("projeto"): (r.get("etapa_migracao"), r.get("status_migracao"))
                    for r in run_sql(f"SELECT projeto, etapa_migracao, status_migracao FROM {T_PIPE}")}
        except HTTPException as e:
            if not _objeto_ausente(e):
                raise
            return {}
    return _cache_lineage(("pipe_egp_map",), _p)


def _pipe_exibido():
    """{projeto: (etapa, status)} EXIBIDOS — `_pipe_egp_map()` com o vínculo antecessor ->
    sucessor aplicado (spec §3.2): etapa espelhada do sucessor e status `Desatualizado`.

    Derivação de LEITURA: o banco segue com o valor real e ele reaparece se o vínculo for
    desfeito (§3.2.6). Cacheado por geração como as duas fontes que ele combina — nenhuma
    superfície paga query extra por usar o derivado em vez do cru."""
    return _cache_lineage(("pipe_exibido",), lambda: vinculos.mapa_exibido(
        _pipe_egp_map(), _vinculos_por_antecessor()))


def _enrich_egp_contexto(rows):
    """Anota, em linhas que têm `projeto`, o que é preciso para julgar "quem ainda depende
    disto" sem sair da tela: `etapa`/`status` do funil de migração e `escopo`, o recorte a
    que o EGP pertence — MESMOS conjuntos usados pelas abas EGPs/Inputs (_frontier_egps +
    _ex_deps), não uma regra paralela:
      'indi' escopo Indicium direto · 'dep' dependência transitiva viva ·
      'ex'   ex-dependência retida  · 'fora' fora do recorte (só na base completa).
    A flag escopo_indi da linha só distingue 'indi'; o resto exige o fecho."""
    if not rows:
        return rows
    frontier, base = _frontier_egps("indi_deps", [])
    ex = _ex_deps(frontier, base)[0]
    # DERIVADO: a pergunta aqui é "em que pé está o EGP que ainda lê este input" — é
    # andamento, não estado gravado de gestão. Cru, o drawer do input diria a etapa velha
    # do antecessor enquanto a aba EGPs diz a espelhada.
    pipe = _pipe_exibido()
    for r in rows:
        pj = r.get("projeto")
        r["escopo"] = ("indi" if pj in base else "dep" if pj in frontier
                       else "ex" if pj in ex else "fora")
        et, st = pipe.get(pj, (None, None))
        r["etapa"], r["status"] = et, st
    return rows


def _familia_de_chave(chave):
    """(categoria, familia, [ARTEFATOS membros]) se `chave` é família OU safra de uma família.

    Aceita as duas formas de propósito: a chave de família (`familia::cat::NOME`) e a chave
    de uma safra qualquer — é isso que faz link/atalho antigo apontando para uma safra abrir
    a família em vez de 404, sem precisar reescrever quem guardou a chave. None = não é (nem
    pertence a) família: o chamador segue no caminho de input único."""
    res = _familias_corpus()
    if chave.startswith(FAMILIA_PREFIX):
        cat, _, fam = chave[len(FAMILIA_PREFIX):].partition("::")
    else:
        r = run_sql(f"SELECT categoria, artifact FROM {T_IN} "
                    f"WHERE chave_canonica = {sql_lit(chave)}")
        if not r:
            return None
        cat = (r[0].get("categoria") or "").strip()
        fam = res["chave"].get((cat, (r[0].get("artifact") or "").strip().upper()))
    membros = res["membros"].get((cat, fam), []) if fam else []
    return (cat, fam, membros) if len(membros) > 1 else None


def _detalhe_familia(cat, fam, membros):
    """`egps`/`produtores` da FAMÍLIA (união das safras) + a lista `safras`.

    Consumidor aparece UMA vez, com quantas safras ele lê e com o vínculo quebrado só
    quando quebrou em TODAS (senão o EGP ainda depende da família). Produtor é a união das
    safras, podada pela escolha de produtor canônico quando existe."""
    art_in = ", ".join(sql_lit(a) for a in membros)
    safras = run_sql(
        f"SELECT chave_canonica, artifact, categoria, etapa, status, modernizada_auto, "
        f"responsavel, observacao FROM {T_IN} "
        f"WHERE categoria = {sql_lit(cat)} AND upper(artifact) IN ({art_in}) "
        f"AND NOT orfao ORDER BY artifact")
    for sr in safras:
        toks = familias.safras_no_nome(sr.get("artifact") or "")
        sr["safra"] = toks[-1] if toks else None
        sr["etapa_efetiva"] = py_eff_etapa(sr)
        sr["status_efetivo"] = py_eff_status(sr)
        sr["resolvido"] = py_modern(sr)
    chaves = [sr["chave_canonica"] for sr in safras if sr.get("chave_canonica")]
    ch_in = ", ".join(sql_lit(c) for c in chaves) or "''"
    egps = run_sql(
        f"SELECT e.projeto, max(n.area) AS area, max(n.onda) AS onda, "
        f"max(CASE WHEN n.escopo_indi THEN 1 ELSE 0 END) AS escopo_indi, "
        f"max(coalesce(n.ciclo_id, 0)) AS ciclo_id, "
        f"count(DISTINCT e.chave_canonica) AS n_safras, "
        f"min(CASE WHEN coalesce(l.link_broken, false) THEN 1 ELSE 0 END) AS todas_quebradas "
        f"FROM {T_EGP} e LEFT JOIN {T_ND} n ON e.projeto = n.projeto "
        f"LEFT JOIN {T_LINK} l ON l.projeto = e.projeto AND l.chave_canonica = e.chave_canonica "
        f"WHERE e.chave_canonica IN ({ch_in}) GROUP BY e.projeto")
    for r in egps:
        r["escopo_indi"] = str(r.pop("escopo_indi")) == "1"
        r["link_broken"] = str(r.pop("todas_quebradas")) == "1"
        r["n_safras"] = int(r.get("n_safras") or 0)
    egps.sort(key=lambda r: (r["link_broken"], not r["escopo_indi"], r["projeto"]))
    produtores = run_sql(
        f"SELECT DISTINCT ed.depende_do AS projeto, n.area, n.onda, n.escopo_indi, n.ciclo_id "
        f"FROM {T_ED} ed LEFT JOIN {T_ND} n ON ed.depende_do = n.projeto "
        f"WHERE {_lista_tem_algum('upper(ed.via_tabelas)', membros)} "
        f"ORDER BY n.escopo_indi DESC NULLS LAST, projeto")
    escolhas = _producer_choices()
    com_escolha = {a: escolhas[a] for a in membros if escolhas.get(a)}
    # Só poda quando TODAS as safras têm produtor canônico escolhido. A versão anterior
    # podava contra a UNIÃO das escolhas existentes, então UMA safra semeada bastava para
    # o filtro derrubar os produtores legítimos de todas as outras — e cobertura parcial é
    # a norma hoje (154 escolhas semeadas, vias sem escolha ainda em fila de revisão).
    # Esta query devolve a união dos produtores sem dizer qual safra cada um produz, então
    # não dá para podar safra a safra aqui; na dúvida mostra todos, porque esconder
    # produtor real é pior do que exibir candidato a mais.
    if membros and len(com_escolha) == len(membros):
        eleitos = set(com_escolha.values())
        if any(p.get("projeto") in eleitos for p in produtores):
            produtores = [p for p in produtores if p.get("projeto") in eleitos]
    _enrich_egp_contexto(egps)
    _enrich_egp_contexto(produtores)
    # profundidade NECESSÁRIA por consumidor + o máximo entre os vivos (a carga a pedir).
    # Vem no mesmo payload de propósito: é a informação que decide a conversa de ingestão,
    # e separá-la num 2º request só criaria estado meio-carregado na tela.
    try:
        pares = _periodo_pares(cat, fam)
        _enrich_egp_contexto(pares)
        try:
            vivos = _frontier_egps("indi_deps", [])[0] - _egps_fora_backlog()
        except HTTPException:
            vivos = None
        maximo, maximo_pj = _periodo_maximo(pares, vivos)
        ingerida = _ingestao_map().get((cat, fam))
        # avisos ANTES de limpar o `piso`: eles comparam pisos (foi o bug pego no dev —
        # o pop rodava primeiro e derrubava o endpoint com KeyError)
        avisos = _avisos_familia(pares, vivos, ingerida) if pares else {}
    except HTTPException:
        pares, maximo, maximo_pj, ingerida, avisos = [], None, None, None, {}
    for p in pares:
        p.pop("piso", None)            # detalhe interno de comparação; não vai p/ o cliente
    periodo = {"pares": pares, "maximo": maximo, "maximo_projeto": maximo_pj,
               "n_esparsos": sum(1 for p in pares if p.get("esparso")),
               "ingerida": ingerida, "avisos": avisos}
    if pares and not maximo:
        # a família tem consumidores, mas nenhum VIVO no recorte: não há carga a pedir hoje.
        # Dizer isso é diferente de mostrar vazio — vazio parece dado faltando.
        periodo["maximo_motivo"] = "nenhum consumidor vivo no recorte pede esta família"
    if maximo:
        periodo["maximo"] = {k: v for k, v in maximo.items() if k != "piso"}
    return {"egps": egps, "produtores": produtores, "safras": safras,
            "familia": fam, "categoria": cat, "n_safras": len(safras),
            "periodo": periodo}


# --- Profundidade NECESSÁRIA por (EGP, família) --------------------------------
# "Até que ponto do passado este EGP precisa desta família para rodar." É propriedade do
# PAR, não da família: medido no corpus, 52 de 74 famílias multi-EGP têm consumidores que
# precisam de profundidades diferentes (CARTAOBV.TBL_RAC_RESUMO é lida por EGPs que
# precisam de 103m, 98m, 36m e 36m). Guardar só o máximo apagaria a informação que decide
# a carga — "dá para subir 12 meses e destravar 3 dos 4". Ver docs/adr/0002.
#
# O DERIVADO não é gravado: é calculado ao vivo a partir das safras que o EGP lê hoje. O
# plano previa semear os pares na tabela, mas valor derivado gravado envelhece (chega safra
# nova e a linha mente). Assim todo par nasce preenchido sem job de semeadura, e a tabela
# guarda só o que humano DECLAROU — que é o que precisa sobreviver a publish e a refresh.
PERIODO_TIPOS = ("todas", "desde", "rolling")


@functools.lru_cache(maxsize=1)
def _ensure_periodo_tables():
    """DDL das tabelas de período (estado + auditoria), no molde de T_LINK: CREATE IF NOT
    EXISTS num bootstrap por processo, FORA do publish — nunca dropadas por ele."""
    if dialeto.PG:  # no Postgres o schema vem das migrações (db/migrations), nunca do app
        return True
    run_sql(f"""CREATE TABLE IF NOT EXISTS {T_PER} (
      projeto STRING NOT NULL,
      categoria STRING NOT NULL,
      familia STRING NOT NULL,
      tipo STRING NOT NULL,          -- todas | desde | rolling
      valor STRING,                  -- 'AAAAMM' p/ desde; nº de meses p/ rolling; NULL p/ todas
      updated_by STRING,
      updated_at TIMESTAMP
    ) USING DELTA""", want_rows=False)
    run_sql(f"""CREATE TABLE IF NOT EXISTS {T_PER_AUD} (
      id STRING, projeto STRING, categoria STRING, familia STRING,
      campo STRING, valor_antigo STRING, valor_novo STRING,
      ator STRING, ts TIMESTAMP
    ) USING DELTA""", want_rows=False)
    return True


def _ym_hoje():
    d = datetime.date.today()
    return d.year * 12 + d.month - 1


def _ym_de_safra(tok):
    """(ano*12+mês-1) de um token de safra; ano solto cai em JANEIRO daquele ano.

    Normalizar o ano solto para janeiro é conservador de propósito: se o EGP lê `_2024`,
    ele pode precisar do ano inteiro, então o piso é o começo dele."""
    ym = familias.safra_ym(tok)
    if ym:
        return ym[0] * 12 + ym[1] - 1
    if len(tok or "") == 4 and tok.isdigit():
        return int(tok) * 12
    return None


def _ym_para_texto(ym):
    return f"{ym // 12:04d}{ym % 12 + 1:02d}"


def _periodo_piso(tipo, valor):
    """Piso comparável (ym) da profundidade. Quanto MENOR, mais fundo.

    `todas` = sem piso (o mais fundo possível). `rolling N` resolve contra a data corrente —
    é a única forma relativa, e é justamente por isso que a absoluta existe (a âncora do
    rolling é o que travou a regra 12M/3M do cliente por semanas)."""
    if tipo == "todas":
        return float("-inf")
    if tipo == "desde":
        return _ym_de_safra(valor) if valor else float("-inf")
    if tipo == "rolling":
        try:
            return _ym_hoje() - int(valor) + 1
        except (TypeError, ValueError):
            return float("-inf")
    return float("inf")


def _periodo_derivado():
    """{(projeto, categoria, familia): dados} derivado do CORPUS, cacheado por geração.

    Para cada par, a profundidade necessária observada = `desde <safra mais antiga que o EGP
    lê>`; se o EGP lê um membro SEM data (a tabela sem sufixo), a necessidade é `todas`.
    Vem junto o que o ticket 08 usa nos avisos: quantas safras ele lê, o span e se a leitura
    é ESPARSA (lê com buracos — ex. só dezembros: 189 dos 431 pares medidos)."""
    def _p():
        _ensure_link_tables()
        mapa = _familias_corpus()["chave"]
        pares = run_sql(
            f"SELECT e.projeto, e.categoria, e.artifact FROM {T_EGP} e "
            f"LEFT JOIN {T_LINK} l ON l.projeto = e.projeto "
            f"AND l.chave_canonica = e.chave_canonica "
            f"WHERE NOT coalesce(l.link_broken, false)")
        agg = {}
        for p in pares:
            cat = (p.get("categoria") or "").strip()
            art = (p.get("artifact") or "").strip().upper()
            pj = p.get("projeto")
            if not art or not pj:
                continue
            fam = mapa.get((cat, art), art)
            if fam == art:
                continue                      # não é família: não há profundidade a declarar
            d = agg.setdefault((pj, cat, fam), {"safras": [], "sem_data": False})
            toks = familias.safras_no_nome(art)
            if toks:
                d["safras"].extend(toks)
            else:
                d["sem_data"] = True          # lê a tabela sem sufixo -> precisa de tudo
        out = {}
        for k, d in agg.items():
            yms = sorted(y for y in (_ym_de_safra(t) for t in d["safras"]) if y is not None)
            n = len(set(yms))
            span = (yms[-1] - yms[0] + 1) if yms else 0
            out[k] = {
                "tipo": "todas" if (d["sem_data"] or not yms) else "desde",
                "valor": None if (d["sem_data"] or not yms) else _ym_para_texto(yms[0]),
                "origem": "derivado",
                "n_safras_lidas": len(d["safras"]),
                "safra_min_lida": _ym_para_texto(yms[0]) if yms else None,
                "safra_max_lida": _ym_para_texto(yms[-1]) if yms else None,
                "span_meses": span,
                # esparso = lê com buracos no intervalo (o span é maior que o nº de meses
                # distintos lidos). A profundidade continua sendo a safra mais antiga, mas
                # carregar o intervalo inteiro entrega muito mais do que o EGP usa.
                "esparso": bool(yms) and span > n,
            }
        return out
    return _cache_lineage(("periodo_derivado",), _p)


def _periodo_declarado():
    """{(projeto, categoria, familia): dados} do que humano DECLAROU (tabela T_PER)."""
    def _p():
        _ensure_periodo_tables()
        try:
            rows = run_sql(f"SELECT projeto, categoria, familia, tipo, valor, updated_by, "
                           f"CAST(updated_at AS STRING) AS updated_at FROM {T_PER}")
        except HTTPException as e:
            if not _objeto_ausente(e):
                raise
            return {}
        return {(r["projeto"], r["categoria"], r["familia"]): {
            "tipo": r.get("tipo"), "valor": r.get("valor"), "origem": "declarado",
            "updated_by": r.get("updated_by"), "updated_at": r.get("updated_at")}
            for r in rows}
    return _cache_lineage(("periodo_declarado",), _p)


def _periodo_pares(cat, familia):
    """Pares (EGP, família) com a profundidade vigente: declarada quando existe, senão a
    derivada do corpus. Recomputar o derivado NUNCA sobrescreve declaração (são fontes
    separadas — é isso que dispensa migração/seed)."""
    der, dec = _periodo_derivado(), _periodo_declarado()
    chaves = {k for k in der if k[1] == cat and k[2] == familia}
    chaves |= {k for k in dec if k[1] == cat and k[2] == familia}
    out = []
    for k in sorted(chaves):
        base = dict(der.get(k) or {})
        d = dec.get(k)
        if d:
            base.update({kk: vv for kk, vv in d.items() if vv is not None or kk == "valor"})
            base["origem"] = "declarado"
            base["derivado_tipo"] = (der.get(k) or {}).get("tipo")
            base["derivado_valor"] = (der.get(k) or {}).get("valor")
        base["projeto"] = k[0]
        base["piso"] = _periodo_piso(base.get("tipo"), base.get("valor"))
        out.append(base)
    return out


def _periodo_maximo(pares, vivos=None):
    """A profundidade A INGERIR da família: a mais funda entre os consumidores VIVOS e em
    escopo (os demais entram na lista, mas não puxam a carga). Devolve (dados, projeto)."""
    cand = [p for p in pares if vivos is None or p["projeto"] in vivos]
    if not cand:
        return None, None
    alvo = min(cand, key=lambda p: (p["piso"], p["projeto"]))
    return alvo, alvo["projeto"]


# --- Profundidade INGERIDA por família + avisos ---------------------------------
# A necessária é PEDIDO (restrita à gestão, T_PER). Esta é FATO CONSUMADO: a safra mais
# antiga que de fato existe no destino depois da carga. Por isso qualquer analista logado
# registra — é o mesmo gesto de "marquei que recebi"; travar o fato atrás da gestão só
# garantiria que ele não fosse registrado. Só a forma absoluta `desde AAAAMM` é aceita
# (decisão do usuário, Q17): "últimos N meses" descreve pedido, não o que está no disco.
#
# Os avisos daqui NUNCA bloqueiam nada (Q13): campo manual esquecido não pode virar
# bloqueio — é o erro que o status_humano ausente já ensinou.


@functools.lru_cache(maxsize=1)
def _ensure_ingestao_tables():
    if dialeto.PG:  # no Postgres o schema vem das migrações (db/migrations), nunca do app
        return True
    run_sql(f"""CREATE TABLE IF NOT EXISTS {T_ING} (
      categoria STRING NOT NULL,
      familia STRING NOT NULL,
      desde STRING NOT NULL,         -- 'AAAAMM': safra mais antiga que existe no destino
      ingerida_em STRING,            -- 'AAAA-MM-DD' (quando a carga aconteceu)
      updated_by STRING,
      updated_at TIMESTAMP
    ) USING DELTA""", want_rows=False)
    run_sql(f"""CREATE TABLE IF NOT EXISTS {T_ING_AUD} (
      id STRING, categoria STRING, familia STRING, campo STRING,
      valor_antigo STRING, valor_novo STRING, ator STRING, ts TIMESTAMP
    ) USING DELTA""", want_rows=False)
    return True


def _ingestao_map():
    """{(categoria, familia): {desde, ingerida_em, updated_by, updated_at}}, por geração."""
    def _p():
        _ensure_ingestao_tables()
        try:
            rows = run_sql(f"SELECT categoria, familia, desde, ingerida_em, updated_by, "
                           f"CAST(updated_at AS STRING) AS updated_at FROM {T_ING}")
        except HTTPException as e:
            if not _objeto_ausente(e):
                raise
            return {}
        return {(r["categoria"], r["familia"]): {
            "desde": r.get("desde"), "ingerida_em": r.get("ingerida_em"),
            "updated_by": r.get("updated_by"), "updated_at": r.get("updated_at")}
            for r in rows}
    return _cache_lineage(("ingestao_map",), _p)


def _profundidade_meses(piso):
    """Profundidade em meses contada de hoje (p/ a mensagem de dispersão). None = `todas`."""
    if piso == float("-inf") or piso == float("inf"):
        return None
    return max(1, _ym_hoje() - int(piso) + 1)


def _avisos_familia(pares, vivos, ingerida):
    """Os três avisos do ticket 08 — todos informativos, nenhum bloqueia.

    1. RASA: a carga não alcança a necessidade de algum consumidor VIVO. Só existe quando
       há `desde` registrado — sem registro não há o que comparar (e inventar um default
       seria pior que não avisar).
    2. DISPERSÃO: a faixa de profundidade pedida pelos consumidores vivos. É o número que
       decide a conversa ("dá para subir 12 meses e destravar 3 dos 4").
    3. ESPARSA: consumidor que lê safras com buracos no intervalo — a profundidade continua
       sendo a safra mais antiga, mas carregar o intervalo inteiro entrega muito mais do
       que ele usa.
    """
    vivas = [p for p in pares if vivos is None or p["projeto"] in vivos]
    out = {"esparsos": [p["projeto"] for p in vivas if p.get("esparso")]}

    def _piso(p):
        # `piso` é campo interno e pode já ter sido limpo pelo chamador: recalcula em vez
        # de depender da ordem das operações.
        return p.get("piso", _periodo_piso(p.get("tipo"), p.get("valor")))

    prof = [(_profundidade_meses(_piso(p)), p) for p in vivas]
    meses = [m for m, _ in prof if m is not None]
    if meses:
        out["dispersao"] = {
            "min_meses": min(meses), "max_meses": max(meses),
            "n_consumidores": len(vivas),
            "mais_fundo": min(prof, key=lambda x: (x[0] is None and -1 or -x[0]))[1]["projeto"],
        }
    if ingerida and ingerida.get("desde"):
        piso_ing = _periodo_piso("desde", ingerida["desde"])
        curtos = [p for p in vivas if _piso(p) < piso_ing]
        if curtos:
            fundo = min(curtos, key=_piso)
            out["rasa"] = {
                "n": len(curtos), "de": len(vivas),
                "projetos": [p["projeto"] for p in curtos],
                "precisa": fundo.get("valor") or "todas as safras",
                "mais_fundo": fundo["projeto"],
            }
    return out


class FamiliaIngestao(BaseModel):
    categoria: str
    familia: str
    desde: str | None = None       # 'AAAAMM'; vazio/None apaga o registro
    ingerida_em: str | None = None  # 'AAAA-MM-DD' (default: hoje)


@app.patch("/api/familia-ingestao")
def patch_familia_ingestao(p: FamiliaIngestao):
    """Registra (ou apaga) a profundidade INGERIDA de uma família. Qualquer analista logado.

    Fato consumado, não pedido: quem subiu os arquivos registra, igual ao "recebido" do
    pré-working. Apagar é idempotente. Só altera aviso — nenhuma contagem, etapa, status
    ou bloqueio depende disto (Q13)."""
    _ensure_ingestao_tables()
    desde = (p.desde or "").strip() or None
    if desde and not re.fullmatch(r"20\d{2}(0[1-9]|1[0-2])", desde):
        raise HTTPException(400, "desde exige safra AAAAMM válida (ex.: 202401)")
    ing_em = (p.ingerida_em or "").strip() or None
    if ing_em and not re.fullmatch(r"20\d{2}-(0[1-9]|1[0-2])-(0[1-9]|[12]\d|3[01])", ing_em):
        raise HTTPException(400, "ingerida_em exige data AAAA-MM-DD")
    chave = (p.categoria, p.familia)
    atual = _ingestao_map().get(chave)
    antigo = (atual or {}).get("desde") or ""
    if (antigo or "") == (desde or ""):
        if not desde:
            return {"ok": True, "categoria": p.categoria, "familia": p.familia, "desde": None}
        raise HTTPException(400, "nada para atualizar (valor idêntico)")
    where = f"categoria = {sql_lit(p.categoria)} AND familia = {sql_lit(p.familia)}"
    if desde:
        # MERGE, não DELETE+INSERT: o par deixava uma janela em que a linha já tinha sido
        # apagada e a nova ainda não existia. Um timeout do warehouse entre os dois
        # (rotineiro — run_sql espera até 50s) apagava a profundidade declarada, e o PATCH
        # só carrega o valor NOVO: nada no request diz o que se perdeu. Mesmo motivo do
        # MERGE em egps_atualizados.py. Apagar de fato (desde vazio) segue DELETE, que já
        # é uma operação só.
        run_sql(
            f"MERGE INTO {T_ING} t USING (SELECT {sql_lit(p.categoria)} AS categoria, "
            f"{sql_lit(p.familia)} AS familia, {sql_lit(desde)} AS desde, "
            f"coalesce({sql_lit(ing_em)}, CAST(current_date AS STRING)) AS ingerida_em) s "
            f"ON t.categoria = s.categoria AND t.familia = s.familia "
            f"WHEN MATCHED THEN UPDATE SET desde = s.desde, ingerida_em = s.ingerida_em, "
            f"updated_by = {_ator()}, updated_at = {AGORA} "
            f"WHEN NOT MATCHED THEN INSERT (categoria, familia, desde, ingerida_em, "
            f"updated_by, updated_at) VALUES (s.categoria, s.familia, s.desde, s.ingerida_em, "
            f"{_ator()}, {AGORA})", want_rows=False)
    else:
        run_sql(f"DELETE FROM {T_ING} WHERE {where}", want_rows=False)
    run_sql(f"INSERT INTO {T_ING_AUD} (id, categoria, familia, campo, valor_antigo, "
            f"valor_novo, ator, ts) VALUES ({sql_lit(uuid.uuid4().hex)}, "
            f"{sql_lit(p.categoria)}, {sql_lit(p.familia)}, 'desde', {sql_lit(antigo)}, "
            f"{sql_lit(desde or '')}, {_ator()}, {AGORA})", want_rows=False)
    _bump_gen()
    return {"ok": True, "categoria": p.categoria, "familia": p.familia, "desde": desde,
            "ingerida_em": ing_em}


def _chaves_para_leitura(chave):
    """Chaves que respondem por uma linha em tabelas de ANOTAÇÃO (auditoria, status da
    Gestão, pré-working): a chave da família E as das suas safras.

    A chave da família é entidade legítima para ANOTAÇÃO (comentário, checklist de
    pré-working — que é config de ingestão, uma por família). O que NÃO mora nela é o
    estado CONTADO (etapa/status/responsável): esse continua nas safras e sobe por
    agregação (ADR 0002). Chave sem família devolve ela mesma."""
    if not FAMILIAS_ON:
        return [chave]
    fam = _familia_de_chave(chave)
    if not fam:
        return [chave]
    cat, nome, membros = fam
    if not membros:
        return [chave]
    art_in = ", ".join(sql_lit(a) for a in membros)
    chaves = [r["chave_canonica"] for r in run_sql(
        f"SELECT chave_canonica FROM {T_IN} WHERE categoria = {sql_lit(cat)} "
        f"AND upper(artifact) IN ({art_in})") if r.get("chave_canonica")]
    return [_chave_familia(cat, nome)] + chaves


def _chaves_estado(chave):
    """Chaves que carregam o estado CONTADO (etapa/status) de `chave` em `T_IN`.

    Complemento de `_chaves_para_leitura`: aquela responde por tabelas de ANOTAÇÃO, onde a
    chave da família É entidade legítima (comentário, checklist). Esta responde por
    `sas_inputs_monitor`, que é chaveada por SAFRA e onde `familia::…` não casa linha
    nenhuma — o estado contado mora nas safras e sobe por agregação (ADR 0002). Quem
    escreve etapa/status a partir de uma chave de família tem que passar por aqui, senão a
    escrita roda sem erro e não muda nada.

    Chave que não é de família devolve ela mesma (inclusive a safra de uma família: quem
    abriu uma safra específica mexe só nela)."""
    if not chave.startswith(FAMILIA_PREFIX):
        return [chave]
    fam = _familia_de_chave(chave)
    if not fam:
        return []
    cat, _nome, membros = fam
    if not membros:
        return []
    art_in = ", ".join(sql_lit(a) for a in membros)
    return [r["chave_canonica"] for r in run_sql(
        f"SELECT chave_canonica FROM {T_IN} WHERE categoria = {sql_lit(cat)} "
        f"AND upper(artifact) IN ({art_in})") if r.get("chave_canonica")]


@app.get("/api/input")
def input_detail(chave: str = ""):
    """Detalhe de um input: lista de EGPs que o usam (reverso input->EGPs).

    Com FAMILIAS_ON, chave de família (ou de qualquer safra dela) devolve o detalhe da
    FAMÍLIA — união dos consumidores/produtores + a lista de safras com o estado de cada."""
    if not chave:
        raise HTTPException(400, "chave obrigatória")
    _ensure_link_tables()
    if FAMILIAS_ON:
        fam = _familia_de_chave(chave)
        if fam:
            return _detalhe_familia(*fam)
    egps = run_sql(
        f"SELECT e.projeto, n.area, n.onda, n.escopo_indi, n.ciclo_id, "
        f"coalesce(l.link_broken, false) AS link_broken "
        f"FROM {T_EGP} e LEFT JOIN {T_ND} n ON e.projeto = n.projeto "
        f"LEFT JOIN {T_LINK} l ON l.projeto = e.projeto AND l.chave_canonica = e.chave_canonica "
        f"WHERE e.chave_canonica = {sql_lit(chave)} "
        f"ORDER BY link_broken ASC NULLS FIRST, n.escopo_indi DESC NULLS LAST, e.projeto")
    # Statement Execution API serializa bool como string ("true"/"false"); coerção
    # explícita p/ FastAPI enviar JSON bool, senão o front lê 'false' como truthy.
    for r in egps:
        r["link_broken"] = str(r.get("link_broken")).lower() == "true"
    # produtor(es): EGP(s) cujo OUTPUT e esta tabela. Na linhagem, depende_do produz as
    # via_tabelas consumidas por projeto_alvo; casamos o artefato do input (apos "::")
    # como token exato em via_tabelas (' | '-separado), case-insensitive.
    artifact = chave.split("::", 1)[-1] if "::" in chave else chave
    needle = (" | " + artifact + " | ").upper()
    produtores = run_sql(
        f"SELECT DISTINCT ed.depende_do AS projeto, n.area, n.onda, n.escopo_indi, n.ciclo_id "
        f"FROM {T_ED} ed LEFT JOIN {T_ND} n ON ed.depende_do = n.projeto "
        f"WHERE instr(upper(concat(' | ', ed.via_tabelas, ' | ')), {sql_lit(needle)}) > 0 "
        f"ORDER BY n.escopo_indi DESC NULLS LAST, projeto")
    _ch = _producer_choices().get(artifact)
    if _ch and any(p.get("projeto") == _ch for p in produtores):
        # produtor canonico escolhido -> mostra so ele (poda os demais candidatos)
        produtores = [p for p in produtores if p.get("projeto") == _ch]
    _enrich_egp_contexto(egps)
    _enrich_egp_contexto(produtores)
    return {"egps": egps, "produtores": produtores}


@app.get("/api/inputs-egps")
def inputs_egps(scope: str = "indi", area: list[str] = Query(default=[])):
    """Mapeamento input -> EGP(s) do recorte, p/ o export 'uma linha por (input x EGP)' do
    Monitor. Aberto a qualquer usuario (mesmo escopo dos inputs). Filtra pares (projeto,
    chave) com vínculo quebrado — CSV nunca exporta uma linha 'não conta para este EGP'."""
    _ensure_link_tables()
    if scope == "indi_deps":
        frontier, _b = _frontier_egps("indi_deps", area)
        if not frontier:
            return {"rows": []}
        inl = ", ".join(sql_lit(pj) for pj in frontier)
        rows = run_sql(
            f"SELECT e.chave_canonica, e.projeto FROM {T_EGP} e "
            f"LEFT JOIN {T_LINK} l ON l.projeto = e.projeto AND l.chave_canonica = e.chave_canonica "
            f"WHERE e.projeto IN ({inl}) AND NOT coalesce(l.link_broken, false)")
    else:
        w = "WHERE e.escopo_indi = true" if scope == "indi" else ""
        rows = run_sql(
            f"SELECT e.chave_canonica, e.projeto FROM {T_EGP} e "
            f"LEFT JOIN {T_LINK} l ON l.projeto = e.projeto AND l.chave_canonica = e.chave_canonica "
            f"{w}{' AND' if w else 'WHERE'} NOT coalesce(l.link_broken, false)")
    return {"rows": rows}


def _outputs_scope_where(scope, por_projeto=False):
    """WHERE do recorte da aba Outputs.

    'indi' usa a flag `escopo_indi` da própria linha; 'indi_deps' usa o FECHO
    (escopo Indicium ∪ dependências transitivas) — o MESMO universo da aba Inputs.
    A flag não serve para o fecho: o recompute só marca `escopo_indi` para EGPs do
    escopo direto, então filtrar por ela devolveria o recorte 'indi'. 'base' = tudo.
    Sem filtro de área: a aba filtra área no cliente, o recorte server-side é o fecho
    inteiro. Devolve None quando o recorte é vazio (o chamador responde lista vazia)."""
    if scope == "indi":
        return " WHERE escopo_indi = true"
    if scope != "indi_deps":
        return ""
    frontier, _base = _frontier_egps("indi_deps", [])
    if not frontier:
        return None
    fin = ", ".join(sql_lit(p) for p in frontier)
    if por_projeto:
        return f" WHERE projeto IN ({fin})"
    return (f" WHERE chave_canonica IN (SELECT DISTINCT chave_canonica FROM {T_EGP_OUT} "
            f"WHERE projeto IN ({fin}))")


@app.get("/api/outputs")
def outputs(scope: str = "indi", only_multi: bool = False):
    """Inventario de outputs (read-only). Filtragem fina (area/categoria/terminal/busca)
    e client-side, como no Monitoramento de Inputs. Tolera tabela ausente (pre-1o publish).
    only_multi=true: so outputs com >1 produtor (candidatos a escolha de produtor canonico)."""
    try:
        where = _outputs_scope_where(scope)
    except HTTPException:   # grafo ausente (pre-1o publish): mesmo tratamento das demais
        where = None
    if where is None:
        return {"total": 0, "returned": 0, "capped": False, "rows": []}
    _cols = ("chave_canonica, artifact, categoria, areas, qtd_produtores, "
             "qtd_consumidores, terminal, modernizada_auto, escopo_indi")
    _order = " ORDER BY qtd_consumidores DESC NULLS LAST, artifact"
    try:
        # qtd_criadores/paths_fisicos podem não existir em tabela pré-republish: fallback em cascata.
        rows = run_sql(f"SELECT {_cols}, qtd_criadores, paths_fisicos FROM {T_OUT}{where}{_order}")
    except HTTPException:
        try:
            rows = run_sql(f"SELECT {_cols}, paths_fisicos FROM {T_OUT}{where}{_order}")
            for r in rows:
                r["qtd_criadores"] = None
        except HTTPException:
            try:
                rows = run_sql(f"SELECT {_cols} FROM {T_OUT}{where}{_order}")
                for r in rows:
                    r["paths_fisicos"] = ""
                    r["qtd_criadores"] = None
            except HTTPException:
                rows = []
    choices = _producer_choices()
    for r in rows:
        r["produtor_escolhido"] = choices.get(r.get("chave_canonica"))
    if only_multi:
        def _np(v):
            try:
                return int(v)
            except (TypeError, ValueError):
                return 0
        rows = [r for r in rows if _np(r.get("qtd_produtores")) > 1]
    return {"total": len(rows), "returned": len(rows), "capped": False, "rows": rows}


@app.get("/api/output")
def output_detail(chave: str):
    """Detalhe p/ o drawer: produtores (sas_egp_outputs) + consumidores (sas_egp_inputs).
    Forma uniforme {projeto, area, onda, escopo_indi, ciclo_id}: sas_egp_outputs NAO tem
    ciclo_id (NULL), sas_egp_inputs tem."""
    try:
        # apenas_contribui (regra do criador): quem só apensa/atualiza — badge no drawer.
        try:
            prod = run_sql("SELECT projeto, area, onda, escopo_indi, NULL AS ciclo_id, apenas_contribui "
                           f"FROM {T_EGP_OUT} WHERE chave_canonica = {sql_lit(chave)} ORDER BY projeto")
            for r in prod:
                r["apenas_contribui"] = str(r.get("apenas_contribui")).lower() == "true"
        except HTTPException:
            prod = run_sql("SELECT projeto, area, onda, escopo_indi, NULL AS ciclo_id "
                           f"FROM {T_EGP_OUT} WHERE chave_canonica = {sql_lit(chave)} ORDER BY projeto")
    except HTTPException:
        prod = []
    try:
        _ensure_link_tables()
        # consumidores: chaves de input tem prefixo categoria (tabela::) e a chave do
        # output nao — casa pelo canon puro (strip do prefixo), igual ao qtd_consumidores.
        # link_broken vem do OVERLAY per-(EGP, Input): EGPs que declararam não depender do
        # input compartilham a lista mas ficam esmaecidos e não contam nos totais.
        cons = run_sql(
            f"SELECT e.projeto, e.area, e.onda, e.escopo_indi, e.ciclo_id, "
            f"max(CASE WHEN coalesce(l.link_broken, false) THEN 1 ELSE 0 END) AS link_broken "
            f"FROM {T_EGP} e "
            f"LEFT JOIN {T_LINK} l ON l.projeto = e.projeto AND l.chave_canonica = e.chave_canonica "
            f"WHERE regexp_replace(e.chave_canonica, '^[^:]*::', '') = {sql_lit(chave)} "
            f"GROUP BY e.projeto, e.area, e.onda, e.escopo_indi, e.ciclo_id "
            f"ORDER BY link_broken ASC, e.projeto")
        for r in cons:
            r["link_broken"] = bool(int(r.get("link_broken") or 0))
    except HTTPException:
        cons = []
    try:
        _ch = run_sql(f"SELECT projeto_escolhido FROM {T_CHOICE} WHERE chave_canonica = {sql_lit(chave)} LIMIT 1")
        _escolhido = _ch[0]["projeto_escolhido"] if _ch else None
    except HTTPException:
        _escolhido = None
    return {"produtores": prod, "consumidores": cons, "produtor_escolhido": _escolhido}


@app.get("/api/outputs-egps")
def outputs_egps(scope: str = "indi"):
    """Pares output->produtor p/ o export explodido (uma linha por output x EGP produtor)."""
    try:
        where = _outputs_scope_where(scope, por_projeto=True)
        rows = [] if where is None else run_sql(
            f"SELECT chave_canonica, projeto FROM {T_EGP_OUT}{where}")
    except HTTPException:
        rows = []
    return {"rows": rows}


# ---- Recebimento manual de Outputs (preenchido no side panel da Gestão) ----
# Tabela própria (CREATE IF NOT EXISTS, nunca dropada, FORA do publish — mesmo espírito de
# T_PWK/T_PIPE): sas_outputs_pipeline, grão chave_canonica (o output é uma entidade global,
# igual sas_outputs_monitor — não faz sentido "recebido" variar por EGP produtor). Alimenta
# n_outputs_disp em _egp_readiness_rows (SUBSTITUI modernizada_auto quando já tocado, ver
# comentário lá) — mesmo padrão de "Pré-working" do EGP (toggle + data, 100% manual).
@functools.lru_cache(maxsize=1)
def _ensure_out_pipe_table():
    if dialeto.PG:  # no Postgres o schema vem das migrações (db/migrations), nunca do app
        return True
    run_sql(f"""CREATE TABLE IF NOT EXISTS {T_OUT_PIPE} (chave_canonica STRING,
  recebido STRING, recebido_data STRING, updated_by STRING, updated_at STRING) USING DELTA""",
            want_rows=False)
    for col in ("carga_fria", "cf_etapa", "cf_status", "cf_responsavel", "cf_inicio", "cf_fim", "cf_caminho", "cf_tabela"):
        try:
            run_sql(f"SELECT {col} FROM {T_OUT_PIPE} LIMIT 0")
        except HTTPException:
            run_sql(f"ALTER TABLE {T_OUT_PIPE} ADD COLUMNS ({col} STRING)", want_rows=False)
    return True


@app.get("/api/outputs-pipeline")
def outputs_pipeline_rows():
    """Recebimento manual de todos os outputs já tocados — tabela pequena, carregada
    inteira 1x (mesmo padrão de /api/inputs/preworking); o frontend monta um Map
    client-side, usado no GestaoStatusPanel (lista de Outputs do EGP)."""
    _ensure_out_pipe_table()
    return {"rows": run_sql(
        f"SELECT chave_canonica, recebido, recebido_data, carga_fria, cf_etapa, cf_status, cf_responsavel, "
        f"cf_inicio, cf_fim, cf_caminho, cf_tabela, updated_by, "
        f"CAST(updated_at AS STRING) AS updated_at FROM {T_OUT_PIPE}")}


class OutputPipe(BaseModel):
    chave_canonica: str
    recebido: bool | None = None
    recebido_data: str | None = None
    carga_fria: bool | None = None
    # Card de carga fria no Kanban de Inputs: o funil de ingestão do output vive aqui (o
    # output não é linha de T_IN). "" limpa; None preserva.
    cf_etapa: str | None = None
    cf_status: str | None = None
    cf_responsavel: str | None = None
    # Janela do histórico a ingerir (YYYY-MM-DD, "" limpa) e destino final dos arquivos.
    cf_inicio: str | None = None
    cf_fim: str | None = None
    cf_caminho: str | None = None
    # Nome da tabela modernizada que receberá o histórico (equivale a "Tbl. Corresp." do input).
    cf_tabela: str | None = None


@app.patch("/api/output-pipeline")
def output_pipeline_patch(p: OutputPipe):
    """Grava o recebimento manual de 1 output (MERGE upsert em sas_outputs_pipeline, só os
    campos enviados). `recebido` é booleano (não string): None enviado preserva o valor
    atual; True/False é valor explícito válido (não pode cair no "or None" das strings,
    senão False viraria None por engano) — mesma convenção de EgpPipe.preworking."""
    if p.recebido_data not in (None, "") and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", p.recebido_data):
        raise HTTPException(400, "recebido_data deve ser YYYY-MM-DD")
    _ensure_out_pipe_table()
    cur = run_sql(f"SELECT recebido, recebido_data, carga_fria, cf_etapa, cf_status, cf_responsavel, "
                  f"cf_inicio, cf_fim, cf_caminho, cf_tabela FROM {T_OUT_PIPE} "
                  f"WHERE chave_canonica = {sql_lit(p.chave_canonica)}")
    old = cur[0] if cur else {}
    rec_new = ("true" if p.recebido else "false") if p.recebido is not None else (old.get("recebido") or None)
    data_new = (p.recebido_data if p.recebido_data is not None else old.get("recebido_data")) or None
    # carga_fria: sinaliza que o output precisa de carga histórica (fria) — só marcação, não
    # entra na prontidão. Mesma convenção do `recebido` (None preserva; False é valor válido).
    cf_new = ("true" if p.carga_fria else "false") if p.carga_fria is not None else (old.get("carga_fria") or None)
    for _k in ("cf_inicio", "cf_fim"):
        _v = getattr(p, _k)
        if _v not in (None, "") and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", _v):
            raise HTTPException(400, f"{_k} deve ser YYYY-MM-DD")
    if p.cf_inicio and p.cf_fim and p.cf_inicio > p.cf_fim:
        raise HTTPException(400, "cf_inicio não pode ser posterior a cf_fim")
    if p.cf_etapa and p.cf_etapa not in PIPELINE_INPUT:
        raise HTTPException(400, "cf_etapa fora do funil de ingestão")
    if p.cf_status and p.cf_status not in STATUS_INPUT:
        raise HTTPException(400, "cf_status inválido")
    etapa_new = (p.cf_etapa if p.cf_etapa is not None else old.get("cf_etapa")) or None
    status_new = (p.cf_status if p.cf_status is not None else old.get("cf_status")) or None
    resp_new = (p.cf_responsavel if p.cf_responsavel is not None else old.get("cf_responsavel")) or None
    ini_new = (p.cf_inicio if p.cf_inicio is not None else old.get("cf_inicio")) or None
    fim_new = (p.cf_fim if p.cf_fim is not None else old.get("cf_fim")) or None
    cam_new = ((p.cf_caminho.strip() if p.cf_caminho is not None else old.get("cf_caminho"))) or None
    tab_new = ((p.cf_tabela.strip() if p.cf_tabela is not None else old.get("cf_tabela"))) or None
    run_sql(
        f"MERGE INTO {T_OUT_PIPE} t USING (SELECT {sql_lit(p.chave_canonica)} AS chave_canonica) s "
        f"ON t.chave_canonica = s.chave_canonica "
        f"WHEN MATCHED THEN UPDATE SET recebido = {sql_lit(rec_new)}, recebido_data = {sql_lit(data_new)}, "
        f"carga_fria = {sql_lit(cf_new)}, cf_etapa = {sql_lit(etapa_new)}, "
        f"cf_status = {sql_lit(status_new)}, cf_responsavel = {sql_lit(resp_new)}, "
        f"cf_inicio = {sql_lit(ini_new)}, cf_fim = {sql_lit(fim_new)}, cf_caminho = {sql_lit(cam_new)}, cf_tabela = {sql_lit(tab_new)}, "
        f"updated_by = {_ator()}, updated_at = cast({AGORA} AS STRING) "
        f"WHEN NOT MATCHED THEN INSERT (chave_canonica, recebido, recebido_data, carga_fria, cf_etapa, "
        f"cf_status, cf_responsavel, cf_inicio, cf_fim, cf_caminho, cf_tabela, updated_by, updated_at) "
        f"VALUES ({sql_lit(p.chave_canonica)}, {sql_lit(rec_new)}, {sql_lit(data_new)}, {sql_lit(cf_new)}, "
        f"{sql_lit(etapa_new)}, {sql_lit(status_new)}, {sql_lit(resp_new)}, "
        f"{sql_lit(ini_new)}, {sql_lit(fim_new)}, {sql_lit(cam_new)}, {sql_lit(tab_new)}, {_ator()}, "
        f"cast({AGORA} AS STRING))", want_rows=False)
    _bump_gen()   # T_OUT_PIPE alimenta n_outputs_disp da aba EGPs
    return {"ok": True, "chave_canonica": p.chave_canonica,
            "recebido": rec_new == "true", "recebido_data": data_new,
            "carga_fria": cf_new == "true", "cf_etapa": etapa_new, "cf_status": status_new,
            "cf_responsavel": resp_new, "cf_inicio": ini_new, "cf_fim": fim_new, "cf_caminho": cam_new, "cf_tabela": tab_new}


class OutputProducer(BaseModel):
    chave_canonica: str
    projeto_escolhido: str


@app.post("/api/output-producer")
def set_output_producer(p: OutputProducer):
    """Marca o produtor correto de um output multi-produtor (poda o grafo — ver _prune_edges).
    Efeito na hora: bump do cache de linhagem (igual recompute_escopo)."""
    global _lineage_gen
    chave = (p.chave_canonica or "").strip()
    proj = (p.projeto_escolhido or "").strip()
    if not chave or not proj:
        raise HTTPException(400, "chave_canonica e projeto_escolhido obrigatórios")
    prods = {r["projeto"] for r in run_sql(
        f"SELECT DISTINCT projeto FROM {T_EGP_OUT} WHERE chave_canonica = {sql_lit(chave)}")}
    if proj not in prods:
        raise HTTPException(400, f'"{proj}" nao e produtor de {chave}')
    if not dialeto.PG:  # no Postgres o schema vem das migrações (db/migrations), nunca do app
        run_sql(f"CREATE TABLE IF NOT EXISTS {T_CHOICE} (chave_canonica STRING, projeto_escolhido STRING, "
                f"chosen_by STRING, chosen_at STRING) USING DELTA", want_rows=False)
    run_sql(f"DELETE FROM {T_CHOICE} WHERE chave_canonica = {sql_lit(chave)}", want_rows=False)
    run_sql(f"INSERT INTO {T_CHOICE} (chave_canonica, projeto_escolhido, chosen_by, chosen_at) "
            f"VALUES ({sql_lit(chave)}, {sql_lit(proj)}, {_ator()}, cast({AGORA} AS STRING))",
            want_rows=False)
    _lineage_gen += 1
    _lineage_cache.clear()
    return {"ok": True, "chave_canonica": chave, "projeto_escolhido": proj}


@app.delete("/api/output-producer")
def clear_output_producer(chave: str):
    """Remove a escolha de produtor de um output (volta ao estado ambiguo)."""
    global _lineage_gen
    try:
        run_sql(f"DELETE FROM {T_CHOICE} WHERE chave_canonica = {sql_lit(chave)}", want_rows=False)
    except HTTPException:
        pass
    _lineage_gen += 1
    _lineage_cache.clear()
    return {"ok": True}


class Patch(BaseModel):
    chave_canonica: str
    etapa: str | None = None
    status: str | None = None
    responsavel: str | None = None
    observacao: str | None = None


def _norm(v):
    return "" if v is None else str(v)


def _msg_trava_derivada(motivo):
    """409 da trava de etapa/status em input sanitizado por derivação (14/10/2026).

    Etapa e status desse input são EXIBIDOS (Modernizado + Sanitizado), não gravados.
    Gravar a etapa tirava o input da derivação — ela só vale para chave pendente — e ele
    passava a contar como modernizado com o status cru do publish ('A Iniciar'): 37 inputs
    lidos só pelo antecessor de um vínculo estavam assim em prod. Não há o que destravar à
    mão: o input volta à fila sozinho quando a condição deixa de valer."""
    rotulo = sanitizacao.MOTIVO_LABEL.get(motivo, motivo)
    return (f"input sanitizado automaticamente ({rotulo}): etapa e status são derivados e "
            f"não se editam. Ele volta para a fila sozinho se a condição deixar de valer "
            f"(vínculo com a versão nova desfeito ou consumidor repriorizado).")


def _patch_familia(p, cat, nome):
    """Escrita de FAMÍLIA: fan-out para todas as safras + auditoria por safra.

    Por que fan-out e não uma linha de estado na chave da família (ADR 0002): duas verdades
    no banco é o que produz número divergente entre telas. Com fan-out, qualquer superfície
    que ainda leia a safra continua coerente, e o histórico do que foi sobrescrito fica em
    sas_inputs_audit — inclusive as sanitizações por safra da regra 12M/3M, que a unificação
    transformou em histórico por decisão explícita.

    Consequência aceita: marcar a família como pendente sobrescreve o `Sanitizado` das safras
    fora da janela. É o desejado (a janela deixou de ser status por safra), mas é irreversível
    na tabela viva — só a auditoria guarda o antes."""
    membros = run_sql(
        f"SELECT chave_canonica, artifact, categoria, origem, source_types, qtd_projetos, "
        f"areas, escopo_indi, modernizada_auto, etapa, status, responsavel, observacao, "
        f"orfao, paths_fisicos, n_paths_fisicos FROM {T_IN} "
        f"WHERE categoria = {sql_lit(cat)} AND upper(artifact) IN "
        f"({', '.join(sql_lit(a) for a in _familias_corpus()['membros'].get((cat, nome), []))}) "
        f"AND NOT orfao")
    if not membros:
        raise HTTPException(404, "família sem safras no corpus")
    # Autoprodutor é isenção por TABELA: a família vale se ALGUMA safra for candidata
    # (o EGP que cria e consome normalmente cria todas as safras).
    if p.status == "Autoprodutor":
        cands = _autoprodutor_candidatos()
        if not any(m["chave_canonica"] in cands for m in membros):
            raise HTTPException(400, "nenhuma safra desta família é candidata a Autoprodutor")
    novos = {"etapa": (p.etapa or None) if p.etapa is not None else None,
             "status": (p.status or None) if p.status is not None else None,
             "responsavel": p.responsavel, "observacao": p.observacao}
    enviados = {k: getattr(p, k) is not None for k in novos}
    # Trava da derivação (ver _msg_trava_derivada): etapa/status vão só para as safras que
    # NÃO estão sanitizadas por derivação — a derivada não é trabalho, a viva é. Família
    # toda derivada -> 409. Responsável/observação seguem para todas. O front manda um
    # campo por PATCH; um PATCH misto (etapa + responsável) escreveria só nas vivas.
    alvo = membros
    if enviados["etapa"] or enviados["status"]:
        _der = _sanitizacao_derivada()
        alvo = [m for m in membros if m["chave_canonica"] not in _der]
        if not alvo:
            raise HTTPException(409, _msg_trava_derivada(_der.get(membros[0]["chave_canonica"])))
    # diffs POR SAFRA: a auditoria tem que registrar o valor antigo de cada uma (é o único
    # lugar onde o estado sobrescrito continua existindo)
    audits = []
    for m in alvo:
        for campo, novo in novos.items():
            if not enviados[campo]:
                continue
            if _norm(novo) == _norm(m.get(campo)):
                continue
            audits.append((m["chave_canonica"], campo, _norm(m.get(campo)), _norm(novo)))
    if not audits:
        raise HTTPException(400, "nada para atualizar (todas as safras já têm esses valores)")
    sets = [f"{c} = {sql_lit(v)}" for c, v in novos.items() if enviados[c]]
    sets += [f"updated_at = {AGORA}", f"updated_by = {_ator()}"]
    chaves_in = ", ".join(sql_lit(m["chave_canonica"]) for m in alvo)
    run_sql(f"UPDATE {T_IN} SET {', '.join(sets)} "
            f"WHERE chave_canonica IN ({chaves_in})", want_rows=False)
    vals = ",\n".join(
        f"({sql_lit(ch)}, {sql_lit(c)}, {sql_lit(va)}, {sql_lit(vn)}, "
        f"{_ator()}, {AGORA})" for ch, c, va, vn in audits)
    run_sql(f"INSERT INTO {T_AUD} (chave_canonica, campo, valor_antigo, valor_novo, "
            f"updated_by, updated_at) VALUES\n{vals}", want_rows=False)
    # devolve a LINHA DE FAMÍLIA recalculada (o front faz merge por chave): reagrega os
    # membros já com os valores novos, então `estado_misto`/`n_safras_pendentes` saem certos
    for m in alvo:
        for campo in novos:
            if enviados[campo]:
                m[campo] = novos[campo]
    # overlay ANTES da agregação, na mesma ordem de `_dataset_escopo`: os motivos são
    # chaveados pela SAFRA e é o status já sobrescrito que a família agrega. Reagregar sem
    # ele devolvia uma família com status/`estado_misto`/`n_safras_pendentes` calculados
    # sobre o status cru — diferentes dos que a própria aba mostra na linha seguinte.
    sanitizacao.aplica_em_linhas(membros, _sanitizacao_derivada())
    agregado = _agrega_familias(membros)
    linha = agregado[0] if agregado else dict(membros[0])
    # o front faz MERGE da resposta na linha em cache: campos que esta escrita não decide
    # saem fora, senão sobrescreveriam estado do cliente com valor inventado aqui
    # (`vinculo_ativo`/`ex_dependencia` dependem do recorte; não são reagregáveis daqui).
    for k in ("vinculo_ativo", "ex_dependencia"):
        linha.pop(k, None)
    return linha, len(audits), len(membros)


@app.patch("/api/inputs")
def patch_input(p: Patch):
    global _lineage_gen
    _ensure_input_pipeline_cols()
    if p.etapa not in (None, "") and p.etapa not in PIPELINE_INPUT:
        raise HTTPException(400, f"etapa inválida: {p.etapa}")
    if p.status not in (None, "") and p.status not in STATUS_INPUT:
        raise HTTPException(400, f"status inválido: {p.status}")
    # chave de FAMÍLIA -> fan-out para as safras (ver _patch_familia). Chave de SAFRA
    # continua escrevendo só nela, de propósito: quem manda uma safra está vendo uma
    # safra (lista de safras dentro do drawer da família, filtro aplicado na aba Inputs,
    # script) e a edição não pode cascatear para 47 linhas que a pessoa não está vendo.
    if FAMILIAS_ON and p.chave_canonica.startswith(FAMILIA_PREFIX):
        cat, _, nome = p.chave_canonica[len(FAMILIA_PREFIX):].partition("::")
        linha, n_aud, n_mem = _patch_familia(p, cat, nome)
        _lineage_gen += 1
        linha["fan_out"] = {"safras": n_mem, "alteracoes": n_aud}
        return linha
    # trava da derivação ANTES de qualquer escrita (ver _msg_trava_derivada)
    if p.etapa is not None or p.status is not None:
        _motivo = _sanitizacao_derivada().get(p.chave_canonica)
        if _motivo:
            raise HTTPException(409, _msg_trava_derivada(_motivo))
    # Autoprodutor é isenção GLOBAL (vale p/ todos os EGPs que consomem o input) — só
    # aceita se o input for de fato candidato (algum EGP cria E consome a mesma tabela;
    # ver _autoprodutor_candidatos()), senão um erro aqui esconderia uma dependência real
    # de ingestão para o app inteiro.
    if p.status == "Autoprodutor" and p.chave_canonica not in _autoprodutor_candidatos():
        raise HTTPException(400, "input não é candidato a Autoprodutor (nenhum EGP "
                             "consumidor é criador único/canônico desta tabela)")
    # estado atual completo (p/ auditoria do diff + montar retorno sem re-SELECT)
    cur = run_sql(
        f"SELECT chave_canonica, artifact, categoria, origem, source_types, qtd_projetos, areas, "
        f"escopo_indi, modernizada_auto, etapa, status, responsavel, observacao, orfao, "
        f"paths_fisicos, n_paths_fisicos "
        f"FROM {T_IN} WHERE chave_canonica = {sql_lit(p.chave_canonica)}")
    if not cur:
        raise HTTPException(404, "chave não encontrada")
    old = cur[0]
    # campo enviado como "" -> grava NULL (não string vazia), mesma convenção do
    # PATCH /api/egp-pipeline (EgpPipe) — evita "" e NULL contarem como valores distintos.
    novos = {"etapa": (p.etapa or None) if p.etapa is not None else None,
             "status": (p.status or None) if p.status is not None else None,
             "responsavel": p.responsavel, "observacao": p.observacao}
    enviados = {"etapa": p.etapa is not None, "status": p.status is not None,
                "responsavel": p.responsavel is not None, "observacao": p.observacao is not None}
    sets, audits = [], []
    for campo, novo in novos.items():
        if not enviados[campo]:
            continue
        if _norm(novo) == _norm(old.get(campo)):
            continue  # sem mudança real -> não audita
        sets.append(f"{campo} = {sql_lit(novo)}")
        audits.append((campo, _norm(old.get(campo)), _norm(novo)))
    if not sets:
        raise HTTPException(400, "nada para atualizar (valores idênticos)")
    sets.append(f"updated_at = {AGORA}")
    sets.append(f"updated_by = {_ator()}")
    run_sql(f"UPDATE {T_IN} SET {', '.join(sets)} WHERE chave_canonica = {sql_lit(p.chave_canonica)}",
            want_rows=False)
    if audits:
        vals = ",\n".join(
            f"({sql_lit(p.chave_canonica)}, {sql_lit(c)}, {sql_lit(va)}, {sql_lit(vn)}, "
            f"{_ator()}, {AGORA})" for c, va, vn in audits)
        run_sql(f"INSERT INTO {T_AUD} (chave_canonica, campo, valor_antigo, valor_novo, "
                f"updated_by, updated_at) VALUES\n{vals}", want_rows=False)
    # edit humano mudou T_IN (etapa/status/responsavel/observacao) -> invalida o cache do
    # dataset do escopo (mesma geração global da linhagem) p/ não servir dado velho.
    _lineage_gen += 1
    # monta a linha de retorno em Python (UPDATE só altera as 4 colunas humanas
    # + updated_at/by, que não fazem parte do retorno) -> evita re-SELECT
    result = dict(old)
    for campo in ("etapa", "status", "responsavel", "observacao"):
        if enviados[campo]:
            result[campo] = novos[campo]
    # MESMA derivação de leitura que `_dataset_escopo` aplica (§3.4.18). Sem ela a resposta
    # devolve o status CRU e o front, que faz merge da resposta na linha em cache, troca o
    # `Sanitizado` DERIVADO pelo cru: a linha pulava de "A Receber/Sanitizado" para
    # "<etapa nova>/A Iniciar" na hora de salvar e voltava a Sanitizado no refetch
    # seguinte — o banco nunca mudou, só a resposta estava sem o overlay. Medido em
    # 09/10/2026: 60 inputs com sanitização derivada, 23 linhas exibidas assim.
    sanitizacao.aplica_em_linhas([result], _sanitizacao_derivada())
    return result


class FamiliaPeriodo(BaseModel):
    projeto: str
    categoria: str
    familia: str
    tipo: str = ""        # todas | desde | rolling | "" (volta ao derivado)
    valor: str | None = None


@app.patch("/api/familia-periodo")
def patch_familia_periodo(p: FamiliaPeriodo):
    """Declara a profundidade que um EGP precisa de uma família (ou volta ao derivado).

    Restrito ao grupo de gestão: declarar "esse EGP precisa de 36 meses" É pedido de
    ingestão ao BV — mesma natureza do vínculo quebrado, não de "marquei que recebi".
    `tipo=""` apaga a declaração e o par volta a valer pelo corpus (o derivado nunca é
    sobrescrito porque nunca é gravado)."""
    _require_gestao()
    _ensure_periodo_tables()
    tipo = (p.tipo or "").strip()
    valor = (p.valor or "").strip() or None
    if tipo and tipo not in PERIODO_TIPOS:
        raise HTTPException(400, f"tipo inválido: {tipo} (use {', '.join(PERIODO_TIPOS)} ou vazio)")
    if tipo == "desde":
        if not (valor and re.fullmatch(r"20\d{2}(0[1-9]|1[0-2])", valor)):
            raise HTTPException(400, "desde exige safra AAAAMM válida (ex.: 202401)")
    elif tipo == "rolling":
        try:
            n = int(valor or "")
        except (TypeError, ValueError):
            raise HTTPException(400, "rolling exige número de meses")
        if not (1 <= n <= 600):
            raise HTTPException(400, "rolling fora da faixa (1..600 meses)")
        valor = str(n)
    else:
        valor = None if tipo == "todas" else valor
    chave = (p.projeto, p.categoria, p.familia)
    atual = _periodo_declarado().get(chave)
    antigo = f"{atual['tipo']}:{atual.get('valor') or ''}" if atual else ""
    novo = f"{tipo}:{valor or ''}" if tipo else ""
    if not tipo and not atual:
        # "voltar ao derivado" quando já está derivado: no-op idempotente (apagar o que não
        # existe não é erro) — 400 aqui só atrapalharia quem reverte duas vezes.
        return {"ok": True, "projeto": p.projeto, "categoria": p.categoria,
                "familia": p.familia, "tipo": None, "valor": None, "origem": "derivado"}
    if antigo == novo:
        raise HTTPException(400, "nada para atualizar (valor idêntico)")
    where = (f"projeto = {sql_lit(p.projeto)} AND categoria = {sql_lit(p.categoria)} "
             f"AND familia = {sql_lit(p.familia)}")
    if tipo:
        # MERGE, não DELETE+INSERT (mesma razão do /api/familia-ingestao): entre os dois
        # statements a linha não existia, e um timeout ali apagava a profundidade
        # DECLARADA do par (EGP, família) — que some sem rastro, porque "sem linha" é
        # indistinguível de "nunca declarado" (volta a origem:'derivado').
        run_sql(
            f"MERGE INTO {T_PER} t USING (SELECT {sql_lit(p.projeto)} AS projeto, "
            f"{sql_lit(p.categoria)} AS categoria, {sql_lit(p.familia)} AS familia, "
            f"{sql_lit(tipo)} AS tipo, {sql_lit(valor)} AS valor) s "
            f"ON t.projeto = s.projeto AND t.categoria = s.categoria "
            f"AND t.familia = s.familia "
            f"WHEN MATCHED THEN UPDATE SET tipo = s.tipo, valor = s.valor, "
            f"updated_by = {_ator()}, updated_at = {AGORA} "
            f"WHEN NOT MATCHED THEN INSERT (projeto, categoria, familia, tipo, valor, "
            f"updated_by, updated_at) VALUES (s.projeto, s.categoria, s.familia, s.tipo, "
            f"s.valor, {_ator()}, {AGORA})", want_rows=False)
    else:
        run_sql(f"DELETE FROM {T_PER} WHERE {where}", want_rows=False)
    run_sql(f"INSERT INTO {T_PER_AUD} (id, projeto, categoria, familia, campo, "
            f"valor_antigo, valor_novo, ator, ts) VALUES ({sql_lit(uuid.uuid4().hex)}, "
            f"{sql_lit(p.projeto)}, {sql_lit(p.categoria)}, {sql_lit(p.familia)}, "
            f"'periodo', {sql_lit(antigo)}, {sql_lit(novo)}, {_ator()}, "
            f"{AGORA})", want_rows=False)
    _bump_gen()   # invalida o cache do declarado (e o payload do detalhe)
    return {"ok": True, "projeto": p.projeto, "categoria": p.categoria,
            "familia": p.familia, "tipo": tipo or None, "valor": valor,
            "origem": "declarado" if tipo else "derivado"}


class EgpInputLink(BaseModel):
    projeto: str
    chave_canonica: str
    link_broken: bool


def _link_escreve(projeto, chave, novo):
    """Grava o vínculo de UM par (EGP, input) + auditoria. Devolve True se mudou.

    Extraído de `patch_egp_input_link` para que a chave de FAMÍLIA possa reusar o mesmo
    caminho por safra (ver o fan-out abaixo) — uma regra de escrita, um lugar."""
    cur = run_sql(
        f"SELECT link_broken FROM {T_LINK} WHERE projeto = {sql_lit(projeto)} "
        f"AND chave_canonica = {sql_lit(chave)}")
    old = bool(cur[0]["link_broken"]) if cur else False
    if old == bool(novo):
        return False
    if novo:
        # UPSERT: linha ausente ≡ linkado; só existem linhas para link_broken=true.
        run_sql(
            f"MERGE INTO {T_LINK} t USING (SELECT {sql_lit(projeto)} AS projeto, "
            f"{sql_lit(chave)} AS chave_canonica) s "
            f"ON t.projeto = s.projeto AND t.chave_canonica = s.chave_canonica "
            f"WHEN MATCHED THEN UPDATE SET link_broken = true, "
            f"updated_by = {_ator()}, updated_at = {AGORA} "
            f"WHEN NOT MATCHED THEN INSERT (projeto, chave_canonica, link_broken, "
            f"updated_by, updated_at) VALUES ({sql_lit(projeto)}, "
            f"{sql_lit(chave)}, true, {_ator()}, {AGORA})",
            want_rows=False)
    else:
        run_sql(
            f"DELETE FROM {T_LINK} WHERE projeto = {sql_lit(projeto)} "
            f"AND chave_canonica = {sql_lit(chave)}", want_rows=False)
    run_sql(
        f"INSERT INTO {T_LINK_AUD} (id, projeto, chave_canonica, campo, valor_antigo, "
        f"valor_novo, ator, ts) VALUES ({sql_lit(uuid.uuid4().hex)}, "
        f"{sql_lit(projeto)}, {sql_lit(chave)}, 'link_broken', "
        f"{sql_lit(_norm(old))}, {sql_lit(_norm(novo))}, {_ator()}, "
        f"{AGORA})", want_rows=False)
    return True


def _safras_do_egp(projeto, chave_familia):
    """Chaves das safras de uma família que AQUELE EGP consome. O vínculo é por par
    (EGP, input): quebrar a família num EGP não pode tocar as safras que ele não lê."""
    cat, _, nome = chave_familia[len(FAMILIA_PREFIX):].partition("::")
    membros = _familias_corpus()["membros"].get((cat, nome), [])
    if not membros:
        return []
    art_in = ", ".join(sql_lit(a) for a in membros)
    return [r["chave_canonica"] for r in run_sql(
        f"SELECT e.chave_canonica FROM {T_EGP} e JOIN {T_IN} i "
        f"ON i.chave_canonica = e.chave_canonica "
        f"WHERE e.projeto = {sql_lit(projeto)} AND i.categoria = {sql_lit(cat)} "
        f"AND upper(i.artifact) IN ({art_in})") if r.get("chave_canonica")]


@app.patch("/api/egp-input-link")
def patch_egp_input_link(p: EgpInputLink):
    """Quebra/restaura o vínculo (EGP, Input). Broken=True → aquele input passa a
    contar como Sanitizado para AQUELE EGP apenas (não afeta outros consumidores).
    Somente gestão (bv_users); auditado em T_LINK_AUD; bumpa _lineage_gen p/ invalidar
    o cache de linhagem (readiness/blocking/priorização recomputam ao vivo).

    Chave de FAMÍLIA (o drawer do EGP lista famílias desde 18/09/2026): fan-out para as
    safras que este EGP consome. Gravar a própria chave `familia::` seria falha
    silenciosa — ela não casa com sas_egp_inputs, então a tela mostraria "vínculo
    quebrado" e o app seguiria contando o input."""
    global _lineage_gen
    _require_gestao()
    _ensure_link_tables()
    if FAMILIAS_ON and p.chave_canonica.startswith(FAMILIA_PREFIX):
        chaves = _safras_do_egp(p.projeto, p.chave_canonica)
        if not chaves:
            raise HTTPException(404, "família sem safras neste EGP")
        n = sum(1 for ch in chaves if _link_escreve(p.projeto, ch, p.link_broken))
        if n:
            _lineage_gen += 1
        return {"ok": True, "projeto": p.projeto, "chave_canonica": p.chave_canonica,
                "link_broken": p.link_broken,
                "fan_out": {"safras": len(chaves), "alteracoes": n}}
    if _link_escreve(p.projeto, p.chave_canonica, p.link_broken):
        _lineage_gen += 1
    return {"ok": True, "projeto": p.projeto, "chave_canonica": p.chave_canonica,
            "link_broken": p.link_broken}


class DepMantida(BaseModel):
    produtor: str
    mantida: bool
    motivo: str | None = None


def _depm_escreve(projeto, chave, novo, motivo=None):
    """Grava a dependência mantida de UM par (EGP consumidor, input) + auditoria. Devolve
    True se mudou. Mesma forma do _link_escreve: linha ausente ≡ não mantida."""
    cur = run_sql(f"SELECT motivo FROM {T_DEPM} WHERE projeto = {sql_lit(projeto)} "
                  f"AND chave_canonica = {sql_lit(chave)}")
    old = bool(cur)
    if old == bool(novo):
        return False
    if novo:
        run_sql(
            f"MERGE INTO {T_DEPM} t USING (SELECT {sql_lit(projeto)} AS projeto, "
            f"{sql_lit(chave)} AS chave_canonica) s "
            f"ON t.projeto = s.projeto AND t.chave_canonica = s.chave_canonica "
            f"WHEN MATCHED THEN UPDATE SET motivo = {sql_lit(motivo)}, "
            f"updated_by = {_ator()}, updated_at = {AGORA} "
            f"WHEN NOT MATCHED THEN INSERT (projeto, chave_canonica, motivo, updated_by, "
            f"updated_at) VALUES ({sql_lit(projeto)}, {sql_lit(chave)}, "
            f"{sql_lit(motivo)}, {_ator()}, {AGORA})", want_rows=False)
    else:
        run_sql(f"DELETE FROM {T_DEPM} WHERE projeto = {sql_lit(projeto)} "
                f"AND chave_canonica = {sql_lit(chave)}", want_rows=False)
    run_sql(
        f"INSERT INTO {T_DEPM_AUD} (id, projeto, chave_canonica, campo, valor_antigo, "
        f"valor_novo, ator, ts) VALUES ({sql_lit(uuid.uuid4().hex)}, {sql_lit(projeto)}, "
        f"{sql_lit(chave)}, 'dep_mantida', {sql_lit('true' if old else 'false')}, "
        f"{sql_lit('true' if novo else 'false')}, {_ator()}, {AGORA})",
        want_rows=False)
    return True


def _pares_do_produtor(produtor):
    """Pares (consumidor, chave_canonica) pelos quais `produtor` é puxado, a partir do
    grafo BRUTO. Grafo bruto de propósito: quando a via já foi dada como resolvida a
    aresta não existe mais no grafo podado — e é exatamente esse o caso que o botão
    conserta. Traduz o ARTIFACT da via para a chave_canonica DAQUELE consumidor (é o grão
    em que o vínculo por par é gravado no app inteiro)."""
    edges = run_sql(f"SELECT projeto_alvo, via_tabelas FROM {T_ED} "
                    f"WHERE depende_do = {sql_lit(produtor)}")
    quer = set()
    for e in edges:
        alvo = e.get("projeto_alvo")
        if not alvo or alvo == produtor:
            continue
        for t in (e.get("via_tabelas") or "").split("|"):
            if t.strip():
                quer.add((alvo, t.strip().upper()))
    if not quer:
        return []
    projs = ", ".join(sql_lit(p) for p in {a for a, _ in quer})
    arts = ", ".join(sql_lit(t) for _, t in quer)
    return [(r["projeto"], r["chave_canonica"]) for r in run_sql(
        f"SELECT e.projeto, e.chave_canonica, upper(i.artifact) AS artifact "
        f"FROM {T_EGP} e JOIN {T_IN} i ON i.chave_canonica = e.chave_canonica "
        f"WHERE e.projeto IN ({projs}) AND upper(i.artifact) IN ({arts}) "
        f"AND i.categoria = 'tabela'")
        if (r.get("projeto"), (r.get("artifact") or "")) in quer]


@app.patch("/api/egp-dep-mantida")
def patch_dep_mantida(p: DepMantida):
    """"Ainda é dependência": o consumidor declara que continua precisando do PRODUTOR,
    mesmo com a via já no lake. Reabre a aresta e o produtor volta ao frontier vivo —
    deixa de ser ex-dependência, volta a puxar os próprios inputs e volta ao funil.

    O botão age no PRODUTOR (é ele que se vê sumindo do recorte) mas GRAVA por par
    (consumidor, input) — mesmo grão do link_broken, e por isso não afeta os outros
    consumidores daquela tabela. Fan-out explícito na resposta.

    Não mexe no status do input: a tabela segue Modernizada no funil de ingestão, porque
    ela ESTÁ no lake. O que o botão diz é outra coisa — que aquela ingestão não cobre o
    que este consumidor precisa. Se o certo for que a ingestão está incompleta, o lugar de
    corrigir é o input, não aqui.

    Somente gestão (bv_users); auditado em T_DEPM_AUD; bumpa _lineage_gen."""
    global _lineage_gen
    _require_gestao()
    _ensure_dep_mantida_tables()
    pares = _pares_do_produtor(p.produtor)
    if not pares:
        raise HTTPException(404, "nenhum consumidor deste produtor no grafo")
    n = sum(1 for proj, ch in pares if _depm_escreve(proj, ch, p.mantida, p.motivo))
    if n:
        _lineage_gen += 1
    return {"ok": True, "produtor": p.produtor, "mantida": p.mantida,
            "fan_out": {"pares": len(pares), "alteracoes": n,
                        "consumidores": sorted({proj for proj, _ in pares})}}


@app.get("/api/landing")
def landing():
    """Visão geral (landing): 7 indicadores + 3 totais. Itens 3/4/6/7 usam status
    EFETIVO (refletem edições em tempo real); 1/2/5 vêm do escopo/grafo (publish)."""
    _ensure_escopo_ativo()
    _ensure_link_tables()
    _ensure_input_pipeline_cols()
    # `lnk` = sanitização derivada (§3.4.18): chave lida só por despriorizados não é
    # pendência. T_IN é consultada sem alias aqui.
    eff_aing = _aingerir(lnk=_san_derivada_sql("chave_canonica"))
    # universo por vínculo (predicado único — ver _ch_vinculo_ativo): escopo_indi é
    # superconjunto (recompute não olha links); o IN estreita p/ quem tem vínculo ativo.
    sub_esc = _ch_vinculo_ativo("e.escopo_indi = true")
    # item 1 (EGPs no escopo) vem da CLASSE gravada na linha de base congelada, não de um
    # count vivo em sas_escopo (régua de 29/09/2026): o denominador exibido — base,
    # dependências e ex-dependências — é a decomposição da lista, e ela não se mexe porque
    # o escopo cresceu, encolheu ou foi dedupado. item 2 (EGPs analisados) continua VIVO:
    # é "quantos dos que contam já estão no grafo", um numerador.
    _dec = linha_base.decomposicao(_linha_base())
    item1 = _dec["base"]
    item2 = int(run_sql(f"SELECT count(*) AS n FROM {T_ND} WHERE escopo_indi = true "
                        f"AND {_sql_na_linha_base('projeto')}")[0]["n"])
    # Os inputs que SÓ os extras leem saem dos grupos Escopo/Dependências e ganham grupo
    # PRÓPRIO (revisão da §3.4.13 pela gestão em 29/09/2026 — antes era "tudo junto").
    # Os TRÊS grupos particionam o Total de Inputs: o total não muda, a leitura muda.
    # Chave compartilhada com a linha de base NÃO entra aqui — ela pertence aos dois e
    # contaria duas vezes; quem responde "o que a versão nova consome" é o `de_extra` da
    # aba Inputs, que é outra pergunta. Ver _chaves_por_extra.
    _de_ex, _de_ct = _chaves_por_extra()
    so_ex = _de_ex - _de_ct
    if FAMILIAS_ON:
        # unidade = família (ADR 0002). Conta do MESMO dataset que a aba Inputs serve,
        # para card e tabela nunca divergirem — ver _dataset_escopo.
        _ri = _universo_contagem(_dataset_escopo("indi", []))
        _ri_sem_ex = [r for r in _ri if not r.get("so_de_extra")]
        item3 = len(_ri_sem_ex)
        # item4 NÃO sai daqui: é atribuído no bloco do `_rd`, abaixo. A família de safras
        # tem estado dependente do RECORTE (ela agrega só as safras em vista), e contar a
        # pendência no dataset do escopo perdia 7 unidades do total — ver lá.
        item4 = 0
    else:
        nex = (f" AND chave_canonica NOT IN ({', '.join(sql_lit(k) for k in sorted(so_ex))})"
               if so_ex else "")
        m = run_sql(f"SELECT count(*) AS tot, count_if({eff_aing}) AS aing "
                    f"FROM {T_IN} WHERE escopo_indi = true AND chave_canonica IN {sub_esc}"
                    f"{nex}")[0]
        item3, item4 = int(m["tot"]), int(m["aing"])

    # grafo: dependências transitivas FORA do escopo Indicium. Reusa o mesmo fecho
    # upstream de /api/egp-readiness?scope=indi_deps (_transitive_upstream) p/ não divergir.
    # `deps`, `indi_chaves` e `aing_chaves` só servem ao ramo SEM família (o `elif deps:` e
    # o bloco dos extras lá embaixo). Com FAMILIAS_SAFRA ligada — prod desde 17/09 — eram 3
    # statements seriais calculados e jogados fora a cada GET.
    deps = set()
    if not FAMILIAS_ON:
        edges = _edges_pruned()
        indi = {r["projeto"] for r in run_sql(f"SELECT projeto FROM {T_ND} WHERE escopo_indi = true")}
        dep_of = _dep_of_map(edges)
        level = _transitive_upstream(indi, dep_of, no_expand=_egps_fora_backlog())
        deps = {p for p, lv in level.items() if lv > 0}  # nível 0 = base (indi); >0 = dependências
    # O CONJUNTO `deps` segue vivo (é dele que saem os inputs das dependências, itens 6/7);
    # o número EXIBIDO vem da classe gravada na linha de base. Uma dependência que apareceu
    # depois do congelamento traz os inputs dela e conta entre os extras, não aqui.
    item5 = _dec["dependencia"]
    # ex-dependências: idem — a classe gravada. O critério "só ex com etapa real conta"
    # (2026-08-10) foi ABSORVIDO pelo congelamento: quem estava contabilizado no dia da
    # foto entrou na lista com a classe `ex_dependencia` e lá fica.
    deps_ex = _dec["ex_dependencia"]
    # extras (§3.1.2): contador PRÓPRIO, exibido AO LADO do total — nunca somado dentro.
    # MESMO conjunto do funil de extras do Resumo (_extras_no_recorte).
    extras_n = len(_extras_no_recorte())

    # 6/7: inputs das deps, disjuntos dos inputs do escopo (sem dupla contagem).
    # Sanitizado é status terminal mas continua no universo (regra do escopo).
    # indi_chaves usa o MESMO universo por vínculo dos itens 3/4: uma chave com todos os
    # vínculos de escopo quebrados mas com vínculo ativo numa dep conta nas deps (6/7),
    # não some em silêncio na subtração.
    indi_chaves = aing_chaves = set()
    if not FAMILIAS_ON:
        indi_chaves = {r["chave_canonica"] for r in run_sql(
            f"SELECT chave_canonica FROM {T_IN} WHERE escopo_indi = true "
            f"AND chave_canonica IN {sub_esc}")}
        aing_chaves = {r["chave_canonica"] for r in run_sql(f"SELECT chave_canonica FROM {T_IN} WHERE {eff_aing}")}
    item6 = item7 = item8 = item9 = 0
    deps_chaves = set()
    if FAMILIAS_ON:
        # "inputs das deps" = unidades do frontier que NÃO estão no escopo (chave de
        # família é a mesma string nos dois datasets, então a subtração não dupla-conta).
        # `_kin` sai do _ri INTEIRO (não do _ri_sem_ex): a unidade só-de-extra que já está
        # no escopo tem de sair dos DOIS grupos e contar uma vez só, no grupo dos extras.
        _rd = _universo_contagem(_dataset_escopo("indi_deps", []))
        _kin = {r.get("chave_canonica") for r in _ri}
        _novos = [r for r in _rd
                  if r.get("chave_canonica") not in _kin and not r.get("so_de_extra")]
        item6 = len(_novos)
        item7 = sum(1 for r in _novos if py_aingerir(r))
        # A PENDÊNCIA de todos os três grupos é contada AQUI, sobre `_rd`, porque a unidade
        # "família de safras" tem estado dependente do recorte: ela agrega só as safras em
        # vista. `MOVTO.BASILEIA` tem 9 das 23 safras no escopo, todas modernizadas — e 22
        # das 23 no recorte ampliado, com safras "A Receber". Contando a do escopo pelo
        # dataset do escopo, 7 famílias assim saíam como resolvidas e o Total dizia 386
        # onde a tabela "Inputs por origem (+deps)" e o funil de ingestão diziam 393.
        # Defeito ANTERIOR à separação de 29/09 (item4 + item7 sempre foi a mesma soma);
        # exigir que as três parcelas fechassem foi o que o revelou.
        # O CONJUNTO de cada grupo não muda — quem muda de lado é só a pendência.
        _kin_sem_ex = {r.get("chave_canonica") for r in _ri_sem_ex}
        item4 = sum(1 for r in _rd
                    if r.get("chave_canonica") in _kin_sem_ex and py_aingerir(r))
        # itens 8/9: o grupo próprio. Sai do dataset do FRONTIER, que é o único que enxerga
        # todos os extras (o do escopo Indicium só pega a casca, que nasce escopo_indi=true).
        _rx = [r for r in _rd if r.get("so_de_extra")]
        item8 = len(_rx)
        item9 = sum(1 for r in _rx if py_aingerir(r))
    elif deps:
        # Universo = o FRONTIER inteiro, não o conjunto `deps`. `deps` é só o fecho
        # transitivo; sucessor, casca e novo entram no recorte POR REGRA e a chave
        # EXCLUSIVA de um deles não está nem em `indi_chaves` nem em `deps_chaves` — ela
        # simplesmente sumia do Total. Defeito ANTERIOR à separação de 29/09 (medido: 27
        # chaves a menos que `origem_deps` no schema dos atualizados), que a separação só
        # tornou visível ao exigir que as três parcelas fechassem. Com FAMILIAS_SAFRA
        # ligada (prod desde 17/09) este ramo não roda; o outro sai de `_dataset_escopo`,
        # que já é o frontier.
        try:
            _universo = _frontier_egps("indi_deps", [])[0] or deps
        except HTTPException:
            _universo = deps
        inlist = ", ".join(sql_lit(p) for p in _universo)
        deps_chaves = {r["chave_canonica"] for r in run_sql(
            f"SELECT chave_canonica FROM {_ch_vinculo_ativo(f'e.projeto IN ({inlist})')} s")}
        # sanit_chaves subtraction removed on develop: Sanitizado é status TERMINAL
        # mas segue no universo do escopo (PR #43). Vínculo quebrado, sim, sai — via LEFT JOIN.
        novo = deps_chaves - indi_chaves - so_ex
        item6 = len(novo)
        item7 = len(novo & aing_chaves)
    if not FAMILIAS_ON and so_ex:
        # `deps_chaves` agora é o frontier, então isto é `so_ex` inteiro — a interseção
        # fica como guarda de que nenhuma chave de extra escapou do universo.
        _x = (indi_chaves | deps_chaves) & so_ex
        item8, item9 = len(_x), len(_x & aing_chaves)

    return {
        "egps_escopo": item1, "egps_analisados": item2,
        "inputs_escopo": item3, "inputs_a_ingerir": item4,
        "deps": item5, "deps_ex": deps_ex,
        "inputs_deps": item6, "inputs_deps_a_ingerir": item7,
        "extras": extras_n,
        # grupo próprio dos extras na Visão geral (29/09/2026), espelho dos itens 6/7 das
        # dependências: só o que NENHUM EGP contável lê — ver so_ex acima.
        "inputs_extras": item8, "inputs_extras_a_ingerir": item9,
        # O TOTAL É A LISTA, não uma soma de contagens vivas (29/09/2026). Bate com
        # item1+item5+deps_ex por construção — os três vêm da mesma decomposição —, mas
        # quem manda é o tamanho da lista: se um dia a decomposição divergir, é ela que
        # está errada, não o total.
        "total_egps": linha_base.total(_linha_base()),
        # o Total NÃO muda com a separação: os três grupos o particionam (a decisão de
        # 29/09/2026 foi de LEITURA, não de denominador — input de extra segue trabalho
        # real, §3.4.13). Se um dia a soma não fechar, o erro está na partição.
        "total_inputs": item3 + item6 + item8,
        "total_nao_modernizados": item4 + item7 + item9,
    }


@app.get("/api/funis")
def funis():
    """Funis da landing em DUAS visoes: escopo Indicium (migracao/ingestao) e
    Indicium + dependencias transitivas, sem dupla contagem (migracao_deps/ingestao_deps).
    2 de projeto (coorte = EGPs com etapa definida em sas_egp_pipeline) + 1 de ingestao
    (derivado da etapa/status efetivos do input). Leitura viva."""
    _ensure_escopo_ativo()
    _ensure_link_tables()
    _ensure_input_pipeline_cols()
    try:
        # pipe-etapa-status: real — leitura crua da tabela; as duas visões dela (a exibida
        # e a gravada) saem daqui, logo abaixo.
        pipe_real = run_sql(f"SELECT projeto, etapa_migracao, status_migracao FROM {T_PIPE}")
    except HTTPException:
        pipe_real = []  # tabela ainda nao existe (antes do 1o PATCH/publish)
    # DERIVADO: as BARRAS do funil mostram andamento do trabalho, e a régua fechada com a
    # gestão diz que "a etapa corre junto com o EGP atualizado — isso será visto nas
    # tabelas de resumo dos funis atuais". Sem isto, o mesmo antecessor aparece numa etapa
    # na aba EGPs (que já deriva, via vinculos.anexa_vinculo) e noutra aqui.
    # `Desatualizado` não é posição de trabalho e não entra em BANDS; quem decide se o
    # antecessor conta como migrado é `_contagem`, logo abaixo.
    # pipe-etapa-status: derivado — entra cru e sai exibido.
    _exib = vinculos.mapa_exibido(
        {r.get("projeto"): (r.get("etapa_migracao"), r.get("status_migracao")) for r in pipe_real},
        _vinculos_por_antecessor())
    # pipe-etapa-status: derivado — mesmas chaves da leitura crua (proj_funnel indexa por
    # nome de coluna), com etapa/status já exibidos.
    pipe = [{"projeto": r.get("projeto"),
             "etapa_migracao": _exib.get(r.get("projeto"), (None, None))[0],
             "status_migracao": _exib.get(r.get("projeto"), (None, None))[1]}
            for r in pipe_real]
    # CONTAGEM separada da EXIBIÇÃO: a barra mostra `Desatualizado` (é o que o antecessor
    # é), o headline conta o status do fim da cadeia de espelhamento. Ver
    # vinculos.mapa_contagem — sem isto o EGP aparece dentro da coluna "Migrado" e fora do
    # "X/Y" que está logo acima dela.
    # pipe-etapa-status: derivado — entra cru (é a cadeia inteira que precisa ser
    # resolvida, e o exibido já perdeu o status do sucessor) e sai como status de contagem.
    _contagem = vinculos.mapa_contagem(
        {r.get("projeto"): (r.get("etapa_migracao"), r.get("status_migracao")) for r in pipe_real},
        _vinculos_por_antecessor())
    # Denominador CONGELADO (29/09/2026): a classe `base` da linha de base, não um count
    # vivo em sas_escopo. As BARRAS seguem vivas — o que congelou foi quem entra na conta,
    # nunca em que etapa cada um está.
    _lb = _linha_base()
    _lb_classes = linha_base.por_classe(_lb)
    total_egp = len(_lb_classes["base"])

    # frontier = escopo Indicium U dependencias transitivas (MESMO fecho de /api/landing
    # e da aba Monitoramento). base = so escopo; frontier - base = dependencias.
    try:
        frontier, _base = _frontier_egps("indi_deps", [])
        # ex-dependências: com a régua congelada elas já ESTÃO na linha de base (classe
        # `ex_dependencia`), então o universo e o denominador do funil +deps saem da lista
        # — não há mais o que derivar aqui. `_ex_deps` continua vivo para a LISTA da aba
        # EGPs (badge/retenção), só não decide mais contagem.
    except HTTPException:
        frontier = set()  # grafo ainda nao publicado: visão +deps sem linhas de recorte
    # universo do 3º funil: MESMO conjunto do contador "(+N extra)" da Visão geral
    # (_extras_no_recorte) — card e funil vivem na mesma tela e não podem discordar.
    extras_recorte = _extras_no_recorte()

    def proj_funnel(stages, et_col, st_col, universe=None, total=None):
        # universe=None -> sem filtro (só fallback de grafo ausente); NUNCA use p/ visao de escopo:
        # universe=set  -> so EGPs do recorte (frontier); denominador = len(universe).
        idx = {s: i for i, s in enumerate(stages)}
        items, migr = [], 0
        phantom = {s: 0 for s in PHANTOM_ETAPAS_MIGRACAO}
        for r in pipe:
            if universe is not None and r.get("projeto") not in universe:
                continue  # fora do recorte (frontier)
            et = r.get(et_col)
            if not et:
                continue
            if et in PHANTOM_ETAPAS_MIGRACAO:
                phantom[et] += 1  # fora do coorte; exibido só em top_stats
                continue
            if et not in idx:
                continue  # etapa desconhecida -> fora do coorte
            stt = r.get(st_col) or "A Iniciar"
            items.append((idx[et], stt, 1))
            # migrados (headline) = status terminais: Migrado + Despriorizado e Contabilizado
            # (= soma das bandas coloridas do funil). Status-based (nao "chegou na ultima etapa"), por pedido.
            # O status lido aqui é o de CONTAGEM, não o exibido: o antecessor espelhado
            # herda o terminal do fim da cadeia em vez de `Desatualizado` (mapa_contagem).
            stc = _contagem.get(r.get("projeto"), stt) or "A Iniciar"
            if stc in BANDS or stc == "Migrado":
                migr += 1
        return {"stages": stages, "bars": _funnel_bars(stages, items),
                "coorte": len(items), "migrados": migr,
                "total": total if total is not None else total_egp,
                # Etapas fantasma: fora do funil natural (skip de partes do funil de
                # migração). Mostradas só no topo — não inflam coorte/migrados.
                "top_stats": [{"label": s, "value": phantom[s], "tone": tone}
                              for s, tone in PHANTOM_ETAPAS_MIGRACAO.items()]}

    # ingestao: funil real de 8 etapas (PIPELINE_INPUT) x 4 status (STATUS_INPUT), MESMO
    # modelo do funil de migração acima (etapa=posição, status=banda por segmento).
    # Coorte = TODOS os inputs (toda etapa efetiva conta, incl. "A Receber" — ao contrário
    # do funil antigo de 3 estágios, que escondia "A receber" fora do coorte).
    eff_et = _eff_etapa()
    # status efetivo COM a sanitização derivada (§3.4.18): a chave lida só por
    # despriorizados entra no funil como Sanitizado — sai do coorte e vira contador, o
    # mesmo lugar onde as 202 sanitizações feitas na mão já estão.
    eff_st = (f"CASE WHEN {_san_derivada_sql('chave_canonica')} THEN "
              f"{sql_lit(sanitizacao.STATUS_SANITIZADO)} ELSE {_eff_status_input()} END")

    def ingest_funnel(rows):
        """rows: [{et, st, n}] (etapa/status EFETIVOS já agregados). Sanitizado = removido
        do escopo (mesma regra app-wide de _sanitizado() — README §Sanitizado): NÃO conta
        no funil (bars/coorte/total/migrados), só aparece como contador informativo no
        topo — não é banda, ao contrário do "Despriorizado e Contabilizado" dos EGPs.

        Autoprodutor (status irmão de Sanitizado — ver STATUS_INPUT) tem tratamento
        OPOSTO: conta como RESOLVIDO, não como excluído. Aqui isso é feito tratando a
        etapa efetiva como "Modernizado" (independente da etapa real) antes do resto da
        lógica — cai no branch `done` normal e aparece como segmento próprio dentro da
        coluna "Modernizado" (cor distinta via SEG no front), coerente com _modern().

        KPIs do topo particionam o UNIVERSO INTEIRO de inputs (sem dupla contagem):
        A Receber + Em Processamento + Modernizado = coorte; + Sanitizado = total de
        inputs. "Em Processamento" agrega todas as etapas intermediárias (Recebido ..
        Aplicação de Grant) — pré-working + ingestão, num único número (pedido 2026-08).

        As BARRAS (gráfico) excluem só a COLUNA "A Receber" (já é KPI; sozinha só teria
        segmento A Iniciar, sem info própria) — pedido 2026-08. O segmento "A Iniciar"
        CONTINUA aparecendo dentro das barras restantes: é o que faz toda barra somar o
        MESMO total (= itens que já passaram de "A Receber", constante em todas as
        colunas — sem isso as colunas encolhiam da esquerda pra direita e paravam de
        bater 100%). Ele representa, em cada coluna, quem ainda não chegou naquela etapa
        — ex.: 336 já passaram de "Recebido" mas só 321 chegaram em "Modernizado"; a
        diferença (15) aparece como "A Iniciar" na coluna Modernizado, não some."""
        idx = {s: i for i, s in enumerate(PIPELINE_INPUT)}
        stages_grafico = PIPELINE_INPUT[1:]   # sem "A Receber" (vira só KPI)
        idx_grafico = {s: i for i, s in enumerate(stages_grafico)}
        items, coorte, done, n_saniz, n_arec, n_proc = [], 0, 0, 0, 0, 0
        for r in rows:
            n = int(r["n"])
            st = r.get("st") or "A Iniciar"
            if st == "Sanitizado":
                n_saniz += n
                continue
            et = r.get("et")
            if st == "Autoprodutor":
                et = "Modernizado"  # conta como resolvido — ver docstring acima; o segmento
                                     # "Autoprodutor" na barra (SEG) mostra o detalhamento
            if et not in idx:
                continue  # etapa desconhecida/vazia -> fora do coorte (não deveria ocorrer)
            coorte += n
            if et == "Modernizado":
                done += n
            elif et == "A Receber":
                n_arec += n
                continue  # fora do gráfico (só conta no KPI) — não entra nas barras
            else:
                n_proc += n
            items.append((idx_grafico[et], st, n))
        bars = _funnel_bars(stages_grafico, items)
        # "coorte" normaliza a altura das barras no front (h = seg/coorte) e por isso tem
        # que bater com a soma de QUALQUER barra — que é sempre a mesma constante (ver
        # docstring acima), igual à soma dos pesos em `items`. Como "A Receber" é excluído
        # de `items` (vira só KPI, não entra nas barras), ele também tem que sair daqui;
        # do contrário as barras nunca preenchem 100% (ficam limitadas a (coorte-n_arec)/coorte).
        # "total" continua sendo o universo inteiro (incl. "A Receber"), pro KPI migrados/total.
        return {"stages": stages_grafico, "bars": bars,
                "coorte": coorte - n_arec, "migrados": done, "total": coorte,
                "top_stats": [
                    {"label": "A Receber", "value": n_arec, "tone": "mut"},
                    {"label": "Em Processamento", "value": n_proc, "tone": "wip"},
                    {"label": "Modernizado", "value": done, "tone": "ok"},
                    {"label": "Sanitizado", "value": n_saniz, "tone": "mut"},
                ]}

    # FORA dos DOIS funis de projeto: o que SÓ os extras leem (`so_de_extra`). Eles têm
    # funil PRÓPRIO logo abaixo, e contar o inventário deles aqui fazia o mesmo input
    # aparecer duas vezes no mesmo Resumo. É a régua que `/api/funil-ingestao-mes`, a
    # tabela de origem e o item 3 da landing (`_ri_sem_ex`) já usavam: o que o extra lê EM
    # COMUM com a linha de base fica na dela; o exclusivo fica na dos extras.
    #
    # Vale para os dois porque os dois são PARES de funis de migração que já contam sem
    # extra — `migracao` conta os 168 da classe base, `migracao_deps` os 193 da linha de
    # base. Medido em prod 05/10/2026: escopo 1.166 -> 1.161 (= item 3 da Visão geral) e
    # +deps coorte 703 -> 630 (= o funil por mês, que já aplicava a régua).
    #
    # Consequência aceita, a mesma do funil por mês: nenhum dos dois bate sozinho com o
    # card "Total de Inputs" da Visão geral, que soma os três baldes — quem bate com o
    # card é `ingestao_deps` + `ingestao_extras`.
    # Com a flag ligada o filtro é por linha (`so_de_extra` já vem no dataset); desligada,
    # é o mesmo recorte por chave de safra que a landing monta.
    _so_ex = set()
    if not FAMILIAS_ON:
        _lidas_por_extra, _lidas_por_contavel = _chaves_por_extra()
        _so_ex = _lidas_por_extra - _lidas_por_contavel
    _nex = (f" AND chave_canonica NOT IN ({', '.join(sql_lit(k) for k in sorted(_so_ex))})"
            if _so_ex else "")

    # universo por vínculo (predicado único — _ch_vinculo_ativo), igual landing/resumo.
    if FAMILIAS_ON:
        rows_indi = _ingest_rows_py([r for r in _dataset_escopo("indi", [])
                                     if not r.get("so_de_extra")])
    else:
        rows_indi = run_sql(f"SELECT {eff_et} AS et, {eff_st} AS st, count(*) AS n FROM {T_IN} "
                            f"WHERE escopo_indi = true AND chave_canonica IN "
                            f"{_ch_vinculo_ativo('e.escopo_indi = true')}{_nex} "
                            f"GROUP BY {eff_et}, {eff_st}")
    # +deps: inputs distintos de TODOS os EGPs do frontier (escopo U deps), sem dupla
    # contagem (T_IN e 1 linha por chave_canonica). Mesma base dos itens 6/7 da landing.
    if FAMILIAS_ON:
        rows_deps = (_ingest_rows_py([r for r in _dataset_escopo("indi_deps", [])
                                      if not r.get("so_de_extra")])
                     if frontier else rows_indi)
    elif frontier:
        inlist = ", ".join(sql_lit(p) for p in frontier)
        rows_deps = run_sql(
            f"SELECT {eff_et} AS et, {eff_st} AS st, count(*) AS n FROM {T_IN} "
            f"WHERE chave_canonica IN {_ch_vinculo_ativo(f'e.projeto IN ({inlist})')}{_nex} "
            f"GROUP BY {eff_et}, {eff_st}")
    else:
        rows_deps = rows_indi  # sem frontier: espelha a visao de escopo

    # extras: o inventário que entrou POR CAUSA das versões novas — as chaves que nenhum
    # EGP contável lê (`so_de_extra`). Mesmo conjunto do card "Inputs dos extras" e da
    # tabela de origem dos extras, para as três superfícies nunca divergirem. O que um
    # extra lê em comum com a linha de base pertence ao funil dela: contar aqui somaria a
    # mesma chave em dois funis.
    if FAMILIAS_ON:
        rows_extras = _ingest_rows_py(
            [r for r in _dataset_escopo("indi_deps", []) if r.get("so_de_extra")])
    else:
        _de_ex, _de_ct = _chaves_por_extra()
        _so_ex = _de_ex - _de_ct
        rows_extras = run_sql(
            f"SELECT {eff_et} AS et, {eff_st} AS st, count(*) AS n FROM {T_IN} "
            f"WHERE chave_canonica IN ({', '.join(sql_lit(k) for k in sorted(_so_ex))}) "
            f"GROUP BY {eff_et}, {eff_st}") if _so_ex else []

    return {
        # universe SEM os extras (§3.1.2): os funis do Resumo não mudam de régua — nada é
        # somado neles porque uma casca/versão nova entrou no corpus.
        # pipe-etapa-status: derivado — nomes de coluna de `pipe`, que já vem exibido.
        # UNIVERSO = a linha de base congelada (classe `base` aqui, a lista inteira no
        # +deps). "Congelado nos dois lados": quem saiu do escopo continua no denominador e
        # continua mostrando a etapa dele na barra — sumir da barra e ficar no denominador
        # faria o funil parecer ter regredido sem ninguém ter desfeito trabalho.
        "migracao": proj_funnel(PIPELINE_PROJETO["migracao"], "etapa_migracao", "status_migracao",
                                universe=_lb_classes["base"]),
        "ingestao": ingest_funnel(rows_indi),
        # pipe-etapa-status: derivado — idem.
        "migracao_deps": proj_funnel(PIPELINE_PROJETO["migracao"], "etapa_migracao", "status_migracao",
                                     universe=linha_base.projetos(_lb),
                                     total=linha_base.total(_lb)),
        "ingestao_deps": ingest_funnel(rows_deps),
        # 3º funil (§3.1.3): os EXTRAS — o que entrou no corpus depois da linha de base
        # (sucessores, com ou sem etapa, e cascas). É um RECORTE, não outra entidade:
        # mesma proj_funnel, mesmas 9 etapas, só o universo muda. Denominador = o próprio
        # conjunto (não total_egp, que é a base): o funil dos extras mede os extras.
        # Extra sem etapa fica no denominador e fora do coorte — o estado honesto.
        # A linha de base NÃO vale como universo aqui: extra é, por definição, quem está
        # fora dela — este funil é o único cujo universo é o conjunto vivo.
        # pipe-etapa-status: derivado — idem aos dois acima (nomes de coluna de `pipe`,
        # que já vem exibido): o funil mostra ANDAMENTO, não o estado gravado.
        "migracao_extras": proj_funnel(PIPELINE_PROJETO["migracao"], "etapa_migracao",
                                       "status_migracao", universe=extras_recorte,
                                       total=len(extras_recorte)),
        # o par de ingestão do funil acima. Mesma `ingest_funnel` das outras duas visões —
        # muda só o universo, como no de migração.
        "ingestao_extras": ingest_funnel(rows_extras),
    }


def _mes_do_plano():
    """{projeto: mês} do plano CONGELADO de priorização (payload cru).

    Cru de propósito: o overlay de `_read_prio_snapshot` traria etapa/status/bloqueio e um
    `_blocking()` inteiro, e aqui só o mês interessa. Sem snapshot -> mapa vazio, e quem
    chama cai todo mundo em "sem mês", que é o estado honesto.

    PODADO pela linha de base, pela MESMA razão e com o MESMO critério de
    `_poda_fora_da_linha_base`: o snapshot foi salvo quando 13 EGPs que já saíram do escopo
    ainda estavam nele. Sem esta poda o app ficava com duas réguas para "quem está no
    plano" — migração contava 193 (podado) e ingestão contava 206 (cru) —, e um input
    consumido só por um daqueles 13 ganhava mês no funil de ingestão enquanto o EGP dono
    dele já não aparecia no de migração."""
    try:
        snap = run_sql(f"SELECT payload FROM {T_PRIO_SNAP} WHERE id = 'current'")
    except HTTPException as e:
        if not _objeto_ausente(e):
            raise
        return {}
    if not snap:
        return {}
    try:
        payload = json.loads(snap[0].get("payload") or "")
    except (TypeError, ValueError):
        return {}
    lb = set(linha_base.projetos(_linha_base()))
    out = {}
    for m in (payload.get("meses") or []):
        for e in (m.get("egps") or []):
            pj = e.get("projeto")
            if pj and pj not in out and (not lb or pj in lb):
                out[pj] = m.get("mes")
    return out


def _mes_dos_extras():
    """{extra: mês} — o mês do ANTECESSOR (decisão da gestão, 30/09/2026).

    O extra não está no plano congelado: ele chegou depois. Mas o TRABALHO dele é o mesmo
    trabalho do antecessor continuando noutro arquivo (§3.3.11), então o mês que vale é o
    de quem ele substitui — senão os extras cairiam todos em "sem mês" e o funil por mês
    não diria nada.

    SOBE A CADEIA: numa cadeia v1 → v2 → v3, o v3 herda o mês do v1, porque é o v1 que está
    no plano (o v2 também é extra e também não está). Mesmo princípio de
    `cadeia_de_sucessores` e `fim_do_espelho` — quem para no 1º salto erra.

    Vários antecessores (unificador) -> o MENOR mês, a mesma régua "conta no 1º mês" que o
    plano já usa para input lido por mais de um EGP. Extra sem antecessor no plano (casca,
    novo) cai no próprio mês se tiver, senão em "sem mês"."""
    extras = _extras_no_recorte()
    if not extras:
        return {}
    plano = _mes_do_plano()
    if not plano:
        return {}
    antes = {}
    for ante, v in _vinculos_por_antecessor().items():
        if v.get("sucessor"):
            antes.setdefault(v["sucessor"], []).append(ante)

    def sobe(projeto, visto):
        """Menor mês encontrado subindo dos antecessores; None se ninguém está no plano."""
        melhor = plano.get(projeto)
        for a in antes.get(projeto, ()):
            if a in visto:
                continue                      # ciclo: o app não deveria permitir, não trava
            visto.add(a)
            m = sobe(a, visto)
            if m is not None and (melhor is None or m < melhor):
                melhor = m
        return melhor

    return {p: m for p in extras
            for m in (sobe(p, {p}),) if m is not None}


@app.get("/api/funil-mes-extras")
def funil_mes_extras():
    """Funil de MIGRAÇÃO por mês, só dos extras — mesmo shape do `meses` de
    /api/priorizacao, para a tabela do Resumo ser o mesmo componente.

    O mês vem do ANTECESSOR (`_mes_dos_extras`); etapa/status vêm EXIBIDOS
    (`_pipe_exibido`), como em toda superfície de andamento."""
    extras = _extras_no_recorte()
    if not extras:
        return {"meses": [], "n_egps": 0, "sem_mes": 0}
    mes_of, pipe = _mes_dos_extras(), _pipe_exibido()
    por_mes, sem_mes = {}, []
    for p in sorted(extras):
        m = mes_of.get(p)
        et, st = pipe.get(p, (None, None))
        reg = {"projeto": p, "etapa": et, "status": st}
        # Sem antecessor no plano não há mês a herdar: casca (ela É o antecessor) e EGP
        # novo. Eles vão numa linha própria em vez de sumir — a tabela tem de fechar com
        # o card de extras, senão o leitor vê dois totais e não sabe qual vale.
        (por_mes.setdefault(m, []) if m is not None else sem_mes).append(reg)
    return {"meses": [{"mes": m, "egps": por_mes[m]} for m in sorted(por_mes)],
            "n_egps": len(extras), "sem_mes": len(sem_mes), "sem_mes_egps": sem_mes}


@app.get("/api/funil-ingestao-mes")
def funil_ingestao_mes():
    """Funil de INGESTÃO cruzado com o mês do plano de priorização.

    UNIVERSO = o mesmo de /api/funis[ingestao_deps] e do card "Total de Inputs" da Visão
    geral MENOS os exclusivos de extra (ver abaixo): inputs com vínculo ativo nos EGPs do
    frontier VIVO (escopo Indicium ∪ dependências transitivas). NÃO é o universo do plano
    congelado — esse fica em
    _prio_live_input_stats (contador de inputs por mês da aba Priorização) e diverge de
    propósito: o plano é um snapshot, o frontier é vivo.

    FORA: o que SÓ os extras leem (`so_de_extra`). Medido em 01/10/2026, a linha "sem mês"
    deste funil era 100% isso — os MESMOS inputs que o funil de ingestão dos extras já
    mostra, aparecendo duas vezes no mesmo Resumo. É a régua que a tabela de origem já
    usava ("o que o extra lê em comum com a linha de base fica na dela; o exclusivo fica na
    dos extras"), agora também aqui. Consequência aceita: este funil deixa de bater com o
    card "Total de Inputs" da Visão geral, que conta os três baldes.

    MÊS de cada input = MENOR mês entre os EGPs do plano que o consomem E QUE ESTÃO NO
    FRONTIER (mesma regra "conta no 1º mês" do plano, só com consumidores vivos). Input do
    frontier que nenhum desses consome cai em `sem_mes` — o frontier anda, o plano fica
    congelado; sem snapshot, tudo cai lá.

    Por que só os vivos (decisão da gestão, 09/10/2026): o plano é podado pela linha de
    base, não pelo frontier, então uma ex-dependência que saiu do recorte continua com mês
    no plano. Contando-a, ela puxava para M1 inputs que nenhum EGP vivo de M1 lê — e o
    funil discordava da aba Inputs, que monta o mês a partir de `/api/inputs-egps`, só
    com pares do frontier. Medido: 22 x 20 em M1/A Receber, os 2 de diferença lidos só
    pelo `Cobranças__CRIAR_MARCACAO_SEGMENTACAO_reap_1` (ex-dependência, M1 no plano, fora
    do frontier), que caem em M4 e M5 pelos consumidores vivos.

    CROSSTAB: cada input numa única célula ({etapa: {status: n}}), ao contrário das barras
    de /api/funis, que são cumulativas e ainda tiram "A Receber" (lá vira KPI). Sanitizado
    sai do funil (regra app-wide de _sanitizado()) e vira contador por mês."""
    _ensure_link_tables()
    _ensure_input_pipeline_cols()
    vazio = {"meses": [], "sem_mes": {"ingestao": {}, "sanitizados": 0, "total": 0},
             "total": 0, "sanitizados": 0, "n_egps": 0}
    try:
        frontier, _base = _frontier_egps("indi_deps", [])
    except HTTPException:
        return vazio                      # grafo ainda não publicado
    if not frontier:
        return vazio
    eff_et = _eff_etapa()
    # mesma sanitização derivada do /api/funis (§3.4.18) — os dois funis de ingestão
    # contam o mesmo universo, então a régua tem que ser a mesma string.
    eff_st = (f"CASE WHEN {_san_derivada_sql('chave_canonica')} THEN "
              f"{sql_lit(sanitizacao.STATUS_SANITIZADO)} ELSE {_eff_status_input()} END")
    inlist = ", ".join(sql_lit(p) for p in frontier)
    if FAMILIAS_ON:
        # unidade = família; `membros` guarda as safras, porque o mês vem do plano por EGP
        # e o EGP consome SAFRAS — o mês da família é o MENOR entre os das suas safras
        # (mesma regra "conta no 1º mês" aplicada um nível acima).
        rows = [{"chave": r.get("chave_canonica"), "et": py_eff_etapa(r),
                 "st": py_eff_status(r),
                 "membros": r.get("membros") or [r.get("chave_canonica")]}
                for r in _universo_contagem(_dataset_escopo("indi_deps", []))
                if not r.get("so_de_extra")]
    else:
        rows = run_sql(f"SELECT chave_canonica AS chave, {eff_et} AS et, {eff_st} AS st "
                       f"FROM {T_IN} WHERE chave_canonica IN "
                       f"{_ch_vinculo_ativo(f'e.projeto IN ({inlist})')}")

    # só consumidores VIVOS dão mês (ver docstring): a mesma régua da aba Inputs
    mes_of = {p: m for p, m in _mes_do_plano().items() if p in frontier}

    return _crosstab_ingestao_mes(rows, mes_of, len(_contaveis(frontier)))


def _crosstab_ingestao_mes(rows, mes_of, n_egps):
    """CROSSTAB mês × etapa × status dos inputs. Compartilhada pelos DOIS funis de ingestão
    por mês (o do plano e o dos extras) para que a régua seja a mesma string — a diferença
    entre eles é só QUAIS linhas entram e de ONDE vem o mês.

    MÊS do input = MENOR mês entre os EGPs que o consomem (regra "conta no 1º mês"); para a
    família, o menor entre as safras. Input que ninguém com mês consome cai em `sem_mes`."""
    ch_mes = {}
    if mes_of:
        pin = ", ".join(sql_lit(p) for p in mes_of)
        pares = run_sql(
            f"SELECT e.projeto AS projeto, e.chave_canonica AS chave FROM {T_EGP} e "
            f"LEFT JOIN {T_LINK} l ON l.projeto = e.projeto AND l.chave_canonica = e.chave_canonica "
            f"WHERE e.projeto IN ({pin}) AND NOT coalesce(l.link_broken, false)")
        for r in pares:
            ch, mm = r.get("chave"), mes_of.get(r.get("projeto"))
            if ch and mm is not None and mm < ch_mes.get(ch, float("inf")):
                ch_mes[ch] = mm

    buckets = {}
    for r in rows:
        if "membros" in r:
            _ms = [ch_mes[m] for m in r["membros"] if m in ch_mes]
            _mes = min(_ms) if _ms else None
        else:
            _mes = ch_mes.get(r.get("chave"))
        b = buckets.setdefault(_mes, {"ingestao": {}, "sanitizados": 0, "total": 0})
        st = r.get("st") or "A Iniciar"
        if st == "Sanitizado":
            b["sanitizados"] += 1
            continue
        et = r.get("et")
        if et not in PIPELINE_INPUT:
            continue                      # etapa desconhecida/vazia: fora do funil
        por_st = b["ingestao"].setdefault(et, {})
        por_st[st] = por_st.get(st, 0) + 1
        b["total"] += 1
    # filtra o bucket None ANTES do sorted: o filtro no for roda depois da ordenação,
    # e input sem mês no plano derrubava o endpoint (None < int, 500 em prod 2026-09-14)
    meses = [dict(mes=k, **v)
             for k, v in sorted(i for i in buckets.items() if i[0] is not None)]
    sem_mes = buckets.get(None) or {"ingestao": {}, "sanitizados": 0, "total": 0}
    return {"meses": meses, "sem_mes": sem_mes,
            "total": sum(m["total"] for m in meses) + sem_mes["total"],
            "sanitizados": sum(m["sanitizados"] for m in meses) + sem_mes["sanitizados"],
            "n_egps": n_egps}


@app.get("/api/funil-ingestao-mes-extras")
def funil_ingestao_mes_extras():
    """Funil de INGESTÃO por mês, só dos extras — irmão de /api/funil-mes-extras.

    UNIVERSO = os inputs que NENHUM EGP contável lê (`so_de_extra`), o mesmo do card
    "Inputs dos extras", da tabela de origem dos extras e do funil de ingestão dos extras.
    O compartilhado com a linha de base pertence ao funil dela.

    MÊS = o do ANTECESSOR do extra que consome o input (`_mes_dos_extras`), pelo mesmo
    caminho do funil do plano: menor mês entre os consumidores."""
    _ensure_link_tables()
    _ensure_input_pipeline_cols()
    vazio = {"meses": [], "sem_mes": {"ingestao": {}, "sanitizados": 0, "total": 0},
             "total": 0, "sanitizados": 0, "n_egps": 0}
    extras = _extras_no_recorte()
    if not extras:
        return vazio
    try:
        rows = [{"chave": r.get("chave_canonica"), "et": py_eff_etapa(r),
                 "st": py_eff_status(r),
                 "membros": r.get("membros") or [r.get("chave_canonica")]}
                for r in _universo_contagem(_dataset_escopo("indi_deps", []))
                if r.get("so_de_extra")]
    except HTTPException:
        return vazio
    return _crosstab_ingestao_mes(rows, _mes_dos_extras(), len(extras))


@app.get("/api/indicium")
def indicium():
    """Lista Indicium (fonte DOR1) + validação de existência: recebido = projeto existe
    nos EGPs extraídos (sas_lineage_nodes); senão = não recebido."""
    _ensure_escopo_ativo()
    rows = run_sql(
        f"SELECT i.id, i.egp_dor1, i.area, i.status_extracao, i.projeto, i.origem, i.ativo, "
        f"n.projeto AS node_projeto, n.onda, n.ciclo_id, "
        f"(n.projeto IS NOT NULL) AS recebido "
        f"FROM {T_ESC} i LEFT JOIN {T_ND} n ON i.projeto = n.projeto AND i.projeto <> '' "
        f"ORDER BY recebido NULLS FIRST, i.area NULLS FIRST, i.egp_dor1 NULLS FIRST")
    return {"rows": rows}


class EscopoAdd(BaseModel):
    egp_dor1: str
    area: str | None = ""
    projeto: str | None = ""


def _esc_audit(acao, egp, projeto):
    run_sql(
        f"INSERT INTO {T_ESC_AUD} (id, acao, egp_dor1, projeto, ator, ts) VALUES "
        f"({sql_lit(uuid.uuid4().hex)}, {sql_lit(acao)}, {sql_lit(egp)}, {sql_lit(projeto)}, "
        f"{_ator()}, cast({AGORA} AS STRING))", want_rows=False)


_escopo_ativo_ok = False


def _ensure_escopo_ativo(exec_fn=None):
    """Garante a coluna `ativo` em sas_escopo (soft-deactivate de entradas do escopo).
    Coluna ausente/NULL = ativa (`ativo IS NOT false`). Idempotente (flag process-local)."""
    if dialeto.PG:  # no Postgres o schema vem das migrações (db/migrations), nunca do app
        return None
    global _escopo_ativo_ok
    exec_fn = exec_fn or run_sql
    if _escopo_ativo_ok:
        return
    try:
        exec_fn(f"SELECT ativo FROM {T_ESC} LIMIT 0")
    except (HTTPException, RuntimeError):  # RuntimeError: via exec_fn alternativo (sem OBO)
        exec_fn(f"ALTER TABLE {T_ESC} ADD COLUMNS (ativo BOOLEAN)", want_rows=False)
    _escopo_ativo_ok = True


_input_pipeline_cols_ok = False
_node_metric_cols_ok = False


def _ensure_node_metric_cols():
    """Garante em sas_lineage_nodes as colunas de LOC/intermediários que o publish novo
    escreve (loc, code_tasks_count, flags de outputs — develop 2026-08-28). Puramente
    aditivo (ALTER ADD COLUMNS, mesmo padrão de _ensure_input_pipeline_cols) — self-heal
    p/ schema publicado ANTES do publish novo: sem isso, /api/egp-readiness e /api/egp
    quebram com UNRESOLVED_COLUMN `loc` até alguém republicar. Valores ficam NULL (a UI
    mostra 0/—) até o próximo publish preencher."""
    if dialeto.PG:  # no Postgres o schema vem das migrações (db/migrations), nunca do app
        return None
    global _node_metric_cols_ok
    if _node_metric_cols_ok:
        return
    try:
        run_sql(f"SELECT loc FROM {T_ND} LIMIT 0")
    except (HTTPException, RuntimeError):
        run_sql(f"ALTER TABLE {T_ND} ADD COLUMNS (loc BIGINT, code_tasks_count BIGINT, "
                f"n_outputs_avaliados BIGINT, n_outputs_consumidos_por_outro_egp BIGINT, "
                f"pct_outputs_consumidos_por_outro_egp DOUBLE, n_egps_consumidores BIGINT, "
                f"n_exports_arquivos BIGINT, flag_output_100pct_egp BOOLEAN, "
                f"flag_algum_output_egp BOOLEAN, flag_sem_export_arquivo BOOLEAN, "
                f"flag_output_unico BOOLEAN, flag_hub_multiplos_consumidores BOOLEAN)",
                want_rows=False)
    _node_metric_cols_ok = True


def _ensure_input_pipeline_cols(exec_fn=None):
    """Garante as colunas `etapa`/`status` em sas_inputs_monitor (funil de ingestão
    dos inputs, ver PIPELINE_INPUT/STATUS_INPUT). Puramente aditivo (ALTER ADD COLUMNS,
    mesmo padrão de _ensure_escopo_ativo/_ensure_pipe_table) — seguro pra self-heal
    automático. O BACKFILL de dados legados (status_humano -> etapa/status) é
    DELIBERADAMENTE separado disto: roda como script manual único
    (scripts/migrate_input_status_split.py), nunca automático, porque é um mapeamento
    de negócio sobre milhares de linhas já editadas por analistas."""
    if dialeto.PG:  # no Postgres o schema vem das migrações (db/migrations), nunca do app
        return None
    global _input_pipeline_cols_ok
    exec_fn = exec_fn or run_sql
    if _input_pipeline_cols_ok:
        return
    try:
        exec_fn(f"SELECT etapa, status FROM {T_IN} LIMIT 0")
    except (HTTPException, RuntimeError):
        exec_fn(f"ALTER TABLE {T_IN} ADD COLUMNS (etapa STRING, status STRING)", want_rows=False)
    _input_pipeline_cols_ok = True


def recompute_escopo(exec_fn=None):
    """Re-deriva escopo_indi (nodes, egp_inputs, inputs_monitor, resumo) e o funil a
    partir de sas_escopo — propaga uma edição de escopo ao app TODO (Resumo/Monitoramento/
    EGPs/landing) na hora, sem republish. Fiel às definições do publish:
      • nodes/egp_inputs.escopo_indi  = projeto ∈ escopo
      • inputs_monitor.escopo_indi    = chave usada por ≥1 EGP do escopo (IN_CATS)
      • resumo.escopo_indi            = projetos do input ∩ escopo (todas categorias, via sas_resumo_proj)
      • resumo.area_principal         = 1 área/input pela área do EGP consumidor no FRONTIER
                                        (escopo ∪ deps); Cobrança>contagem>alfab. (_recompute_area_principal)
      • funil                         = por área, a partir de status_extracao do sas_escopo
    Statements idênticos ao bloco de recompute do publish_to_databricks.py — mantenha em sincronia.
    Roda como o usuário (OBO); requer MODIFY nas tabelas-núcleo (o owner tem)."""
    global _lineage_gen
    exec_fn = exec_fn or run_sql
    _ensure_escopo_ativo(exec_fn)
    esc = f"(SELECT projeto FROM {T_ESC} WHERE projeto <> '' AND ativo IS NOT false)"
    ch_egp = f"(SELECT DISTINCT chave_canonica FROM {T_EGP} WHERE escopo_indi = true)"
    ch_res = f"(SELECT DISTINCT chave_canonica FROM {T_RESP} WHERE projeto IN {esc})"
    for s in [
        f"UPDATE {T_ND}  SET escopo_indi = false",
        f"UPDATE {T_ND}  SET escopo_indi = true WHERE projeto IN {esc}",
        f"UPDATE {T_EGP} SET escopo_indi = false",
        f"UPDATE {T_EGP} SET escopo_indi = true WHERE projeto IN {esc}",
        f"UPDATE {T_IN}  SET escopo_indi = false",
        f"UPDATE {T_IN}  SET escopo_indi = true WHERE chave_canonica IN {ch_egp}",
        f"UPDATE {T_RES} SET escopo_indi = false",
        f"UPDATE {T_RES} SET escopo_indi = true WHERE chave_canonica IN {ch_res}",
        # self-heal: entrada adicionada antes do EGP existir no corpus fica 'faltante' p/ sempre;
        # se o projeto agora está no grafo, promove a 'exato' (senão o funil por área subconta).
        f"UPDATE {T_ESC} SET status_extracao = 'exato' WHERE ativo IS NOT false "
        f"AND status_extracao = 'faltante' AND projeto <> '' AND projeto IN (SELECT projeto FROM {T_ND})",
        # funil: DELETE+INSERT (não CREATE OR REPLACE) p/ ficar dentro de MODIFY — usuários
        # OBO sem privilégio CREATE no schema falhariam, deixando o funil defasado.
        f"DELETE FROM {T_FUN}",
        f"""INSERT INTO {T_FUN} (area, qtd_dor1, egps_enviados, egps_analisados)
  SELECT area, count(*),
    count_if(status_extracao <> 'faltante'),
    count_if(status_extracao IN ('exato','variante','confirmado_area','ingerido_extraido'))
  FROM {T_ESC} WHERE ativo IS NOT false AND {SQL_ESC_NAO_EXTRA} GROUP BY area""",
    ]:
        exec_fn(s, want_rows=False)
    # area_principal: 1 área/input LASTREADA no frontier (escopo ∪ dependências transitivas).
    # É lógica de grafo (frontier), então Python — não cabe no bloco SQL acima. Roda DEPOIS do
    # escopo_indi (usa o escopo_indi já re-derivado). Autoridade sobre o valor inicial do publish.
    _recompute_area_principal(exec_fn)
    # outputs: só se as tabelas já existem (criadas no 1º publish com outputs) — nunca pode
    # quebrar a edição de escopo. exec_fn=run_sql (OBO) lança HTTPException; um exec_fn sem OBO lança RuntimeError.
    try:
        exec_fn(f"SELECT 1 FROM {T_EGP_OUT} LIMIT 0", want_rows=False)
        for s in [
            f"UPDATE {T_EGP_OUT} SET escopo_indi = false",
            f"UPDATE {T_EGP_OUT} SET escopo_indi = true WHERE projeto IN {esc}",
            f"UPDATE {T_OUT} SET escopo_indi = false",
            f"UPDATE {T_OUT} SET escopo_indi = true WHERE chave_canonica IN "
            f"(SELECT DISTINCT chave_canonica FROM {T_EGP_OUT} WHERE escopo_indi = true)",
        ]:
            exec_fn(s, want_rows=False)
    except (HTTPException, RuntimeError):
        pass
    # escopo_indi mudou nos nós de linhagem -> invalida o cache do grafo p/ a
    # coloração de escopo não ficar stale (areas/graph/neighbors recalculam).
    _lineage_gen += 1
    _lineage_cache.clear()


@app.post("/api/escopo")
def escopo_add(p: EscopoAdd):
    _ensure_escopo_ativo()
    egp = (p.egp_dor1 or "").strip()
    if not egp:
        raise HTTPException(400, "nome do EGP obrigatório")
    projeto = (p.projeto or egp).strip()
    area = (p.area or "").strip()
    # dup: mesmo EGP (por rotulo DOR1 ou projeto). Se existe mas DESATIVADO -> reativa (em vez
    # de 409): "voltou pro escopo" sem re-adicionar. Se ativo -> 409. Guard autoritativo (corrida).
    dup = run_sql(
        f"SELECT id, ativo FROM {T_ESC} WHERE egp_dor1 = {sql_lit(egp)} "
        f"OR (projeto <> '' AND projeto = {sql_lit(projeto)}) LIMIT 1")
    if dup:
        if str(dup[0].get("ativo")).lower() == "false":
            run_sql(f"UPDATE {T_ESC} SET ativo = true WHERE id = {sql_lit(dup[0]['id'])}", want_rows=False)
            _esc_audit("reativar", egp, projeto)
            recompute_escopo()
            return {"ok": True, "id": dup[0]["id"], "reativado": True}
        raise HTTPException(409, f'O EGP "{egp}" ja esta no escopo.')
    rid = uuid.uuid4().hex
    # classificação derivada do mapeamento — exato se o EGP já está extraído (casa um nó), senão faltante
    classif = "faltante"
    if projeto:
        match = run_sql(f"SELECT 1 FROM {T_ND} WHERE projeto = {sql_lit(projeto)} LIMIT 1")
        if match:
            classif = "exato"
    run_sql(
        f"INSERT INTO {T_ESC} (id, egp_dor1, area, status_extracao, projeto, origem, ativo, created_by, created_at) "
        f"VALUES ({sql_lit(rid)}, {sql_lit(egp)}, {sql_lit(area)}, {sql_lit(classif)}, {sql_lit(projeto)}, "
        f"'manual', true, {_ator()}, cast({AGORA} AS STRING))", want_rows=False)
    _esc_audit("add", egp, projeto)
    recompute_escopo()
    return {"ok": True, "id": rid}


@app.delete("/api/escopo/{rid}")
def escopo_del(rid: str, hard: bool = False):
    """Por padrão DESATIVA (soft, ativo=false) — entrada preservada p/ reativar sem
    re-adicionar. hard=true remove de vez (DELETE). Ambos re-derivam o escopo."""
    _ensure_escopo_ativo()
    cur = run_sql(f"SELECT egp_dor1, projeto FROM {T_ESC} WHERE id = {sql_lit(rid)}")
    if not cur:
        raise HTTPException(404, "registro não encontrado")
    if hard:
        run_sql(f"DELETE FROM {T_ESC} WHERE id = {sql_lit(rid)}", want_rows=False)
        _esc_audit("remove", cur[0]["egp_dor1"], cur[0]["projeto"])
    else:
        run_sql(f"UPDATE {T_ESC} SET ativo = false WHERE id = {sql_lit(rid)}", want_rows=False)
        _esc_audit("desativar", cur[0]["egp_dor1"], cur[0]["projeto"])
    recompute_escopo()
    return {"ok": True}


@app.post("/api/escopo/{rid}/ativar")
def escopo_reactivate(rid: str):
    """Reativa uma entrada desativada do escopo (ativo=true) + re-deriva o escopo."""
    _ensure_escopo_ativo()
    cur = run_sql(f"SELECT egp_dor1, projeto FROM {T_ESC} WHERE id = {sql_lit(rid)}")
    if not cur:
        raise HTTPException(404, "registro não encontrado")
    run_sql(f"UPDATE {T_ESC} SET ativo = true WHERE id = {sql_lit(rid)}", want_rows=False)
    _esc_audit("reativar", cur[0]["egp_dor1"], cur[0]["projeto"])
    recompute_escopo()
    return {"ok": True}


def _sincronizado_em():
    """Fim da última sincronização boa (só na AWS). O front mostra "dados de HH:MM" e fica
    vermelho quando envelhece — falha da sincronização não pode passar em silêncio."""
    if not dialeto.PG:
        return None
    r = run_sql("SELECT max(concluida_em) AS em FROM historico.publicacao "
                "WHERE ok AND origem = 'sync_databricks'")
    return r[0]["em"] if r else None


@app.get("/api/config")
def config():
    # O front só dispara o prefetch das abas quando /api/config responde: era 3 statements
    # seriais (áreas + gestão + admin) segurando a página inteira. Áreas vêm de coluna do
    # publish (cache por geração); grupos vêm da _sessao() (1 query por token).
    def _areas():
        return _cache_lineage(("config_areas",), lambda: [r["area"] for r in run_sql(
            f"SELECT DISTINCT trim(a) AS area FROM ("
            f"SELECT explode(split(areas, '[|]')) a FROM {T_IN} "
            f"WHERE areas IS NOT NULL AND areas <> '') WHERE trim(a) <> '' ORDER BY area")])
    areas, _g = _parallel(_areas, _is_gestao)
    return {"status_options": STATUS_INPUT, "etapa_options": PIPELINE_INPUT,
            "categorias": CATEGORIAS, "origens": ORIGENS,
            "areas": areas, "scope": FQ, "is_gestao": _is_gestao(), "is_admin": _is_admin(),
            # unidade de contagem de input em vigor: com família ligada, safras da mesma
            # tabela contam como 1. A UI precisa DIZER isso — a fila cai pela metade e quem
            # lembra do número antigo tem que entender por quê, não desconfiar do app.
            "familias_safra": FAMILIAS_ON,
            "somente_leitura": SOMENTE_LEITURA,
            "sincronizado_em": _sincronizado_em(),
            # aba Perguntas (Genie embutido): só aparece com a env setada E para bv_users.
            # O controle de acesso REAL é a permissão do space no Databricks (o iframe roda
            # com a sessão do usuário) — esconder a aba aqui é só para não mostrar a quem
            # não tem acesso. Sem a env a aba some. O space lê tabelas de PROD, inclusive no
            # app dev (mesma URL no app.dev.yaml) — o aviso da aba diz isso.
            "genie_embed_url": os.environ.get("GENIE_EMBED_URL") or None}


NODE_COLS = "projeto, area, onda, escopo_indi, n_inputs, n_outputs, ciclo_id"


def _fetch_nodes(ids):
    ids = [i for i in ids if i]
    if not ids:
        return []
    inlist = ", ".join(sql_lit(i) for i in ids)
    return run_sql(f"SELECT {NODE_COLS} FROM {T_ND} WHERE projeto IN ({inlist})")


def _producer_choices():
    """{output_key: projeto_escolhido} de sas_output_producer_choice. Tolera tabela ausente.
    Cacheado junto da linhagem (mesma invalidacao: bump _lineage_gen no save)."""
    def _p():
        try:
            return {r["chave_canonica"]: r["projeto_escolhido"]
                    for r in run_sql(f"SELECT chave_canonica, projeto_escolhido FROM {T_CHOICE}")
                    if r.get("chave_canonica") and r.get("projeto_escolhido")}
        except HTTPException as e:
            if not _objeto_ausente(e):
                raise
            return {}
    return _cache_lineage(("prodchoice",), _p)


def _autoprodutor_candidatos():
    """{chave_canonica do input: projeto} dos pares (EGP, input) onde o MESMO EGP
    consumidor também CRIA a tabela (não só apensa/atualiza) — candidato a
    'Autoprodutor' (ver STATUS_INPUT/_modern()): o dado já é produzido internamente, não
    precisa de ingestão separada. Restrito a criador ÚNICO (qtd_criadores<=1) ou ao
    produtor CANÔNICO escolhido (_producer_choices()) quando há mais de um criador —
    mesma régua Tier 1/Tier 2 da análise manual de 2026-08-12
    (docs/analises/BV_Migracao_SAS_Analise_Inputs_Autogerados_2026-08-12.md). Só
    categoria 'tabela' (autoprodução só faz sentido p/ tabelas SAS/Local). Join por
    (projeto, chave) contra sas_egp_outputs — via_tabelas/sas_lineage_edges NÃO serve
    aqui: o orchestrator deliberadamente pula a self-edge quando o leitor também escreve
    a tabela (ver docs/CLASSIFICACAO_INPUTS_SAS.md §"input que também é output do próprio
    EGP"), então o produtor não apareceria como dependência ali. Tolera tabela ausente
    (pré-1º publish). Cacheado junto da linhagem (mesma invalidação de
    _producer_choices())."""
    def _p():
        try:
            choices = _producer_choices()
            rows = run_sql(
                f"SELECT e.chave_canonica AS chave_in, e.projeto AS projeto, "
                f"o.chave_canonica AS chave_out, t.qtd_criadores AS qtd_criadores "
                f"FROM {T_EGP} e JOIN {T_EGP_OUT} o ON o.projeto = e.projeto "
                f"AND e.chave_canonica = concat('tabela::', o.chave_canonica) "
                f"LEFT JOIN {T_OUT} t ON t.chave_canonica = o.chave_canonica "
                f"WHERE e.categoria = 'tabela' AND o.apenas_contribui = false")
            out = {}
            for r in rows:
                ch, proj, chout = r.get("chave_in"), r.get("projeto"), r.get("chave_out")
                if not ch or not proj:
                    continue
                qc = int(r.get("qtd_criadores") or 1)
                if qc <= 1 or choices.get(chout) == proj:
                    out[ch] = proj
            return out
        except HTTPException as e:
            if not _objeto_ausente(e):
                raise
            return {}
    return _cache_lineage(("autoprodcand",), _p)


def _prod_declarado_escolhidas():
    """{chave -> {projetos que declaram esse output}} de sas_egp_outputs para as chaves com
    escolha de produtor (são poucas: 11 em prod). A lista de chaves sai de uma subquery em
    sas_output_producer_choice — então a leitura roda NA MESMA onda paralela de
    `_edges_pruned` em vez de esperar `choices` (era 1 rodada serial no frio). Quem chama
    recorta pelas chaves de `choices` (só as com projeto escolhido). Tabela ausente -> {}."""
    try:
        rows = run_sql(f"SELECT o.projeto, o.chave_canonica FROM {T_EGP_OUT} o "
                       f"WHERE o.chave_canonica IN (SELECT chave_canonica FROM {T_CHOICE})")
    except HTTPException as e:
        if not _objeto_ausente(e):
            raise
        return {}
    out = {}
    for r in rows:
        ch, pj = r.get("chave_canonica"), r.get("projeto")
        if ch and pj:
            out.setdefault(ch, set()).add(pj)
    return out


def _membro_via(t):
    """Membro (depois do ultimo ponto) de uma via LIB.MEMBRO; None para caminho de
    arquivo. `/a/x.sas7bdat` daria membro "SAS7BDAT" e casaria arquivos sem relacao
    nenhuma — em prod ha 3 caminhos .sas7bdat distintos que cairiam no mesmo balde."""
    if not t or "/" in t or "\\" in t or "." not in t:
        return None
    return t.rsplit(".", 1)[-1].upper()


def _prune_edges(rows, choices, prod_declarado=None):
    """Poda arestas pela escolha de produtor canonico. Remove a via T de arestas cujo
    produtor != choices[T]; descarta aresta sem vias. Self-heal: so honra choices[T] se
    choices[T] for produtor atual de T nas rows (evita orfao por escolha obsoleta).

    ALIAS DE LIBNAME (2026-09-28): a escolha e gravada com a chave que o PRODUTOR declara
    em sas_egp_outputs (`NPS.BA_ESTOQUE_NPSENVIO_CARTAO`) e a aresta carrega o alias que o
    CONSUMIDOR usa (`NPS_NEW.BA_...`). Casando so por string a escolha nunca entrava no
    `eff` e ainda era descartada inteira pelo self-heal: 5 das 11 escolhas em prod estavam
    inertes, e por isso a copia `__v2` do Cartao Amigavel continuava puxada como
    dependencia. `prod_declarado` ({chave -> {produtores}}, de sas_egp_outputs) liga a
    equivalencia.

    A equivalencia e CONSERVADORA de proposito: vale so quando o conjunto de produtores da
    via e IDENTICO ao da chave. Mesmo membro com produtores diferentes e homonimo REAL
    (`B_GERAL.DIAS_UTEIS` x `CARNEIRO.DIAS_UTEIS`, `TBPESSOA` em 5 variantes — 9 casos em
    prod contra 28 alias) e colapsar fundiria tabelas distintas, contra a identidade por
    caminho fisico."""
    if not choices:
        return rows
    prod_by_via = {}
    for e in rows:
        for t in (e.get("via_tabelas") or "").split(" | "):
            t = t.strip()
            if t:
                prod_by_via.setdefault(t, set()).add(e.get("depende_do"))
    eff = {t: p for t, p in choices.items() if p in prod_by_via.get(t, ())}
    if prod_declarado:
        por_membro = {}
        for via in prod_by_via:
            m = _membro_via(via)
            if m:
                por_membro.setdefault(m, set()).add(via)
        for t, p in choices.items():
            prods = prod_declarado.get(t)
            m = _membro_via(t)
            if t in eff or not m or not prods or p not in prods:
                continue
            for via in por_membro.get(m, ()):
                if via not in eff and prod_by_via[via] == prods:
                    eff[via] = p
    if not eff:
        return rows
    out = []
    for e in rows:
        vias = [t.strip() for t in (e.get("via_tabelas") or "").split(" | ") if t.strip()]
        keep = [t for t in vias if not (t in eff and eff[t] != e.get("depende_do"))]
        if keep:
            out.append({**e, "via_tabelas": " | ".join(keep)})
    return out


def _vias_resolvidas():
    """Tabelas (artifact UPPER, categoria 'tabela') com status EFETIVO Modernizado ou
    Sanitizado — via de dependencia RESOLVIDA: o dado ja esta no lake (ou foi descartado
    do escopo), logo o consumidor nao precisa mais do EGP produtor por causa dela.
    Mesma regra do _modern(); derivada do status a cada leitura (reverter o status do
    input traz a dependencia de volta). Cache OBO+TTL da linhagem, como o _blocking."""
    def _p():
        try:
            _ensure_input_pipeline_cols()
            return {(r.get("artifact") or "").strip().upper()
                    for r in run_sql(f"SELECT artifact FROM {T_IN} "
                                     f"WHERE categoria = 'tabela' AND ({_modern()})")
                    if (r.get("artifact") or "").strip()}
        except HTTPException as e:
            if not _objeto_ausente(e):
                raise
            return set()
    return _cache_lineage(("viasresolvidas",), _p)


def _vias_sanitizadas():
    """Subconjunto de _vias_resolvidas cuja resolução foi DESCARTE (status efetivo
    Sanitizado), não entrega. Existe para separar os dois finais possíveis de uma
    ex-dependência que perdeu a aresta: a tabela ENTROU no lake (o produtor virou
    dispensável — houve entrega, o esforço dele conta) ou a tabela saiu do escopo (nada
    foi entregue). Mesma derivação-a-cada-leitura do _vias_resolvidas."""
    def _p():
        try:
            _ensure_input_pipeline_cols()
            return {(r.get("artifact") or "").strip().upper()
                    for r in run_sql(f"SELECT artifact FROM {T_IN} "
                                     f"WHERE categoria = 'tabela' AND ({_sanitizado()})")
                    if (r.get("artifact") or "").strip()}
        except HTTPException as e:
            if not _objeto_ausente(e):
                raise
            return set()
    return _cache_lineage(("viassanitizadas",), _p)


def _filter_vias_resolvidas(rows):
    """Remove das arestas as vias ja resolvidas (input Modernizado/Sanitizado); aresta
    que ficar sem via e descartada — dependencia satisfeita nao aponta/puxa o produtor.
    Aresta sem via declarada e mantida (nao ha como avaliar). Compoe com _prune_edges."""
    return _filter_vias_resolvidas_res(rows, _vias_resolvidas())


def _filter_vias_resolvidas_res(rows, res, mantidas=frozenset()):
    """Parte pura de _filter_vias_resolvidas (recebe o set `res` em vez de consultar).
    Reusada por _frontier_via, que le `res` via exec_fn (funciona como SP, sem OBO).

    `mantidas`: pares (projeto_alvo, ARTIFACT upper) em que o CONSUMIDOR declarou que a
    dependencia continua viva apesar da via estar resolvida (ver _ensure_dep_mantida_
    tables). Essa via nao e removida daquela aresta — e so daquela: o mesmo artifact segue
    resolvido para todos os outros consumidores."""
    if not res:
        return rows
    out = []
    for e in rows:
        vias = [t.strip() for t in (e.get("via_tabelas") or "").split(" | ") if t.strip()]
        if not vias:
            out.append(e)
            continue
        alvo = e.get("projeto_alvo")
        keep = [t for t in vias
                if t.upper() not in res or (alvo, t.upper()) in mantidas]
        if keep:
            out.append({**e, "via_tabelas": " | ".join(keep)})
    return out


def _edges_pruned():
    """Arestas de sas_lineage_edges podadas pela escolha de produtor canonico E pelas
    vias resolvidas (via Modernizada/Sanitizada nao gera dependencia — vale em todo o
    app: frontier/+deps, depende_de/alimenta, bloqueio, priorizacao/alavancagem), MENOS os
    pares em que o consumidor declarou a dependencia mantida (_deps_mantidas)."""
    def _p():
        edges, choices, res, mant, decl = _parallel(
            lambda: run_sql(f"SELECT projeto_alvo, depende_do, via_tabelas FROM {T_ED}"),
            _producer_choices, _vias_resolvidas, _deps_mantidas, _prod_declarado_escolhidas)
        decl = {ch: pjs for ch, pjs in decl.items() if ch in choices}
        return _filter_vias_resolvidas_res(
            _prune_edges(edges, choices, decl), res, mant)
    return _cache_lineage(("edges_pruned",), _p)


def _dep_of_map(edges):
    """Mapa CONSUMIDOR -> {PRODUTORES} a partir de sas_lineage_edges. Em sas_lineage_edges:
    depende_do = PRODUTOR, projeto_alvo = CONSUMIDOR. "X depende de Y" = aresta
    (projeto_alvo=X, depende_do=Y); logo dep_of[X] contem Y. Ignora self-loops."""
    dep_of: dict = {}
    for e in edges:
        a, d = e["projeto_alvo"], e["depende_do"]
        if a and d and a != d:
            dep_of.setdefault(a, set()).add(d)
    return dep_of


def _transitive_upstream(base_set, dep_of, max_hop=None, no_expand=frozenset()):
    """Fecho transitivo UPSTREAM (dependencias) a partir de base_set, por NIVEL (BFS).
    De cada no X, suas dependencias sao dep_of[X] (= produtores de X). Retorna dict
    {projeto -> dep_nivel}: base = 0, dependencia direta = 1, dep-de-dep = 2, ... Cada no
    recebe a MENOR distancia a base. max_hop=1 limita a 1-hop (so nivel 1). Reusado por
    /api/landing (deps = fecho - base) e /api/egp-readiness?scope=indi_deps (niveis).
    `no_expand`: nos que NAO puxam dependencias — recebem nivel (se base/alcancados por
    um no vivo) mas nao expandem o fecho. Uso: EGPs fora do backlog (status
    'Despriorizado e Contabilizado'); a dependencia exclusiva deles some por
    alcancabilidade, a compartilhada com um EGP vivo permanece."""
    level = {p: 0 for p in base_set}
    frontier = set(base_set) - set(no_expand)
    hop = 0
    while frontier and (max_hop is None or hop < max_hop):
        hop += 1
        nxt = set()
        for p in frontier:
            for dep in dep_of.get(p, ()):  # produtores de p = deps de p
                if dep not in level:
                    level[dep] = hop
                    if dep not in no_expand:
                        nxt.add(dep)
        frontier = nxt
    return level


def _egps_fora_backlog():
    """EGPs com status de migracao 'Despriorizado e Contabilizado' = FORA do backlog:
    nao semeiam/expandem o fecho de dependencias (no_expand do _transitive_upstream) e
    ficam fora do plano de priorizacao. DERIVADO do status a cada request (nada e
    cascateado/escrito): reverter o status traz as dependencias de volta na hora; dep
    compartilhada com EGP vivo nunca some (alcancabilidade decide). Robusto a T_PIPE
    ausente -> set vazio. NAO usar no _blocking (semantica downstream, intocada)."""
    def _p():
        try:
            # pipe-etapa-status: real — a pergunta é pelo ESTADO GRAVADO de gestão ("quem
            # a gestão tirou do backlog"), não pelo andamento. `Desatualizado` é derivado e
            # o status verdadeiro continua por baixo (§3.2.6): derivar aqui inverteria a
            # regra — um despriorizado que ganhasse vínculo sairia do conjunto e voltaria a
            # puxar dependências exclusivas, e a sanitização derivada que depende deste
            # conjunto (§3.4.18) mudaria de resultado sem ninguém ter mexido em nada.
            return {r["projeto"] for r in run_sql(
                f"SELECT projeto FROM {T_PIPE} "
                f"WHERE status_migracao = 'Despriorizado e Contabilizado'") if r.get("projeto")}
        except HTTPException as e:
            if not _objeto_ausente(e):
                raise
            return set()
    return _cache_lineage(("fora_backlog",), _p)


def _edges_raw():
    """Arestas CRUAS de `sas_lineage_edges`: o grafo como o publish gravou, SEM poda de
    produtor canônico, de via resolvida ou de vínculo quebrado. Cacheado por geração —
    `_retidos` e `_ex_deps` leem o mesmo conjunto, e eram duas queries idênticas."""
    def _p():
        return run_sql(f"SELECT projeto_alvo, depende_do, via_tabelas FROM {T_ED}")
    return _cache_lineage(("edges_raw",), _p)


def _retidos(base):
    """Fecho transitivo sobre o grafo BRUTO = o universo que a aba RETÉM (frontier vivo ∪
    ex-dependências), e não só o que ela conta.

    Existe porque reter a ex-dependência sem reter o SUCESSOR dela é meia retenção. A
    ex-dependência fica listada com badge para "o esforço não sumir" (`_ex_deps`), mas a
    cadeia de sucessores era semeada só com o fecho PODADO: no instante em que a via de um
    produtor entrava no lake, o produtor virava ex-dependência (certo, fica retido) e a
    VERSÃO NOVA dele sumia de todas as telas (errado — ninguém desfez trabalho nenhum).

    Medido em prod 07/10/2026: `PAGOSCBR.PAGOS_CYBER_202603` virou `Modernizado` em 06/10
    19:35; era a única via que puxava o `Performance_Saldo_COLORE_…_Lite_V5`, que virou
    ex-dependência — e levou junto o `…__ATU20260901`, com 79 inputs, para fora do recorte.
    O contador de extras caiu de 33 para 32 sem que EGP algum tivesse sido resolvido.

    Mesmo fecho bruto de `_ex_deps` (sem poda, sem `no_expand`), de propósito: são a mesma
    pergunta — "quem já esteve no recorte" — e duas definições divergiriam no dia em que
    uma delas mudasse."""
    def _p():
        return set(_transitive_upstream(base, _dep_of_map(_edges_raw())))
    return _cache_lineage(("retidos", tuple(sorted(base))), _p)


def _frontier_egps(scope, areas):
    """Conjunto de EGPs (projetos) do recorte do Monitor por escopo:
      'indi'      -> nós escopo_indi [∩ áreas]
      'base'      -> todos os nós [∩ áreas]
      'indi_deps' -> base Indicium [∩ áreas] ∪ dependências TRANSITIVAS (fecho upstream)
    `areas` (lista) filtra a BASE por nó.area. Retorna (frontier:set, base:set)."""
    conds = []
    if scope != "base":
        conds.append("escopo_indi = true")
    if areas:
        conds.append(f"area IN ({', '.join(sql_lit(a) for a in areas)})")
    wsql = (" WHERE " + " AND ".join(conds)) if conds else ""

    def _p():
        if scope != "indi_deps":
            base = {r["projeto"] for r in run_sql(f"SELECT projeto FROM {T_ND}{wsql}") if r["projeto"]}
            return base, base
        # leituras independentes em paralelo; edges/fora ficam cache-quentes p/ o resto do
        # request. Cascas, novos e vínculos não dependem de nada daqui — eram 3 rodadas
        # seriais depois desta onda no caminho frio de toda tela.
        # `_edges_raw` entra na onda só para AQUECER o cache: `_retidos` depende de `base`
        # (que só existe depois daqui), mas a query dele não — sem isto ela viraria uma
        # rodada serial nova no caminho frio de toda tela.
        base_rows, edges, fora, _casc, _novos, _vinc, _ = _parallel(
            lambda: run_sql(f"SELECT projeto FROM {T_ND}{wsql}"),
            _edges_pruned, _egps_fora_backlog, _cascas, _egps_novos, _vinculos_por_antecessor,
            _edges_raw)
        base = {r["projeto"] for r in base_rows if r["projeto"]}
        # A CASCA NÃO É BASE (§3.6 regra 27): ela nasce com escopo_indi=true — que é o que
        # a mantém visível depois do recompute —, mas é `extra`, não escopo. Sem tirá-la
        # daqui ela ficava classificada nos DOIS conjuntos ao mesmo tempo (base e extras),
        # e a linha de base subia de 168 p/ 173 sem que EGP algum tivesse entrado no
        # escopo. Ela volta ao recorte logo abaixo, pela mesma porta dos sucessores.
        # o EGP NOVO declarado (§3.1.2, 29/09/2026) também não é base, pela mesma razão da
        # casca: `_egps_novos` já descarta quem está na linha de base, então o que sobra
        # aqui é, por construção, gente de fora do denominador.
        base = base - _casc - _novos
        # fora do backlog: continua na base (DOR1) mas nao puxa dependencias
        level = _transitive_upstream(base, _dep_of_map(edges), no_expand=fora)
        # Sucessores e cascas entram no recorte POR REGRA (spec §3.1.2): não são
        # dependência de ninguém, então o grafo nunca os traria — e sem eles os inputs da
        # versão nova não aparecem em lugar nenhum. Só entram os sucessores de antecessores
        # já no recorte; a casca entra sempre, porque o antecessor dela é ela mesma.
        # FECHO, não uma passada: cadeia v1 -> v2 -> v3 (o BV manda versão nova da versão
        # nova). Com uma passada só, o v3 ficava gravado no vínculo e invisível em tela.
        #
        # A cadeia parte de `level` MAIS casca e novo, não só de `level`: os dois foram
        # tirados de `base` (regra 27) e voltam depois, no `|` do return — então, partindo
        # só de `level`, o SUCESSOR de uma casca nunca era alcançado. Medido em 30/09/2026,
        # quando o unificador de 4 cascas finalmente entrou no corpus: as 4 apontavam para
        # ele e ele continuava invisível em todas as telas, com os inputs dele fora de
        # qualquer balde. A casca entra por regra; o que ela sucede tem de entrar junto.
        # Semeado com o universo RETIDO (`_retidos`), não só com `level`: o antecessor que
        # virou ex-dependência continua listado, e o sucessor dele tem de continuar junto —
        # ver `_retidos` para o caso medido. `level` sozinho fazia a versão nova sumir no
        # dia em que a via do antecessor fosse ingerida.
        _ret = _retidos(base)
        _semente = set(level) | _ret | _casc | _novos
        suc = vinculos.cadeia_de_sucessores(_vinc, _semente)
        # `cadeia_de_sucessores` devolve SEM a semente, porque o chamador normal a reúne de
        # volta no return. Aqui não: `_ret` entra só para ALCANÇAR sucessores, e a
        # ex-dependência em si continua fora do frontier (quem a retém é `_ex_deps`, com
        # badge). O efeito colateral é que um sucessor que TAMBÉM está em `_ret` era
        # subtraído junto — 5 sumiram do recorte na primeira medição desta mudança — então
        # ele volta aqui. Só o sucessor DE QUEM ESTÁ NA SEMENTE: "sucessor entra por regra"
        # exige o antecessor no recorte (§3.1.2). `_ret & sucessores(_vinc)` trazia também o
        # sucessor de antecessor não retido, que é ex-dependência como qualquer outro (sem
        # caso em prod em 08/10/2026 — 27 pelas duas regras; o teste fixa a regra).
        suc |= _ret & {v["sucessor"] for a, v in _vinc.items()
                       if a in _semente and v.get("sucessor")}
        # o novo declarado entra pela MESMA porta do sucessor e da casca: o grafo nunca o
        # traria (ele não é dependência de ninguém) e sem ele os inputs dele não aparecem.
        return set(level) | suc | _casc | _novos, base
    return _cache_lineage(("frontier", scope, tuple(areas)), _p)


def _vinculos_por_antecessor():
    """{antecessor: {tipo, sucessor}} do funil. Cacheado por geração como o resto da
    linhagem: é lido no recorte e em toda contagem de EGP."""
    def _p():
        try:
            return vinculos.mapa_vinculos(run_sql(
                f"SELECT projeto, egp_vinculo_tipo, egp_sucessor FROM {T_PIPE}"))
        except HTTPException as e:
            if not _objeto_ausente(e):
                raise
            return {}
    return _cache_lineage(("vinculos",), _p)


def _cascas():
    """EGPs CASCA (spec §3.6): antecessor sem inventário próprio, criado no publish e
    marcado em sas_escopo por `origem = 'casca'`. A linha em sas_escopo existe só p/ o
    recompute_escopo() não apagar o escopo_indi dela (regra 24) — nunca p/ contar.
    Cacheado por geração como o resto do recorte; tabela/coluna ausente -> vazio."""
    def _p():
        try:
            return {(r.get("projeto") or "").strip() for r in run_sql(
                f"SELECT projeto FROM {T_ESC} WHERE origem = {sql_lit(vinculos.ORIGEM_CASCA)} "
                f"AND projeto <> '' AND ativo IS NOT false")} - {""}
        except HTTPException as e:
            if not _objeto_ausente(e):
                raise
            return set()
    return _cache_lineage(("cascas",), _p)


def _egps_novos():
    """EGPs NOVOS declarados à mão (`sas_app_config`, chave 'egps_novos' = JSON
    ["Área__Projeto", ...]): entraram no escopo depois do congelamento e **não substituem
    ninguém**, então nenhum vínculo os alcança.

    Decisão da gestão de 29/09/2026 sobre o `Cobranças__ROI`: *"entra como um a mais
    mesmo"*. Antes disso ele não cabia em lugar nenhum — nem nos 193 (congelados por
    decisão anterior) nem em `extra` (enumeração que só conhecia sucessor e casca). Ficava
    visível só na aba EGPs Atualizados, que o §5 aposenta.

    LISTA, nunca regra. Foi definição por exclusão (`recorte − linha_base`) que produziu o
    bug do ticket 21; aqui ninguém entra sem ter sido nomeado. Quem já está na linha de
    base é DESCARTADO na leitura: declarar como novo quem já conta no denominador o poria
    nos dois lados ao mesmo tempo — o mesmo erro que a casca cometeu em 28/09.

    Robusto a tabela/chave ausente (o app roda antes do 1º publish). Cacheado por
    geração: era 1 statement em TODA chamada — inclusive com o resto quente (scope-egps,
    egps-extras, 2x na cauda do readiness) —, e `_grava_egps_novos` já bumpa a geração."""
    def _p():
        try:
            r = run_sql(f"SELECT valor FROM {T_CFG} WHERE chave = 'egps_novos'")
            return set(json.loads(r[0]["valor"])) if r and r[0].get("valor") else set()
        except (HTTPException, TypeError, ValueError, KeyError, IndexError) as e:
            if isinstance(e, HTTPException) and not _objeto_ausente(e):
                raise
            return set()
    return _cache_lineage(("egps_novos",), _p) - set(_linha_base())


def _egps_novos_raw():
    """A lista DECLARADA, crua — sem o filtro da linha de base que `_egps_novos` aplica.

    É o que a gestão edita. `_egps_novos` descarta na LEITURA quem entrou na linha de base
    (para nunca contar dos dois lados); se a escrita usasse a lista já filtrada, remover um
    item escondido por esse filtro seria um clique sem efeito nenhum, e o item voltaria a
    aparecer no dia em que saísse da linha de base."""
    try:
        r = run_sql(f"SELECT valor FROM {T_CFG} WHERE chave = 'egps_novos'")
        bruto = json.loads(r[0]["valor"]) if r and r[0].get("valor") else []
        return [str(x) for x in bruto] if isinstance(bruto, list) else []
    except (HTTPException, TypeError, ValueError, KeyError, IndexError) as e:
        if isinstance(e, HTTPException) and not _objeto_ausente(e):
            raise
        return []


def _grava_egps_novos(lista, antes):
    """Persiste a lista em `sas_app_config` + auditoria. Mesmo molde do
    `priorizacao_set_capacidade`: MERGE por chave, `updated_by`/`updated_at` sempre
    preenchidos (a linha semeada por script em 29/09 deixou os dois NULL — ver ticket 24)
    e um evento em `sas_pipeline_audit` no projeto sentinela `'(config)'`."""
    novo_json = json.dumps(sorted(set(lista)), ensure_ascii=False)
    if not dialeto.PG:  # no Postgres o schema vem das migrações (db/migrations), nunca do app
        run_sql(f"CREATE TABLE IF NOT EXISTS {T_CFG} "
                f"(chave STRING, valor STRING, updated_by STRING, updated_at STRING)",
                want_rows=False)
    run_sql(
        f"MERGE INTO {T_CFG} t USING (SELECT 'egps_novos' AS chave) s ON t.chave = s.chave "
        f"WHEN MATCHED THEN UPDATE SET valor = {sql_lit(novo_json)}, "
        f"updated_by = {_ator()}, updated_at = cast({AGORA} AS STRING) "
        f"WHEN NOT MATCHED THEN INSERT (chave, valor, updated_by, updated_at) VALUES "
        f"('egps_novos', {sql_lit(novo_json)}, {_ator()}, "
        f"cast({AGORA} AS STRING))", want_rows=False)
    run_sql(
        f"INSERT INTO {T_PIPE_AUD} (id, projeto, funil, campo, valor_antigo, valor_novo, ator, ts) "
        f"VALUES ({sql_lit(uuid.uuid4().hex)}, '(config)', 'migracao', 'egps_novos', "
        f"{sql_lit(json.dumps(sorted(set(antes)), ensure_ascii=False))}, {sql_lit(novo_json)}, "
        f"{_ator()}, cast({AGORA} AS STRING))", want_rows=False)
    # A declaração muda quem é extra, e extra entra no frontier: sem bump, o contador
    # "(+N extra)" e a aba EGPs seguiriam servindo a geração anterior.
    _bump_gen()
    return novo_json


class EgpNovoPatch(BaseModel):
    projeto: str
    acao: str = "declarar"      # declarar | remover


@app.get("/api/egps-novos")
def egps_novos_listar():
    """A lista declarada + POR QUE cada item é extra hoje.

    O motivo serve para a gestão ver quando a declaração virou REDUNDANTE: se o EGP ganhou
    vínculo depois (virou sucessor), `motivo_extra` passa a responder `sucessor` sozinho e
    a linha da lista deixou de fazer efeito. Mostrar isso evita a lista virar um depósito
    de declarações mortas que ninguém sabe se ainda valem."""
    _require_gestao()
    declarados = _egps_novos_raw()
    if not declarados:
        return {"n": 0, "rows": []}
    lb, vinc, casc = _linha_base(), _vinculos_por_antecessor(), _cascas()
    try:
        no_corpus = {r["projeto"] for r in run_sql(f"SELECT projeto FROM {T_ND}")}
    except HTTPException:
        no_corpus = set()
    rows = []
    for p in sorted(declarados):
        # motivo SEM a lista: o que sobraria se a declaração fosse removida agora.
        sem_decl = vinculos.motivo_extra(p, lb, vinc, casc, novos=set())
        rows.append({
            "projeto": p,
            "na_linha_base": p in lb,
            "no_corpus": p in no_corpus,
            "motivo_sem_declaracao": sem_decl,
            "redundante": sem_decl is not None,
        })
    return {"n": len(rows), "rows": rows}


@app.patch("/api/egps-novos")
def egps_novos_patch(p: EgpNovoPatch):
    """Declara (ou retira) um EGP como NOVO — a 3ª perna do `extra` (ticket 24).

    As outras duas pernas não precisam disto: `sucessor` sai do vínculo (ticket 20) e
    `casca` é derivada do publish. `novo` era a única que só existia como linha escrita por
    script no warehouse, o que deixava a gestão dependente de alguém com acesso.

    Tudo aqui RECUSA em vez de adivinhar — declarar errado cria um extra fantasma que
    ninguém consegue rastrear até um clique."""
    _require_gestao()
    projeto = (p.projeto or "").strip()
    if not projeto:
        raise HTTPException(400, "projeto é obrigatório")
    if p.acao not in ("declarar", "remover"):
        raise HTTPException(400, "acao deve ser 'declarar' ou 'remover'")
    antes = _egps_novos_raw()

    if p.acao == "remover":
        if projeto not in antes:
            raise HTTPException(404, f"'{projeto}' não está declarado como novo")
        _grava_egps_novos([x for x in antes if x != projeto], antes)
        return {"ok": True, "acao": "remover", "projeto": projeto,
                "declarados": sorted(set(antes) - {projeto})}

    if projeto in antes:
        raise HTTPException(409, f"'{projeto}' já está declarado como novo")
    # 1) fora do corpus: declarar quem não existe cria um extra fantasma.
    if not run_sql(f"SELECT projeto FROM {T_ND} WHERE projeto = {sql_lit(projeto)} LIMIT 1"):
        raise HTTPException(404, f"'{projeto}' não está no corpus — rode o pipeline "
                                 "(extrator + orquestrador + publish) antes de declarar")
    # 2) na linha de base: `_egps_novos` o descartaria em silêncio na leitura. Quem clicou
    #    merece saber que o clique não faria nada.
    if projeto in _linha_base():
        raise HTTPException(409, f"'{projeto}' está na linha de base congelada — já conta "
                                 "no total de 193 e não pode ser extra ao mesmo tempo")
    # 3) o vínculo vence a declaração (`motivo_extra` já decide assim), então declarar
    #    seria um no-op enganoso: a linha apareceria na lista sem mudar nada.
    _ja = vinculos.motivo_extra(projeto, _linha_base(), _vinculos_por_antecessor(),
                                _cascas(), novos=set())
    if _ja:
        raise HTTPException(409, f"'{projeto}' já é extra por '{_ja}' — o vínculo vence a "
                                 "declaração, então declarar não mudaria nada")
    _grava_egps_novos(antes + [projeto], antes)
    return {"ok": True, "acao": "declarar", "projeto": projeto,
            "declarados": sorted(set(antes) | {projeto})}



def _linha_base():
    """A LISTA CONGELADA de EGPs que contam ({projeto: classe}), lida do arquivo
    versionado `egps_analysis/src/linha_base_congelada_2026-09-29.csv`.

    Decisão da gestão de 29/09/2026: o total de EGPs deixa de ser calculado e passa a ser
    o tamanho desta lista. Quem não está nela é `extra` — inclusive o que o grafo
    classificaria como dependência. Congelado nos dois lados: quem SAI do escopo continua
    no denominador, e `Despriorizado e Contabilizado` segue dentro, como sempre esteve.

    **Só o denominador congela.** Etapa, status, barras dos funis, coorte, migrados,
    inputs e fila continuam derivados do estado atual a cada leitura: é "X de 193", com o
    193 parado e o X vivo.

    Arquivo ausente EXPLODE (linha_base.LinhaBaseAusente): sem a lista o total seria um
    número inventado, e um zero silencioso é pior do que um 500. Sem try/except de
    propósito — é a única leitura do app que não tem fallback."""
    return linha_base.carrega()


def _extras(egps):
    """Categoria `extra` (spec §3.1.2): o EGP do recorte que tem VÍNCULO DE ATUALIZAÇÃO
    com outro — sucessor ou casca — e não está na linha de base.

    ENUMERAÇÃO, restaurada em 29/09/2026 (o ticket 19 tinha trocado por `recorte −
    linha_base`, que varria junto as ex-dependências fora da contagem e as rotulava de
    "novo"). Ex-dependência nunca é extra; quem não tem vínculo também não é — estar fora
    da lista é um fato do DENOMINADOR (ver `_contaveis`), não um rótulo.

    Ex-dependência não precisa ser subtraída aqui porque não está no frontier por
    construção (`_ex_deps` = fecho bruto − frontier); quem opera sobre LINHAS — onde ela
    aparece — é `vinculos.anexa_vinculo`, que a veta explicitamente. É isso que faz o
    contador do card e a tabela da aba falarem do mesmo conjunto.

    O extra fica no recorte (é listado e traz os inputs dele), fora do total, com contador
    próprio ao lado.

    Quarta perna desde 13/10/2026: a DEPENDÊNCIA que apareceu depois do congelamento
    (`_deps_novas`). Os 193 estão fechados — "dependência que vier vira extra"."""
    return vinculos.extras(egps, _linha_base(), _vinculos_por_antecessor(), _cascas(),
                           novos=_egps_novos(), deps_novas=_deps_novas())


def _deps_novas():
    """Dependências do recorte que NÃO estão na linha de base congelada — viram extra
    (decisão da gestão, 13/10/2026: "os 193 estão fechados; dependência que vier vira
    extra, e os inputs dela entram em extra").

    O que o `landing()` já prometia em comentário ("uma dependência que apareceu depois do
    congelamento traz os inputs dela e conta entre os extras, não aqui") e `extras()`
    nunca fez: o EGP ficava fora de tudo, mas os inputs exclusivos dele entravam no card
    de DEPENDÊNCIAS — 11 dependências na tela e os inputs de 12. Caso que revelou, em
    13/10/2026: `20. Performance Safrada Fase Ativa - Agente IA`, publicado sem vínculo e
    puxado pelo grafo, levou +10 inputs / +9 a ingerir para aquele card.

    Dependência = quem está no frontier e não na base viva — o fecho de `_frontier_egps`,
    sem o que já entra lá POR REGRA (sucessor, casca, novo declarado), que tem rótulo
    próprio. Ex-dependência não está no frontier por construção, então não cai aqui."""
    def _p():
        try:
            frontier, base = _frontier_egps("indi_deps", [])
        except HTTPException as e:
            if not _objeto_ausente(e):
                raise
            return set()
        nomeados = vinculos.candidatos_extra(_vinculos_por_antecessor(), _cascas(),
                                             _egps_novos())
        return set(frontier) - set(base) - set(_linha_base()) - nomeados
    return _cache_lineage(("deps_novas",), _p)


def _extras_no_recorte():
    """Os extras que estão DENTRO do recorte `indi_deps` — o conjunto do contador próprio
    da Visão geral, do endpoint /api/egps-extras e do universo do funil de extras (§3.1.3).

    Uma definição só, de propósito: o card "(+N extra)" e o funil logo abaixo dele estão
    na MESMA tela, e duas definições do mesmo recorte foi o bug que o off-by-one do Resumo
    já custou em julho/2026. Sem grafo publicado -> vazio."""
    try:
        return _extras(_frontier_egps("indi_deps", [])[0])
    except HTTPException as e:
        if not _objeto_ausente(e):
            raise
        return set()


def _contaveis(egps):
    """Os EGPs do recorte que CONTAM: a interseção com a linha de base congelada.

    NÃO é o total — o total é `linha_base.total(_linha_base())`, que não olha para o
    recorte. Este aqui responde "destes, quais contam", para as superfícies que precisam
    do conjunto (universo de funil, EGPs por mês, tabela por área). O recorte em si (e
    portanto o universo de INPUTS) continua com os extras dentro."""
    return vinculos.contaveis(egps, _linha_base())


def _sql_na_linha_base(col):
    """Predicado SQL "esta coluna de projeto ESTÁ na linha de base" — p/ as contagens que
    somam direto no warehouse (sas_escopo / sas_lineage_nodes) em vez de sobre conjunto."""
    lb = _linha_base()
    return f"{col} IN ({', '.join(sql_lit(p) for p in sorted(lb))})"


def _area_por_projeto():
    """{projeto: area} de TODOS os nós — a linha de base congela quem conta, mas não a
    área (ela é atributo vivo do nó). Usado só para filtrar a lista por área."""
    def _p():
        try:
            return {r["projeto"]: r.get("area") for r in
                    run_sql(f"SELECT projeto, area FROM {T_ND}") if r.get("projeto")}
        except HTTPException as e:
            if not _objeto_ausente(e):
                raise
            return {}
    return _cache_lineage(("area_por_projeto",), _p)


def _linha_base_filtrada(areas):
    """A linha de base restrita às áreas pedidas. Sem filtro -> a lista inteira."""
    lb = _linha_base()
    if not areas:
        return lb
    ar, alvo = _area_por_projeto(), set(areas)
    return {p: c for p, c in lb.items() if ar.get(p) in alvo}


def _ex_deps_manuais():
    """Ex-dependências RETIDAS À MÃO (sas_app_config, chave 'ex_deps_manuais' = JSON
    ["Área__Projeto", ...]): cobre o caso em que a aresta saiu do próprio grafo BRUTO
    (ex.: produtor-fantasma corrigido na extração) e a derivação retroativa do _ex_deps
    não alcança mais o EGP — mas o esforço já contabilizado deve permanecer nos totais
    (etapa real segue exigida pelo critério do _ex_deps_contab). Editar = UPDATE na
    config (sobrevive ao publish); robusto a tabela/chave ausente."""
    try:
        r = run_sql(f"SELECT valor FROM {T_CFG} WHERE chave = 'ex_deps_manuais'")
        return set(json.loads(r[0]["valor"])) if r and r[0].get("valor") else set()
    except (HTTPException, TypeError, ValueError, KeyError, IndexError) as e:
        if isinstance(e, HTTPException) and not _objeto_ausente(e):
            raise
        return set()


def _ex_deps(frontier, base):
    """Ex-dependências (spec 2026-08-06): EGPs que JÁ foram dependência mas saíram do
    frontier vivo — retidos no painel (badge "ex-dependência") para o esforço não sumir
    (caso Riscos: despriorizar a cadeia derrubou despriorizados/convertidos da tela).
    Derivação RETROATIVA, sem tabela nova: fecho transitivo sobre o grafo BRUTO
    (sas_lineage_edges SEM poda de produtor canônico, SEM filtro de vias resolvidas e
    SEM no_expand de despriorização) − frontier vivo. TODO ex é retido, trabalhado ou
    não (decisão do PM). Devolve (ex:set, motivo:{pj->str}, nivel:{pj->int}):
      'cadeia despriorizada'       — a aresta segue viva; saiu só porque quem o puxava
                                     foi despriorizado (no_expand);
      'resolvida por ingestão'     — TODAS as vias entraram no lake (Modernizado/
                                     Autoprodutor, nenhuma Sanitizada): a tabela foi
                                     ingerida PORQUE o consumidor precisava dela para
                                     migrar, e isso dispensou o EGP produtor. Houve
                                     ENTREGA — se este EGP já tinha esforço gasto (etapa
                                     preenchida), é candidato a 'Despriorizado e
                                     Contabilizado'; ver docs/analises/
                                     EX_DEP_RESOLVIDA_POR_INGESTAO.md;
      'via descartada/desvinculada'— a aresta foi podada por descarte (via Sanitizada),
                                     vínculo quebrado ou produtor canônico: nada foi
                                     entregue por este EGP.
    Falha de grafo -> conjuntos vazios (nunca derruba o endpoint)."""
    def _p():
        try:
            raw, manuais_all, res, san = _parallel(
                _edges_raw, _ex_deps_manuais, _vias_resolvidas, _vias_sanitizadas)
            lv_raw = _transitive_upstream(base, _dep_of_map(raw))
            manuais = manuais_all - set(frontier)
            ex = (set(lv_raw) - set(frontier)) | manuais
            if not ex:
                return set(), {}, {}
            # fecho com as arestas PODADAS mas SEM no_expand: quem reaparece aqui só saiu
            # do frontier pela despriorização; o resto perdeu a própria aresta.
            so_noexpand = set(_transitive_upstream(base, _dep_of_map(_edges_pruned())))
            # vias BRUTAS por produtor = o que este EGP entregava a quem o puxava.
            vias_de: dict = {}
            for e in raw:
                d, a = e.get("depende_do"), e.get("projeto_alvo")
                if d and a and d != a:
                    vias_de.setdefault(d, set()).update(
                        t.strip().upper() for t in (e.get("via_tabelas") or "").split("|")
                        if t.strip())

            def _motivo(p):
                if p in manuais and p not in lv_raw:
                    return "retida manualmente"
                if p in so_noexpand:
                    return "cadeia despriorizada"
                # Entrega = TODA via resolvida E nenhuma resolvida por descarte. Via ainda
                # aberta (aresta podada por produtor canônico, não pelo dado) não é entrega
                # deste EGP — por isso o teste é `v <= res`, não `v & res`.
                v = vias_de.get(p) or set()
                if v and v <= res and not (v & san):
                    return "resolvida por ingestão"
                return "via descartada/desvinculada"
            motivo = {p: _motivo(p) for p in ex}
            return ex, motivo, {p: int(lv_raw.get(p, 1)) for p in ex}
        except HTTPException as e:
            if not _objeto_ausente(e):
                raise
            return set(), {}, {}
    return _cache_lineage(("ex_deps", frozenset(frontier), frozenset(base)), _p)


def _ex_deps_na_foto(frontier, base):
    """Ex-dependências que CONTAM: as que estão na LISTA CONGELADA (§3.1.2).

    É a régua de `contaNoTotalEgp` no frontend, e a que o `total_egps` da Visão geral usa
    desde 29/09/2026 — quando o total deixou de ser calculado e passou a ser o tamanho da
    foto. O critério "189" (`_ex_deps_contab`, só ex com etapa REAL) foi ABSORVIDO por ela
    nessa data e sobreviveu em superfícies que ninguém reviu; cada sobra apareceu como um
    número a menos numa tela: a Gestão dizia 31 EGPs `Desatualizado` onde a aba dizia 33
    (07/10/2026), e a tabela por área dizia 192 onde a Visão geral dizia 193 (08/10/2026).

    `p in linha_base`, e NÃO "classe `ex_dependencia` na foto": o
    `Performance_Saldo_COLORE_…_V5` entrou na lista como `dependencia` e virou ex depois. A
    pergunta é "está na lista", nunca "foi classificado ex na lista".

    A lista vem de um CSV versionado (`_linha_base`), então isto não custa query."""
    return _ex_deps(frontier, base)[0] & set(_linha_base())


def _ex_deps_contab(frontier, base):
    """Ex-dependências CONTABILIZADAS nos totais de EGP (critério 2026-08-10, o mesmo do
    denominador do funil +deps): só ex com ETAPA REAL (não-fantasma) contam — Resumo
    (total_egps), aba EGPs (total/ex_count), card de EGPs da aba Inputs, tabela por área
    do Resumo e Gestão. Ex sem etapa seguem LISTADOS com badge (retenção/auditoria) mas
    fora dos totais; etapa fantasma (Pré-conversão) aparece só no contador do card do
    funil. Em prod (2026-08): 183 vivos + 6 contabilizados = 189.

    EXCEÇÃO (2026-09-25): etapa FANTASMA conta quando o status é 'Despriorizado e
    Contabilizado'. Pré-conversão é anterior a "Projetos Habilitados" — é só a conversão
    do código, sem tabela correta nem nada pronto —, então NUNCA entra na ordem do funil
    (PIPELINE_PROJETO segue sem ela). Mas despriorizar um EGP que já teve pré-conversão
    feita é justamente reconhecer o esforço gasto: é o que o nome do status diz. Sem esta
    exceção, o esforço sumiria em silêncio no único caso em que ele é definitivo. Caso que
    motiva: ex-dependência 'resolvida por ingestão' (ver _ex_deps) — a tabela entrou no
    lake porque o consumidor precisava dela para migrar, o produtor virou dispensável e o
    trabalho de pré-conversão dele ficou órfão."""
    def _p():
        ex = _ex_deps(frontier, base)[0]
        if not ex:
            return set()
        try:
            # pipe-etapa-status: real — DENOMINADOR (critério 189), não exibição. Mesma
            # razão do `et_by_pj` de /api/funis: a etapa espelhada não pode fazer uma
            # ex-dependência entrar no total só porque ela ganhou sucessor (spec §4).
            # O status vem junto porque a exceção de 2026-09-25 conta a etapa fantasma
            # quando ele é 'Despriorizado e Contabilizado' (esforço gasto e reconhecido).
            pipe = run_sql(f"SELECT projeto, etapa_migracao, status_migracao FROM {T_PIPE}")
        except HTTPException as e:
            if not _objeto_ausente(e):
                raise
            return set()
        # pipe-etapa-status: real — DENOMINADOR, não exibição (ver o SELECT acima): a etapa
        # espelhada não pode fazer uma ex-dependência entrar no total só porque ganhou
        # sucessor (spec §4).
        et = {r.get("projeto"): r.get("etapa_migracao") for r in pipe}
        # pipe-etapa-status: real — o status GRAVADO decide a exceção da etapa fantasma
        # (Despriorizado e Contabilizado), que é regra de denominador, não de exibição.
        st = {r.get("projeto"): r.get("status_migracao") for r in pipe}
        return {p for p in ex if et.get(p) and (
            et.get(p) not in PHANTOM_ETAPAS_MIGRACAO
            or st.get(p) == "Despriorizado e Contabilizado")}
    return _cache_lineage(("ex_contab", frozenset(frontier), frozenset(base)), _p)


# --- area_principal: 1 área por input, lastreada no FRONTIER (escopo ∪ dependências) ---
# Regra (2026-07): o input é atribuído à área do EGP do frontier que o consome; entre as
# áreas candidatas Cobrança vence, senão a de maior nº de EGPs, empate -> alfabética; input
# sem nenhum EGP no frontier -> "(sem área)". A FONTE é o frontier (não só o escopo): uma
# dependência fora do escopo conta com a área do próprio nó — por isso os inputs que entram
# pelas "+Dependências" recebem a área da dependência. Ver docs/superpowers/specs/
# 2026-07-08-area-principal-input-design.md.
AREA_PREF = "Cobrança"
# Linha à parte do Funil por área (+deps) para o que só os extras leem — ver resumo().
AREA_EXTRAS = "Extras"


def _pick_area(votes):
    """votes: {área -> nº de EGPs do frontier que consomem o input naquela área}."""
    if not votes:
        return "(sem área)"
    if AREA_PREF in votes:
        return AREA_PREF
    top = max(votes.values())
    return sorted(a for a, c in votes.items() if c == top)[0]


def _frontier_via(exec_fn):
    """(frontier, base) de 'indi_deps' usando exec_fn — reproduz _frontier_egps('indi_deps', [])
    sem depender de run_sql/OBO: recompute_escopo aceita um exec_fn alternativo (sem token
    de usuário)."""
    def rd(sql):
        try:
            return exec_fn(sql, want_rows=True) or []
        except (HTTPException, RuntimeError) as e:
            if not _objeto_ausente(e):
                raise
            return []
    _ensure_input_pipeline_cols(exec_fn)
    edges = rd(f"SELECT projeto_alvo, depende_do, via_tabelas FROM {T_ED}")
    choices = {r["chave_canonica"]: r["projeto_escolhido"]
               for r in rd(f"SELECT chave_canonica, projeto_escolhido FROM {T_CHOICE}")
               if r.get("chave_canonica") and r.get("projeto_escolhido")}
    res = {(r.get("artifact") or "").strip().upper()
           for r in rd(f"SELECT artifact FROM {T_IN} WHERE categoria = 'tabela' AND ({_modern()})")
           if (r.get("artifact") or "").strip()}
    # NAO passar `_prod_declarado_escolhidas()` aqui: ele usa run_sql e este caminho roda sem
    # OBO (ver o comentario do no_expand abaixo). Como ele engole HTTPException e devolve
    # {}, a escolha de produtor deixaria de valer EM SILENCIO. O leitor injetado (`rd`) e
    # a forma correta neste caminho — e o self-heal por alias ja vive dentro de _prune_edges.
    pruned = _filter_vias_resolvidas_res(_prune_edges(edges, choices), res,
                                         _deps_mantidas_rd(rd))
    base = {r["projeto"] for r in rd(f"SELECT projeto FROM {T_ND} WHERE escopo_indi = true") if r.get("projeto")}
    # pipe-etapa-status: real — mesma pergunta do _egps_fora_backlog (estado gravado de
    # gestão). E aqui a leitura é obrigatoriamente crua por outro motivo: isto roda dentro
    # do recompute_escopo, com um exec_fn SEM OBO — nada aqui pode depender de run_sql,
    # que é o que os helpers de derivação (_vinculos_por_antecessor/_pipe_exibido) usam.
    no_expand = {r["projeto"] for r in
                 rd(f"SELECT projeto FROM {T_PIPE} WHERE status_migracao = 'Despriorizado e Contabilizado'")
                 if r.get("projeto")}
    return set(_transitive_upstream(base, _dep_of_map(pruned), no_expand=no_expand)), base


def _recompute_area_principal(exec_fn):
    """Reescreve sas_resumo_inputs.area_principal a partir do FRONTIER (escopo ∪ deps), via
    _pick_area. Reset em '(sem área)' + UPDATE por área (IN-list em blocos, dentro de MODIFY —
    sem CREATE/MERGE, como o resto do recompute). Chamado no fim de recompute_escopo."""
    frontier, _base = _frontier_via(exec_fn)
    exec_fn(f"UPDATE {T_RES} SET area_principal = '(sem área)'", want_rows=False)
    if not frontier:
        return
    inl = ", ".join(sql_lit(p) for p in frontier)
    proj_area = {r["projeto"]: r["area"] for r in
                 (exec_fn(f"SELECT projeto, area FROM {T_ND} WHERE projeto IN ({inl})", want_rows=True) or [])}
    in2proj = {}
    for r in (exec_fn(f"SELECT chave_canonica, projeto FROM {T_EGP} WHERE projeto IN ({inl})", want_rows=True) or []):
        in2proj.setdefault(r["chave_canonica"], []).append(r["projeto"])
    by_area = {}
    for ch, projs in in2proj.items():
        votes = {}
        for p in projs:
            a = proj_area.get(p)
            if a:
                votes[a] = votes.get(a, 0) + 1
        by_area.setdefault(_pick_area(votes), []).append(ch)
    for area, chaves in by_area.items():
        if area == "(sem área)":
            continue
        for i in range(0, len(chaves), 400):
            inlist = ", ".join(sql_lit(c) for c in chaves[i:i + 400])
            exec_fn(f"UPDATE {T_RES} SET area_principal = {sql_lit(area)} "
                    f"WHERE chave_canonica IN ({inlist})", want_rows=False)


@app.get("/api/scope-egps")
def scope_egps(scope: str = "indi", area: list[str] = Query(default=[])):
    """Quantidade de EGPs do recorte (scope + áreas) p/ correlacionar com os inputs no Monitor.

    Régua CONGELADA (29/09/2026): n_egps/n_base/n_deps/n_ex saem da LINHA DE BASE e da
    CLASSE gravada nela, não do grafo vivo — por isso `indi_deps` sem filtro de área dá
    sempre o mesmo número, em qualquer schema, cresça o corpus o quanto crescer. O filtro
    de ÁREA estreita a lista (a área é atributo vivo do nó); o de escopo escolhe as
    classes. `n_extra` é o contador PRÓPRIO dos extras: fica AO LADO, nunca dentro."""
    frontier, _base = _frontier_egps(scope, area)
    dec = linha_base.decomposicao(_linha_base_filtrada(area))
    # `indi` é o único recorte que exclui dependências e ex-dependências: é o escopo
    # direto. `indi_deps` e `base` ("todos") contam a lista inteira. `n_extra` não é "o
    # corpus fora da lista": é a enumeração (sucessor ∪ casca) dentro do recorte — o resto
    # do corpus fica fora do total sem entrar em contador nenhum, por decisão de 29/09.
    _so_escopo = scope == "indi"
    n_deps = 0 if _so_escopo else dec["dependencia"]
    n_ex = 0 if _so_escopo else dec["ex_dependencia"]
    return {"n_egps": dec["base"] + n_deps + n_ex, "n_base": dec["base"],
            "n_deps": n_deps, "n_ex": n_ex,
            "n_extra": len(_extras(frontier))}


@app.get("/api/egps-extras")
def egps_extras():
    """Os EXTRAS do recorte: quantos E QUAIS (régua congelada, 29/09/2026).

    O contador "(+N extra)" sozinho diz que chegou trabalho novo mas não diz o quê — e é
    justamente essa lista que a gestão precisa ver para decidir se um extra deve entrar
    numa próxima linha de base. `motivo` ∈ sucessor | casca, só para o detalhe: o filtro
    da aba EGPs continua com um valor só."""
    extras = _extras_no_recorte()
    if not extras:
        return {"n": 0, "rows": [], "projetos": []}
    vinc, casc, lb = _vinculos_por_antecessor(), _cascas(), _linha_base()
    novos, deps_novas = _egps_novos(), _deps_novas()
    try:
        area_of = _area_por_projeto()
    except HTTPException:
        area_of = {}
    rows = [{"projeto": p, "area": area_of.get(p),
             "motivo": vinculos.motivo_extra(p, lb, vinc, casc, novos=novos,
                                             deps_novas=deps_novas),
             "tipos": vinculos.tipos_do_extra(p, vinc, casc, novos, deps_novas)}
            for p in sorted(extras)]
    return {"n": len(rows), "rows": rows, "projetos": [r["projeto"] for r in rows]}


GRAPH_EDGE_CAP = 4000


@app.get("/api/lineage/areas")
def lineage_areas():
    def _produce():
        rows = run_sql(
            f"SELECT area, count(*) AS n, "
            f"sum(CASE WHEN escopo_indi THEN 1 ELSE 0 END) AS n_indi "
            f"FROM {T_ND} GROUP BY area ORDER BY area NULLS FIRST")
        return {"rows": rows}
    return _cache_lineage(("areas",), _produce)


@app.get("/api/lineage/search")
def lineage_search(q: str = "", scope: str = "", area: str = "", limit: int = 100):
    where = []
    if q:
        where.append(f"upper(projeto) LIKE upper({sql_lit('%' + q + '%')})")
    if scope == "indi":
        where.append("escopo_indi = true")
    if area:
        where.append(f"area = {sql_lit(area)}")
    wsql = (" WHERE " + " AND ".join(where)) if where else ""
    lim = max(1, min(int(limit), 5000))
    rows = run_sql(f"SELECT {NODE_COLS} FROM {T_ND}{wsql} "
                   f"ORDER BY escopo_indi DESC, projeto LIMIT {lim}")
    return {"rows": rows}


@app.get("/api/lineage/graph")
def _blocking():
    """Bloqueio transitivo. Leaf-blocker = EGP que le >=1 tabela SAS/Local sem produtor
    mapeado e ainda nao modernizada ("tabela SAS sem EGP"). Propaga dos leaf-blockers
    para todos os consumidores transitivos (quem depende deles, direta/indiretamente).
    Retorna leaf_tables {projeto -> [tabelas]}, blocked {set} e dep_of (consumer->produtores).
    Cacheado por OBO+TTL como a linhagem."""
    def _produce():
        _ensure_link_tables()
        _ensure_input_pipeline_cols()
        lnk = "coalesce(l.link_broken, false)"
        # arestas, candidatos e famílias não dependem um do outro: 1 onda, não 3 rodadas
        edges, cand, _fam = _parallel(
            _edges_pruned,
            lambda: run_sql(
                f"SELECT e.projeto AS projeto, i.artifact AS artifact "
                f"FROM {T_EGP} e JOIN {T_IN} i ON e.chave_canonica = i.chave_canonica "
                f"LEFT JOIN {T_LINK} l ON l.projeto = e.projeto AND l.chave_canonica = e.chave_canonica "
                f"WHERE i.categoria = 'tabela' AND NOT i.orfao "
                f"AND NOT ({_modern('i.etapa', 'i.modernizada_auto', 'i.status', lnk)}) "
                f"AND upper(i.source_types) LIKE '%SAS/LOCAL%'"),
            (_familias_corpus if FAMILIAS_ON else (lambda: None)))
        produced = set()
        for e in edges:
            for t in (e.get("via_tabelas") or "").split(" | "):
                t = t.strip().upper()
                if t:
                    produced.add(t)
        leaf = {}
        for r in cand:
            art = r.get("artifact") or ""
            if art and art.upper() not in produced:
                leaf.setdefault(r["projeto"], set()).add(art)
        dep_of = _dep_of_map(edges)
        cons_map = {}
        for e in edges:
            a, d = e["projeto_alvo"], e["depende_do"]
            if a and d and a != d:
                cons_map.setdefault(d, set()).add(a)
        blocked = set(_transitive_upstream(set(leaf.keys()), cons_map).keys())
        out = {"leaf_tables": {k: sorted(v) for k, v in leaf.items()},
               "blocked": blocked, "dep_of": dep_of}
        if FAMILIAS_ON:
            # tabela leaf -> NOME da família (identidade quando não tem família). Serve a
            # dois consumidores: o front agrupa as causas-raiz por família sem conhecer a
            # regra (ela fica no servidor), e `leaf_tables` passa a listar famílias — senão
            # o drawer do EGP mostraria 47 tabelas bloqueadoras que são uma só.
            mapa = _fam["chave"]
            fam_de = {}
            for tabs in leaf.values():
                for t in tabs:
                    up = t.upper()
                    fam_de[up] = mapa.get(("tabela", up), up)
            out["familia_de"] = fam_de
            out["leaf_tables"] = {p: sorted({fam_de.get(t.upper(), t) for t in tabs})
                                  for p, tabs in out["leaf_tables"].items()}
        return out
    return _cache_lineage(("blocking",), _produce)


def lineage_graph(area: str = "", scope: str = "", mode: str = "", deps: bool = True):
    """Subgrafo em lote. base = nós que casam (area / scope=indi); mode=all = tudo.
    deps=true inclui arestas que TOCAM a base (puxa vizinhos externos);
    deps=false só arestas internas à base."""
    def _produce():
        conds = []
        if area:
            conds.append(f"area = {sql_lit(area)}")
        if scope == "indi":
            conds.append("escopo_indi = true")
        if not conds and mode != "all":
            raise HTTPException(400, "informe area, scope=indi ou mode=all")
        wsql = (" WHERE " + " AND ".join(conds)) if conds else ""
        base = {r["projeto"] for r in run_sql(f"SELECT projeto FROM {T_ND}{wsql}")}
        raw = run_sql(f"SELECT depende_do AS dep, projeto_alvo AS alvo, via_tabelas AS via FROM {T_ED}")
        sel = []
        for e in raw:
            din, ain = e["dep"] in base, e["alvo"] in base
            if mode == "all" or (deps and (din or ain)) or (not deps and din and ain):
                sel.append(e)
        capped = len(sel) > GRAPH_EDGE_CAP
        sel = sel[:GRAPH_EDGE_CAP]
        ids = set(base)
        for e in sel:
            ids.add(e["dep"])
            ids.add(e["alvo"])
        edges = [{"from": e["dep"], "to": e["alvo"], "via": e["via"]} for e in sel]
        return {"nodes": _fetch_nodes(ids), "edges": edges, "capped": capped}
    return _cache_lineage(("graph", area, scope, mode, deps), _produce)


@app.get("/api/lineage/neighbors")
def lineage_neighbors(node: str, dir: str = "both"):
    def _produce():
        nlit = sql_lit(node)
        # aresta = produtor (depende_do) -> consumidor (projeto_alvo)
        raw = []
        if dir in ("up", "both"):   # o que `node` consome (depende)
            raw += run_sql(f"SELECT depende_do AS dep, projeto_alvo AS alvo, via_tabelas AS via "
                           f"FROM {T_ED} WHERE projeto_alvo = {nlit}")
        if dir in ("down", "both"):  # quem consome `node`
            raw += run_sql(f"SELECT depende_do AS dep, projeto_alvo AS alvo, via_tabelas AS via "
                           f"FROM {T_ED} WHERE depende_do = {nlit}")
        seen, edges, ids = set(), [], {node}
        for r in raw:
            key = (r["dep"], r["alvo"])
            if key in seen:
                continue
            seen.add(key)
            edges.append({"from": r["dep"], "to": r["alvo"], "via": r.get("via")})
            ids.add(r["dep"])
            ids.add(r["alvo"])
        return {"nodes": _fetch_nodes(ids), "edges": edges, "root": node}
    return _cache_lineage(("neighbors", node, dir), _produce)


# ---- aba EGP (projeto -> inputs + dependências) ----
@app.get("/api/egp")
def egp_detail(projeto: str):
    """Payload cacheado por identidade OBO + projeto + geração (ver _cache_endpoint)."""
    return _cache_endpoint(("egp", projeto), lambda: _egp_detail_uncached(projeto))


def _egp_detail_uncached(projeto: str):
    plit = sql_lit(projeto)
    _ensure_node_metric_cols()

    def _inputs_q():
        _ensure_link_tables()
        _ensure_input_pipeline_cols()
        return run_sql(
            f"SELECT e.chave_canonica, e.artifact, e.categoria, e.source_types, e.modernizada_auto, "
            f"i.origem, i.etapa, i.status, i.responsavel, i.observacao, "
            f"i.paths_fisicos, i.n_paths_fisicos, "
            f"coalesce(l.link_broken, false) AS link_broken "
            f"FROM {T_EGP} e LEFT JOIN {T_IN} i ON e.chave_canonica = i.chave_canonica "
            f"LEFT JOIN {T_LINK} l ON l.projeto = e.projeto AND l.chave_canonica = e.chave_canonica "
            f"WHERE e.projeto = {plit} ORDER BY e.categoria, e.artifact")

    def _pr_q():
        try:
            # pipe-etapa-status: real — leitura crua da linha deste EGP; jira/responsáveis
            # saem daqui e etapa/status viram o fallback de `_pipe_exibido()` lá embaixo.
            return run_sql(f"SELECT etapa_migracao, status_migracao, jira_id, "
                           f"responsavel, responsavel_bv "
                           f"FROM {T_PIPE} WHERE projeto = {plit}")
        except HTTPException as e:
            if not _objeto_ausente(e):
                raise
            return []

    # onda 1: leituras independentes em paralelo (teto _PAR_MAX); _edges_pruned/
    # _blocking/_egps_fora_backlog costumam estar cache-quentes (a aba EGPs aquece).
    node, inputs, _pe, _ndm_rows, pr, _bl, _fora, _san = _parallel(
        lambda: run_sql(f"SELECT projeto, area, onda, escopo_indi, n_inputs, n_outputs, ciclo_id, "
                        f"loc, code_tasks_count, n_outputs_avaliados, n_outputs_consumidos_por_outro_egp, "
                        f"pct_outputs_consumidos_por_outro_egp, n_egps_consumidores, n_exports_arquivos, "
                        f"flag_output_100pct_egp, flag_algum_output_egp, flag_sem_export_arquivo, "
                        f"flag_output_unico, flag_hub_multiplos_consumidores "
                        f"FROM {T_ND} WHERE projeto = {plit}"),
        _inputs_q, _edges_pruned,
        lambda: run_sql(f"SELECT projeto, area, onda, ciclo_id FROM {T_ND}"),
        _pr_q, _blocking, _egps_fora_backlog, _sanitizacao_derivada)
    if not node:
        raise HTTPException(404, "EGP não encontrado")
    node = node[0]
    # Statement Execution API serializa bool como string ("true"/"false"); coerção
    # explícita p/ FastAPI enviar JSON bool, senão o front lê 'false' como truthy.
    for i in inputs:
        i["link_broken"] = str(i.get("link_broken")).lower() == "true"
    # sanitização derivada também no drawer (14/10/2026): sem ela, o input que a aba Inputs
    # mostra como Modernizado + Sanitizado aparecia aqui com a etapa/status crus e
    # editáveis — o mesmo caminho da marcação manual que tirou 37 inputs da derivação.
    # ANTES da agregação, na ordem de `_dataset_escopo` (os motivos são por safra).
    sanitizacao.aplica_em_linhas(inputs, _san)
    # grão FAMÍLIA também aqui (18/09/2026): o cabeçalho do painel já conta por família
    # (n_faltam vem de /api/egp-readiness) e a lista mostrava as safras uma a uma — a
    # mesma tela dizia "45 de 69" e listava 87 linhas. Régua do CORPUS, igual à aba
    # Inputs; o roll-up do vínculo vive em _agrega_familias.
    if FAMILIAS_ON:
        inputs = _agrega_familias(inputs)
    # arestas ja podadas pela escolha de produtor canonico (consistente com o recorte)
    _ndm = {n["projeto"]: n for n in _ndm_rows}
    def _via_n(v):
        return len([t for t in (v or "").split(" | ") if t.strip()])
    depende_de = sorted(
        ({"projeto": e["depende_do"], "via_tabelas": e["via_tabelas"], "qtd_via": _via_n(e["via_tabelas"]),
          "area": _ndm.get(e["depende_do"], {}).get("area"), "onda": _ndm.get(e["depende_do"], {}).get("onda"),
          "ciclo_id": _ndm.get(e["depende_do"], {}).get("ciclo_id")}
         for e in _pe if e["projeto_alvo"] == projeto), key=lambda x: x["projeto"] or "")
    alimenta = sorted(
        ({"projeto": e["projeto_alvo"], "via_tabelas": e["via_tabelas"], "qtd_via": _via_n(e["via_tabelas"]),
          "area": _ndm.get(e["projeto_alvo"], {}).get("area"), "onda": _ndm.get(e["projeto_alvo"], {}).get("onda"),
          "ciclo_id": _ndm.get(e["projeto_alvo"], {}).get("ciclo_id")}
         for e in _pe if e["depende_do"] == projeto), key=lambda x: x["projeto"] or "")
    # status de migração dos relacionados -> selo "Migrado"/"Despriorizado" no painel
    rel = {d["projeto"] for d in depende_de} | {a["projeto"] for a in alimenta}

    def _st_rel_q():
        if not rel:
            return {}
        try:
            _inl = ", ".join(sql_lit(x) for x in rel)
            _vinc = _vinculos_por_antecessor()
            # DERIVADO: é o selo de status do EGP relacionado — exibição. Só precisa do
            # vínculo do próprio relacionado (o status não é espelho de ninguém: §3.2.8),
            # então não paga o mapa inteiro. Na prática o selo não muda hoje, e de
            # propósito: "Migrado" não pode ser antecessor (o PATCH recusa) e
            # "Despriorizado e Contabilizado" vence o derivado (§3.2.9).
            # pipe-etapa-status: derivado.
            return {r["projeto"]: vinculos.status_exibido(
                r.get("status_migracao"), (_vinc.get(r["projeto"]) or {}).get("tipo"))
                for r in run_sql(
                    f"SELECT projeto, status_migracao FROM {T_PIPE} WHERE projeto IN ({_inl})")}
        except HTTPException as e:
            if not _objeto_ausente(e):
                raise
            return {}

    def _ciclo_q():
        cid = int(node.get("ciclo_id") or 0)
        if cid <= 0:
            return []
        return run_sql(
            f"SELECT projeto, area, onda FROM {T_ND} WHERE ciclo_id = {cid} AND projeto <> {plit} "
            f"ORDER BY projeto")

    def _ativos_q():
        # #Proj Ativos Dentro do Escopo: consumidores de cada input que estão no recorte
        # indi_deps (escopo Indicium ∪ dependências) E NÃO estão despriorizados. O frontier
        # ainda inclui despriorizados que são base Indicium (nível 0, não expandem) — por isso
        # subtraímos _fora explicitamente. Pares (projeto, chave) com vínculo quebrado saem da
        # contagem: o EGP declarou não depender do input, então não é consumidor "ativo".
        # 0 => nenhum EGP vivo do escopo consome o input.
        _chaves = {i["chave_canonica"] for i in inputs if i.get("chave_canonica")}
        if not _chaves:
            return None
        try:
            _ativo_set = _frontier_egps("indi_deps", [])[0] - _fora
            if not _ativo_set:
                return {}
            _cin = ", ".join(sql_lit(c) for c in _chaves)
            _pin = ", ".join(sql_lit(p) for p in _ativo_set)
            return {r["chave_canonica"]: int(r["n"]) for r in run_sql(
                f"SELECT e.chave_canonica, count(DISTINCT e.projeto) AS n FROM {T_EGP} e "
                f"LEFT JOIN {T_LINK} l ON l.projeto = e.projeto AND l.chave_canonica = e.chave_canonica "
                f"WHERE e.chave_canonica IN ({_cin}) AND e.projeto IN ({_pin}) "
                f"AND NOT coalesce(l.link_broken, false) GROUP BY e.chave_canonica")}
        except HTTPException:
            return None

    # onda 2: dependem de node/inputs/arestas da onda 1, mas não entre si
    # (_pipe_exibido entra aqui só p/ não pagar serial o round-trip do mapa quando o
    # drawer é aberto por deep-link, com o cache de linhagem frio)
    st_rel, em_ciclo_com, _ativos, _exib_egp = _parallel(
        _st_rel_q, _ciclo_q, _ativos_q, _pipe_exibido)
    for d in depende_de:
        d["status"] = st_rel.get(d["projeto"])
    for a in alimenta:
        a["status"] = st_rel.get(a["projeto"])
    p0 = pr[0] if pr else {}
    # DERIVADO: o drawer abre EM CIMA da linha da aba EGPs, que já mostra a etapa
    # espelhada — discordarem aqui é o mesmo defeito, um clique adiante. A edição segue
    # protegida onde importa: o PATCH recusa a etapa espelhada (§3.2.7) e a aba desabilita
    # o <select> por `etapa_editavel`. Mapa vazio (tabela ausente) -> cai no valor cru.
    # pipe-etapa-status: derivado — etapa espelhada + status `Desatualizado`.
    _et_exib, _st_exib = _exib_egp.get(
        projeto, (p0.get("etapa_migracao"), p0.get("status_migracao")))
    pipeline = {
        "migracao": {"etapa": _et_exib, "status": _st_exib,
                     "jira_id": p0.get("jira_id"), "responsavel": p0.get("responsavel"),
                     "responsavel_bv": p0.get("responsavel_bv")},
    }
    _up = _transitive_upstream({projeto}, _bl["dep_of"])
    _deps_bloq = [{"projeto": p, "tabelas": _bl["leaf_tables"][p]}
                  for p in sorted(_up) if p != projeto and p in _bl["leaf_tables"]]
    _proprias = _bl["leaf_tables"].get(projeto, [])
    bloqueio = {"bloqueado": bool(_proprias or _deps_bloq),
                "proprias": _proprias, "deps_bloqueadoras": _deps_bloq}
    # dependencia (transitiva) DESPRIORIZADA: o dependente precisa ver o impacto — o
    # produtor saiu do backlog e o output que este EGP consome nao sera migrado por ele.
    _deps_desp = sorted(p for p in _up if p != projeto and p in _fora)
    impacto_despriorizado = {"impactado": bool(_deps_desp), "deps": _deps_desp}
    for i in inputs:
        i["n_proj_ativos"] = _ativos.get(i["chave_canonica"], 0) if _ativos is not None else None
    return {"node": node, "inputs": inputs, "depende_de": depende_de,
            "alimenta": alimenta, "em_ciclo_com": em_ciclo_com, "pipeline": pipeline,
            "bloqueio": bloqueio, "impacto_despriorizado": impacto_despriorizado}


class EgpPipe(BaseModel):
    projeto: str
    funil: str = "migracao"
    etapa: str | None = None
    status: str | None = None
    responsavel: str | None = None
    responsavel_bv: str | None = None
    jira_id: str | None = None
    preworking: bool | None = None
    preworking_data: str | None = None   # "YYYY-MM-DD", 100% manual (não é setada por automação)
    egp_atualizado_key: str | None = None  # vínculo manual p/ sas_egp_atualizados.egp_key ("" limpa)
    # Vínculo REAL antecessor -> sucessor (spec 2026-09-24 §1). Aponta para o PROJETO do
    # corpus (Área__nome__ATU<data>), não para a chave da aba — são chaves diferentes, e a
    # egp_atualizado_key acima segue sendo a sugestão da chegada.
    egp_vinculo_tipo: str | None = None    # Atualizado | Substituído | Unificado ("" limpa)
    egp_sucessor: str | None = None        # projeto do corpus ("" limpa)


@functools.lru_cache(maxsize=1)
def _ensure_pipe_table():
    if dialeto.PG:  # no Postgres o schema vem das migrações (db/migrations), nunca do app
        return True
    # pipe-etapa-status: real — DDL da tabela de estado. O derivado não existe no banco.
    run_sql(f"""CREATE TABLE IF NOT EXISTS {T_PIPE} (projeto STRING,
  etapa_migracao STRING, status_migracao STRING, etapa_progresso STRING, status_progresso STRING,
  responsavel STRING, responsavel_bv STRING, jira_id STRING, updated_by STRING, updated_at STRING) USING DELTA""",
            want_rows=False)
    try:
        run_sql(f"SELECT responsavel FROM {T_PIPE} LIMIT 0")
    except HTTPException:
        run_sql(f"ALTER TABLE {T_PIPE} ADD COLUMNS (responsavel STRING)", want_rows=False)
    try:
        run_sql(f"SELECT mes_prioridade FROM {T_PIPE} LIMIT 0")
    except HTTPException:
        run_sql(f"ALTER TABLE {T_PIPE} ADD COLUMNS (mes_prioridade INT)", want_rows=False)
    try:
        run_sql(f"SELECT jira_id FROM {T_PIPE} LIMIT 0")
    except HTTPException:
        run_sql(f"ALTER TABLE {T_PIPE} ADD COLUMNS (jira_id STRING)", want_rows=False)
    try:
        run_sql(f"SELECT responsavel_bv FROM {T_PIPE} LIMIT 0")
    except HTTPException:
        run_sql(f"ALTER TABLE {T_PIPE} ADD COLUMNS (responsavel_bv STRING)", want_rows=False)
    try:
        run_sql(f"SELECT preworking_preenchido FROM {T_PIPE} LIMIT 0")
    except HTTPException:
        run_sql(f"ALTER TABLE {T_PIPE} ADD COLUMNS (preworking_preenchido STRING)", want_rows=False)
    try:
        run_sql(f"SELECT preworking_data FROM {T_PIPE} LIMIT 0")
    except HTTPException:
        run_sql(f"ALTER TABLE {T_PIPE} ADD COLUMNS (preworking_data STRING)", want_rows=False)
    try:
        run_sql(f"SELECT egp_atualizado_key FROM {T_PIPE} LIMIT 0")
    except HTTPException:
        run_sql(f"ALTER TABLE {T_PIPE} ADD COLUMNS (egp_atualizado_key STRING)", want_rows=False)
    for _col in ("egp_vinculo_tipo", "egp_sucessor"):
        try:
            run_sql(f"SELECT {_col} FROM {T_PIPE} LIMIT 0")
        except HTTPException:
            run_sql(f"ALTER TABLE {T_PIPE} ADD COLUMNS ({_col} STRING)", want_rows=False)
    run_sql(f"""CREATE TABLE IF NOT EXISTS {T_PIPE_AUD} (id STRING, projeto STRING, funil STRING,
  campo STRING, valor_antigo STRING, valor_novo STRING, ator STRING, ts STRING) USING DELTA""",
            want_rows=False)
    return True


# campo da lógica pura (vinculos.CAMPOS_COPIADOS) -> coluna de sas_egp_pipeline
# pipe-etapa-status: real — mapa de ESCRITA (a cópia do §3.3.11 grava na tabela).
_COPIA_COLS = {"etapa": "etapa_migracao", "mes_prioridade": "mes_prioridade",
               "jira_id": "jira_id", "responsavel": "responsavel"}


def _copia_trabalho_para_sucessor(sucessor: str, origem: dict):
    """Leva o trabalho de gestão do antecessor para o sucessor NO ATO do vínculo (§3.3.11).

    É o que faz quem executa achar o trabalho no lugar certo sem remontar o contexto à
    mão — e é também o que impede o antecessor de sumir da coluna do funil +deps no
    instante do vínculo, espelhando a etapa vazia de um sucessor recém-chegado ao corpus.

    Uma cópia, não uma sincronização: daqui em diante os dois divergem livremente. Quem
    decide o QUE copiar é `vinculos.campos_copiados_no_vinculo` (status fica de fora — §3.5.21).
    Devolve os campos efetivamente copiados.
    """
    # pipe-etapa-status: real — o destino da cópia é a linha GRAVADA do sucessor, e a
    # guarda de cadeia (v1 -> v2 -> v3) precisa saber se a etapa DELE já é espelho.
    cur = run_sql(f"SELECT etapa_migracao AS etapa, mes_prioridade AS mes_prioridade, "
                  f"jira_id AS jira_id, responsavel AS responsavel, "
                  f"egp_vinculo_tipo AS vinc_tipo, egp_sucessor AS sucessor "
                  f"FROM {T_PIPE} WHERE projeto = {sql_lit(sucessor)}")
    destino = cur[0] if cur else {}
    # o sucessor também pode ser antecessor de outro (cadeia v1 -> v2 -> v3): lá a etapa
    # DELE já é espelho e o servidor recusa a escrita — a cópia respeita a mesma guarda.
    espelhado = bool(destino.get("sucessor")) and vinculos.espelha(destino.get("vinc_tipo"))
    campos = vinculos.campos_copiados_no_vinculo(origem, destino, espelhado)
    if not campos:
        return {}
    # mes_prioridade é INT na tabela: literal sem aspas (sql_lit gravaria string).
    lits = {c: (str(int(v)) if c == "mes_prioridade" else sql_lit(v)) for c, v in campos.items()}
    cols = [_COPIA_COLS[c] for c in campos]
    run_sql(
        f"MERGE INTO {T_PIPE} t USING (SELECT {sql_lit(sucessor)} AS projeto) s ON t.projeto = s.projeto "
        f"WHEN MATCHED THEN UPDATE SET "
        + ", ".join(f"{_COPIA_COLS[c]} = {lits[c]}" for c in campos)
        + f", updated_by = {_ator()}, updated_at = cast({AGORA} AS STRING) "
        f"WHEN NOT MATCHED THEN INSERT (projeto, {', '.join(cols)}, updated_by, updated_at) "
        f"VALUES ({sql_lit(sucessor)}, {', '.join(lits[c] for c in campos)}, {_ator()}, "
        f"cast({AGORA} AS STRING))", want_rows=False)
    for campo, valor in campos.items():
        run_sql(
            f"INSERT INTO {T_PIPE_AUD} (id, projeto, funil, campo, valor_antigo, valor_novo, ator, ts) "
            f"VALUES ({sql_lit(uuid.uuid4().hex)}, {sql_lit(sucessor)}, 'migracao', "
            f"{sql_lit(_COPIA_COLS[campo])}, {sql_lit(_norm(destino.get(campo)))}, "
            f"{sql_lit(_norm(valor))}, {_ator()}, cast({AGORA} AS STRING))",
            want_rows=False)
    return campos


@app.patch("/api/egp-pipeline")
def egp_pipeline(p: EgpPipe):
    """Grava etapa+status de 1 EGP num funil de projeto (upsert em sas_egp_pipeline) + auditoria.
    Alimenta os funis da landing na hora (React Query invalida ['funis'])."""
    if p.funil != "migracao":
        raise HTTPException(400, "só funil migracao")
    if (p.etapa not in (None, "") and p.etapa not in PIPELINE_PROJETO[p.funil]
            and p.etapa not in PHANTOM_ETAPAS_MIGRACAO):
        raise HTTPException(400, f"etapa inválida: {p.etapa}")
    if p.status not in (None, "") and p.status not in STATUS_PROJETO:
        raise HTTPException(400, f"status inválido: {p.status}")
    if p.jira_id not in (None, "") and not JIRA_ID_RE.match(p.jira_id):
        raise HTTPException(400, f"jira_id inválido: {p.jira_id} (esperado formato PROJ-123)")
    if p.egp_atualizado_key not in (None, ""):
        ok = run_sql(f"SELECT 1 FROM {T_ATU} WHERE egp_key = {sql_lit(p.egp_atualizado_key)} LIMIT 1")
        if not ok:
            raise HTTPException(404, "EGP atualizado não encontrado")
    if p.egp_vinculo_tipo:
        if not vinculos.tipo_valido(p.egp_vinculo_tipo):
            raise HTTPException(400, f"tipo de vínculo inválido: {p.egp_vinculo_tipo}")
    # Gate de gestão SÓ dos campos de vínculo (spec §3.5.19): este endpoint é aberto para
    # etapa/status desde sempre, e fechá-lo inteiro tiraria de todo mundo uma edição que
    # hoje funciona. Vem antes da leitura: quem não pode nem chega a consultar.
    if p.egp_vinculo_tipo is not None or p.egp_sucessor is not None:
        _require_gestao()
    # pipe-etapa-status: real — colunas de ESCRITA. `Desatualizado` nem é valor gravável
    # (não está em STATUS_PROJETO); o que a tela mostra é derivado na leitura.
    et_col = "etapa_migracao" if p.funil == "migracao" else "etapa_progresso"
    st_col = "status_migracao" if p.funil == "migracao" else "status_progresso"  # pipe-etapa-status: real (escrita)
    _ensure_pipe_table()
    cur = run_sql(f"SELECT {et_col} AS et, {st_col} AS st, responsavel AS resp, responsavel_bv AS resp_bv, "
                  f"jira_id AS jira, preworking_preenchido AS pw, preworking_data AS pw_data, "
                  f"egp_atualizado_key AS atu_key, egp_vinculo_tipo AS vinc_tipo, "
                  f"egp_sucessor AS sucessor, mes_prioridade AS mes "
                  f"FROM {T_PIPE} WHERE projeto = {sql_lit(p.projeto)}")
    old = cur[0] if cur else {}
    # Guardas do vínculo (spec §2 etapa 3, §3.2.7 e §4). Tudo aqui RECUSA — nunca decide
    # sozinho: estado que o app não sabe reconciliar é melhor falhar alto do que adivinhar.
    if p.egp_sucessor:
        # AUTO-VÍNCULO: o EGP não sucede a si mesmo. Não é hipótese — o pareamento
        # SUGERE isso sozinho quando o `egp_key` de sas_egp_atualizados coincide com o
        # projeto do corpus (a chave de CHEGADA é igual à do projeto). Medido em
        # 02/10/2026: 2 das 26 sugestões eram `X -> X`. `fim_do_espelho` e
        # `cadeia_de_sucessores` sobrevivem ao ciclo, mas os dois docstrings já diziam
        # "que o app não deveria permitir" — e o resultado seria um EGP extra, espelhando
        # a própria etapa, impossível de explicar em tela.
        if p.egp_sucessor == p.projeto:
            raise HTTPException(409, "um EGP não pode ser sucessor de si mesmo — a chave "
                                     "de chegada coincide com o projeto do corpus; "
                                     "confirme qual é o antecessor de verdade")
        if not run_sql(f"SELECT projeto FROM {T_ND} WHERE projeto = {sql_lit(p.egp_sucessor)} LIMIT 1"):
            raise HTTPException(404, f"sucessor '{p.egp_sucessor}' não está no corpus — rode o "
                                     "pipeline (extrator + orquestrador + publish) antes de vincular")
        # Migrado é terminal: EGP em produção e validado não recebe sucessor. Não deve
        # acontecer (em 24/09/2026 nenhum antecessor estava nesse status); se acontecer, o
        # app recusa em vez de inventar regra.
        if old.get("st") == "Migrado":
            raise HTTPException(409, "EGP com status Migrado não recebe sucessor — reabra o "
                                     "status antes de vincular")
    # Etapa espelhada é read-only no SERVIDOR, não só na tela: só no front, a próxima
    # integração escreveria por baixo.
    _tipo_efetivo = (p.egp_vinculo_tipo if p.egp_vinculo_tipo is not None
                     else old.get("vinc_tipo")) or None
    if p.etapa is not None and not vinculos.pode_editar_etapa(_tipo_efetivo):
        raise HTTPException(409, "etapa espelhada do sucessor — edite a etapa no EGP sucessor")
    # campo não enviado → preserva o atual; vazio ("") → NULL (não grava string vazia)
    et_new = (p.etapa if p.etapa is not None else old.get("et")) or None
    st_new = (p.status if p.status is not None else old.get("st")) or None
    resp_new = (p.responsavel if p.responsavel is not None else old.get("resp")) or None
    respbv_new = (p.responsavel_bv if p.responsavel_bv is not None else old.get("resp_bv")) or None
    jira_new = (p.jira_id if p.jira_id is not None else old.get("jira")) or None
    # booleano (não string): None enviado preserva; True/False é valor explícito válido,
    # não pode cair no "or None" das strings acima (False viraria None por engano).
    pw_new = ("true" if p.preworking else "false") if p.preworking is not None else (old.get("pw") or "false")
    pwdata_new = (p.preworking_data if p.preworking_data is not None else old.get("pw_data")) or None
    atukey_new = (p.egp_atualizado_key if p.egp_atualizado_key is not None else old.get("atu_key")) or None
    tipo_new = (p.egp_vinculo_tipo if p.egp_vinculo_tipo is not None else old.get("vinc_tipo")) or None
    suc_new = (p.egp_sucessor if p.egp_sucessor is not None else old.get("sucessor")) or None
    # WHEN MATCHED grava SÓ os campos enviados. O front manda um campo por PATCH; regravar
    # todos com o `old` lido acima fazia dois PATCHes concorrentes no mesmo EGP (etapa e,
    # logo depois, status) se desfazerem — o segundo devolvia a etapa antiga (lost update).
    # Linha nova (NOT MATCHED) segue inserindo tudo: não há valor concorrente a preservar.
    _sets = [(et_col, et_new, p.etapa), (st_col, st_new, p.status),
             ("responsavel", resp_new, p.responsavel),
             ("responsavel_bv", respbv_new, p.responsavel_bv),
             ("jira_id", jira_new, p.jira_id), ("preworking_preenchido", pw_new, p.preworking),
             ("preworking_data", pwdata_new, p.preworking_data),
             ("egp_atualizado_key", atukey_new, p.egp_atualizado_key),
             ("egp_vinculo_tipo", tipo_new, p.egp_vinculo_tipo),
             ("egp_sucessor", suc_new, p.egp_sucessor)]
    set_sql = "".join(f"{col} = {sql_lit(val)}, " for col, val, enviado in _sets
                      if enviado is not None)
    run_sql(
        f"MERGE INTO {T_PIPE} t USING (SELECT {sql_lit(p.projeto)} AS projeto) s ON t.projeto = s.projeto "
        f"WHEN MATCHED THEN UPDATE SET {set_sql}"
        f"updated_by = {_ator()}, updated_at = cast({AGORA} AS STRING) "
        f"WHEN NOT MATCHED THEN INSERT (projeto, {et_col}, {st_col}, responsavel, responsavel_bv, jira_id, "
        f"preworking_preenchido, preworking_data, egp_atualizado_key, egp_vinculo_tipo, "
        f"egp_sucessor, updated_by, updated_at) VALUES "
        f"({sql_lit(p.projeto)}, {sql_lit(et_new)}, {sql_lit(st_new)}, {sql_lit(resp_new)}, {sql_lit(respbv_new)}, {sql_lit(jira_new)}, "
        f"{sql_lit(pw_new)}, {sql_lit(pwdata_new)}, {sql_lit(atukey_new)}, {sql_lit(tipo_new)}, "
        f"{sql_lit(suc_new)}, {_ator()}, cast({AGORA} AS STRING))", want_rows=False)
    audits = []
    if p.etapa is not None and _norm(p.etapa) != _norm(old.get("et")):
        audits.append(("etapa", _norm(old.get("et")), _norm(p.etapa)))
    if p.status is not None and _norm(p.status) != _norm(old.get("st")):
        audits.append(("status", _norm(old.get("st")), _norm(p.status)))
    if p.responsavel is not None and _norm(p.responsavel) != _norm(old.get("resp")):
        audits.append(("responsavel", _norm(old.get("resp")), _norm(p.responsavel)))
    if p.responsavel_bv is not None and _norm(p.responsavel_bv) != _norm(old.get("resp_bv")):
        audits.append(("responsavel_bv", _norm(old.get("resp_bv")), _norm(p.responsavel_bv)))
    if p.jira_id is not None and _norm(p.jira_id) != _norm(old.get("jira")):
        audits.append(("jira_id", _norm(old.get("jira")), _norm(p.jira_id)))
    if p.preworking is not None and pw_new != (old.get("pw") or "false"):
        audits.append(("preworking_preenchido", old.get("pw") or "false", pw_new))
    if p.preworking_data is not None and _norm(p.preworking_data) != _norm(old.get("pw_data")):
        audits.append(("preworking_data", _norm(old.get("pw_data")), _norm(p.preworking_data)))
    if p.egp_atualizado_key is not None and _norm(p.egp_atualizado_key) != _norm(old.get("atu_key")):
        audits.append(("egp_atualizado_key", _norm(old.get("atu_key")), _norm(p.egp_atualizado_key)))
    if p.egp_vinculo_tipo is not None and _norm(p.egp_vinculo_tipo) != _norm(old.get("vinc_tipo")):
        audits.append(("egp_vinculo_tipo", _norm(old.get("vinc_tipo")), _norm(p.egp_vinculo_tipo)))
    if p.egp_sucessor is not None and _norm(p.egp_sucessor) != _norm(old.get("sucessor")):
        audits.append(("egp_sucessor", _norm(old.get("sucessor")), _norm(p.egp_sucessor)))
    for campo, va, vn in audits:
        run_sql(
            f"INSERT INTO {T_PIPE_AUD} (id, projeto, funil, campo, valor_antigo, valor_novo, ator, ts) "
            f"VALUES ({sql_lit(uuid.uuid4().hex)}, {sql_lit(p.projeto)}, {sql_lit(p.funil)}, "
            f"{sql_lit(campo)}, {sql_lit(va)}, {sql_lit(vn)}, {_ator()}, "
            f"cast({AGORA} AS STRING))", want_rows=False)
    # No ATO do vínculo o trabalho de gestão vai junto para o sucessor (§3.3.11). Depois do
    # MERGE acima: a etapa copiada é a que o antecessor acabou de ficar.
    if vinculos.vinculo_criado_agora(tipo_new, suc_new, old.get("vinc_tipo"), old.get("sucessor")):
        # destino = o FIM da cadeia de espelhamento, não o sucessor direto: é de lá que a
        # etapa exibida sai (`fim_do_espelho`). Escrevendo no sucessor direto quando ele
        # também espelha, a cópia caía na própria guarda de cadeia e não copiava nada — foi
        # assim que 2 EGPs da linha de base ficaram sem etapa em 29/09.
        _destino = vinculos.fim_do_espelho(suc_new, _vinculos_por_antecessor())
        _copia_trabalho_para_sucessor(_destino, {
            "etapa": et_new, "mes_prioridade": old.get("mes"),
            "jira_id": jira_new, "responsavel": resp_new})
    _bump_gen()   # T_PIPE alimenta readiness/frontier/gestão — invalida payloads
    return {"ok": True, "etapa": et_new or None, "status": st_new or None,
            "responsavel": resp_new or None, "responsavel_bv": respbv_new or None,
            "jira_id": jira_new or None, "preworking": pw_new == "true", "preworking_data": pwdata_new or None,
            "egp_atualizado_key": atukey_new or None}


# ---- prontidão por EGP (% de inputs modernizados = pode começar a migrar?) ----
def _egp_readiness_rows(scope: str = "indi"):
    """Computa a prontidão por EGP (n_inputs/n_disp/n_faltam/pct), n_deps e o
    status/etapa do pipeline de migração. Helper compartilhado por /api/egp-readiness
    e /api/egp-readiness?scope=indi_deps (que hidrata p/ TODOS os EGPs e filtra a frontier) — fonte
    única da hidratação de cada EGP, p/ não divergir. scope='indi' restringe a EGPs do
    escopo Indicium; qualquer outro valor inclui todos.

    Sanitizado é excluído das CONTAGENS (n_inputs/n_disp), NÃO do universo de EGPs — senão
    um EGP cujos inputs foram TODOS sanitizados sumiria da lista da aba EGPs (mismatch com
    scope-egps, que conta EGPs do frontier via T_ND). pct=100 quando n_inputs=0 alinha com
    o `_stub` do caminho indi_deps (nada a modernizar = feito)."""
    _ensure_link_tables()
    _ensure_input_pipeline_cols()
    _ensure_node_metric_cols()
    where = "WHERE e.escopo_indi = true" if scope == "indi" else ""
    # vínculo quebrado OU sanitização derivada (§3.4.15/18) — ver _lnk_resolvido.
    lnk = _lnk_resolvido()
    san = _sanitizado("i.etapa", "e.modernizada_auto", "i.status", lnk)
    mod = _modern("i.etapa", "e.modernizada_auto", "i.status", lnk)
    # outputs por EGP (aba Outputs): "disponível" = recebimento MANUAL (sas_outputs_pipeline,
    # preenchido pelo side panel da Gestão — ver /api/output-pipeline) quando já tocado;
    # SUBSTITUI modernizada_auto (detecção automática Chameleon/BQ), que vira só informativo
    # na UI. Enquanto ninguém tocou o manual daquele output (mp.recebido IS NULL), cai no
    # fallback automático — evita que todo o corpus zere a prontidão de outputs no dia em
    # que a feature sobe, antes de alguém começar a marcar (pedido 2026-08). Tolera tabela
    # ausente (pre-1o publish), mesmo padrao do try/except em /api/outputs.
    def _out_q():
        try:
            _ensure_out_pipe_table()
            return run_sql(
                f"SELECT o.projeto, count(DISTINCT o.chave_canonica) AS n_outputs, "
                f"count(DISTINCT CASE WHEN COALESCE(mp.recebido = 'true', t.modernizada_auto = 'Disponível') "
                f"THEN o.chave_canonica END) AS n_outputs_disp, "
                f"count(DISTINCT CASE WHEN mp.carga_fria = 'true' THEN o.chave_canonica END) AS n_carga_fria, "
                f"count(DISTINCT CASE WHEN mp.carga_fria = 'true' AND mp.cf_etapa = 'Modernizado' "
                f"THEN o.chave_canonica END) AS n_carga_fria_ok "
                f"FROM {T_EGP_OUT} o LEFT JOIN {T_OUT} t ON t.chave_canonica = o.chave_canonica "
                f"LEFT JOIN {T_OUT_PIPE} mp ON mp.chave_canonica = o.chave_canonica "
                f"GROUP BY o.projeto")
        except HTTPException as e:
            if not _objeto_ausente(e):
                raise
            return []

    def _pipe_q():
        try:
            _ensure_pipe_table()
            # pipe-etapa-status: real — estas linhas ainda vão passar por
            # `vinculos.anexa_vinculo` em /api/egp-readiness, que é quem deriva etapa/status
            # (e escreve etapa_editavel/vinculo_tipo). Derivar aqui seria derivar duas vezes.
            return run_sql(f"SELECT projeto, status_migracao, etapa_migracao, responsavel, responsavel_bv, "
                           f"jira_id, preworking_preenchido, preworking_data, egp_atualizado_key FROM {T_PIPE}")
        except HTTPException as e:
            if not _objeto_ausente(e):
                raise
            return []

    def _tabela_ausente_atup(exc) -> bool:
        """True só quando é ESPECIFICAMENTE sas_egp_atualizados_pipeline que falta —
        mesmo critério de egps_atualizados.py:_tabela_ausente (msg da exceção cita a
        tabela pelo nome), pra não confundir com T_ATU faltando ou outro erro real."""
        msg = str(getattr(exc, "detail", exc) or "").upper()
        if "TABLE_OR_VIEW_NOT_FOUND" not in msg and "CANNOT BE FOUND" not in msg:
            return False
        return "SAS_EGP_ATUALIZADOS_PIPELINE" in msg

    # candidato AUTOMÁTICO de "EGP atualizado" (pareamento por hash de tasks feito offline
    # em publish_egps_atualizados.py, exposto em sas_egp_atualizados.egp_original — 1+
    # antecessores por " + "). Só a versão mais recente por egp_key entra na disputa (mesma
    # regra da LISTA da aba EGPs Atualizados). Tabela ausente = nenhuma versão publicada
    # ainda -> nenhum EGP tem badge, não erro (mesma tolerância do _pipe_q acima).
    def _atu_q():
        # LEFT JOIN com o funil da TROCA (tipo_vinculo: atualização/substituição/
        # agrupamento — decidido pelo humano ali, não aqui) resolve o rótulo automático
        # (Atualizado/Descontinuado/Unificado) que a aba EGPs mostra quando o vínculo é
        # confirmado. T_ATUP pode não existir ainda (lazy ensure em egps_atualizados.py,
        # só roda quando alguém abre aquela aba) — se faltar, cai pra query SEM o join em
        # vez de esvaziar os badges de EGPs Atualizados inteiros (regressão que uma tabela
        # secundária ausente não deveria causar numa tabela primária presente).
        try:
            return run_sql(f"""
                SELECT versao_id, egp_key, nome, egp_original, confianca_par, tipo_vinculo FROM (
                    SELECT a.versao_id, a.egp_key, a.nome, a.egp_original, a.confianca_par,
                           p.tipo_vinculo,
                           ROW_NUMBER() OVER (PARTITION BY a.egp_key
                               ORDER BY a.data_recebimento DESC, a.publicado_em DESC) AS rn
                    FROM {T_ATU} a LEFT JOIN {T_ATUP} p ON p.egp_key = a.egp_key
                ) WHERE rn = 1""")
        except HTTPException as e:
            if not _tabela_ausente_atup(e):
                return []
            try:
                return run_sql(f"""
                    SELECT versao_id, egp_key, nome, egp_original, confianca_par,
                           CAST(NULL AS STRING) AS tipo_vinculo FROM (
                        SELECT versao_id, egp_key, nome, egp_original, confianca_par,
                               ROW_NUMBER() OVER (PARTITION BY egp_key
                                   ORDER BY data_recebimento DESC, publicado_em DESC) AS rn
                        FROM {T_ATU}
                    ) WHERE rn = 1""")
            except HTTPException as e:
                if not _objeto_ausente(e):
                    raise
                return []

    # leituras independentes em paralelo (teto _PAR_MAX) — antes eram 6 round-trips seriais
    # Com família ligada, a unidade é a FAMÍLIA: n_inputs/n_faltam por count(DISTINCT
    # chave de família) e n_disp = n_inputs - n_faltam. `n_disp` NÃO pode ser contado
    # direto ("alguma safra modernizada") — família com 1 safra pronta e 46 pendentes
    # apareceria como resolvida; a régua do ADR 0002 é a inversa (qualquer safra pendente
    # segura a família), e é isso que `n_faltam` expressa.
    # tier intermediário "desbloqueado" (pedido cliente BV 2026-09): input que já passou de
    # Ingestão PRD (ou Aplicação de Grant), mas AINDA NÃO chegou em Modernizado. Conta com o
    # MESMO peso de um input disponível no `pct` (ver composição abaixo) — sinaliza que o EGP
    # já pode começar a ser trabalhado mesmo sem a esteira 100% concluída — mas fica exposto
    # à parte (`n_prd`) para a UI pintar como uma 2ª cor/flag no anel, nunca se confundindo
    # com "realmente em BigQuery/lake" (Modernizado). Subconjunto de n_faltam por construção
    # (mesma condição NOT san AND NOT mod, só que restrita à etapa PRD/Grant) — nunca soma
    # mais do que o que falta.
    _et_eff = _eff_etapa("i.etapa", "e.modernizada_auto")
    prd = f"({_et_eff} IN ('Ingestão PRD', 'Aplicação de Grant'))"
    # "remessa" (pedido cliente BV 2026-09): banda PDI+GMUD∪Ingestão PRD — as 2 etapas
    # que uma remessa em trânsito ocupa antes de virar Modernizado. Subconjunto de
    # n_faltam (mesma condição NOT san AND NOT mod, restrita a essas 2 etapas). Serve só
    # para simular "quantos EGPs ficam 100% se esta remessa completar": EGP se desbloqueia
    # com a remessa quando TODO o que falta (n_faltam) já está nessa banda — se sobrar
    # pendência numa etapa anterior (ex.: A Receber), a remessa por si não resolve o EGP.
    remessa = f"({_et_eff} IN ('PDI + GMUD', 'Ingestão PRD'))"
    _fam = _fam_sql_egp()
    _cnt_in = (f"count(DISTINCT CASE WHEN NOT ({san}) THEN {_fam} END)" if FAMILIAS_ON
               else f"count(CASE WHEN NOT ({san}) THEN 1 END)")
    _cnt_falta = (f"count(DISTINCT CASE WHEN NOT ({san}) AND NOT ({mod}) THEN {_fam} END)"
                  if FAMILIAS_ON else f"count(CASE WHEN NOT ({san}) AND NOT ({mod}) THEN 1 END)")
    _cnt_prd = (f"count(DISTINCT CASE WHEN NOT ({san}) AND NOT ({mod}) AND {prd} THEN {_fam} END)"
                if FAMILIAS_ON else f"count(CASE WHEN NOT ({san}) AND NOT ({mod}) AND {prd} THEN 1 END)")
    _cnt_remessa = (f"count(DISTINCT CASE WHEN NOT ({san}) AND NOT ({mod}) AND {remessa} THEN {_fam} END)"
                    if FAMILIAS_ON else f"count(CASE WHEN NOT ({san}) AND NOT ({mod}) AND {remessa} THEN 1 END)")
    _cnt_lnk = (f"count(DISTINCT CASE WHEN {lnk} THEN {_fam} END)" if FAMILIAS_ON
                else f"count(CASE WHEN {lnk} THEN 1 END)")
    rows, out_rows, _ndm_rows, pipe, _pe, _bl, atu_rows = _parallel(
        lambda: run_sql(
            f"SELECT e.projeto, e.area, e.onda, e.escopo_indi, e.ciclo_id, "
            f"{_cnt_in} AS n_inputs, "
            f"{_cnt_falta} AS n_faltam, "
            f"{_cnt_prd} AS n_prd, "
            f"{_cnt_remessa} AS n_remessa, "
            f"{_cnt_lnk} AS n_links_broken "
            f"FROM {T_EGP} e LEFT JOIN {T_IN} i ON e.chave_canonica = i.chave_canonica "
            f"LEFT JOIN {T_LINK} l ON l.projeto = e.projeto AND l.chave_canonica = e.chave_canonica "
            f"{where} GROUP BY e.projeto, e.area, e.onda, e.escopo_indi, e.ciclo_id"),
        _out_q,
        lambda: run_sql(f"SELECT projeto, escopo_indi, area, ciclo_id, loc FROM {T_ND}"),
        _pipe_q, _edges_pruned, _blocking, _atu_q)
    # projeto (antecessor) -> candidatos [{egp_key, nome, versao_id, confianca_par}], e
    # egp_key -> linha (p/ resolver o nome do vínculo MANUAL gravado em sas_egp_pipeline).
    _CONF_RANK = {"ok": 0, "alerta": 1, "forcado": 2}
    atu_by_key = {}
    atu_by_antecessor: dict[str, list] = {}
    for a in atu_rows:
        atu_by_key[a["egp_key"]] = a
        for ant in (a.get("egp_original") or "").split(" + "):
            ant = ant.strip()
            if ant:
                atu_by_antecessor.setdefault(ant, []).append(a)
    out_map = {r["projeto"]: r for r in out_rows}
    # deps ja podadas pela escolha de produtor canonico (consistente com recorte/bloqueio)
    _ndm = {n["projeto"]: n for n in _ndm_rows}
    dmap = {}
    for e in _pe:
        nd = _ndm.get(e["depende_do"], {})
        dmap.setdefault(e["projeto_alvo"], []).append({
            "projeto": e["depende_do"],
            "escopo_indi": str(nd.get("escopo_indi")).lower() == "true",
            "area": nd.get("area"),
            "ciclo_id": int(nd.get("ciclo_id") or 0),
        })
    out = []
    for r in rows:
        ni = int(r.get("n_inputs") or 0)
        nf = int(r.get("n_faltam") or 0)
        np_ = int(r.get("n_prd") or 0)
        nr_ = int(r.get("n_remessa") or 0)
        nd = ni - nf
        # pct "desbloqueado": PRD/Grant conta com o MESMO peso de disponível (pedido cliente
        # BV 2026-09) — mas nunca fecha em 100% enquanto sobrar pendência real (nf > 0), senão
        # um EGP com tudo em PRD (nada Modernizado ainda) apareceria como "pronto" no bucket
        # da aba EGPs. `n_prd` vai junto pra UI decompor o anel/barra em 2 cores.
        pct = round(100 * (nd + np_) / ni, 1) if ni else 100.0
        if nf > 0:
            pct = min(pct, 99.9)
        dl = dmap.get(r["projeto"], [])
        n_indi = sum(1 for x in dl if x["escopo_indi"])
        loc = int((_ndm.get(r["projeto"]) or {}).get("loc") or 0)
        out.append({
            "projeto": r["projeto"], "area": r.get("area"), "onda": r.get("onda"),
            "escopo_indi": str(r.get("escopo_indi")).lower() == "true",
            "ciclo_id": int(r.get("ciclo_id") or 0),
            "loc": loc,
            "n_inputs": ni, "n_disp": nd, "n_faltam": nf, "n_prd": np_, "n_remessa": nr_,
            # true só quando falta algo E tudo que falta já está em PDI+GMUD/Ingestão PRD
            # (a remessa cobre 100% da pendência real deste EGP)
            "desbloqueia_remessa": nf > 0 and nf == nr_,
            "n_links_broken": int(r.get("n_links_broken") or 0),
            "pct": pct,
            "n_deps": len(dl), "n_deps_indi": n_indi, "n_deps_ext": len(dl) - n_indi,
            "deps": dl,
            "n_outputs": int((out_map.get(r["projeto"]) or {}).get("n_outputs") or 0),
            "n_outputs_disp": int((out_map.get(r["projeto"]) or {}).get("n_outputs_disp") or 0),
            # outputs marcados p/ carga fria (histórico) e quantos já finalizados (cf_etapa =
            # Modernizado) — só sinalização no card do Kanban, não entra no pct.
            "n_carga_fria": int((out_map.get(r["projeto"]) or {}).get("n_carga_fria") or 0),
            "n_carga_fria_ok": int((out_map.get(r["projeto"]) or {}).get("n_carga_fria_ok") or 0),
        })
    out.sort(key=lambda x: (-x["pct"], -x["n_inputs"]))
    pmap = {r["projeto"]: r for r in pipe}
    for r in out:
        pr = pmap.get(r["projeto"])
        # pipe-etapa-status: real — hidratação crua; quem deriva é anexa_vinculo, no
        # endpoint (ver _pipe_q acima).
        r["status"] = (pr or {}).get("status_migracao") or "A Iniciar"
        r["etapa"] = (pr or {}).get("etapa_migracao") or ""   # pipe-etapa-status: real (idem)
        r["responsavel"] = (pr or {}).get("responsavel") or None
        r["responsavel_bv"] = (pr or {}).get("responsavel_bv") or None
        r["jira_id"] = (pr or {}).get("jira_id") or None
        r["preworking"] = (pr or {}).get("preworking_preenchido") == "true"
        r["preworking_data"] = (pr or {}).get("preworking_data") or None
        atukey_manual = (pr or {}).get("egp_atualizado_key") or None
        cands = sorted(atu_by_antecessor.get(r["projeto"], ()),
                       key=lambda c: _CONF_RANK.get(c.get("confianca_par"), 3))
        auto = cands[0] if cands else None
        manual = atu_by_key.get(atukey_manual) if atukey_manual else None
        r["egp_atualizado_key"] = atukey_manual
        r["atualizado_auto_key"] = auto["egp_key"] if auto else None
        r["atualizado_auto_nome"] = auto["nome"] if auto else None
        r["atualizado_auto_confianca"] = (auto or {}).get("confianca_par")
        # resolvido: MANUAL vence (confirmação/correção do usuário); sem manual, cai no
        # melhor candidato automático — front distingue "sugerido" de "confirmado" por
        # egp_atualizado_key (só != None quando o humano confirmou).
        link = manual or auto
        r["atualizado_link_key"] = link["egp_key"] if link else None
        r["atualizado_link_nome"] = link["nome"] if link else None
        r["atualizado_link_versao_id"] = link["versao_id"] if link else None
        # tipo_vinculo da TROCA (atualização/substituição/agrupamento), decidido no funil
        # da troca (EgpsAtualizadosView.tsx) — front usa pra rotular Atualizado/
        # Descontinuado/Unificado no lugar do "Substituído" genérico. None = ainda não
        # decidido (funil da troca sem tipo_vinculo, ou T_ATUP ausente).
        r["atualizado_link_tipo_vinculo"] = (link or {}).get("tipo_vinculo")
    for r in out:
        r["bloqueado_dep"] = r["projeto"] in _bl["blocked"]
    # dependencia DESPRIORIZADA impactando: propaga dos EGPs fora do backlog para os
    # consumidores transitivos (mesma direcao do bloqueio) — o dependente ve QUEM impacta.
    fora = _egps_fora_backlog()
    imp = {}
    if fora:
        cons_map = {}
        for e in _pe:
            a, d = e["projeto_alvo"], e["depende_do"]
            if a and d and a != d:
                cons_map.setdefault(d, set()).add(a)
        for f in fora:
            for p in _transitive_upstream({f}, cons_map):
                if p != f:
                    imp.setdefault(p, set()).add(f)
    for r in out:
        r["deps_despriorizadas"] = sorted(imp.get(r["projeto"], ()))
    return out


# ---- prontidão por EGP + escopo de migração (base + fecho upstream de dependências) ----
def _sem_fonte_by_proj(projetos):
    """Por EGP do recorte: nº de inputs DISTINTOS com origem 'SAS/Local (externo)' AINDA
    PENDENTES = DEPENDÊNCIA AUSENTE (produtor fora do corpus, sem fonte externa reconhecida).
    Já modernizado/sanitizado NÃO conta (resolvido). Retorna {projeto -> n}."""
    out = {}
    if not projetos:
        return out
    _fin = ",".join(sql_lit(x) for x in projetos)
    _ensure_link_tables()
    _ensure_input_pipeline_cols()
    _lnk = _lnk_resolvido()
    _mod = _modern("i.etapa", "e.modernizada_auto", "i.status", _lnk)
    # unidade: chave física, ou FAMÍLIA com a flag ligada — "dependência ausente" é
    # uma tabela a resolver, e 47 safras da mesma tabela são uma dependência, não 47.
    _u = _fam_sql_egp() if FAMILIAS_ON else "e.chave_canonica"
    for rr in run_sql(
        f"SELECT e.projeto, count(DISTINCT CASE WHEN i.origem = {sql_lit('SAS/Local (externo)')} "
        f"AND NOT ({_mod}) THEN {_u} END) AS n FROM {T_EGP} e "
        f"LEFT JOIN {T_IN} i ON e.chave_canonica = i.chave_canonica "
        f"LEFT JOIN {T_LINK} l ON l.projeto = e.projeto AND l.chave_canonica = e.chave_canonica "
        f"WHERE e.projeto IN ({_fin}) GROUP BY e.projeto"):
        out[rr["projeto"]] = int(rr.get("n") or 0)
    return out


def _readiness_inputs_header(frontier, base):
    """Inputs DISTINTOS do recorte (sem dupla contagem entre EGPs) — visão do esforço de
    ingestão. disp = modernizado (mesma def. da prontidão); faltam = distinto que NUNCA
    aparece modernizado. base = só os EGPs do escopo (sem as dependências), p/ comparar
    núcleo vs +deps. sem_fonte = origem 'SAS/Local (externo)' AINDA PENDENTE (fonte não
    mapeada; já modernizado/sanitizado NÃO conta), igual à flag dep_ausente por EGP.
    Retorna (n_dist, n_disp, n_dist_base, n_sem_fonte)."""
    if not frontier:
        return 0, 0, 0, 0
    front_in = ",".join(sql_lit(x) for x in frontier)
    base_in = ",".join(sql_lit(x) for x in base) or "''"
    _ensure_link_tables()
    _ensure_input_pipeline_cols()
    lnk = _lnk_resolvido()
    mod = _modern("i.etapa", "e.modernizada_auto", "i.status", lnk)
    # unidade do header: chave física, ou FAMÍLIA com a flag ligada. `n_falta` (família
    # com ALGUMA safra pendente) é o que define o "faltam" — contar "aparece modernizado"
    # diria que uma família com 1 safra pronta e 46 pendentes está resolvida. No grão
    # safra a regra antiga é preservada ("nunca aparece modernizado"), que difere da nova
    # só quando a MESMA chave está quebrada num EGP e pendente noutro.
    _u = _fam_sql_egp() if FAMILIAS_ON else "e.chave_canonica"
    dd = run_sql(
        f"SELECT count(DISTINCT {_u}) AS n_dist, "
        f"count(DISTINCT CASE WHEN ({mod}) THEN {_u} END) AS n_disp, "
        f"count(DISTINCT CASE WHEN NOT ({mod}) THEN {_u} END) AS n_falta, "
        f"count(DISTINCT CASE WHEN e.projeto IN ({base_in}) THEN {_u} END) AS n_base, "
        f"count(DISTINCT CASE WHEN i.origem = {sql_lit('SAS/Local (externo)')} AND NOT ({mod}) THEN {_u} END) AS n_sem_fonte "
        f"FROM {T_EGP} e LEFT JOIN {T_IN} i ON e.chave_canonica = i.chave_canonica "
        f"LEFT JOIN {T_LINK} l ON l.projeto = e.projeto AND l.chave_canonica = e.chave_canonica "
        f"WHERE e.projeto IN ({front_in}) "
        f"AND NOT ({_sanitizado('i.etapa', 'e.modernizada_auto', 'i.status', lnk)})")
    if not dd:
        return 0, 0, 0, 0
    n_dist = int(dd[0].get("n_dist") or 0)
    n_disp = (n_dist - int(dd[0].get("n_falta") or 0)) if FAMILIAS_ON \
        else int(dd[0].get("n_disp") or 0)
    return (n_dist, n_disp, int(dd[0].get("n_base") or 0),
            int(dd[0].get("n_sem_fonte") or 0))


@app.get("/api/egps-sem-vinculo")
def egps_sem_vinculo():
    """Ticket 23: o que entrou no corpus e NÃO aparece em tela nenhuma, e os vínculos que
    ficaram inertes.

    Contrapartida de /api/egps-atualizados/aguardando-corpus, que cobre o sentido inverso
    (versão recebida que ainda não entrou no corpus). Sem este aqui, um EGP publicado sem
    vínculo some de todas as telas — e, pior, pode ser reclassificado como dependência e
    mexer no card da gestão sem ninguém ver (medido em 30/09: 26 inputs, deps 88 × 61).

    `antecessor_sugerido` sai do pareamento JÁ MEDIDO em sas_egp_atualizados (egp_original,
    por hash de tasks), casado pela chave prevista — não por semelhança de nome. Sem
    candidato vem None: sugerir errado aqui custa um vínculo errado."""
    try:
        nos = {(r.get("projeto") or "").strip()
               for r in run_sql(f"SELECT projeto FROM {T_ND}")} - {""}
    except HTTPException:
        return {"sem_vinculo": [], "orfaos": [], "n": 0, "n_orfaos": 0}
    # UNIVERSO = as versões RECEBIDAS que viraram projeto do corpus, não o corpus inteiro.
    # O corpus tem ~1.270 nós e o recorte ~237: sem este recorte a lista traria os ~1.000
    # EGPs que nunca foram escopo (medido: 1.051), afogando os poucos que a issue procura.
    # Duas grafias porque as duas existem: a chave PREVISTA (`…__ATU<data>`, régua §2) casa
    # 14 de 41, e o `egp_key` puro casa 39 — a etapa de renomeação não passou por todas.
    sugestao = {}
    try:
        for r in run_sql(f"SELECT egp_key, data_recebimento, egp_original FROM {T_ATU}"):
            key = (r.get("egp_key") or "").strip()
            if not key:
                continue
            for chave in (key, egps_atualizados.chave_prevista(key, r.get("data_recebimento"))):
                if chave in nos:
                    # O antecessor medido pode ser o PRÓPRIO projeto: acontece quando o
                    # `egp_key` (chave de CHEGADA) coincide com a chave do corpus, que é o
                    # caso quando a versão nova não foi renomeada com o sufixo da régua.
                    # Medido em prod em 02/10/2026: as 3 linhas da lista sugeriam `X -> X`,
                    # ou seja 100% do que a tela oferecia era armadilha. Sugerir isso é pior
                    # que não sugerir nada — quem clica cria o EGP como sucessor de si
                    # mesmo. A guarda do PATCH recusa (409), mas a sugestão não pode chegar
                    # lá: o alerta existe para orientar, não para induzir ao erro.
                    ant = (r.get("egp_original") or "").strip()
                    partes = [x.strip() for x in ant.split(" + ") if x.strip() and x.strip() != chave]
                    sugestao.setdefault(chave, " + ".join(partes) or None)
    except HTTPException:
        pass
    # ... MAIS o que nasceu com o sufixo da régua sem passar por `sas_egp_atualizados`:
    # EGP carregado pela skill ou à mão não tem linha na tabela de chegada e ficava CEGO
    # para este contador — o ponto exato que o ticket 23 descreve. Medido em 01/10/2026 no
    # clone: +1 caso real (`manut_acordo__ATU20260901`) e ZERO ruído, porque o sufixo é
    # ancorado. O que ainda escapa é versão sem o sufixo e fora da tabela: aí não há sinal
    # nenhum para pegar, e inventar um seria adivinhar.
    universo = set(sugestao) | {p for p in nos if egps_atualizados.eh_chave_atu(p)}
    frontier, base = _frontier_egps("indi_deps", [])
    vinc = _vinculos_por_antecessor()
    soltos = vinculos.sem_vinculo(universo, _linha_base(), frontier, vinc)
    # MESMO recorte que a aba EGPs monta (ver `_egp_readiness_uncached`): frontier +
    # ex-dependências + linha de base. Usar só o frontier classificaria como invisível o
    # ex-dependência, que aparece na tabela com badge.
    try:
        em_tela = set(frontier) | set(_ex_deps(frontier, base)[0]) | set(_linha_base())
    except HTTPException:
        em_tela = set(frontier)
    orfaos = vinculos.vinculos_orfaos(vinc, frontier, em_tela)
    return {
        "sem_vinculo": [{"projeto": p, "antecessor_sugerido": sugestao.get(p)} for p in soltos],
        "orfaos": orfaos,
        "n": len(soltos),
        "n_orfaos": len(orfaos),
        # o subconjunto que pede AÇÃO: o EGP não existe em tela nenhuma.
        "n_orfaos_invisiveis": sum(1 for o in orfaos if o.get("sucessor_em_tela") is False),
    }


@app.get("/api/egp-readiness")
def egp_readiness(scope: str = "indi"):
    """Payload cacheado por identidade OBO + scope + geração (ver _cache_endpoint)."""
    return _cache_endpoint(("egp_readiness", scope), lambda: _egp_readiness_uncached(scope))


def _egp_readiness_uncached(scope: str = "indi"):
    """Prontidão por EGP (aba EGPs). scope ∈ {indi, base, indi_deps}:
      indi/base -> linhas do escopo (tipo='escopo', dep_nivel=0), como antes;
      indi_deps -> base Indicium ∪ dependências TRANSITIVAS (fecho upstream por nível).
    Cada linha (base ou dependência) é hidratada com a MESMA prontidão (pct, n_deps,
    etapa/status/responsável, bloqueado_dep, deps[]...) via _egp_readiness_rows, + os
    campos n_sem_fonte/dep_ausente (dependência ausente = input SAS/Local externo não
    modernizado). O header é sempre calculado sobre os projetos do recorte."""
    if scope == "indi_deps":
        # base = escopo Indicium (nós); frontier = base ∪ fecho upstream (níveis via BFS).
        # Mesmo recorte que /api/landing e /api/scope-egps (via _frontier_egps).
        frontier, base = _frontier_egps("indi_deps", [])   # aquece edges/fora p/ o resto
        # ex-dependências: retidas na aba com badge (spec 2026-08-06) — hidratadas
        # como qualquer EGP; NÃO entram no header de inputs (contadores de inputs
        # seguem o frontier vivo).
        # fecho por nível, ex-deps e hidratação: leituras independentes -> paralelo.
        level, _ex_trip, _rr_all = _parallel(
            lambda: _transitive_upstream(
                base, _dep_of_map(_edges_pruned()),
                no_expand=_egps_fora_backlog()),
            lambda: _ex_deps(frontier, base),
            lambda: _egp_readiness_rows("base"))
        ex, ex_motivo, ex_nivel = _ex_trip
        # + quem está na LINHA DE BASE e sumiu do corpus (saiu do escopo, foi dedupado,
        # republish incompleto): continua no denominador — "congelado nos dois lados" —,
        # então continua na lista, com linha vazia (o `_stub` abaixo). Sem isto a tabela
        # diria 192 enquanto o card diz 193 e ninguém saberia qual EGP faltou. Em 29/09
        # o conjunto é vazio nos dois schemas; é guarda, não caso corrente.
        recorte = list(frontier) + sorted(ex) + sorted(set(_linha_base()) - frontier - ex)
        # cada EGP (base OU dependência) hidratado com a prontidão de TODOS os EGPs
        by_proj = {r["projeto"]: r for r in _rr_all}
        # dependência sem NENHUM input no inventário (EGP só-produtor) não vem da hidratação
        # -> linha default COMPLETA (dict pelado quebrava o sort/contrato com KeyError -> 500)
        missing = [p for p in recorte if p not in by_proj]
        area_missing = {}
        if missing:
            _inl = ", ".join(sql_lit(p) for p in missing)
            area_missing = {r["projeto"]: r.get("area") for r in run_sql(
                f"SELECT projeto, area FROM {T_ND} WHERE projeto IN ({_inl})")}

        def _stub(p):
            return {"projeto": p, "area": area_missing.get(p) or "", "onda": "",
                    "escopo_indi": False, "ciclo_id": 0, "n_inputs": 0, "n_disp": 0,
                    "n_faltam": 0, "n_prd": 0, "n_links_broken": 0, "pct": 100, "n_deps": 0,
                    "n_deps_indi": 0, "n_deps_ext": 0, "deps": [], "status": "",
                    "etapa": "", "bloqueado_dep": False, "responsavel": None,
                    "n_outputs": 0, "n_outputs_disp": 0, "n_carga_fria": 0, "n_carga_fria_ok": 0,
                    "preworking": False,
                    "egp_atualizado_key": None, "atualizado_auto_key": None,
                    "atualizado_auto_nome": None, "atualizado_auto_confianca": None,
                    "atualizado_link_key": None, "atualizado_link_nome": None,
                    "atualizado_link_versao_id": None, "atualizado_link_tipo_vinculo": None}
        prod_mant = _produtores_mantidos()
        src_rows = [{**(by_proj.get(p) or _stub(p)),
                     "dep_nivel": int(level.get(p, ex_nivel.get(p, 1))),
                     "ex_dependencia": p in ex,
                     "ex_motivo": ex_motivo.get(p),
                     "dep_mantida": p in prod_mant} for p in recorte]
        # NOTA (merge develop, 01/10): aqui a develop calculava um `ex_contab` local para
        # `ex_count`/`total`. Na linha de base CONGELADA esse total deixou de ser calculado
        # (ticket 19) e o bloco ficaria atribuído sem ninguém ler — por isso saiu. A regra
        # dele (etapa fantasma conta se Despriorizado e Contabilizado) não se perdeu: vive
        # em `_ex_deps_contab` e em `contaNoTotalEgp`, que são quem decide denominador.
    else:
        # indi / base: as LINHAS são as do recorte pedido, mas a CLASSIFICAÇÃO (`tipo`) é
        # sempre contra o recorte Indicium — ela é propriedade do EGP, não do recorte que o
        # cliente pediu. Antes `dep_nivel` era forçado a 0 aqui e TODA linha saía `escopo`:
        # medido em prod 07/10/2026, os 1.250 do corpus vinham como escopo no recorte
        # "todos", 1.082 deles fora do escopo Indicium — e o drawer do EGP, que pede
        # `base` fixo (EgpDetailPanel), exibia o badge de escopo para o corpus inteiro.
        src_rows = [{**r, "dep_nivel": 0} for r in _egp_readiness_rows(scope)]
        base = {r["projeto"] for r in src_rows}
        frontier = set(base)
        ex = set()
        if scope == "base":
            # `frontier`/`base` locais NÃO mudam: eles alimentam o header de inputs deste
            # recorte, que continua sendo "tudo". O que entra aqui é só rótulo por linha.
            try:
                _fr, _bs = _frontier_egps("indi_deps", [])
                _ex_i, _mot_i, _niv_i = _ex_deps(_fr, _bs)
            except HTTPException as e:
                # Só "grafo ainda não publicado" cai no vazio. Timeout/403 rotulariam o corpus
                # INTEIRO `fora_do_recorte`, e o payload vai para o cache compartilhado.
                if not _objeto_ausente(e):
                    raise
                _fr, _bs, _ex_i, _mot_i, _niv_i = set(), set(), set(), {}, {}
            for r in src_rows:
                pj = r["projeto"]
                r["ex_dependencia"] = pj in _ex_i
                r["ex_motivo"] = _mot_i.get(pj)
                if pj in _ex_i:
                    r["dep_nivel"] = int(_niv_i.get(pj, 1))
                elif pj in _bs:
                    r["dep_nivel"] = 0
                elif pj in _fr:
                    r["dep_nivel"] = 1
                else:
                    # 4º valor (07/10/2026): está no corpus e fora do recorte INTEIRO. Não
                    # é escopo, nem dependência, nem ex-dependência — e chamá-lo de escopo
                    # era a mentira que este bloco contava.
                    r["fora_do_recorte"] = True

    # fim_conversao por EGP (sas_gestao_datas) — habilita o filtro "convertidos" na aba EGPs.
    # Tabela ainda inexistente antes do 1o PATCH -> map vazio (fallback silencioso).
    def _fim_conv():
        try:
            _ensure_gestao_tables()
            return {r["entity_id"]: r.get("fim_conversao") for r in run_sql(
                f"SELECT entity_id, fim_conversao FROM {T_GDT} WHERE entity = 'egp'")}
        except HTTPException as e:
            if not _objeto_ausente(e):
                raise
            return {}

    # sem_fonte / fim_conversao / header de inputs: independentes -> paralelo
    sem_fonte_by_proj, fim_conv_by_proj, _hdr = _parallel(
        lambda: _sem_fonte_by_proj(set(frontier) | ex),
        _fim_conv,
        lambda: _readiness_inputs_header(frontier, base))
    rows = []
    for r in src_rows:
        lv = int(r.get("dep_nivel") or 0)
        proj = r["projeto"]
        rows.append({
            **r,
            "tipo": ("ex_dependencia" if r.get("ex_dependencia")
                     else "fora_do_recorte" if r.get("fora_do_recorte")
                     else "escopo" if lv == 0 else "dependencia"),
            "dep_nivel": lv,
            "n_sem_fonte": int(sem_fonte_by_proj.get(proj, 0)),
            "dep_ausente": sem_fonte_by_proj.get(proj, 0) > 0,
            "fim_conversao": fim_conv_by_proj.get(proj) or None,
        })
    # Vínculo antecessor -> sucessor: derivação de leitura (spec §3.2). MESMA fonte do
    # recorte e das contagens (_vinculos_por_antecessor, cacheado por geração) — duas
    # queries para o mesmo fato dariam recorte e card discordando entre si. O helper já
    # degrada para {} se a coluna ainda não existe, então aqui não há o que capturar.
    _vinc, _casc, _lb = _vinculos_por_antecessor(), _cascas(), _linha_base()
    # pipe-etapa-status: real — leitura CRUA da tabela inteira, usada só como fonte da etapa
    # ESPELHADA quando o sucessor está fora do recorte pedido (ver anexa_vinculo.etapa_de).
    # Cacheada por geração: não custa query por recorte.
    _etapa_crua = {p: et for p, (et, _st) in _pipe_egp_map().items()}
    vinculos.anexa_vinculo(rows, _vinc, _casc, linha_base=_lb, novos=_egps_novos(),
                           etapa_de=_etapa_crua, deps_novas=_deps_novas())
    # escopo (dep_nivel 0) primeiro, depois por nível, área, projeto; ex-dependências no fim
    rows.sort(key=lambda x: (1 if x.get("ex_dependencia") else 0,
                             x["dep_nivel"], (x["area"] or ""), x["projeto"]))

    n_dist, n_disp, n_dist_base, n_sem_fonte = _hdr
    # Cards do topo: CONGELADOS na linha de base (29/09/2026). base/dep/ex vêm da CLASSE
    # gravada no CSV e o total é o tamanho da lista — nada disso olha para o grafo vivo,
    # então republish, dedup e saída de escopo não mexem mais no denominador. O header de
    # INPUTS (n_dist/n_disp/...) e a LISTA de linhas seguem o frontier vivo, como sempre:
    # rows.length pode exceder o total, e é isso que o chip de ex-dependência esconde.
    _dec = linha_base.decomposicao(_lb)
    # `indi` é o único recorte que exclui dependências e ex-dependências (ver scope_egps).
    _so_escopo = scope == "indi"
    return {
        "rows": rows,
        "base_count": _dec["base"],
        "dep_count": 0 if _so_escopo else _dec["dependencia"],
        "ex_count": 0 if _so_escopo else _dec["ex_dependencia"],
        "total": _dec["base"] if _so_escopo else linha_base.total(_lb),
        # contador PRÓPRIO dos extras: exibido AO LADO do total, nunca dentro — a linha de
        # base não sobe porque uma versão nova/casca/dependência inédita chegou.
        "extra_count": len(_extras(frontier)),
        "inputs_distintos": n_dist,
        "inputs_distintos_disp": n_disp,
        "inputs_distintos_faltam": n_dist - n_disp,
        "inputs_distintos_base": n_dist_base,
        "inputs_sem_fonte": n_sem_fonte,
    }


# ---- unidades de input por EGP (cards vivos da aba EGPs) -------------------------
@app.get("/api/egp-input-units")
def egp_input_units(scope: str = "indi"):
    """Mapa EGP -> unidades de input do MESMO dataset que a Visão geral conta.

    Existe porque o header de `/api/egp-readiness` não serve aos cards da aba: ele agrega
    por SQL, EXCLUI o Sanitizado do universo e não sabe de filtro de tela — com os filtros
    da tabela aplicados daria um número que não existe em superfície nenhuma, e sem filtro
    já divergia da Visão geral (711 × 1.303 unidades em prod, 05/10/2026). Aqui a unidade
    e o estado saem de `_dataset_escopo` + `_universo_contagem`, exatamente as linhas que
    /api/landing e a aba Inputs contam; o que a aba faz é escolher QUAIS EGPs entram.

    Consequência desejada: sem filtro, a soma dos EGPs em tela bate com a Visão geral por
    construção. Medido em prod (05/10/2026): os 168 do escopo -> 1.161 unidades / 311 a
    ingerir (itens 3/4 da landing); os 214 do frontier -> 1.303 / 377 (o total dela).

    O estado da unidade é o do RECORTE INTEIRO, não o do subconjunto filtrado — família de
    safras agrega só as safras em vista (ver o bloco dos itens 4/7 em `landing`), e
    reagregar por filtro faria a MESMA família responder coisas diferentes conforme o
    chip ligado. O filtro escolhe o que contar, nunca o que a unidade é.
    """
    # `indi` e `indi_deps` partilham o dataset (e o cache): o recorte de EGP é do cliente.
    ds = "base" if scope == "base" else "indi_deps"
    return _cache_endpoint(("egp_input_units", ds), lambda: _egp_input_units_uncached(ds))


def _egp_input_units_uncached(ds):
    rows = _universo_contagem(_dataset_escopo(ds, []))
    unidades = []
    fisica = {}            # chave FÍSICA -> índice da unidade (família colapsa N:1)
    for i, r in enumerate(rows):
        pend = py_aingerir(r)
        unidades.append({
            "k": r.get("chave_canonica"),
            "a": pend,
            # mesma régua do `n_sem_fonte` do header: origem externa AINDA pendente
            "sf": pend and (r.get("origem") or "") == "SAS/Local (externo)",
        })
        if r.get("is_familia"):
            for m in (r.get("membros") or []):
                fisica[m] = i
        else:
            fisica[r.get("chave_canonica")] = i

    _ensure_link_tables()
    # `e.projeto` fora do recorte não some: ele só aparece aqui se LÊ uma unidade do
    # recorte, e nesse caso a aba pode listá-lo (recorte "todos"). Vínculo quebrado sai —
    # é a mesma exclusão que `_ch_vinculo_ativo` faz no universo da Visão geral, só que
    # por par (EGP, input) em vez de por chave.
    por = {}
    for p in run_sql(
            f"SELECT e.projeto, e.chave_canonica, coalesce(l.link_broken, false) AS broken "
            f"FROM {T_EGP} e LEFT JOIN {T_LINK} l ON l.projeto = e.projeto "
            f"AND l.chave_canonica = e.chave_canonica"):
        if str(p.get("broken")).lower() == "true":
            continue
        i = fisica.get(p.get("chave_canonica"))
        if i is None:
            continue
        por.setdefault(p["projeto"], set()).add(i)
    return {"grao": "familia" if FAMILIAS_ON else "safra",
            "unidades": unidades,
            "por_egp": {k: sorted(v) for k, v in sorted(por.items())}}


# ---- ondas (status dinâmico = progresso real de ingestão) ----
@app.get("/api/waves")
def waves(scope: str = "indi"):
    _ensure_link_tables()
    _ensure_input_pipeline_cols()
    lnk = _lnk_resolvido()
    san = _sanitizado("i.etapa", "e.modernizada_auto", "i.status", lnk)
    where = f"WHERE NOT ({san})" + (" AND e.escopo_indi = true" if scope == "indi" else "")
    eff_et = _eff_etapa("i.etapa", "e.modernizada_auto")
    mod = _modern("i.etapa", "e.modernizada_auto", "i.status", lnk)
    rows = run_sql(
        f"SELECT e.onda AS onda, count(DISTINCT e.projeto) AS n_egps, "
        f"count(DISTINCT e.chave_canonica) AS n_inputs, "
        f"count(DISTINCT CASE WHEN {mod} THEN e.chave_canonica END) AS n_ingeridos, "
        f"count(DISTINCT CASE WHEN NOT ({mod}) AND {eff_et} <> 'A Receber' "
        f"THEN e.chave_canonica END) AS n_andamento "
        f"FROM {T_EGP} e LEFT JOIN {T_IN} i ON e.chave_canonica = i.chave_canonica "
        f"LEFT JOIN {T_LINK} l ON l.projeto = e.projeto AND l.chave_canonica = e.chave_canonica "
        f"{where} GROUP BY e.onda")
    out = []
    for r in rows:
        onda = r.get("onda") or "(sem onda)"
        ni = int(r.get("n_inputs") or 0)
        ning = int(r.get("n_ingeridos") or 0)
        nand = int(r.get("n_andamento") or 0)
        pct = round(100 * ning / ni, 1) if ni else 0.0
        if ni and ning >= ni:
            st = "Concluída"
        elif ning > 0 or nand > 0:
            st = "Em andamento"
        else:
            st = "Não iniciada"
        m = re.search(r"\d+", onda)
        out.append({"onda": onda, "onda_num": int(m.group()) if m else 999,
                    "n_egps": int(r.get("n_egps") or 0), "n_inputs": ni,
                    "n_ingeridos": ning, "n_andamento": nand, "pct": pct,
                    "status": st, "em_ciclo": bool(re.search(r"cicl", onda, re.I))})
    out.sort(key=lambda x: x["onda_num"])
    return {"rows": out}


# ---- histórico de edições (quem mudou o quê) ----
def _migrados_mes(frontier):
    """Nº de EGPs do recorte cujo status de migração virou 'Migrado' NESTE mês de
    calendário (via auditoria T_PIPE_AUD). KPI de velocidade — só 'Migrado' (não conta
    Despriorizado e Contabilizado, que é saída de backlog). Robusto a falha de SQL -> 0."""
    if not frontier:
        return 0
    inl = ", ".join(sql_lit(pj) for pj in frontier)
    try:
        r = run_sql(
            f"SELECT count(DISTINCT projeto) AS n FROM {T_PIPE_AUD} "
            f"WHERE funil = 'migracao' AND campo = 'status' AND valor_novo = 'Migrado' "
            f"AND substr(ts, 1, 7) = date_format(current_date, 'yyyy-MM') "
            f"AND projeto IN ({inl})")
        return int(r[0]["n"]) if r and r[0].get("n") is not None else 0
    except HTTPException:
        return 0


# Feriados nacionais BR (2025–2027) — ESPELHO de FERIADOS_BR em frontend/src/diasUteis.ts;
# mudou lá, sincronize aqui. Fora dessa faixa só fins de semana são descontados.
FERIADOS_BR = frozenset(datetime.date.fromisoformat(d) for d in (
    "2025-01-01", "2025-03-03", "2025-03-04", "2025-04-18", "2025-04-21", "2025-05-01",
    "2025-06-19", "2025-09-07", "2025-10-12", "2025-11-02", "2025-11-15", "2025-11-20", "2025-12-25",
    "2026-01-01", "2026-02-16", "2026-02-17", "2026-04-03", "2026-04-21", "2026-05-01",
    "2026-06-04", "2026-09-07", "2026-10-12", "2026-11-02", "2026-11-15", "2026-11-20", "2026-12-25",
    "2027-01-01", "2027-02-08", "2027-02-09", "2027-03-26", "2027-04-21", "2027-05-01",
    "2027-05-27", "2027-09-07", "2027-10-12", "2027-11-02", "2027-11-15", "2027-11-20", "2027-12-25",
))


def _dias_uteis_entre(lo, hi):
    """Dias ÚTEIS (seg–sex, sem feriado nacional BR) em [lo, hi) — semiaberto, a mesma
    convenção do `(hi - lo).days` que substitui (seg->ter = 1; sex->seg = 1, só a sexta
    conta). Fins de semana e feriados não entram em nenhuma conta da aba Tempo por Etapa
    (pedido 2026-10-06). hi <= lo -> 0."""
    if hi <= lo:
        return 0
    one = datetime.timedelta(days=1)
    n, d = 0, lo
    while d < hi:
        if d.weekday() < 5 and d not in FERIADOS_BR:
            n += 1
        d += one
    return n


def _ownership_days(eventos, day_in, day_out, hoje):
    """Reparte [day_in, day_out) (date, date) entre "Com BV" e "Conosco", segundo `eventos`
    — lista [(data:date, com_bv:bool), ...] ORDENADA do switch "Com BV" (sas_gestao_bv) de 1
    projeto. Sem nenhum evento -> intervalo inteiro cai em "Conosco" (fallback: só sabemos
    que o EGP esteve "com BV" quando alguém registrou o toggle; ausência de registro não
    significa que esteve com a gente o tempo todo, só que não temos como distinguir).
    Retorna (dias_conosco, dias_com_bv)."""
    if not eventos:
        return _dias_uteis_entre(day_in, day_out), 0
    segs, prev_data, prev_bv = [], None, False  # antes do 1º evento: assume Conosco
    for d, bv in eventos:
        segs.append((prev_data, d, prev_bv))
        prev_data, prev_bv = d, bv
    segs.append((prev_data, None, prev_bv))  # última: aberta (persiste até hoje)
    conosco, com_bv = 0, 0
    for seg_ini, seg_fim, bv in segs:
        lo = max(day_in, seg_ini) if seg_ini is not None else day_in
        hi = min(day_out, seg_fim) if seg_fim is not None else min(day_out, hoje)
        if hi > lo:
            d = _dias_uteis_entre(lo, hi)
            if bv:
                com_bv += d
            else:
                conosco += d
    return conosco, com_bv


def _label_days(eventos, day_in, day_out, default_label):
    """Reparte [day_in, day_out) (date, date) entre os valores de `eventos` — lista
    [(data:date, label), ...] ORDENADA — igual em espírito a _ownership_days, mas genérico
    pra N labels em vez de Com BV/Conosco (usado pro breakdown por STATUS_PROJETO dentro de
    cada etapa). Sem nenhum evento -> tudo em `default_label`. Segmento aberto (após o
    último evento) fecha em `day_out` — diferente de _ownership_days, aqui quem chama
    já resolveu o teto certo (a saída da ETAPA, não "hoje": status muda de sentido quando
    o EGP já foi pra próxima etapa). Retorna dict {label: dias}."""
    if not eventos:
        return {default_label: _dias_uteis_entre(day_in, day_out)}
    segs, prev_data, prev_label = [], None, default_label
    for d, label in eventos:
        segs.append((prev_data, d, prev_label))
        prev_data, prev_label = d, label
    segs.append((prev_data, None, prev_label))
    out: dict = {}
    for seg_ini, seg_fim, label in segs:
        lo = max(day_in, seg_ini) if seg_ini is not None else day_in
        hi = min(day_out, seg_fim) if seg_fim is not None else day_out
        if hi > lo:
            out[label] = out.get(label, 0) + _dias_uteis_entre(lo, hi)
    return out


def _dias_uteis_segmentos(eventos_status, day_in, day_out):
    """Sub-divide [day_in, day_out) (date, date) em sub-intervalos [(lo, hi), ...] que
    EXCLUEM os dias em que o status era "Em espera" — segundo `eventos_status`, lista
    [(data, status), ...] ORDENADA (mesma forma de _label_days). Sem evento "Em espera" no
    meio -> devolve o intervalo inteiro, sem partição. Quem chama soma (hi - lo).days de
    cada sub-intervalo pra ter o total "útil" (ou repassa os sub-intervalos pra
    _ownership_days, pra não contar "Em espera" nem em Com BV nem em Conosco). Pedido
    2026-10-01: 1 responsável só avança 1 EGP por vez, então tempo em "Em espera" não é
    tempo real gasto NESTE EGP — superdimensionaria lead_time/aging/tempo-por-etapa."""
    if not eventos_status:
        return [(day_in, day_out)]
    segs, prev_data, prev_status = [], None, "A Iniciar"
    for d, st in eventos_status:
        segs.append((prev_data, d, prev_status))
        prev_data, prev_status = d, st
    segs.append((prev_data, None, prev_status))
    out = []
    for seg_ini, seg_fim, status in segs:
        lo = max(day_in, seg_ini) if seg_ini is not None else day_in
        hi = min(day_out, seg_fim) if seg_fim is not None else day_out
        if hi > lo and status != "Em espera":
            out.append((lo, hi))
    return out


def _hoje_utc():
    """Data de hoje no fuso do warehouse — equivalente a `current_date()` sem a ida ao
    warehouse (~1 s por chamada): a sessão SQL roda em Etc/UTC (medido 06/10/2026). Se o
    fuso do warehouse mudar, isto muda junto."""
    return datetime.datetime.now(datetime.timezone.utc).date()


def _tempo_etapas(base):
    """Tempo (dias) que os EGPs de `base` (escopo Indicium) levaram em cada etapa do funil
    de migração, a partir das transições registradas em sas_pipeline_audit (campo='etapa'),
    repartido entre "Com BV" (bloqueado esperando a área/banco) e "Conosco" (trabalho
    nosso) via o switch de sas_gestao_bv (aba Priorização/Kanban — histórico append-only,
    ver _bv_audit). Intervalo fechado = diferença entre 2 transições consecutivas do mesmo
    projeto; intervalo aberto (etapa ainda em curso) conta até agora, só quando bate com a
    etapa VIVA em sas_egp_pipeline (evita contar tempo "aberto" de uma transição que já foi
    substituída por outra fora desta linha, ex. edição direta na tabela).

    Também reparte cada etapa por STATUS_PROJETO (A Iniciar/Em Andamento/Concluído/Block/…)
    via sas_pipeline_audit (campo='status') — 2º gráfico no front, independente do de
    Com BV/Conosco (são 2 cortes ortogonais do mesmo tempo, não um refinamento do outro).

    Ressalvas: (1) EGPs cuja etapa nunca foi alterada via PATCH (sem linha na auditoria)
    ficam de fora — não há baseline pra medir a entrada; `n` por etapa expõe o tamanho da
    amostra pro front não passar confiança indevida numa média de 1-2 EGPs. (2) EGP sem
    NENHUM toggle "Com BV" registrado conta o intervalo inteiro como "Conosco" — é a melhor
    aproximação sem o dado, não uma afirmação de que nunca esteve com o banco. (3) Sem
    NENHUMA transição de status dentro do intervalo da etapa, assume "A Iniciar" (default
    do funil, mesma convenção do resto do app — ver proj_funnel). (4) Dias em que o status
    era "Em espera" são EXCLUÍDOS de `total`/`media_dias_conosco`/`media_dias_com_bv` (via
    _dias_uteis_segmentos) — 1 responsável só avança 1 EGP por vez, então esse tempo não é
    tempo realmente gasto NESTE EGP; `por_status` continua reportando "Em espera" como
    corte ortogonal (não some do breakdown, só não entra no total)."""
    from datetime import date
    if not base:
        return []
    inl = ", ".join(sql_lit(pj) for pj in base)
    try:
        # 4 leituras independentes numa onda (eram 5 rodadas seriais, uma delas só para
        # saber a data — ver _hoje_utc).
        etapa_rows, status_rows, pipe_rows, bv_rows = _parallel(
            lambda: run_sql(
                f"SELECT projeto, valor_novo AS etapa, ts FROM {T_PIPE_AUD} "
                f"WHERE funil = 'migracao' AND campo = 'etapa' AND projeto IN ({inl}) "
                f"ORDER BY projeto, ts"),
            lambda: run_sql(
                f"SELECT projeto, valor_novo AS status, ts FROM {T_PIPE_AUD} "
                f"WHERE funil = 'migracao' AND campo = 'status' AND projeto IN ({inl}) "
                f"ORDER BY projeto, ts"),
            # pipe-etapa-status: real — a etapa viva casa com a trilha do sas_egp_pipeline_audit,
            # que é do PRÓPRIO EGP; a derivada (a do sucessor) nunca casaria e o intervalo em
            # curso sumiria.
            lambda: run_sql(
                f"SELECT projeto, etapa_migracao FROM {T_PIPE} WHERE projeto IN ({inl})"),
            lambda: run_sql(
                f"SELECT entity_id AS projeto, com_bv, data FROM {T_GBV} "
                f"WHERE entity = 'egp' AND entity_id IN ({inl}) ORDER BY entity_id, data, ts"))
        hoje = _hoje_utc()
    except HTTPException as e:
        if not _objeto_ausente(e):
            raise
        return []

    # pipe-etapa-status: real — mesma leitura gravada de cima (casa com a auditoria).
    cur_etapa = {r["projeto"]: r.get("etapa_migracao") for r in pipe_rows}
    bv_timeline: dict = {}
    for r in bv_rows:
        if not r.get("data"):
            continue
        bv_timeline.setdefault(r["projeto"], []).append(
            (date.fromisoformat(r["data"][:10]), str(r["com_bv"]).lower() == "true"))
    status_timeline: dict = {}
    for r in status_rows:
        status_timeline.setdefault(r["projeto"], []).append(
            (date.fromisoformat(r["ts"][:10]), r.get("status")))

    # "Migrado" é a etapa TERMINAL do funil (sem próxima etapa que feche o intervalo) —
    # o ramo de intervalo aberto acima mediria "há quanto tempo migrou", não "tempo gasto
    # na etapa", então é excluída daqui (pedido 2026-09-29).
    etapas_medidas = [et for et in PIPELINE_PROJETO["migracao"] if et != "Migrado"]

    rows_by_projeto: dict = {}
    for r in _canon_etapa_rows(etapa_rows):
        rows_by_projeto.setdefault(r["projeto"], []).append(r)

    total_por_etapa: dict = {}
    conosco_por_etapa: dict = {}
    com_bv_por_etapa: dict = {}
    status_por_etapa: dict = {}  # etapa -> {status: [dias, ...]} (1 entrada por EGP-intervalo)
    for projeto, rows in rows_by_projeto.items():
        for i, r in enumerate(rows):
            et = r.get("etapa")
            if et not in etapas_medidas:
                continue
            day_in = date.fromisoformat(r["ts"][:10])
            if i + 1 < len(rows):
                day_out = date.fromisoformat(rows[i + 1]["ts"][:10])
            elif cur_etapa.get(projeto) == et:
                day_out = hoje  # etapa ainda em curso
            else:
                continue  # última transição registrada não é mais a etapa viva -> sem saída
            status_evts = status_timeline.get(projeto, [])
            segmentos = _dias_uteis_segmentos(status_evts, day_in, day_out)
            total = sum(_dias_uteis_entre(lo, hi) for lo, hi in segmentos)
            conosco = com_bv = 0
            for lo, hi in segmentos:
                c, b = _ownership_days(bv_timeline.get(projeto, []), lo, hi, hoje)
                conosco += c
                com_bv += b
            total_por_etapa.setdefault(et, []).append(total)
            conosco_por_etapa.setdefault(et, []).append(conosco)
            com_bv_por_etapa.setdefault(et, []).append(com_bv)

            por_status = _label_days(status_evts, day_in, day_out, "A Iniciar")
            acc = status_por_etapa.setdefault(et, {})
            for st in STATUS_PROJETO:
                acc.setdefault(st, []).append(por_status.get(st, 0))

    out = []
    for et in etapas_medidas:
        ds = sorted(total_por_etapa.get(et, []))
        n = len(ds)
        if n == 0:
            out.append({"etapa": et, "media_dias": None, "mediana_dias": None, "n": 0,
                        "media_dias_conosco": None, "media_dias_com_bv": None, "por_status": []})
            continue
        media = round(sum(ds) / n, 1)
        mediana = ds[n // 2] if n % 2 else round((ds[n // 2 - 1] + ds[n // 2]) / 2, 1)
        por_status = [{"status": st, "media_dias": round(sum(vs) / n, 1)}
                      for st, vs in status_por_etapa.get(et, {}).items() if sum(vs) > 0]
        out.append({
            "etapa": et, "media_dias": media, "mediana_dias": mediana, "n": n,
            "media_dias_conosco": round(sum(conosco_por_etapa[et]) / n, 1),
            "media_dias_com_bv": round(sum(com_bv_por_etapa[et]) / n, 1),
            "por_status": por_status,
        })
    return out


def _analises_tempo(base):
    """4 análises complementares de tempo, a partir da MESMA leitura de sas_pipeline_audit
    (campo='etapa') usada em _tempo_etapas — mas olhando o EGP inteiro, não etapa por
    etapa:

    - lead_time: tempo total (dias) da 1ª transição de etapa registrada até a entrada em
      "Migrado" — só conta EGPs cujo STATUS ATUAL é "Migrado" (não só a etapa ter passado
      por lá: "Despriorizado e Contabilizado" é BAND, pode sobrepor QUALQUER etapa incl.
      "Migrado" — ver BANDS/_funnel_bars —, então um EGP despriorizado que passou pela
      etapa Migrado no caminho NÃO entra no cohort de conclusão). `por_mes` agrupa pelo
      mês em que cada EGP migrou, pra ver se o funil está acelerando/desacelerando.
    - aging: EGPs AINDA em curso — etapa viva != Migrado E status != Migrado/Despriorizado
      e Contabilizado (EGP que já terminou ou saiu do backlog de propósito não está
      "preso"). `dias` (total na etapa atual) é repartido em `dias_trabalho` (até o status
      virar "Concluído" dentro desta etapa) e `dias_espera` (depois disso — pronto, só não
      avançou de etapa ainda); sem "Concluído" registrado, todo o tempo é `dias_trabalho`.
      Ordenado por `dias` desc — oposto do lead_time: não espera o EGP terminar pra dizer
      algo, aponta quem precisa de atenção AGORA.
    - retrabalho: quantas vezes um EGP voltou pra uma etapa ANTERIOR na ordem do funil
      (regressão real — índice menor que o da etapa anterior; etapas fantasma ficam de
      fora por não terem ordem). Sinal de retrabalho/qualidade que o resto das análises
      (sempre "pra frente") não captura.
    - por_responsavel: lead_time médio (só EGPs completos, mesmo cohort do bloco acima)
      agrupado pelo responsável ATUAL em sas_egp_pipeline — não pelo responsável de época
      (não auditado separadamente); EGP que trocou de responsável no meio do caminho conta
      inteiro pro responsável de agora.

    Mesma ressalva de _tempo_etapas: só cobre EGPs com pelo menos 1 transição de etapa
    auditada (sem isso, não há baseline). Também a mesma exclusão de "Em espera" (pedido
    2026-10-01, ver _dias_uteis_segmentos): dias nesse status não contam em `lead_time`
    nem em `dias`/`dias_trabalho`/`dias_espera` do aging — 1 responsável só avança 1 EGP
    por vez, então esse tempo pertence a OUTRO EGP, não a este."""
    vazio = {"lead_time": {"media_dias": None, "mediana_dias": None, "n": 0, "por_mes": []},
             "aging": [], "retrabalho": {"n_egps": 0, "n_eventos": 0, "pares": []},
             "por_responsavel": []}
    if not base:
        return vazio
    from datetime import date
    inl = ", ".join(sql_lit(pj) for pj in base)
    try:
        etapa_rows, status_rows, pipe_rows = _parallel(
            lambda: run_sql(
                f"SELECT projeto, valor_novo AS etapa, ts FROM {T_PIPE_AUD} "
                f"WHERE funil = 'migracao' AND campo = 'etapa' AND projeto IN ({inl}) "
                f"ORDER BY projeto, ts"),
            lambda: run_sql(
                f"SELECT projeto, valor_novo AS status, ts FROM {T_PIPE_AUD} "
                f"WHERE funil = 'migracao' AND campo = 'status' AND projeto IN ({inl}) "
                f"ORDER BY projeto, ts"),
            # pipe-etapa-status: real — a etapa viva casa com a trilha do sas_egp_pipeline_audit,
            # que é do PRÓPRIO EGP; a derivada (a do sucessor) nunca casaria e o intervalo em
            # curso sumiria.
            lambda: run_sql(
                f"SELECT projeto, etapa_migracao, status_migracao, responsavel FROM {T_PIPE} "
                f"WHERE projeto IN ({inl})"))
        hoje = _hoje_utc()
    except HTTPException as e:
        if not _objeto_ausente(e):
            raise
        return vazio

    # pipe-etapa-status: real — mesma leitura gravada de cima (casa com a auditoria).
    cur_etapa = {r["projeto"]: r.get("etapa_migracao") for r in pipe_rows}
    # pipe-etapa-status: real — mesma leitura gravada de cima (casa com a auditoria).
    cur_status = {r["projeto"]: r.get("status_migracao") for r in pipe_rows}
    cur_resp = {r["projeto"]: r.get("responsavel") for r in pipe_rows}
    idx = {s: i for i, s in enumerate(PIPELINE_PROJETO["migracao"])}
    status_por_projeto: dict = {}
    for r in status_rows:
        status_por_projeto.setdefault(r["projeto"], []).append(
            (date.fromisoformat(r["ts"][:10]), r.get("status")))

    rows_by_projeto: dict = {}
    for r in _canon_etapa_rows(etapa_rows):
        rows_by_projeto.setdefault(r["projeto"], []).append(r)

    lead_dias: dict = {}     # projeto -> (dias, mes "YYYY-MM")
    aging: list = []
    retrab_pares: dict = {}  # (de, para) -> n
    retrab_egps: set = set()

    for projeto, rows in rows_by_projeto.items():
        if not rows:
            continue
        primeiro = date.fromisoformat(rows[0]["ts"][:10])
        migrado = next((r for r in rows if r["etapa"] == "Migrado"), None)
        # cohort de "migrado" = status ATUAL confirma "Migrado", não só o histórico de
        # etapa: "Despriorizado e Contabilizado" é BAND (pode sobrepor QUALQUER etapa,
        # incl. "Migrado" — ver BANDS/_funnel_bars), então um EGP despriorizado que passou
        # pela etapa Migrado no caminho NÃO conta como migrado de verdade (pedido
        # 2026-09-30: despriorizado/sanitizado não entram nos KPIs de conclusão).
        if migrado and cur_status.get(projeto) == "Migrado":
            dt_migrado = date.fromisoformat(migrado["ts"][:10])
            # exclui dias em "Em espera" (responsável só avança 1 EGP por vez — ver
            # _dias_uteis_segmentos) do lead time, senão o tempo parado em outro EGP conta
            # como se fosse tempo gasto neste.
            segmentos = _dias_uteis_segmentos(status_por_projeto.get(projeto, []), primeiro, dt_migrado)
            dias_lead = sum(_dias_uteis_entre(lo, hi) for lo, hi in segmentos)
            lead_dias[projeto] = (dias_lead, migrado["ts"][:7])

        ultimo = rows[-1]
        et_viva = cur_etapa.get(projeto)
        st_viva = cur_status.get(projeto)
        # Etapas FANTASMA (Pré-conversão/Conversão pela Área) ENTRAM no aging de propósito
        # — diferente de _tempo_etapas, que as exclui por quebrarem a ordem linear do funil.
        # Aging não depende de ordem, só de "a última transição bate com a etapa viva": um
        # EGP parado há 60+ dias em Pré-conversão é exatamente o tipo de coisa que esta
        # análise existe pra apontar (validado com dado de prod: foi o achado mais forte).
        # STATUS "Migrado"/"Despriorizado e Contabilizado" excluem o EGP do aging — não
        # está "preso precisando de atenção", já terminou ou saiu do backlog de propósito
        # (mesmo critério do cohort de lead_time acima).
        if (ultimo["etapa"] == et_viva and et_viva not in (None, "", "Migrado")
                and st_viva not in ("Migrado", "Despriorizado e Contabilizado")):
            day_in = date.fromisoformat(ultimo["ts"][:10])
            status_evts = status_por_projeto.get(projeto, [])
            # Quebra dias_trabalho / dias_espera: 1ª vez que o STATUS virou "Concluído"
            # DEPOIS de entrar nesta etapa marca o fim do trabalho ativo — o resto é espera
            # (o EGP está pronto, só não avançou de etapa ainda). Pedido 2026-09-30: manter
            # o total como estava (não mudou comportamento de aging/lead_time), só expor a
            # quebra — achado real em prod: 80 de 83 EGPs em "Pré-conversão" já estão
            # Concluído, alguns há 60+ dias, e sem o corte pareciam "travados" por igual.
            # Dentro de cada metade, exclui dias em "Em espera" (pedido 2026-10-01: ver
            # _dias_uteis_segmentos) — distinto deste "dias_espera" (espera do BV após
            # Concluído): "Em espera" é o responsável ocupado em OUTRO EGP, não espera
            # externa, então não é tempo real gasto neste EGP em nenhuma das 2 metades.
            concluido_em = next((d for d, st in status_evts if d >= day_in and st == "Concluído"), None)
            if concluido_em:
                dias_trabalho = sum(_dias_uteis_entre(lo, hi) for lo, hi in
                                    _dias_uteis_segmentos(status_evts, day_in, concluido_em))
                dias_espera = sum(_dias_uteis_entre(lo, hi) for lo, hi in
                                  _dias_uteis_segmentos(status_evts, concluido_em, hoje))
            else:
                dias_trabalho = sum(_dias_uteis_entre(lo, hi) for lo, hi in
                                    _dias_uteis_segmentos(status_evts, day_in, hoje))
                dias_espera = 0
            dias = dias_trabalho + dias_espera
            aging.append({"projeto": projeto, "etapa": et_viva, "dias": dias,
                         "dias_trabalho": dias_trabalho, "dias_espera": dias_espera,
                         "responsavel": cur_resp.get(projeto)})

        for i in range(len(rows) - 1):
            a, b = rows[i]["etapa"], rows[i + 1]["etapa"]
            if a in idx and b in idx and idx[b] < idx[a]:
                retrab_pares[(a, b)] = retrab_pares.get((a, b), 0) + 1
                retrab_egps.add(projeto)

    aging.sort(key=lambda x: -x["dias"])

    ds = sorted(d for d, _ in lead_dias.values())
    n = len(ds)
    if n:
        media = round(sum(ds) / n, 1)
        mediana = ds[n // 2] if n % 2 else round((ds[n // 2 - 1] + ds[n // 2]) / 2, 1)
        por_mes_acc: dict = {}
        for d, mes in lead_dias.values():
            por_mes_acc.setdefault(mes, []).append(d)
        por_mes = [{"mes": m, "media_dias": round(sum(vs) / len(vs), 1), "n": len(vs)}
                  for m, vs in sorted(por_mes_acc.items())]
        lead_time = {"media_dias": media, "mediana_dias": mediana, "n": n, "por_mes": por_mes}
    else:
        lead_time = {"media_dias": None, "mediana_dias": None, "n": 0, "por_mes": []}

    retrabalho = {
        "n_egps": len(retrab_egps), "n_eventos": sum(retrab_pares.values()),
        "pares": [{"de": a, "para": b, "n": cnt} for (a, b), cnt in
                 sorted(retrab_pares.items(), key=lambda kv: -kv[1])],
    }

    resp_acc: dict = {}
    for projeto, (d, _) in lead_dias.items():
        resp = cur_resp.get(projeto) or "Sem responsável"
        resp_acc.setdefault(resp, []).append(d)
    por_responsavel = sorted(
        ({"responsavel": r, "media_dias": round(sum(vs) / len(vs), 1), "n": len(vs)}
         for r, vs in resp_acc.items()),
        key=lambda x: -x["media_dias"])

    return {"lead_time": lead_time, "aging": aging, "retrabalho": retrabalho,
            "por_responsavel": por_responsavel}


def _tempo_base_filtrado(responsavel, responsavel_bv, projeto, status=None, com_bv=None):
    """Resolve o `base` (set de projeto) compartilhado pelos endpoints de análise de tempo
    (/api/tempo-etapas, /api/tempo-analises) — mesmos filtros, mesma semântica (ver
    docstring de tempo_etapas). Extraído pra não duplicar a query entre os 2 endpoints.

    `status` filtra pelo status_migracao ATUAL (sas_egp_pipeline, não histórico — mesma
    convenção de responsavel/responsavel_bv). `com_bv` filtra pelo estado ATUAL do switch
    "Com BV" (sas_gestao_bv) — valores aceitos no front: "com_bv"/"conosco"; EGP sem
    NENHUM evento registrado conta como "conosco" (mesmo fallback de _ownership_days)."""
    _ensure_escopo_ativo()
    _ensure_pipe_table()
    try:
        _, base = _frontier_egps("indi_deps", [])
    except HTTPException:
        base = set()
    if base and (responsavel or responsavel_bv or status):
        inl = ", ".join(sql_lit(pj) for pj in base)
        cond = []
        if responsavel:
            cond.append(f"responsavel IN ({', '.join(sql_lit(v) for v in responsavel)})")
        if responsavel_bv:
            cond.append(f"responsavel_bv IN ({', '.join(sql_lit(v) for v in responsavel_bv)})")
        if status:
            # pipe-etapa-status: real — filtro SQL direto na coluna gravada, coerente com a
            # trilha de auditoria que a aba mede.
            cond.append(f"status_migracao IN ({', '.join(sql_lit(v) for v in status)})")
        rows = run_sql(f"SELECT projeto FROM {T_PIPE} WHERE projeto IN ({inl}) "
                       f"AND {' AND '.join(cond)}")
        base = {r["projeto"] for r in rows}
    if projeto:
        base = base & set(projeto)
    if base and com_bv:
        inl = ", ".join(sql_lit(pj) for pj in base)
        bv_rows = run_sql(
            f"SELECT entity_id AS projeto, com_bv FROM (SELECT entity_id, com_bv, "
            f"row_number() OVER (PARTITION BY entity_id ORDER BY ts DESC) AS rn FROM {T_GBV} "
            f"WHERE entity = 'egp' AND entity_id IN ({inl})) t WHERE rn = 1")
        cur_bv = {r["projeto"]: str(r["com_bv"]).lower() == "true" for r in bv_rows}
        quer_com_bv = "com_bv" in com_bv
        quer_conosco = "conosco" in com_bv
        base = {pj for pj in base
                if (cur_bv.get(pj, False) and quer_com_bv) or (not cur_bv.get(pj, False) and quer_conosco)}
    return base


@app.get("/api/tempo-etapas")
def tempo_etapas(responsavel: list[str] = Query(default=[]),
                 responsavel_bv: list[str] = Query(default=[]), projeto: list[str] = Query(default=[]),
                 status: list[str] = Query(default=[]), com_bv: list[str] = Query(default=[])):
    """Tempo médio/mediano (dias) que os EGPs do escopo Indicium passaram em cada etapa do
    funil de migração, via sas_pipeline_audit. Ver _tempo_etapas.

    Filtros (todos opcionais, aplicados ANTES do cálculo — reduzem o `base` que vira
    universo da amostra, não um pós-filtro no resultado agregado): `responsavel`/
    `responsavel_bv` batem (IN, texto exato — o front manda os valores exatos escolhidos no
    MultiSelect) contra sas_egp_pipeline; `projeto` restringe a N EGPs — usado tanto pela
    busca de 1 EGP quanto pelo filtro de Sub-área BV do front (que resolve a sub-área numa
    lista de projetos antes de mandar pra cá, já que sub-área é derivada no cliente a
    partir do cadastro de Responsáveis BV, não uma coluna própria); `status` filtra pelo
    status_migracao ATUAL (STATUS_PROJETO); `com_bv` filtra pelo estado ATUAL do switch
    "Com BV" (valores "com_bv"/"conosco" — ver _tempo_base_filtrado).

    Restrito ao grupo de gestão (bv_users) — mesma régua da aba (front esconde a aba pra
    quem não é `cfg.is_gestao`, isto é o gate que importa: sem ele o endpoint respondia
    pra qualquer um que soubesse a URL)."""
    _require_gestao()
    base = _tempo_base_filtrado(responsavel, responsavel_bv, projeto, status, com_bv)
    return {"etapas": _tempo_etapas(base)}


@app.get("/api/tempo-analises")
def tempo_analises(responsavel: list[str] = Query(default=[]),
                   responsavel_bv: list[str] = Query(default=[]), projeto: list[str] = Query(default=[]),
                   status: list[str] = Query(default=[]), com_bv: list[str] = Query(default=[])):
    """4 análises complementares de tempo (mesmos filtros/semântica de /api/tempo-etapas).
    Ver _analises_tempo. Restrito ao grupo de gestão (bv_users) — ver /api/tempo-etapas."""
    _require_gestao()
    base = _tempo_base_filtrado(responsavel, responsavel_bv, projeto, status, com_bv)
    return _analises_tempo(base)


def _tempo_base_filtrado_input(responsavel=None, categoria=None, origem=None, chave=None,
                               status=None, com_bv=None):
    """Irmã de _tempo_base_filtrado, pro lado dos INPUTS (funil de ingestão). Universo =
    MESMO "universo por vínculo" do resto do app (escopo_indi=true + _ch_vinculo_ativo —
    ver _ch_vinculo_ativo/README §universo por vínculo), sem deps (escopo "indi" simples,
    mesmo recorte padrão da aba Inputs). `com_bv` usa o MESMO sas_gestao_bv do lado EGP,
    só com entity='input' (entity_id = chave_canonica) — o switch "Com BV" já é genérico
    por entidade (ver /api/gestao/bv)."""
    _ensure_link_tables()
    try:
        sub_esc = _ch_vinculo_ativo("e.escopo_indi = true")
        base = {r["chave_canonica"] for r in run_sql(
            f"SELECT chave_canonica FROM {T_IN} WHERE escopo_indi = true "
            f"AND chave_canonica IN {sub_esc}")}
    except HTTPException:
        base = set()
    if base and (responsavel or categoria or origem or status):
        inl = ", ".join(sql_lit(c) for c in base)
        cond = []
        if responsavel:
            cond.append(f"responsavel IN ({', '.join(sql_lit(v) for v in responsavel)})")
        if categoria:
            cond.append(f"categoria IN ({', '.join(sql_lit(v) for v in categoria)})")
        if origem:
            cond.append(f"origem IN ({', '.join(sql_lit(v) for v in origem)})")
        if status:
            cond.append(f"status IN ({', '.join(sql_lit(v) for v in status)})")
        rows = run_sql(f"SELECT chave_canonica FROM {T_IN} WHERE chave_canonica IN ({inl}) "
                       f"AND {' AND '.join(cond)}")
        base = {r["chave_canonica"] for r in rows}
    if chave:
        base = base & set(chave)
    if base and com_bv:
        inl = ", ".join(sql_lit(c) for c in base)
        bv_rows = run_sql(
            f"SELECT entity_id AS chave, com_bv FROM (SELECT entity_id, com_bv, "
            f"row_number() OVER (PARTITION BY entity_id ORDER BY ts DESC) AS rn FROM {T_GBV} "
            f"WHERE entity = 'input' AND entity_id IN ({inl})) t WHERE rn = 1")
        cur_bv = {r["chave"]: str(r["com_bv"]).lower() == "true" for r in bv_rows}
        quer_com_bv = "com_bv" in com_bv
        quer_conosco = "conosco" in com_bv
        base = {c for c in base
                if (cur_bv.get(c, False) and quer_com_bv) or (not cur_bv.get(c, False) and quer_conosco)}
    return base


def _tempo_etapas_input(base):
    """Irmã de _tempo_etapas pro funil de INGESTÃO (PIPELINE_INPUT/STATUS_INPUT), via
    sas_inputs_audit (T_AUD, chaveada por chave_canonica — não por projeto). Mesma
    semântica: intervalo fechado = 2 transições de etapa consecutivas da MESMA chave;
    aberto conta até hoje só quando bate com a etapa VIVA em sas_inputs_monitor. "Modernizado"
    é a etapa TERMINAL (sem próxima que feche o intervalo) — excluída como "Migrado" é do
    lado EGP. Repartição Com BV/Conosco usa o MESMO sas_gestao_bv (entity='input')."""
    from datetime import date
    if not base:
        return []
    inl = ", ".join(sql_lit(c) for c in base)
    try:
        etapa_rows, status_rows, pipe_rows, bv_rows = _parallel(
            lambda: run_sql(
                f"SELECT chave_canonica AS chave, valor_novo AS etapa, CAST(updated_at AS STRING) AS ts "
                f"FROM {T_AUD} WHERE campo = 'etapa' AND chave_canonica IN ({inl}) "
                f"ORDER BY chave_canonica, updated_at"),
            lambda: run_sql(
                f"SELECT chave_canonica AS chave, valor_novo AS status, CAST(updated_at AS STRING) AS ts "
                f"FROM {T_AUD} WHERE campo = 'status' AND chave_canonica IN ({inl}) "
                f"ORDER BY chave_canonica, updated_at"),
            lambda: run_sql(f"SELECT chave_canonica AS chave, etapa FROM {T_IN} WHERE chave_canonica IN ({inl})"),
            lambda: run_sql(f"SELECT entity_id AS chave, com_bv, data FROM {T_GBV} "
                            f"WHERE entity = 'input' AND entity_id IN ({inl}) ORDER BY entity_id, data, ts"))
        hoje = _hoje_utc()
    except HTTPException as e:
        if not _objeto_ausente(e):
            raise
        return []

    cur_etapa = {r["chave"]: r.get("etapa") for r in pipe_rows}
    bv_timeline: dict = {}
    for r in bv_rows:
        if not r.get("data"):
            continue
        bv_timeline.setdefault(r["chave"], []).append(
            (date.fromisoformat(r["data"][:10]), str(r["com_bv"]).lower() == "true"))
    status_timeline: dict = {}
    for r in status_rows:
        status_timeline.setdefault(r["chave"], []).append(
            (date.fromisoformat(r["ts"][:10]), r.get("status")))

    etapas_medidas = [et for et in PIPELINE_INPUT if et != "Modernizado"]

    rows_by_chave: dict = {}
    for r in etapa_rows:
        rows_by_chave.setdefault(r["chave"], []).append(r)

    total_por_etapa: dict = {}
    conosco_por_etapa: dict = {}
    com_bv_por_etapa: dict = {}
    status_por_etapa: dict = {}
    for chave, rows in rows_by_chave.items():
        for i, r in enumerate(rows):
            et = r.get("etapa")
            if et not in etapas_medidas:
                continue
            day_in = date.fromisoformat(r["ts"][:10])
            if i + 1 < len(rows):
                day_out = date.fromisoformat(rows[i + 1]["ts"][:10])
            elif cur_etapa.get(chave) == et:
                day_out = hoje
            else:
                continue
            total = _dias_uteis_entre(day_in, day_out)
            conosco, com_bv = _ownership_days(bv_timeline.get(chave, []), day_in, day_out, hoje)
            total_por_etapa.setdefault(et, []).append(total)
            conosco_por_etapa.setdefault(et, []).append(conosco)
            com_bv_por_etapa.setdefault(et, []).append(com_bv)

            por_status = _label_days(status_timeline.get(chave, []), day_in, day_out, "A Iniciar")
            acc = status_por_etapa.setdefault(et, {})
            for st in STATUS_INPUT:
                acc.setdefault(st, []).append(por_status.get(st, 0))

    out = []
    for et in etapas_medidas:
        ds = sorted(total_por_etapa.get(et, []))
        n = len(ds)
        if n == 0:
            out.append({"etapa": et, "media_dias": None, "mediana_dias": None, "n": 0,
                        "media_dias_conosco": None, "media_dias_com_bv": None, "por_status": []})
            continue
        media = round(sum(ds) / n, 1)
        mediana = ds[n // 2] if n % 2 else round((ds[n // 2 - 1] + ds[n // 2]) / 2, 1)
        por_status = [{"status": st, "media_dias": round(sum(vs) / n, 1)}
                      for st, vs in status_por_etapa.get(et, {}).items() if sum(vs) > 0]
        out.append({
            "etapa": et, "media_dias": media, "mediana_dias": mediana, "n": n,
            "media_dias_conosco": round(sum(conosco_por_etapa[et]) / n, 1),
            "media_dias_com_bv": round(sum(com_bv_por_etapa[et]) / n, 1),
            "por_status": por_status,
        })
    return out


def _analises_tempo_input(base):
    """Irmã de _analises_tempo pro funil de ingestão — mesmas 4 análises, chaveadas por
    chave_canonica. Cohort de lead_time/aging exclui "Sanitizado"/"Autoprodutor" (saídas
    terminais do funil normal, mesmo papel de "Despriorizado e Contabilizado" do lado EGP:
    ver STATUS_INPUT/README §Sanitizado). Exploratório — sem a mesma validação cruzada
    contra prod que o lado EGP teve; use com essa ressalva."""
    vazio = {"lead_time": {"media_dias": None, "mediana_dias": None, "n": 0, "por_mes": []},
             "aging": [], "retrabalho": {"n_egps": 0, "n_eventos": 0, "pares": []},
             "por_responsavel": []}
    if not base:
        return vazio
    from datetime import date
    inl = ", ".join(sql_lit(c) for c in base)
    try:
        etapa_rows, status_rows, pipe_rows = _parallel(
            lambda: run_sql(
                f"SELECT chave_canonica AS chave, valor_novo AS etapa, CAST(updated_at AS STRING) AS ts "
                f"FROM {T_AUD} WHERE campo = 'etapa' AND chave_canonica IN ({inl}) "
                f"ORDER BY chave_canonica, updated_at"),
            lambda: run_sql(
                f"SELECT chave_canonica AS chave, valor_novo AS status, CAST(updated_at AS STRING) AS ts "
                f"FROM {T_AUD} WHERE campo = 'status' AND chave_canonica IN ({inl}) "
                f"ORDER BY chave_canonica, updated_at"),
            lambda: run_sql(
                f"SELECT chave_canonica AS chave, etapa, status, responsavel FROM {T_IN} "
                f"WHERE chave_canonica IN ({inl})"))
        hoje = _hoje_utc()
    except HTTPException as e:
        if not _objeto_ausente(e):
            raise
        return vazio

    cur_etapa = {r["chave"]: r.get("etapa") for r in pipe_rows}
    cur_status = {r["chave"]: r.get("status") for r in pipe_rows}
    cur_resp = {r["chave"]: r.get("responsavel") for r in pipe_rows}
    idx = {s: i for i, s in enumerate(PIPELINE_INPUT)}
    status_por_chave: dict = {}
    for r in status_rows:
        status_por_chave.setdefault(r["chave"], []).append(
            (date.fromisoformat(r["ts"][:10]), r.get("status")))

    rows_by_chave: dict = {}
    for r in etapa_rows:
        rows_by_chave.setdefault(r["chave"], []).append(r)

    lead_dias: dict = {}
    aging: list = []
    retrab_pares: dict = {}
    retrab_chaves: set = set()

    for chave, rows in rows_by_chave.items():
        if not rows:
            continue
        primeiro = date.fromisoformat(rows[0]["ts"][:10])
        modernizado = next((r for r in rows if r["etapa"] == "Modernizado"), None)
        if modernizado and cur_status.get(chave) not in ("Sanitizado",):
            dt_mod = date.fromisoformat(modernizado["ts"][:10])
            lead_dias[chave] = (_dias_uteis_entre(primeiro, dt_mod), modernizado["ts"][:7])

        ultimo = rows[-1]
        et_viva = cur_etapa.get(chave)
        st_viva = cur_status.get(chave)
        if (ultimo["etapa"] == et_viva and et_viva not in (None, "", "Modernizado")
                and st_viva not in ("Sanitizado", "Autoprodutor")):
            day_in = date.fromisoformat(ultimo["ts"][:10])
            dias = _dias_uteis_entre(day_in, hoje)
            concluido_em = next(
                (d for d, st in status_por_chave.get(chave, []) if d >= day_in and st == "Concluído"),
                None)
            if concluido_em:
                dias_trabalho = _dias_uteis_entre(day_in, concluido_em)
                dias_espera = _dias_uteis_entre(concluido_em, hoje)
            else:
                dias_trabalho, dias_espera = dias, 0
            aging.append({"projeto": chave, "etapa": et_viva, "dias": dias,
                         "dias_trabalho": dias_trabalho, "dias_espera": dias_espera,
                         "responsavel": cur_resp.get(chave)})

        for i in range(len(rows) - 1):
            a, b = rows[i]["etapa"], rows[i + 1]["etapa"]
            if a in idx and b in idx and idx[b] < idx[a]:
                retrab_pares[(a, b)] = retrab_pares.get((a, b), 0) + 1
                retrab_chaves.add(chave)

    aging.sort(key=lambda x: -x["dias"])

    ds = sorted(d for d, _ in lead_dias.values())
    n = len(ds)
    if n:
        media = round(sum(ds) / n, 1)
        mediana = ds[n // 2] if n % 2 else round((ds[n // 2 - 1] + ds[n // 2]) / 2, 1)
        por_mes_acc: dict = {}
        for d, mes in lead_dias.values():
            por_mes_acc.setdefault(mes, []).append(d)
        por_mes = [{"mes": m, "media_dias": round(sum(vs) / len(vs), 1), "n": len(vs)}
                  for m, vs in sorted(por_mes_acc.items())]
        lead_time = {"media_dias": media, "mediana_dias": mediana, "n": n, "por_mes": por_mes}
    else:
        lead_time = {"media_dias": None, "mediana_dias": None, "n": 0, "por_mes": []}

    retrabalho = {
        "n_egps": len(retrab_chaves), "n_eventos": sum(retrab_pares.values()),
        "pares": [{"de": a, "para": b, "n": cnt} for (a, b), cnt in
                 sorted(retrab_pares.items(), key=lambda kv: -kv[1])],
    }

    resp_acc: dict = {}
    for chave, (d, _) in lead_dias.items():
        resp = cur_resp.get(chave) or "Sem responsável"
        resp_acc.setdefault(resp, []).append(d)
    por_responsavel = sorted(
        ({"responsavel": r, "media_dias": round(sum(vs) / len(vs), 1), "n": len(vs)}
         for r, vs in resp_acc.items()),
        key=lambda x: -x["media_dias"])

    return {"lead_time": lead_time, "aging": aging, "retrabalho": retrabalho,
            "por_responsavel": por_responsavel}


@app.get("/api/tempo-etapas-input")
def tempo_etapas_input(responsavel: list[str] = Query(default=[]), categoria: list[str] = Query(default=[]),
                       origem: list[str] = Query(default=[]), chave: list[str] = Query(default=[]),
                       status: list[str] = Query(default=[]), com_bv: list[str] = Query(default=[])):
    """Irmã de /api/tempo-etapas pro funil de INGESTÃO. Ver _tempo_etapas_input.
    Restrito ao grupo de gestão (bv_users) — mesma régua do lado EGP."""
    _require_gestao()
    base = _tempo_base_filtrado_input(responsavel, categoria, origem, chave, status, com_bv)
    return {"etapas": _tempo_etapas_input(base)}


@app.get("/api/tempo-analises-input")
def tempo_analises_input(responsavel: list[str] = Query(default=[]), categoria: list[str] = Query(default=[]),
                         origem: list[str] = Query(default=[]), chave: list[str] = Query(default=[]),
                         status: list[str] = Query(default=[]), com_bv: list[str] = Query(default=[])):
    """Irmã de /api/tempo-analises pro funil de INGESTÃO. Ver _analises_tempo_input.
    Restrito ao grupo de gestão (bv_users) — mesma régua do lado EGP."""
    _require_gestao()
    base = _tempo_base_filtrado_input(responsavel, categoria, origem, chave, status, com_bv)
    return _analises_tempo_input(base)


def _prio_capacidade():
    """Capacidade (inputs/mes) do plano de priorizacao. Configuravel pela gestao via
    PATCH /api/priorizacao/capacidade e PERSISTIDA em sas_app_config — o plano e UNICO
    e compartilhado (muda para todos, incl. a coluna Mes das outras abas). Default 400;
    robusto a tabela/valor ausente."""
    try:
        r = run_sql(f"SELECT valor FROM {T_CFG} WHERE chave = 'prio_capacidade'")
        v = int(r[0]["valor"]) if r and r[0].get("valor") is not None else 0
        return v if v > 0 else 400
    except (HTTPException, TypeError, ValueError, KeyError, IndexError):
        return 400


def _compute_priorizacao(scope: str = "indi", area: str = "", deps: str = "transitive",
                         capacidade: int = 0, pin_override=None):
    """Plano de ingestão por CAPACIDADE: empacota os EGPs do recorte (scope/area + deps) em
    'meses' de no máximo `capacidade` inputs DISTINTOS a ingerir. Prioridade LEXICOGRÁFICA:
    (1) VIABILIDADE — não bloqueado e com pendências ingeríveis vem antes de bloqueado / só-SAS-local;
    (2) ALAVANCAGEM — maior fan-out (output alimenta mais EGPs do recorte);
    (3) QUICK WIN — menos inputs a ingerir (desempate). DEDUPE entre meses (input compartilhado
    conta 1x, no 1o mês). O teto conta TODOS os inputs a ingerir (incl. SAS/local); SAS/local já
    cai pro fim via viabilidade."""
    # capacidade=0 (default do front) -> usa a config persistida (gestao); >0 = override explicito
    cap = max(1, int(capacidade)) if capacidade else _prio_capacidade()
    all_nodes = run_sql(f"SELECT projeto, area, escopo_indi FROM {T_ND}")
    area_of = {r["projeto"]: r.get("area") for r in all_nodes if r.get("projeto")}
    base = set()
    for r in all_nodes:
        pj = r.get("projeto")
        if not pj:
            continue
        if scope == "indi" and str(r.get("escopo_indi")).lower() != "true":
            continue
        if area and r.get("area") != area:
            continue
        base.add(pj)
    edges = _edges_pruned()
    # 'Despriorizado e Contabilizado' nao puxa dependencias EXCLUSIVAS (no_expand), mas o
    # EGP em si participa do plano como um EGP normal — mes, capacidade, resumo e pin
    # (pedido 2026-07: a exclusao do empacotamento foi revertida; so a regra de deps fica).
    fora = _egps_fora_backlog()
    if deps and deps != "none":
        dep_of = _dep_of_map(edges)
        frontier = set(_transitive_upstream(base, dep_of, no_expand=fora))
        # ex-dependências: retidas no plano (Recalcular não as derruba — decisão 3 da
        # spec 2026-08). Entram no FIM da ordem com ZERO pendência: não consomem
        # capacidade e seus inputs ficam fora da fila e da contagem viva do mês.
        ex_plan = _ex_deps(frontier, base)[0]
    else:
        frontier = set(base)
        ex_plan = set()
    if not frontier:
        return {"meses": [], "n_meses": 0, "n_inputs": 0, "n_egps": 0, "capacidade": cap,
                "resumo": {"total": 0, "bloqueados": 0, "habilitados": 0, "migrados_mes": 0}}
    # fan-out (alavancagem): nº de EGPs DO FRONTIER que consomem o output de cada EGP
    fan = {}
    for e in edges:
        alvo, dep = e.get("projeto_alvo"), e.get("depende_do")
        if dep and alvo and dep != alvo and dep in frontier and alvo in frontier:
            fan.setdefault(dep, set()).add(alvo)
    fanout = {pj: len(s) for pj, s in fan.items()}
    # inputs a ingerir por EGP (+ origem p/ separar SAS/local do que é ingerível de verdade)
    _ensure_link_tables()
    _ensure_input_pipeline_cols()
    inl = ", ".join(sql_lit(pj) for pj in frontier)
    lnk = _lnk_resolvido()
    # A UNIDADE que dimensiona o mês: chave física, ou FAMÍLIA com a flag ligada. Era aqui
    # que a contagem por safra mais doía — um EGP que lê 47 safras da mesma tabela ocupava
    # 47 vagas da capacidade do mês tendo UMA ingestão a pedir (ADR 0002).
    _fam = _fam_sql_egp()
    pairs = run_sql(
        f"SELECT e.projeto AS projeto, e.chave_canonica AS chave, i.origem AS origem, "
        f"{_fam} AS fam "
        f"FROM {T_EGP} e LEFT JOIN {T_IN} i ON e.chave_canonica = i.chave_canonica "
        f"LEFT JOIN {T_LINK} l ON l.projeto = e.projeto AND l.chave_canonica = e.chave_canonica "
        f"WHERE e.projeto IN ({inl}) "
        f"AND NOT ({_modern('i.etapa', 'e.modernizada_auto', 'i.status', lnk)})")
    egp_inputs = {}
    _ingerivel = {}
    for r in pairs:
        ch = (r.get("fam") if FAMILIAS_ON else r.get("chave")) or r.get("chave")
        if not ch:
            continue
        pj = r["projeto"]
        egp_inputs.setdefault(pj, set()).add(ch)
        # set, não contador: no grão safra é equivalente (o par projeto×chave é único),
        # e no grão família impede contar a mesma família uma vez por safra
        if not (r.get("origem") or "").startswith("SAS/Local"):
            _ingerivel.setdefault(pj, set()).add(ch)
    n_ingerivel = {pj: len(v) for pj, v in _ingerivel.items()}
    try:
        _ensure_pipe_table()
        # pipe-etapa-status: real — `etapa_of` é DENOMINADOR aqui (critério 189, via
        # _prio_contabiliza): a etapa espelhada não pode puxar uma ex-dependência para
        # dentro do total do plano sozinha. A EXIBIÇÃO sai de `etapa_exib`/`status_exib`.
        pipe_rows = run_sql(f"SELECT projeto, responsavel, mes_prioridade, etapa_migracao, status_migracao FROM {T_PIPE}")
        resp_of = {r["projeto"]: r.get("responsavel") for r in pipe_rows}
        etapa_of = {r["projeto"]: r.get("etapa_migracao") for r in pipe_rows}    # pipe-etapa-status: real (denominador)
        status_of = {r["projeto"]: r.get("status_migracao") for r in pipe_rows}  # pipe-etapa-status: real (base do derivado)
        # DERIVADO (exibição): a coluna Etapa/Status da aba Priorização mostra andamento —
        # o mesmo EGP não pode dizer uma etapa aqui e outra na aba EGPs.
        _exib_prio = vinculos.mapa_exibido(
            {p: (etapa_of.get(p), status_of.get(p)) for p in etapa_of}, _vinculos_por_antecessor())
        etapa_exib = {p: v[0] for p, v in _exib_prio.items()}
        status_exib = {p: v[1] for p, v in _exib_prio.items()}
        pin = {}
        for r in pipe_rows:
            pj, mp = r.get("projeto"), r.get("mes_prioridade")
            if (pj in frontier or pj in ex_plan) and mp is not None and str(mp) != "":
                try:
                    mv = int(mp)
                except (TypeError, ValueError):
                    continue
                if 1 <= mv <= 100:   # faixa válida; fora dela ignora (protege o loop do plano)
                    pin[pj] = mv
    except HTTPException:
        resp_of, pin = {}, {}
        etapa_of, status_of = {}, {}
        etapa_exib, status_exib = {}, {}
    try:
        blocked = _blocking()["blocked"]
    except HTTPException:
        blocked = set()

    def _viab(pj):
        # 0 = viável agora (não bloqueado; nada pendente OU tem pendência ingerível);
        # 1 = pendência só SAS/local (aguardando produtor); 2 = bloqueado por dependência.
        if pj in blocked:
            return 2
        if len(egp_inputs.get(pj, ())) == 0 or n_ingerivel.get(pj, 0) > 0:
            return 0
        return 1

    # overrides de pin NÃO persistidos (edições locais da aba, aplicadas p/ preview/save):
    # {projeto: mes} fixa; {projeto: None} desafixa. Só afeta EGPs do recorte (frontier).
    if pin_override:
        for pj, mv in pin_override.items():
            if pj not in frontier and pj not in ex_plan:
                continue
            if mv is None or str(mv) == "":
                pin.pop(pj, None)
                continue
            try:
                mv = int(mv)
            except (TypeError, ValueError):
                continue
            if 1 <= mv <= 100:
                pin[pj] = mv
    # ordem lexicográfica: viabilidade asc, fan-out desc, esforço asc, nome.
    # Ex-dependências vão no FIM (fora do egp_inputs -> 0 novos; sem elas no inlist de
    # pairs, suas pendências não entram no plano nem na contagem viva).
    order = sorted(frontier, key=lambda pj: (_viab(pj), -fanout.get(pj, 0), len(egp_inputs.get(pj, ())), pj))
    order += sorted(ex_plan)
    # régua do denominador: a LISTA CONGELADA (arquivo versionado, sem ida ao warehouse).
    _lb_prio = set(_linha_base())
    meses_raw = plan_months(order, egp_inputs, pin, cap)
    out = []
    for i, mth in enumerate(meses_raw):
        egps_out = []
        for e in mth["egps"]:
            pj = e["projeto"]
            egps_out.append({"projeto": pj, "area": area_of.get(pj),
                             "n_inputs_novos": e["n_inputs_novos"],
                             "responsavel": resp_of.get(pj) or None, "excede": e["excede"],
                             "bloqueado": pj in blocked, "fan_out": fanout.get(pj, 0),
                             "mes_pin": pin.get(pj),
                             "ex_dependencia": pj in ex_plan,
                             "etapa": etapa_exib.get(pj) or None, "status": status_exib.get(pj) or None})
        out.append({"mes": i + 1, "n_inputs": len(mth["inputs"]),
                    # contagem pela etapa REAL (etapa_of), exibição pela derivada
                    "n_egps": sum(1 for e in egps_out
                                   if _prio_contabiliza(e, etapa_of, _lb_prio)),
                    "egps": egps_out})
    # Totais seguem a LISTA CONGELADA, a mesma régua de `contaNoTotalEgp`, do universo da
    # Gestão e da tabela por área: ex-dependência conta se está na foto. As demais seguem
    # LISTADAS (badge/retenção) mas fora do denominador — sem isso o plano dizia 207
    # enquanto o escopo dizia 193. Era o critério "189" (ex só com etapa REAL), que a foto
    # absorveu em 29/09/2026 e que divergia dela em ex com etapa FANTASMA presente na lista.
    contab = set(frontier) | (set(ex_plan) & _lb_prio)
    resumo = resumo_counts(contab, blocked)
    resumo["migrados_mes"] = _migrados_mes(contab)
    total_inputs = sum(len(m["inputs"]) for m in meses_raw)
    payload = {"meses": out, "n_meses": len(out), "n_inputs": total_inputs,
               "n_egps": len(contab), "capacidade": cap, "resumo": resumo}
    # mesmos campos vivos do overlay do snapshot (p/ o preview exibir o bloco novo)
    try:
        tots = _prio_live_input_stats(out)
        if tots is not None:
            payload["n_inputs_modernizados"], payload["n_inputs_total"] = tots
    except HTTPException:
        pass
    return payload


# ---- Snapshot (congelamento) do plano de priorização --------------------------
# O plano é derivado a cada request; p/ não ficar recalculando/derivando o tempo todo,
# a aba mostra um SNAPSHOT salvo (1 linha id='current'). Recalcular = /preview (ao vivo,
# não salva); Salvar = POST /snapshot (admin). Ver spec priorizacao-snapshot-design.
def _ensure_prio_snapshot_table(sp=False):
    if dialeto.PG:  # no Postgres o schema vem das migrações (db/migrations), nunca do app
        return None
    ddl = (f"CREATE TABLE IF NOT EXISTS {T_PRIO_SNAP} (id STRING, payload STRING, "
           f"capacidade INT, saved_by STRING, saved_at STRING) USING DELTA")
    (_run_sp if sp else run_sql)(ddl, want_rows=False)


def _prio_live_input_stats(meses):
    """Anota em cada mês (in-place) a contagem VIVA `n_inputs_modernizados`/`n_inputs_total`
    dos inputs distintos dos EGPs CONGELADOS do mês, e em cada EGP o marginal vivo
    `n_inputs_novos_vivo` (a coluna "+Inputs" da aba; o `n_inputs_novos` congelado fica
    intacto ao lado, para comparação). Devolve (modernizados, total) somados, ou None se
    não há EGPs. Regras:
      • universo por vínculo (pares link_broken fora — mesmo predicado do Resumo/Inputs);
      • dedupe igual ao plano: input compartilhado conta no 1º mês em que aparece;
      • TOTAL é vivo (cresce quando o corpus ganha inputs — ex.: fix da descompactação);
        os EGPs do mês NÃO mudam — o plano segue congelado mesmo se o total passar da
        capacidade-guia (pedido 2026-07-30);
      • modernizado = chave com TODOS os pares resolvidos (_modern; humano prevalece);
      • EGPs com flag ex_dependencia ficam FORA: inputs de ex-dep não entram na fila
        nem na contagem viva do mês (decisão 3 da spec 2026-08)."""
    projs = {e.get("projeto") for m in meses for e in m.get("egps", [])
             if e.get("projeto") and not e.get("ex_dependencia")}
    if not projs:
        return None
    _ensure_link_tables()
    _ensure_input_pipeline_cols()
    inl = ", ".join(sql_lit(p) for p in projs)
    # sanitização derivada entra como `lnk` (§3.4.18): chave lida só por despriorizados
    # conta como resolvida no mês, igual ao Sanitizado humano.
    ok = _modern("i.etapa", "coalesce(i.modernizada_auto, e.modernizada_auto)", "i.status",
                 _lnk_resolvido())
    pairs = run_sql(
        f"SELECT e.projeto AS projeto, e.chave_canonica AS chave, ({ok}) AS ok, "
        f"{_fam_sql_egp()} AS fam "
        f"FROM {T_EGP} e LEFT JOIN {T_IN} i ON i.chave_canonica = e.chave_canonica "
        f"LEFT JOIN {T_LINK} l ON l.projeto = e.projeto AND l.chave_canonica = e.chave_canonica "
        f"WHERE e.projeto IN ({inl}) AND NOT coalesce(l.link_broken, false)")
    by_egp, chave_ok = {}, {}
    for r in pairs:
        # unidade = família com a flag ligada; o AND acumulado abaixo já dá a régua certa
        # (família modernizada só quando TODAS as suas safras estão)
        ch = (r.get("fam") if FAMILIAS_ON else r.get("chave")) or r.get("chave")
        if not ch:
            continue
        by_egp.setdefault(r.get("projeto"), set()).add(ch)
        # Statement API serializa bool como string; chave modernizada = todos os pares ok
        v = str(r.get("ok")).lower() == "true"
        chave_ok[ch] = chave_ok.get(ch, True) and v
    seen, tot_all, mod_all = set(), 0, 0
    for m in meses:
        chaves = set()
        for e in m.get("egps", []):
            if e.get("ex_dependencia"):
                e["n_inputs_novos_vivo"] = 0
                continue
            # marginal VIVO por EGP, na ordem congelada do mês: o que este EGP traz e
            # ainda não veio de um mês anterior nem de um EGP acima. Mesma regra do plano
            # (plan_months), só que na unidade de hoje — sem isso a coluna "+Inputs"
            # continuava com o número gravado no snapshot, contado por safra.
            novas = by_egp.get(e.get("projeto"), set()) - seen - chaves
            chaves |= novas
            e["n_inputs_novos_vivo"] = sum(1 for ch in novas if not chave_ok.get(ch))
        chaves -= seen
        seen |= chaves
        m["n_inputs_total"] = len(chaves)
        m["n_inputs_modernizados"] = sum(1 for ch in chaves if chave_ok.get(ch))
        tot_all += m["n_inputs_total"]
        mod_all += m["n_inputs_modernizados"]
    return mod_all, tot_all


def _prio_contabiliza(e, etapa_real_of=None, linha_base=None):
    """Entrada do plano conta nos TOTAIS de EGP? Tudo conta, menos ex-dependência que não
    está na LISTA CONGELADA. Ela segue LISTADA no plano — só não entra no denominador, p/
    o plano bater com o escopo.

    `linha_base` (conjunto de projetos da foto) é a régua, a mesma de `contaNoTotalEgp` e
    do universo da Gestão. Sem ela, cai no critério "189" (ex só conta com etapa REAL), que
    é o comportamento anterior — a foto ABSORVEU esse critério em 29/09/2026 (§3.1.2) e ele
    sobrevive aqui só como fallback para quem chamar sem a lista.

    `etapa_real_of` ({projeto: etapa GRAVADA}) separa os dois eixos: a linha `e` carrega a
    etapa EXIBIDA (pode ser espelho do sucessor — §3.2.7) e o denominador tem de ler a
    GRAVADA, senão uma ex-dependência sem etapa entra no total só porque ganhou vínculo
    (spec §4). Sem o mapa — payload congelado, lido sem acesso ao funil vivo — cai na
    etapa da própria linha, que é o comportamento antigo.

    Espelha também a exceção de 2026-09-25: etapa fantasma conta se o status for
    'Despriorizado e Contabilizado' (esforço gasto e reconhecido); ver _ex_deps_contab.
    Os dois eixos são independentes — um diz QUAL etapa ler, o outro O QUE ela vale."""
    if not e.get("ex_dependencia"):
        return True
    if linha_base is not None:
        return e.get("projeto") in linha_base
    et = (e.get("etapa") if etapa_real_of is None
          else etapa_real_of.get(e.get("projeto"), e.get("etapa")))
    if not et:
        return False
    return (et not in PHANTOM_ETAPAS_MIGRACAO
            or e.get("status") == "Despriorizado e Contabilizado")


def _overlay_live_attribution(payload):
    """Sobrescreve, in-place, os campos EDITÁVEIS-mid-execução do payload congelado:
    responsavel/etapa/status (de T_PIPE) e bloqueado (de _blocking), + resumo.bloqueados
    e resumo.migrados_mes. O RESTO (mês, EGP, n_inputs_novos, excede, fan_out, mes_pin,
    capacidade) fica FROZEN — é o plano. Silencia falhas: se a live query falha, mantém
    o valor congelado (melhor mostrar stale do que quebrar a aba)."""
    live_resp, live_etapa, live_status, live_etapa_real = {}, {}, {}, {}
    try:
        _ensure_pipe_table()
        # pipe-etapa-status: real — `live_etapa_real` é o denominador (critério 189, via
        # _prio_contabiliza); o que o overlay EXIBE é derivado logo abaixo. Mesmo par de
        # eixos do /api/prio/preview, que este overlay tem de reproduzir.
        for r in run_sql(f"SELECT projeto, responsavel, etapa_migracao, status_migracao FROM {T_PIPE}"):
            pj = r.get("projeto")
            if not pj:
                continue
            live_resp[pj] = r.get("responsavel")
            live_etapa_real[pj] = r.get("etapa_migracao")    # pipe-etapa-status: real (denominador)
            live_status[pj] = r.get("status_migracao")       # pipe-etapa-status: real (base do derivado)
        # DERIVADO (exibição): a aba Priorização mostra andamento, igual à aba EGPs.
        _exib = vinculos.mapa_exibido(
            {p: (live_etapa_real.get(p), live_status.get(p)) for p in live_etapa_real},
            _vinculos_por_antecessor())
        live_etapa = {p: v[0] for p, v in _exib.items()}
        live_status = {p: v[1] for p, v in _exib.items()}
    except HTTPException:
        pass
    _lb_live = set(_linha_base())      # régua do denominador (ver _prio_contabiliza)
    try:
        live_blocked = _blocking()["blocked"]
    except HTTPException:
        live_blocked = None                 # sem live -> mantém 'bloqueado' congelado
    frontier = []
    for mes in payload.get("meses", []):
        for e in mes.get("egps", []):
            pj = e.get("projeto")
            if not pj:
                continue
            if pj in live_resp:
                e["responsavel"] = live_resp.get(pj) or None
            if pj in live_etapa:
                e["etapa"] = live_etapa.get(pj) or None
            if pj in live_status:
                e["status"] = live_status.get(pj) or None
            if live_blocked is not None:
                e["bloqueado"] = pj in live_blocked
            # contabiliza DEPOIS do overlay: a etapa acabou de ser atualizada e é ela que
            # decide se uma ex-dependência entra nos totais (critério "189") — pela etapa
            # REAL, nunca pela espelhada (mapa vazio = sem live -> etapa da própria linha).
            if _prio_contabiliza(e, live_etapa_real or None, _lb_live):
                frontier.append(pj)
        mes["n_egps"] = sum(1 for e in mes.get("egps", [])
                            if _prio_contabiliza(e, live_etapa_real or None, _lb_live))
    # resumo derivado do overlay (mesma semântica do compute original)
    resumo = payload.get("resumo") or {}
    if live_blocked is not None and frontier:
        resumo["bloqueados"] = sum(1 for pj in frontier if pj in live_blocked)
        resumo["habilitados"] = len(frontier) - resumo["bloqueados"]
    resumo["total"] = len(frontier)
    resumo["migrados_mes"] = _migrados_mes(frontier)
    payload["resumo"] = resumo
    payload["n_egps"] = len(frontier)
    # contagem VIVA de inputs por mês (modernizados/total) sobre os EGPs congelados —
    # substitui o n_inputs congelado na UI. Falha não derruba a aba (campos ausentes).
    try:
        tots = _prio_live_input_stats(payload.get("meses", []))
        if tots is not None:
            payload["n_inputs_modernizados"], payload["n_inputs_total"] = tots
    except HTTPException:
        pass
    return payload


def _read_prio_snapshot():
    """Snapshot vigente: devolve o PAYLOAD CONGELADO (mês/EGPs/n_inputs/etc. — o plano)
    com overlay live de atribuição (responsavel/etapa/status/bloqueado) e resumo derivado.
    None se não há/ilegível. Payloads antigos (formato {projeto: mes} do fix inicial)
    são ignorados — o cliente vê 'sem snapshot' e o admin re-salva."""
    try:
        rows = run_sql(f"SELECT payload, saved_by, saved_at FROM {T_PRIO_SNAP} WHERE id = 'current'")
    except HTTPException:
        return None
    if not rows:
        return None
    try:
        payload = json.loads(rows[0].get("payload") or "")
    except (TypeError, ValueError):
        return None
    if not isinstance(payload, dict) or "meses" not in payload:
        return None                          # formato do fix intermediário / lixo
    # Poda ANTES do overlay: é ele que recalcula n_egps do mês e resumo.total, e contando
    # sobre a lista ainda cheia o card dizia 206 com 193 na tela (30/09/2026).
    _poda_fora_da_linha_base(payload)
    _overlay_live_attribution(payload)
    return {**payload, "snapshot": {"saved_by": rows[0].get("saved_by"),
                                    "saved_at": rows[0].get("saved_at")}}


def _write_prio_snapshot(payload, saved_by_expr, sp=False):
    """Grava/atualiza o snapshot vigente. saved_by_expr = expressão SQL ('auto' no seed via
    SP; _ator() no save do admin). sp=True escreve como SP (seed sem depender do
    privilégio do leitor)."""
    run = _run_sp if sp else run_sql
    _ensure_prio_snapshot_table(sp=sp)
    pj = sql_lit(json.dumps(payload, ensure_ascii=False))                   # payload congelado inteiro
    cap = int(payload.get("capacidade") or 0)
    run(f"MERGE INTO {T_PRIO_SNAP} t USING (SELECT 'current' AS id) s ON t.id = s.id "
        f"WHEN MATCHED THEN UPDATE SET payload = {pj}, capacidade = {cap}, "
        f"saved_by = {saved_by_expr}, saved_at = cast({AGORA} AS STRING) "
        f"WHEN NOT MATCHED THEN INSERT (id, payload, capacidade, saved_by, saved_at) VALUES "
        f"('current', {pj}, {cap}, {saved_by_expr}, cast({AGORA} AS STRING))",
        want_rows=False)


def _poda_fora_da_linha_base(payload):
    """Tira do plano os EGPs que já saíram do escopo — DERIVADO, na leitura.

    O plano e a linha de base são dois congelamentos diferentes. O snapshot foi salvo
    quando esses EGPs ainda estavam no escopo; desde então eles saíram (`escopo_indi` =
    false, alguns com `ativo` = false), mas o snapshot é congelado e seguia listando todos.
    Medido em 30/09/2026: plano 206, lista congelada 193, e os 13 de diferença são
    exatamente os que saíram — nenhum EGP da lista está fora do plano.

    Poda na LEITURA, não re-salvando o snapshot: re-salvar recalcularia mês e ordem de
    todo mundo e jogaria fora os pins que a gestão fixou. Também não é patch de dado — o
    snapshot fica como está, e a poda se refaz sozinha se a lista congelada mudar.

    Mês que fica sem EGP é mantido: a capacidade do mês é decisão de plano, não
    consequência de quem sobrou nele."""
    lb = set(linha_base.projetos(_linha_base()))
    if not lb:
        return payload            # sem lista congelada não há o que podar
    n_fora = 0
    for mm in (payload or {}).get("meses") or []:
        egps = mm.get("egps") or []
        mantidos = [e for e in egps if e.get("projeto") in lb]
        n_fora += len(egps) - len(mantidos)
        mm["egps"] = mantidos
    if n_fora:
        payload["fora_linha_base"] = n_fora
    return payload


def _extras_do_plano():
    """[{projeto, mes}] dos Extras que herdam mês do Antecessor — o MESMO mapa que os
    funis de extras já usam (`_mes_dos_extras`), exposto no payload do plano porque o
    FRONT precisa dele: `useMesPlan` monta `mesOf` só com `meses[].egps[]` (os 193 do
    plano), então todo Extra ficava com mês "—" e era derrubado por qualquer filtro de mês
    nas 11 telas que usam o hook — levando junto os inputs que só Extra lê (66 medidos em
    08/10/2026, dos quais 60 passam a ter mês).

    Campo SEPARADO de `meses[].egps[]` de propósito: quem CONTA o plano (FunilMesTable,
    _prio_live_input_stats) continua contando 193. Extra não entra no plano; só ganha mês.

    Casca e Extra sem antecessor no plano ficam de fora (`_mes_dos_extras` já os omite):
    casca não é trabalho, e novo declarado só a gestão data.

    Grafo ainda não publicado -> lista vazia. O plano é o payload principal e tem de
    renderizar sem os extras; qualquer OUTRA falha sobe (ver _objeto_ausente)."""
    try:
        return [{"projeto": p, "mes": m} for p, m in sorted(_mes_dos_extras().items())]
    except HTTPException as e:
        if not _objeto_ausente(e):
            raise
        return []


def _com_extras(payload):
    """Anexa `extras` ao payload do plano (ver _extras_do_plano). Em todos os caminhos de
    retorno de /api/priorizacao, p/ o front nunca receber um plano sem o campo."""
    payload["extras"] = _extras_do_plano()
    return payload


@app.get("/api/priorizacao")
def priorizacao(scope: str = "indi", area: str = "", deps: str = "transitive", capacidade: int = 0):
    """Plano FIXADO: devolve o SNAPSHOT salvo (não recalcula). Sem snapshot -> auto-seed
    (computa 1x e grava via SP, p/ não depender do privilégio do leitor) e devolve.
    Recalcular ao vivo = GET /preview; salvar novo snapshot = POST /snapshot (admin)."""
    snap = _read_prio_snapshot()
    if snap is not None:
        return _com_extras(_poda_fora_da_linha_base(snap))
    payload = _compute_priorizacao(scope, area, deps, capacidade)
    if dialeto.PG and SOMENTE_LEITURA:   # AWS em modo leitura (Fase 1): quem congela é o Databricks
        return _com_extras({**payload, "snapshot": None})
    try:
        _write_prio_snapshot(payload, "'auto'", sp=True)
    except Exception as e:
        print(f"[priorizacao] auto-seed falhou (segue ao vivo, sem congelar): {e}", flush=True)
        return _com_extras({**payload, "snapshot": None})
    return _com_extras(_poda_fora_da_linha_base(
        _read_prio_snapshot() or {**payload, "snapshot": None}))


class PrioEdits(BaseModel):
    pins: dict[str, int | None] = {}   # override local NÃO salvo: {projeto: mes} fixa; None desafixa
    capacidade: int | None = None      # override local de capacidade (None = usa a persistida)


def _persist_pins(pins):
    """Persiste overrides de pin em sas_egp_pipeline (MERGE mes_prioridade por EGP). Auditado."""
    if not pins:
        return
    _ensure_pipe_table()
    for pj, mv in pins.items():
        try:
            mes_lit = "NULL" if (mv is None or str(mv) == "") else str(int(mv))
        except (TypeError, ValueError):
            continue
        cur = run_sql(f"SELECT mes_prioridade AS mp FROM {T_PIPE} WHERE projeto = {sql_lit(pj)}")
        old = cur[0].get("mp") if cur else None
        run_sql(
            f"MERGE INTO {T_PIPE} t USING (SELECT {sql_lit(pj)} AS projeto) s ON t.projeto = s.projeto "
            f"WHEN MATCHED THEN UPDATE SET mes_prioridade = {mes_lit}, "
            f"updated_by = {_ator()}, updated_at = cast({AGORA} AS STRING) "
            f"WHEN NOT MATCHED THEN INSERT (projeto, mes_prioridade, updated_by, updated_at) VALUES "
            f"({sql_lit(pj)}, {mes_lit}, {_ator()}, cast({AGORA} AS STRING))",
            want_rows=False)
        if _norm(old) != _norm(mv):
            run_sql(
                f"INSERT INTO {T_PIPE_AUD} (id, projeto, funil, campo, valor_antigo, valor_novo, ator, ts) "
                f"VALUES ({sql_lit(uuid.uuid4().hex)}, {sql_lit(pj)}, 'migracao', 'mes_prioridade', "
                f"{sql_lit(_norm(old))}, {sql_lit(_norm(mv))}, {_ator()}, cast({AGORA} AS STRING))",
                want_rows=False)


@app.post("/api/priorizacao/preview")
def priorizacao_preview(edits: PrioEdits = PrioEdits()):
    """Recalcula AO VIVO com as edições locais (pins/capacidade) SEM salvar nada. View-all."""
    cap = edits.capacidade if (edits.capacidade and edits.capacidade > 0) else 0
    return {**_compute_priorizacao(capacidade=cap, pin_override=(edits.pins or None)), "snapshot": None}


@app.post("/api/priorizacao/snapshot")
def priorizacao_save_snapshot(edits: PrioEdits = PrioEdits()):
    """Persiste as edições (pins/capacidade) e SALVA o snapshot recomputado. SÓ admin (bv_admins).
    Auditado. Determinístico -> o salvo == o que o admin pré-visualizou."""
    _require_admin()
    _persist_pins(edits.pins or {})
    cap = 0
    if edits.capacidade and 1 <= edits.capacidade <= 10000:
        old_cap = _prio_capacidade()
        if not dialeto.PG:  # no Postgres o schema vem das migrações (db/migrations), nunca do app
            run_sql(f"CREATE TABLE IF NOT EXISTS {T_CFG} "
                    f"(chave STRING, valor STRING, updated_by STRING, updated_at STRING)", want_rows=False)
        run_sql(
            f"MERGE INTO {T_CFG} t USING (SELECT 'prio_capacidade' AS chave) s ON t.chave = s.chave "
            f"WHEN MATCHED THEN UPDATE SET valor = {sql_lit(str(edits.capacidade))}, "
            f"updated_by = {_ator()}, updated_at = cast({AGORA} AS STRING) "
            f"WHEN NOT MATCHED THEN INSERT (chave, valor, updated_by, updated_at) VALUES "
            f"('prio_capacidade', {sql_lit(str(edits.capacidade))}, {_ator()}, cast({AGORA} AS STRING))",
            want_rows=False)
        if old_cap != edits.capacidade:   # auditoria (aba Histórico, fonte 'EGPs')
            run_sql(
                f"INSERT INTO {T_PIPE_AUD} (id, projeto, funil, campo, valor_antigo, valor_novo, ator, ts) "
                f"VALUES ({sql_lit(uuid.uuid4().hex)}, '(config)', 'migracao', 'capacidade_mes', "
                f"{sql_lit(str(old_cap))}, {sql_lit(str(edits.capacidade))}, {_ator()}, cast({AGORA} AS STRING))",
                want_rows=False)
        cap = edits.capacidade
    payload = _compute_priorizacao(capacidade=cap)   # pins/capacidade já persistidos -> lê do DB
    _write_prio_snapshot(payload, _ator(), sp=False)
    try:
        run_sql(
            f"INSERT INTO {T_PIPE_AUD} (id, projeto, funil, campo, valor_antigo, valor_novo, ator, ts) "
            f"VALUES ({sql_lit(uuid.uuid4().hex)}, '(config)', 'migracao', 'priorizacao_snapshot', "
            f"'', cast({AGORA} AS STRING), {_ator()}, cast({AGORA} AS STRING))",
            want_rows=False)
    except HTTPException:
        pass
    return _read_prio_snapshot() or {**payload, "snapshot": None}


class PrioMesPin(BaseModel):
    projeto: str
    mes: int | None = None


# DESATIVADO (2026-07): a aba Priorização agora edita pins localmente e persiste só via
# POST /api/priorizacao/snapshot (admin). Rota não-registrada de propósito (código mantido
# para referência/rollback). Reabilitar = descomentar o @app.patch — mas prefira o fluxo snapshot.
# @app.patch("/api/priorizacao/mes")
def priorizacao_set_mes(p: PrioMesPin):
    """Fixa (mes>=1) ou limpa (mes=null) o mês de prioridade de 1 EGP na aba Priorização.
    Pin absoluto (o teto de capacidade vira guia). Só gestão (bv_users). Auditado."""
    _require_gestao()
    if p.mes is not None and (not isinstance(p.mes, int) or isinstance(p.mes, bool)
                              or p.mes < 1 or p.mes > 100):
        raise HTTPException(400, "mes deve ser inteiro entre 1 e 100, ou null")
    _ensure_pipe_table()
    cur = run_sql(f"SELECT mes_prioridade AS mp FROM {T_PIPE} WHERE projeto = {sql_lit(p.projeto)}")
    old = cur[0].get("mp") if cur else None
    mes_lit = "NULL" if p.mes is None else str(int(p.mes))
    run_sql(
        f"MERGE INTO {T_PIPE} t USING (SELECT {sql_lit(p.projeto)} AS projeto) s ON t.projeto = s.projeto "
        f"WHEN MATCHED THEN UPDATE SET mes_prioridade = {mes_lit}, "
        f"updated_by = {_ator()}, updated_at = cast({AGORA} AS STRING) "
        f"WHEN NOT MATCHED THEN INSERT (projeto, mes_prioridade, updated_by, updated_at) VALUES "
        f"({sql_lit(p.projeto)}, {mes_lit}, {_ator()}, cast({AGORA} AS STRING))",
        want_rows=False)
    if _norm(old) != _norm(p.mes):
        run_sql(
            f"INSERT INTO {T_PIPE_AUD} (id, projeto, funil, campo, valor_antigo, valor_novo, ator, ts) "
            f"VALUES ({sql_lit(uuid.uuid4().hex)}, {sql_lit(p.projeto)}, 'migracao', 'mes_prioridade', "
            f"{sql_lit(_norm(old))}, {sql_lit(_norm(p.mes))}, {_ator()}, "
            f"cast({AGORA} AS STRING))", want_rows=False)
    return {"ok": True, "projeto": p.projeto, "mes": p.mes}


class PrioCapacidade(BaseModel):
    capacidade: int


# DESATIVADO (2026-07): capacidade agora é editada localmente e persistida só via
# POST /api/priorizacao/snapshot (admin). Rota não-registrada de propósito (código mantido).
# @app.patch("/api/priorizacao/capacidade")
def priorizacao_set_capacidade(p: PrioCapacidade):
    """Muda a CAPACIDADE (inputs/mes) do plano de priorizacao. Persistida em sas_app_config:
    o plano e UNICO e compartilhado — muda para todos, incl. a coluna Mes das outras abas.
    So gestao (bv_users). Auditado em T_PIPE_AUD com projeto sentinela '(config)'."""
    _require_gestao()
    if not isinstance(p.capacidade, int) or isinstance(p.capacidade, bool) \
            or p.capacidade < 1 or p.capacidade > 10000:
        raise HTTPException(400, "capacidade deve ser inteiro entre 1 e 10000")
    old = _prio_capacidade()
    if not dialeto.PG:  # no Postgres o schema vem das migrações (db/migrations), nunca do app
        run_sql(f"CREATE TABLE IF NOT EXISTS {T_CFG} "
                f"(chave STRING, valor STRING, updated_by STRING, updated_at STRING)",
                want_rows=False)
    run_sql(
        f"MERGE INTO {T_CFG} t USING (SELECT 'prio_capacidade' AS chave) s ON t.chave = s.chave "
        f"WHEN MATCHED THEN UPDATE SET valor = {sql_lit(str(p.capacidade))}, "
        f"updated_by = {_ator()}, updated_at = cast({AGORA} AS STRING) "
        f"WHEN NOT MATCHED THEN INSERT (chave, valor, updated_by, updated_at) VALUES "
        f"('prio_capacidade', {sql_lit(str(p.capacidade))}, {_ator()}, "
        f"cast({AGORA} AS STRING))", want_rows=False)
    if old != p.capacidade:
        run_sql(
            f"INSERT INTO {T_PIPE_AUD} (id, projeto, funil, campo, valor_antigo, valor_novo, ator, ts) "
            f"VALUES ({sql_lit(uuid.uuid4().hex)}, '(config)', 'migracao', 'capacidade_mes', "
            f"{sql_lit(str(old))}, {sql_lit(str(p.capacidade))}, {_ator()}, "
            f"cast({AGORA} AS STRING))", want_rows=False)
    return {"ok": True, "capacidade": p.capacidade}


def _aud_monitor_sql(lim, where=""):
    """SELECT da auditoria do Monitor com o fan-out da família COLAPSADO em uma linha.

    Editar etapa/status de uma família grava uma linha POR SAFRA, todas no mesmo instante
    (`_patch_familia`). Sem colapsar, um clique virava 20 linhas idênticas no histórico do
    input e, na aba Histórico, essas 20 comiam o LIMIT e empurravam o resto do dia para
    fora — o histórico ficava ilegível justamente no dia em que alguém trabalhou.

    O colapso é de EXIBIÇÃO: as linhas continuam gravadas por safra, que é onde o estado
    mora (ADR 0002). Agrupa por chave de família + campo + valores + autor + instante, e
    devolve `n_safras`. A chave de família no GROUP BY é o que separa fan-out de edição em
    LOTE: tabelas diferentes tocadas no mesmo segundo seguem uma linha cada, porque a
    regra de família só junta nomes que diferem no token de data.
    """
    cat = "regexp_extract(chave_canonica, '^([^:]+)::', 1)"
    art = "regexp_replace(chave_canonica, '^[^:]+::', '')"
    fam = familias.familia_candidata_sql(art, cat)
    return (
        f"SELECT min(chave_canonica) AS chave_canonica, {fam} AS familia, campo, "
        f"valor_antigo, valor_novo, updated_by, "
        f"CAST(updated_at AS STRING) AS updated_at, count(*) AS n_safras "
        f"FROM {T_AUD}{where} "
        f"GROUP BY {fam}, {cat}, campo, valor_antigo, valor_novo, updated_by, updated_at "
        f"ORDER BY updated_at DESC, chave_canonica, campo, valor_antigo NULLS FIRST, "
        f"valor_novo NULLS FIRST LIMIT {lim}")


@app.get("/api/audit")
def audit(chave: str = "", limit: int = 200):
    lim = max(1, min(int(limit), 1000))
    # Caso de uso 1: filtro por 1 input específico → só Monitoramento (T_AUD), igual ao
    # comportamento histórico, apenas anotando a fonte. Não quebra quem chama com chave.
    if chave:
        # família: o histórico é o das SAFRAS (é onde o estado foi escrito) — ver
        # _chaves_para_leitura. Chave sem família continua com o WHERE de sempre.
        try:
            # DENTRO do try: `_chaves_para_leitura` também consulta o warehouse (resolve a
            # família em sas_inputs_monitor). Fora dele, uma falha ali escapava como 403/502
            # em vez do {"rows": []} que este endpoint promete — e o histórico sumia com
            # erro, não com lista vazia.
            _chs = ", ".join(sql_lit(c) for c in _chaves_para_leitura(chave))
            rows = run_sql(_aud_monitor_sql(lim, f" WHERE chave_canonica IN ({_chs})"))
        except HTTPException:
            return {"rows": []}  # tabela ainda não existe (antes do 1º publish c/ auditoria)
        for r in rows:
            r["fonte"] = "Monitoramento"
        return {"rows": rows}

    # Caso de uso 2 (aba Histórico): une as 3 tabelas de auditoria num shape único.
    # Cada SELECT já vem ordenado/limitado em {lim} (não puxa tudo) e tem seu próprio
    # try/except — uma tabela ausente contribui com 0 linhas, sem derrubar as outras.
    def _safe(sql):
        try:
            return run_sql(sql)
        except HTTPException:
            return []

    merged = []
    # chave_familia: para onde o LINK do Histórico aponta (a aba Inputs lista família).
    # Sai do mapa de CORPUS, não do `familia` do SELECT acima: aquele é candidato por NOME
    # (regex do token de data) e existe para o RÓTULO — nome candidato que não tem ≥2
    # membros no corpus não vira linha de família na aba Inputs, e linkar por ele daria
    # "não encontrado". A guarda dos ≥2 é decisão de corpus (ADR 0002).
    _fam = _familia_por_chave()
    for r in _safe(_aud_monitor_sql(lim)):
        merged.append({
            "fonte": "Monitoramento",
            "chave_canonica": r.get("chave_canonica"),
            "chave_familia": _fam.get(r.get("chave_canonica")),
            "campo": r.get("campo"),
            "valor_antigo": r.get("valor_antigo"),
            "valor_novo": r.get("valor_novo"),
            "updated_by": r.get("updated_by"),
            "updated_at": r.get("updated_at"),
            "n_safras": r.get("n_safras"),
            "familia": r.get("familia"),
        })

    for r in _safe(
        f"SELECT projeto, campo, valor_antigo, valor_novo, ator, "
        f"CAST(ts AS STRING) AS ts FROM {T_PIPE_AUD} "
        f"ORDER BY ts DESC, projeto, campo, valor_novo NULLS FIRST LIMIT {lim}"):
        merged.append({
            "fonte": "EGPs",
            "chave_canonica": r.get("projeto"),
            "campo": r.get("campo"),
            "valor_antigo": r.get("valor_antigo"),
            "valor_novo": r.get("valor_novo"),
            "updated_by": r.get("ator"),
            "updated_at": r.get("ts"),
        })

    for r in _safe(
        f"SELECT acao, egp_dor1, projeto, ator, CAST(ts AS STRING) AS ts "
        f"FROM {T_ESC_AUD} ORDER BY ts DESC, egp_dor1, acao LIMIT {lim}"):
        acao = r.get("acao")
        if acao == "remove":
            va, vn = "no escopo", "removido"
        else:  # "add" (e qualquer outro valor) → trata como inclusão
            va, vn = "—", "adicionado"
        merged.append({
            "fonte": "Escopo",
            "chave_canonica": r.get("projeto") or r.get("egp_dor1"),
            "campo": "escopo",
            "valor_antigo": va,
            "valor_novo": vn,
            "updated_by": r.get("ator"),
            "updated_at": r.get("ts"),
        })

    for r in _safe(
        f"SELECT projeto, chave_canonica, valor_antigo, valor_novo, ator, "
        f"CAST(ts AS STRING) AS ts FROM {T_LINK_AUD} "
        f"ORDER BY ts DESC, projeto, chave_canonica LIMIT {lim}"):
        merged.append({
            "fonte": "Vínculos",
            "chave_canonica": r.get("projeto"),                          # entidade no Histórico: o EGP
            "campo": f"link_broken@{r.get('chave_canonica')}",           # frontend parseia o sufixo p/ mostrar qual input
            "valor_antigo": r.get("valor_antigo"),
            "valor_novo": r.get("valor_novo"),
            "updated_by": r.get("ator"),
            "updated_at": r.get("ts"),
        })

    # ordena por updated_at desc; None vai pro fim (mais antigo). Corta no total em {lim}.
    merged.sort(key=lambda x: (x["updated_at"] is not None, x["updated_at"] or ""), reverse=True)
    return {"rows": merged[:lim]}


@app.get("/api/resumo")
def resumo():
    """Tabelas do Resumo em DUAS visões (mesmo padrão dos funis): escopo Indicium
    (funil/origem) e Indicium + dependências transitivas (funil_deps/origem_deps),
    sem dupla contagem. Libname_in fica FORA da tabela de origem (pedido do usuário)."""
    _ensure_input_pipeline_cols()
    # sem LEFT JOIN em T_LINK aqui (o universo já é filtrado por _ch_vinculo_ativo), então
    # o `lnk` carrega só a sanitização derivada (§3.4.18).
    modern = _modern("i.etapa", "coalesce(i.modernizada_auto, r.modernizada_auto)", "i.status",
                     _san_derivada_sql("i.chave_canonica"))
    BUCKET_ORDER = ["BigQuery", "Arquivo", "Transacional", "SAS/Local"]
    # Dirigido pelo MONITOR (i), não por sas_resumo (r): sas_resumo só é reescrita pelo
    # publish completo, então input que entra por carga avulsa (ex.: overlay do
    # descompacta) não tem linha lá — com o JOIN no sentido antigo (T_RES LEFT T_IN) a
    # tabela de origem subcontava vs o card da landing (5 chaves em 2026-09-14). O que
    # se perde ao inverter: só as órfãs de sas_resumo, todas Libname_in (fora da tabela
    # por pedido do usuário — e fora da landing também). r vira fallback de
    # area_principal/origem_bucket (NULL p/ linha nova até o próximo publish → área "—").
    FRM = f"{T_IN} i LEFT JOIN {T_RES} r ON i.chave_canonica = r.chave_canonica"
    # bucket derivado AO VIVO de i.origem (mesma autoridade dos cards da aba Inputs —
    # r.origem_bucket do publish divergia: TODO script era bucketado 'SAS/Local').
    # Fallback r.origem_bucket cobre i.origem NULL (hoje só fora do universo) — não usar
    # r.origem_bucket direto, senão Resumo ≠ Monitor por bucket.
    bkt = ("CASE WHEN i.origem IN ('SAS/Local (externo)', 'SAS/Local (dependência)') "
           "THEN 'SAS/Local' "
           "WHEN i.origem IN ('Arquivo', 'Script') THEN 'Arquivo' "
           "WHEN i.origem IN ('BigQuery', 'Transacional') THEN i.origem "
           "ELSE r.origem_bucket END")

    def origem_block(where):
        rows = run_sql(
            f"SELECT {bkt} AS bucket, count(*) AS total, "
            f"count(CASE WHEN {modern} THEN 1 END) AS modernizado, "
            f"count(CASE WHEN NOT {modern} THEN 1 END) AS nao_modernizado "
            f"FROM {FRM} WHERE {where} GROUP BY {bkt}")
        om = {x["bucket"]: x for x in rows}
        orows, otot = [], {"total": 0, "modernizado": 0, "nao_modernizado": 0}
        for b in BUCKET_ORDER:
            x = om.get(b)
            row = {"bucket": b,
                   "total": int(x["total"]) if x else 0,
                   "modernizado": int(x["modernizado"]) if x else 0,
                   "nao_modernizado": int(x["nao_modernizado"]) if x else 0}
            for k in otot:
                otot[k] += row[k]
            orows.append(row)
        return {"rows": orows, "total": otot}

    def nao_mod_por_area(where):
        # MESMA régua da tabela de origem (só os 4 buckets — Libname_in fora, pedido
        # 2026-07). Sem este filtro o funil contava 114 libnames a mais (2.204 vs 2.092).
        b4 = ", ".join(f"'{b}'" for b in BUCKET_ORDER)
        rows = run_sql(
            f"SELECT r.area_principal AS area, count(CASE WHEN NOT {modern} THEN 1 END) AS nao_mod "
            f"FROM {FRM} WHERE {where} AND {bkt} IN ({b4}) "
            f"GROUP BY r.area_principal")
        return {x["area"]: int(x["nao_mod"]) for x in rows}

    def funil_block(raw, nm):
        frows, ftot = [], {"qtd_dor1": 0, "deps": 0, "egps_enviados": 0,
                           "egps_analisados": 0, "inputs_nao_modernizados": 0}
        for x in raw:
            row = {"area": x["area"], "qtd_dor1": int(x["qtd_dor1"]), "deps": int(x.get("deps") or 0),
                   "egps_enviados": int(x["egps_enviados"]), "egps_analisados": int(x["egps_analisados"]),
                   "inputs_nao_modernizados": nm.get(x["area"], 0)}
            if x.get("a_parte"):
                # linha à parte (extras): só os inputs somam no total — ver o chamador.
                row["a_parte"] = True
                ftot["inputs_nao_modernizados"] += row["inputs_nao_modernizados"]
            else:
                for k in ftot:
                    ftot[k] += row[k]
            frows.append(row)
        # área de input SEM linha de EGP no recorte (ex.: input Jurídico consumido por
        # EGP de Cobrança): ganha linha própria zerada em EGPs — sem ela o total perdia
        # esses inputs em silêncio (21 na visão +deps quando detectado, 2026-07).
        # Normaliza dos DOIS lados com a mesma régua. `nm` vem de r.area_principal, que
        # passou a poder ser NULL depois que o join do resumo inverteu para T_IN (linha
        # de monitor sem par em sas_resumo). Comparando `None` cru contra um `vistos`
        # que já guardava "—" (ou ""), a checagem passava e saía uma SEGUNDA linha "—"
        # — duplicando a chave de render no ResumoView.
        _norm_area = lambda a: (a or "").strip() or "—"
        vistos = {_norm_area(x["area"]) for x in raw}
        for a, n in sorted(nm.items(), key=lambda kv: str(kv[0])):
            if _norm_area(a) not in vistos and n > 0:
                row = {"area": _norm_area(a), "qtd_dor1": 0, "deps": 0, "egps_enviados": 0,
                       "egps_analisados": 0, "inputs_nao_modernizados": n}
                ftot["inputs_nao_modernizados"] += n
                frows.append(row)
        frows.sort(key=lambda r: (bool(r.get("a_parte")), -r["qtd_dor1"], -r["inputs_nao_modernizados"]))
        return {"rows": frows, "total": ftot}

    try:
        _ensure_link_tables()
        # universo por vínculo (predicado único — _ch_vinculo_ativo), igual landing/funis.
        w_esc = (f"i.escopo_indi = true AND i.chave_canonica IN "
                 f"{_ch_vinculo_ativo('e.escopo_indi = true')}")
        funil = run_sql(f"SELECT area, qtd_dor1, egps_enviados, egps_analisados FROM {T_FUN}")
        # Com família ligada, os blocos de INPUT saem do dataset do escopo (mesmo conjunto
        # que a aba Inputs serve) em vez de uma contagem SQL paralela: família de origem
        # mista tem UM bucket (a moda, como na tela) e a unidade é a família. Contar por
        # SQL aqui poria a mesma família em dois buckets e o total passaria do distinto.
        # O lado de EGP (qtd_dor1/enviados/analisados/deps) não é input e não muda.
        if FAMILIAS_ON:
            _ri = _dataset_escopo("indi", [])
            # Pendência pelo RECORTE AMPLIADO, a régua do card "A ingerir" (landing, item4):
            # a família agrega só as safras em vista, e no dataset do escopo saíam
            # resolvidas as famílias cuja safra pendente só a dependência/o extra lê —
            # 194 aqui × 205 no card, 11 famílias, medido em 14/10/2026. Bucket e área
            # continuam os do escopo; só o modernizado/não vem do recorte ampliado.
            _mod_amp = {r.get("chave_canonica"): py_modern(r)
                        for r in _universo_contagem(_dataset_escopo("indi_deps", []))}
            _mod = lambda r: _mod_amp.get(r.get("chave_canonica"), py_modern(r))
            origem, nm = _origem_block_py(_ri, _mod), _nao_mod_area_py(_ri, _mod)
        else:
            origem = origem_block(w_esc)
            nm = nao_mod_por_area(w_esc)
    except HTTPException:
        # tabelas ainda não existem (antes do 1º publish que cria resumo/funil)
        empty_f = {"rows": [], "total": {"qtd_dor1": 0, "deps": 0, "egps_enviados": 0,
                                         "egps_analisados": 0, "inputs_nao_modernizados": 0}}
        empty_o = {"rows": [], "total": {"total": 0, "modernizado": 0, "nao_modernizado": 0}}
        return {"funil": empty_f, "origem": empty_o, "funil_deps": None, "origem_deps": None}

    # ---- visão + dependências (MESMO frontier dos funis/landing — não divergir) ----
    funil_deps = origem_deps = origem_extras = None
    try:
        frontier = _frontier_egps("indi_deps", [])[0]
    except HTTPException:
        frontier = set()
    # EGPs: dependências e ex-dependências pela classe GRAVADA na linha de base — a régua
    # do `total_egps` da Visão geral e do card da aba EGPs, que vivem na mesma tela. Contar
    # pelo grafo vivo (frontier − base, + ex na foto) perdia a dependência da foto que saiu
    # do recorte: 192 × 193 em 08/10/2026 (ex com etapa fantasma) e de novo em 14/10/2026
    # (`Fechamento_Contabil_RPDD_3040`, unificado num sucessor). Extra não é dependência
    # (§3.1.2) e ganha linha à parte, abaixo. O universo de INPUTS (ch_fr) segue o frontier.
    _pc = linha_base.por_classe(_linha_base())
    deps = _pc["dependencia"] | _pc["ex_dependencia"]
    if frontier:
        inl = ", ".join(sql_lit(p) for p in frontier)
        ch_fr = f"i.chave_canonica IN {_ch_vinculo_ativo(f'e.projeto IN ({inl})')}"
        # Inputs que SÓ extras leem vão para a linha "Extras", não para a área principal:
        # ela é calculada sobre escopo ∪ dependências e não enxerga extra, então esses
        # inputs caíam numa linha "(sem área)" com 0 EGPs (103 de 116 em 14/10/2026).
        if FAMILIAS_ON:
            _rd = _dataset_escopo("indi_deps", [])
            origem_deps = _origem_block_py(_rd)
            nm_deps = _nao_mod_area_py(
                _rd, area_of=lambda r: AREA_EXTRAS if r.get("so_de_extra") else r.get("area_principal"))
            # 3ª tabela, ISOLADA — mesmo papel do funil de extras logo acima: as duas de
            # cima são cumulativas (escopo ⊂ escopo+deps), esta é um recorte à parte.
            # Conjunto EXCLUSIVO (`so_de_extra`), o mesmo do card "Inputs dos extras": é o
            # que faz a tabela e o card falarem do mesmo número. O filtro da aba Inputs
            # mostra mais (tudo que um extra lê, incl. o compartilhado) — de propósito.
            origem_extras = _origem_block_py([r for r in _rd if r.get("so_de_extra")])
        else:
            origem_deps = origem_block(ch_fr)
            _de_ex, _de_ct = _chaves_por_extra()   # local: o `so_ex` da landing é de lá
            _so_ex = _de_ex - _de_ct
            if _so_ex:
                # `ch_fr` junto: sem o predicado de universo a tabela contava linhas de
                # T_IN que o card não conta, e as duas discordavam (52 × 25 medido).
                _in_so = f"i.chave_canonica IN ({', '.join(sql_lit(k) for k in sorted(_so_ex))})"
                origem_extras = origem_block(f"{ch_fr} AND {_in_so}")
                nm_deps = nao_mod_por_area(f"{ch_fr} AND NOT ({_in_so})")
                nm_deps[AREA_EXTRAS] = origem_extras["total"]["nao_modernizado"]
            else:
                nm_deps = nao_mod_por_area(ch_fr)
        # por área: base (sas_funil_area, por status_extracao) + deps agrupadas pela área
        # do nó — dep já está no corpus, então conta como enviada E analisada.
        by_area = {x["area"]: {"area": x["area"], "qtd_dor1": int(x["qtd_dor1"]), "deps": 0,
                               "egps_enviados": int(x["egps_enviados"]),
                               "egps_analisados": int(x["egps_analisados"])} for x in funil}
        if deps:
            inl_d = ", ".join(sql_lit(p) for p in deps)
            area_nd = {r["projeto"]: r["area"] for r in run_sql(
                f"SELECT projeto, coalesce(nullif(area, ''), '—') AS area "
                f"FROM {T_ND} WHERE projeto IN ({inl_d})")}
            # Projeto da lista sem nó no corpus conta em "—": tirá-lo faria a tabela
            # voltar a divergir do total, que é o tamanho da lista. Enviado/analisado só
            # quem tem nó — sem ele, não está no corpus.
            for p in deps:
                a = area_nd.get(p, "—")
                row = by_area.setdefault(a, {"area": a, "qtd_dor1": 0, "deps": 0,
                                             "egps_enviados": 0, "egps_analisados": 0})
                row["qtd_dor1"] += 1
                row["deps"] += 1
                if p in area_nd:
                    row["egps_enviados"] += 1
                    row["egps_analisados"] += 1
        # Extras à PARTE, como o "(+N extra)" do card Total de EGPs: os EGPs não entram no
        # total da tabela (que é a linha de base), os inputs entram (o Total de Inputs do
        # card também os conta).
        n_ext = len(_extras_no_recorte())
        if n_ext or nm_deps.get(AREA_EXTRAS):
            by_area[AREA_EXTRAS] = {"area": AREA_EXTRAS, "qtd_dor1": n_ext, "deps": 0,
                                    "egps_enviados": n_ext, "egps_analisados": n_ext,
                                    "a_parte": True}
        funil_deps = funil_block(list(by_area.values()), nm_deps)

    return {"funil": funil_block(funil, nm), "origem": origem,
            "funil_deps": funil_deps, "origem_deps": origem_deps,
            "origem_extras": origem_extras}


# ---- Gestão de EGPs/Inputs (aba Gestão): datas + status/comentários ----
# Tabelas próprias (CREATE IF NOT EXISTS, nunca dropadas, FORA do publish — zero
# interação com o MERGE): sas_gestao_status (histórico; o mais recente é o "último
# status" exibido na tabela — SEM resumo IA, por decisão do usuário) e sas_gestao_datas
# (datas por entity+id, vale p/ EGP e Input sem ALTER nas tabelas existentes).
# Edições abertas a qualquer usuário logado (OBO), como o resto do app.

@functools.lru_cache(maxsize=1)
def _ensure_gestao_tables():
    if dialeto.PG:  # no Postgres o schema vem das migrações (db/migrations), nunca do app
        return True
    run_sql(f"CREATE TABLE IF NOT EXISTS {T_GST} ("
            f"id STRING, entity STRING, entity_id STRING, autor STRING, criado_por STRING, "
            f"ts STRING, texto STRING) USING DELTA", want_rows=False)
    run_sql(f"CREATE TABLE IF NOT EXISTS {T_GDT} ("
            f"entity STRING, entity_id STRING, inicio STRING, fim_conversao STRING, fim STRING, "
            f"updated_by STRING, updated_at STRING) USING DELTA", want_rows=False)
    run_sql(f"CREATE TABLE IF NOT EXISTS {T_GBV} ("
            f"id STRING, entity STRING, entity_id STRING, com_bv BOOLEAN, data STRING, "
            f"autor STRING, ts STRING) USING DELTA", want_rows=False)
    run_sql(f"CREATE TABLE IF NOT EXISTS {T_GRV} ("
            f"entity STRING, entity_id STRING, contador INT, "
            f"updated_by STRING, updated_at STRING) USING DELTA", want_rows=False)
    return True


def _gestao_extras(entity):
    """Datas + texto/data do ÚLTIMO status + eventos do switch "Com BV" por entity_id."""
    _ensure_gestao_tables()
    _d_rows, _u_rows, _bv_rows = _parallel(
        lambda: run_sql(
            f"SELECT entity_id, inicio, fim_conversao, fim, "
            f"CAST(updated_at AS STRING) AS updated_at FROM {T_GDT} "
            f"WHERE entity = {sql_lit(entity)}"),
        lambda: run_sql(
            f"SELECT entity_id, texto, ts FROM (SELECT entity_id, texto, ts, "
            f"row_number() OVER (PARTITION BY entity_id ORDER BY ts DESC) AS rn "
            f"FROM {T_GST} WHERE entity = {sql_lit(entity)}) t WHERE rn = 1"),
        lambda: run_sql(f"SELECT id, entity_id, com_bv, data, autor FROM {T_GBV} "
                        f"WHERE entity = {sql_lit(entity)} ORDER BY ts"))
    datas = {r["entity_id"]: r for r in _d_rows}
    ultimos = {r["entity_id"]: {"texto": r.get("texto"), "data": r.get("ts")} for r in _u_rows}
    bv = {}
    for r in _bv_rows:
        bv.setdefault(r["entity_id"], []).append(
            {"id": r["id"], "comBv": str(r["com_bv"]).lower() == "true",
             "data": r["data"], "autor": r.get("autor")})
    return datas, ultimos, bv


def _revisoes_regras(entity):
    """Contador manual de revisões de regras de negócio (EGP devolvido de PRD p/ DES) por
    entity_id. Só existe p/ EGP; Input devolve {} sem tocar o warehouse."""
    if entity != "egp":
        return {}
    _ensure_gestao_tables()
    return {r["entity_id"]: int(r["contador"] or 0) for r in run_sql(
        f"SELECT entity_id, contador FROM {T_GRV} WHERE entity = 'egp' AND contador > 0")}


def _gestao_anota(rid, membros, datas, ultimos, bv):
    """Anotação de gestão de uma linha: datas, último status e eventos "Com BV".

    Para uma FAMÍLIA, o que está gravado na chave da família manda e o que falta é
    herdado das safras — 442 datas e 940 comentários (18/09/2026) foram escritos por
    carga antes de a família existir, e migrá-los seria reescrever histórico de gestão.
    Campo vazio na família herda do membro atualizado por último; o último status é o
    mais recente entre família e safras; os eventos de BV são a união, em ordem.

    Linha sem família (membros vazio) devolve exatamente o que já estava na chave."""
    chaves = [rid] + [m for m in (membros or []) if m != rid]
    d = dict(datas.get(rid) or {})
    for m in sorted((m for m in chaves[1:] if m in datas),
                    key=lambda k: str((datas.get(k) or {}).get("updated_at") or ""),
                    reverse=True):
        for campo in ("inicio", "fim_conversao", "fim"):
            if not d.get(campo) and (datas[m] or {}).get(campo):
                d[campo] = datas[m][campo]
    u = {}
    for m in chaves:
        c = ultimos.get(m)
        if c and str(c.get("data") or "") > str(u.get("data") or ""):
            u = c
    ev = [e for m in chaves for e in bv.get(m, [])]
    ev.sort(key=lambda e: str(e.get("data") or ""))
    return d, u, ev


def _sem_historico_com_bv(payload):
    """Para quem não é da gestão, o registro "Com BV" vira só o ESTADO ATUAL (último evento,
    sem id nem autor). Hoje a tela já esconde o histórico desse público, mas a rota o
    devolvia a qualquer logado. Copia: o payload original está no cache compartilhado."""
    linhas = []
    for r in payload.get("rows", []):
        ev = r.get("bvEventos") or []
        ult = [{"comBv": ev[-1].get("comBv"), "data": ev[-1].get("data")}] if ev else []
        linhas.append({**r, "bvEventos": ult})
    return {**payload, "rows": linhas}


@app.get("/api/gestao/rows")
def gestao_rows(entity: str = "egp"):
    """Payload cacheado por identidade OBO + entity + geração (ver _cache_endpoint)."""
    payload = _cache_endpoint(("gestao_rows", entity), lambda: _gestao_rows_uncached(entity))
    return payload if _is_gestao() else _sem_historico_com_bv(payload)


def _gestao_rows_uncached(entity: str = "egp"):
    """Linhas da Gestão. Recorte = frontier indi_deps (escopo Indicium ∪ dependências
    transitivas), p/ bater com os totais que já contam dependências (Resumo/funil, plano).
    EGP = nós do frontier ⋈ sas_egp_pipeline (responsável/etapa); Input = sas_inputs_monitor
    consumidos por EGPs do frontier com vínculo NÃO quebrado (sem sanitizados) + esses
    EGPs consumidores (sas_egp_inputs ⋈ sas_egp_input_link),
    no grão FAMÍLIA quando FAMILIAS_SAFRA está ligada (um card por ingestão, não por carga).
    Datas de sas_gestao_datas; "último status" = texto mais recente de sas_gestao_status.
    Frontier indisponível (erro) -> cai no escopo Indicium base (comportamento antigo)."""
    if entity not in ("egp", "input"):
        raise HTTPException(400, "entity deve ser egp|input")
    def _front_q():
        try:
            _front, _b = _frontier_egps("indi_deps", [])
            # EGPs: ex-dependências retidas também aqui — um convertido (fim_conversao
            # preenchido) que sai do frontier não pode sumir do "EGPs convertidos por mês".
            # Inputs seguem só o frontier vivo (decisão 3 da spec: fila de entrega intacta).
            #
            # A régua é a LISTA CONGELADA, a mesma de `contaNoTotalEgp` na aba EGPs: quem
            # está na foto conta, qualquer que seja a etapa de hoje. Aqui estava o critério
            # "189" (`_ex_deps_contab`: só ex com etapa REAL), que a lista ABSORVEU em
            # 29/09/2026 (§3.1.2) e que sobrou neste ponto — era ele que fazia a
            # Acompanhamento dizer 31 EGPs Desatualizado onde a aba EGPs dizia 33 (medido
            # 07/10/2026). Os dois que faltavam são ex com etapa FANTASMA (`Pré-conversão`)
            # presentes na foto; o critério 189 os descarta e a foto não.
            #
            # `& set(_linha_base())` e não `classe == 'ex_dependencia'`: o
            # `Performance_Saldo_COLORE_…_V5` entrou na foto como `dependencia` e só virou
            # ex depois. A pergunta é "está na lista", nunca "foi classificado ex na lista".
            #
            # Membro da foto que não é frontier vivo NEM ex (o grafo deixou de alcançá-lo)
            # também fica: a aba EGPs o lista (`linha_base - frontier - ex`, em
            # `_egp_readiness_uncached`) e o Kanban tem que listar o mesmo. Medido em
            # 16/10/2026: 44 `Desatualizado` na aba x 43 aqui — o 44º era
            # `Fechamento_Contabil_RPDD_3040`, `dependencia` na foto, fora do frontier.
            if entity == "egp":
                _front = _front | _ex_deps_na_foto(_front, _b) | set(_linha_base())
            return _front
        except HTTPException as e:
            if not _objeto_ausente(e):
                raise
            return set()

    # extras da Gestão / frontier / colunas de pipeline: independentes -> paralelo
    _ge, _front, _, _rev = _parallel(lambda: _gestao_extras(entity), _front_q,
                                     _ensure_input_pipeline_cols,
                                     lambda: _revisoes_regras(entity))
    datas, ultimos, bv = _ge
    _finl = ", ".join(sql_lit(p) for p in _front) if _front else ""

    def _row(rid, nome, area, resp, etapa, egps, status=None, membros=()):
        d, ultimo, eventos = _gestao_anota(rid, membros, datas, ultimos, bv)
        return {"id": rid, "nome": nome, "area": area or None,
                "responsavel": resp or None, "etapa": etapa or None, "status": status or None,
                "inicioMigracao": d.get("inicio") or None,
                "fimConversao": d.get("fim_conversao") or None,
                "fimMigracao": d.get("fim") or None,
                "resumoStatus": ultimo.get("texto") or None,
                "resumoStatusData": ultimo.get("data") or None,
                "egps": egps, "bvEventos": eventos,
                "revisoesRegras": _rev.get(rid, 0)}

    rows = []
    if entity == "egp":
        def _pipe_q():
            try:
                _ensure_pipe_table()
                # pipe-etapa-status: real — daqui sai o RESPONSÁVEL; a etapa exibida vem
                # de `_pipe_exibido()` abaixo.
                return {r["projeto"]: r for r in run_sql(
                    f"SELECT projeto, responsavel, etapa_migracao FROM {T_PIPE}")}
            except HTTPException as e:
                if not _objeto_ausente(e):
                    raise
                return {}
        _egp_where = f"projeto IN ({_finl})" if _finl else "escopo_indi = true"
        pipe, _nd_rows = _parallel(_pipe_q, lambda: run_sql(
            f"SELECT projeto, area FROM {T_ND} WHERE {_egp_where} ORDER BY projeto"))
        # DERIVADO: a coluna Etapa da Gestão é leitura de andamento (e filtro por etapa) —
        # não pode divergir da aba EGPs. Nada aqui conta EGP pela etapa. Deriva sobre as
        # linhas JÁ LIDAS (e não via _pipe_exibido) p/ não gastar um 2º round-trip na
        # mesma tabela; o status não é usado aqui, por isso entra como None.
        # pipe-etapa-status: derivado.
        _exib_gestao = vinculos.mapa_exibido(
            {pj: (r.get("etapa_migracao"), None) for pj, r in pipe.items()},
            _vinculos_por_antecessor())
        for r in _nd_rows:
            pj = r["projeto"]
            p = pipe.get(pj) or {}
            nome = pj.split("__", 1)[-1] if "__" in pj else pj
            # pipe-etapa-status: derivado — fallback no valor cru se o mapa não carregou.
            _et = _exib_gestao.get(pj, (p.get("etapa_migracao"), None))[0]
            rows.append(_row(pj, nome, r.get("area"), p.get("responsavel"), _et, [pj]))
    else:
        cons = {}
        if _finl:
            # universo = inputs consumidos por EGPs do frontier; egps = consumidores do frontier.
            # Vínculo quebrado = o EGP não consome mais: sai da lista do card e, se todos
            # quebraram, o input sai da Gestão — a régua de todas as outras telas
            # (_ch_vinculo_ativo). Sem isso, em prod (08/10/2026), 62 inputs sem nenhum
            # vínculo ativo seguiam na Gestão e 53 cards listavam EGP desvinculado.
            _ensure_link_tables()
            cons_sql = (f"SELECT e.chave_canonica AS ch, e.projeto AS pj FROM {T_EGP} e "
                        f"LEFT JOIN {T_LINK} l ON l.projeto = e.projeto "
                        f"AND l.chave_canonica = e.chave_canonica "
                        f"WHERE e.projeto IN ({_finl}) AND NOT coalesce(l.link_broken, false)")
            in_where = f"chave_canonica IN {_ch_vinculo_ativo(f'e.projeto IN ({_finl})')}"
        else:  # fallback: frontier indisponível -> escopo Indicium base (comportamento antigo)
            cons_sql = (f"SELECT e.chave_canonica AS ch, e.projeto AS pj FROM {T_EGP} e "
                        f"JOIN {T_IN} i ON e.chave_canonica = i.chave_canonica WHERE i.escopo_indi = true")
            in_where = "escopo_indi = true"
        # etapa/status CRUS + categoria/modernizada_auto: o roll-up da família precisa do
        # estado de cada safra (o efetivo sai depois, por py_eff_*, igual para os dois casos).
        _cons_rows, _in_rows = _parallel(lambda: run_sql(cons_sql), lambda: run_sql(
            f"SELECT chave_canonica, artifact, categoria, areas, responsavel, etapa, status, "
            f"modernizada_auto, observacao FROM {T_IN} "
            f"WHERE {in_where} AND NOT ({_sanitizado(lnk=_san_derivada_sql('chave_canonica'))}) "
            f"ORDER BY artifact"))
        for r in _cons_rows:
            cons.setdefault(r["ch"], []).append(r["pj"])
        # grão FAMÍLIA (18/09/2026): a Gestão lia o monitor por conta própria e ficou no grão
        # antigo — 1.608 cards onde há 754 unidades. Mesma régua do resto do app; a anotação
        # já gravada nas safras é herdada na leitura (_gestao_anota), sem migrar nada.
        if FAMILIAS_ON:
            _in_rows = _agrega_familias(_in_rows)
        for r in _in_rows:
            ch = r["chave_canonica"]
            membros = [m for m in (r.get("membros") or []) if m != ch]
            area = (r.get("areas") or "").replace("|", ",").split(",")[0].strip() or None
            egps = sorted({p for k in [ch] + membros for p in cons.get(k, [])})
            _linha = _row(ch, r.get("nome_exibicao") or r.get("artifact") or ch, area,
                          r.get("responsavel"), py_eff_etapa(r), egps,
                          status=py_eff_status(r), membros=membros)
            # "Tbl. Corresp." (= coluna observacao do monitor): nome da tabela modernizada
            _linha["tabelaCorresp"] = (r.get("observacao") or "").strip() or None
            rows.append(_linha)
        rows.extend(_cards_carga_fria(_row))
    return {"rows": rows}


CF_PREFIX = "cf::"   # id do card de carga fria no Kanban de Inputs (output, não linha de T_IN)


def _cards_carga_fria(make_row):
    """Cards de CARGA FRIA no Kanban de Inputs: um por output marcado (`carga_fria`) na aba
    EGPs/Kanban. O id é `cf::<chave_canonica>` — nunca colide com input real, e o front usa
    o prefixo p/ rotear etapa/status/responsável ao PATCH /api/output-pipeline em vez do
    PATCH /api/inputs (o output não é linha de T_IN). Falha aqui não pode derrubar o Kanban."""
    try:
        _ensure_out_pipe_table()
        marc = run_sql(f"SELECT chave_canonica, cf_etapa, cf_status, cf_responsavel, cf_tabela FROM {T_OUT_PIPE} "
                       f"WHERE carga_fria = 'true'")
        if not marc:
            return []
        fin = ", ".join(sql_lit(m["chave_canonica"]) for m in marc)
        info = {r["chave_canonica"]: r for r in run_sql(
            f"SELECT chave_canonica, artifact, areas FROM {T_OUT} WHERE chave_canonica IN ({fin})")}
        prod = {}
        for r in run_sql(f"SELECT chave_canonica, projeto FROM {T_EGP_OUT} WHERE chave_canonica IN ({fin})"):
            prod.setdefault(r["chave_canonica"], []).append(r["projeto"])
    except HTTPException:
        return []
    out = []
    for m in marc:
        ch = m["chave_canonica"]
        o = info.get(ch) or {}
        area = (o.get("areas") or "").replace("|", ",").split(",")[0].strip() or None
        row = make_row(CF_PREFIX + ch, o.get("artifact") or ch, area, m.get("cf_responsavel"),
                       m.get("cf_etapa") or PIPELINE_INPUT[0], sorted(set(prod.get(ch, []))),
                       status=m.get("cf_status") or "A Iniciar")
        row["cargaFria"] = True
        row["tabelaCorresp"] = (m.get("cf_tabela") or "").strip() or None
        out.append(row)
    return out


@app.get("/api/gestao/status")
def gestao_status(entity: str, id: str):
    """Histórico de status/comentários de 1 entidade (desc; índice 0 = último).

    "egp_atualizado" (grão egp_key) foi somado aos dois entities originais para os
    comentários da aba EGPs Atualizados (troca) — mesma tabela T_GST, sem tabela nova;
    esse grão não passa por _chaves_para_leitura (não tem noção de família)."""
    if entity not in ("egp", "input", "egp_atualizado"):
        raise HTTPException(400, "entity deve ser egp|input|egp_atualizado")
    _ensure_gestao_tables()
    # input que é família: o histórico é a UNIÃO (comentário na família + comentários que
    # já existiam nas safras) — senão a caixa apareceria vazia para a linha de família.
    ids = _chaves_para_leitura(id) if entity == "input" else [id]
    _in = ", ".join(sql_lit(i) for i in ids)
    return {"rows": run_sql(
        f"SELECT id, autor, ts AS data, texto FROM {T_GST} "
        f"WHERE entity = {sql_lit(entity)} AND entity_id IN ({_in}) ORDER BY ts DESC")}


class GestaoStatusNovo(BaseModel):
    entity: str
    id: str
    autor: str   # do dropdown (grupo bv_users); criado_por = _ator() (no Databricks, current_user() do OBO)
    texto: str


@app.post("/api/gestao/status")
def gestao_status_add(p: GestaoStatusNovo):
    """Novo status/comentário — vira o "último status" da entidade na tabela da Gestão."""
    if p.entity not in ("egp", "input", "egp_atualizado"):
        raise HTTPException(400, "entity deve ser egp|input|egp_atualizado")
    if not p.texto.strip():
        raise HTTPException(400, "comentário vazio")
    if not p.autor.strip():
        raise HTTPException(400, "autor obrigatório")
    _ensure_gestao_tables()
    sid = uuid.uuid4().hex
    run_sql(
        f"INSERT INTO {T_GST} (id, entity, entity_id, autor, criado_por, ts, texto) VALUES ("
        f"{sql_lit(sid)}, {sql_lit(p.entity)}, {sql_lit(p.id)}, {sql_lit(p.autor)}, "
        f"{_ator()}, cast({AGORA} AS STRING), {sql_lit(p.texto)})",
        want_rows=False)
    _bump_gen()   # último status aparece na Gestão (payload cacheado)
    return {"ok": True, "id": sid}


class GestaoBV(BaseModel):
    entity: str
    id: str
    comBv: bool
    data: str | None = None   # YYYY-MM-DD; ausente = hoje (bv_users). Presente = correção (bv_admins).


def _bv_label(com_bv):
    """Rótulo humano do estado ComBV p/ a trilha de auditoria (aba Histórico)."""
    return "Com BV" if str(com_bv).lower() == "true" else "Conosco"


def _bv_audit(entity_id, de, para):
    """Registra a transição do switch "Com BV" na trilha de auditoria (T_PIPE_AUD → fonte
    'EGPs' na aba Histórico). campo='ComBV', valor_antigo/valor_novo em -|Com BV|Conosco|DELETADO."""
    _ensure_pipe_table()   # audit vive em T_PIPE_AUD (criada aqui); não depender de outro endpoint tê-la criado
    run_sql(
        f"INSERT INTO {T_PIPE_AUD} (id, projeto, funil, campo, valor_antigo, valor_novo, ator, ts) "
        f"VALUES ({sql_lit(uuid.uuid4().hex)}, {sql_lit(entity_id)}, 'gestao', 'ComBV', "
        f"{sql_lit(de)}, {sql_lit(para)}, {_ator()}, cast({AGORA} AS STRING))",
        want_rows=False)


@app.post("/api/gestao/bv")
def gestao_bv_add(p: GestaoBV):
    """Registra 1 toggle do switch "Com BV" (append-only). Sem `data` = hoje (SP), aberto a
    bv_users. Com `data` (retroativa) = correção, restrita a bv_admins."""
    if p.entity not in ("egp", "input"):
        raise HTTPException(400, "entity deve ser egp|input")
    _require_gestao()
    if p.data is not None:
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", p.data):
            raise HTTPException(400, "data deve ser YYYY-MM-DD")
        _require_admin()   # data explícita = reescrita de histórico
    _ensure_gestao_tables()
    bid = uuid.uuid4().hex
    data_lit = (sql_lit(p.data) if p.data is not None else
                f"date_format(from_utc_timestamp({AGORA}, 'America/Sao_Paulo'), 'yyyy-MM-dd')")
    # DE = predecessor CRONOLÓGICO exato do evento inserido ("-" se nenhum): o evento mais
    # recente com data <= data deste (desempate por ts — o novo é sempre o mais novo). Em
    # correção retroativa (data no passado) isso pega o vizinho anterior à data inserida, não o
    # topo do log — a trilha reflete a transição real.
    prev = run_sql(f"SELECT com_bv FROM {T_GBV} WHERE entity = {sql_lit(p.entity)} "
                   f"AND entity_id = {sql_lit(p.id)} AND data <= {data_lit} "
                   f"ORDER BY data DESC, ts DESC LIMIT 1")
    run_sql(
        f"INSERT INTO {T_GBV} (id, entity, entity_id, com_bv, data, autor, ts) VALUES ("
        f"{sql_lit(bid)}, {sql_lit(p.entity)}, {sql_lit(p.id)}, {str(p.comBv).lower()}, "
        f"{data_lit}, {_ator()}, cast({AGORA} AS STRING))",
        want_rows=False)
    _bv_audit(p.id, _bv_label(prev[0]["com_bv"]) if prev else "-", _bv_label(p.comBv))
    _bump_gen()
    return {"ok": True, "id": bid}


@app.delete("/api/gestao/bv")
def gestao_bv_del(id: str):
    """Remove 1 evento do log "Com BV" pelo id. Correção — restrita a bv_admins (hard-delete)."""
    _require_gestao()
    _require_admin()
    _ensure_gestao_tables()
    cur = run_sql(f"SELECT entity_id, com_bv FROM {T_GBV} WHERE id = {sql_lit(id)}")
    run_sql(f"DELETE FROM {T_GBV} WHERE id = {sql_lit(id)}", want_rows=False)
    if cur:
        _bv_audit(cur[0]["entity_id"], _bv_label(cur[0]["com_bv"]), "DELETADO")
    _bump_gen()
    return {"ok": True}


class GestaoRevisao(BaseModel):
    id: str
    delta: int   # +1 / -1 (botões do card); o contador nunca fica abaixo de 0


@app.post("/api/gestao/revisao")
def gestao_revisao(p: GestaoRevisao):
    """Ajusta o contador manual de "revisão de regras de negócio" de 1 EGP (voltou de PRD p/
    validação em DES). >0 pinta o card no Kanban. MERGE por entity+id (como as datas) +
    auditoria em T_PIPE_AUD (campo 'RevisaoRegras'). Aberto a bv_users, como o switch Com BV."""
    if p.delta not in (-1, 1):
        raise HTTPException(400, "delta deve ser +1 ou -1")
    _require_gestao()
    _ensure_gestao_tables()
    cur = run_sql(f"SELECT contador FROM {T_GRV} WHERE entity = 'egp' AND entity_id = {sql_lit(p.id)}")
    old = int(cur[0]["contador"] or 0) if cur else 0
    novo = max(0, old + p.delta)
    if novo == old:
        return {"ok": True, "contador": novo}
    run_sql(
        f"MERGE INTO {T_GRV} t USING (SELECT 'egp' AS entity, {sql_lit(p.id)} AS entity_id) s "
        f"ON t.entity = s.entity AND t.entity_id = s.entity_id "
        f"WHEN MATCHED THEN UPDATE SET contador = {novo}, updated_by = {_ator()}, "
        f"updated_at = cast({AGORA} AS STRING) "
        f"WHEN NOT MATCHED THEN INSERT (entity, entity_id, contador, updated_by, updated_at) "
        f"VALUES (s.entity, s.entity_id, {novo}, {_ator()}, cast({AGORA} AS STRING))",
        want_rows=False)
    run_sql(
        f"INSERT INTO {T_PIPE_AUD} (id, projeto, funil, campo, valor_antigo, valor_novo, ator, ts) "
        f"VALUES ({sql_lit(uuid.uuid4().hex)}, {sql_lit(p.id)}, 'gestao', 'RevisaoRegras', "
        f"{sql_lit(str(old))}, {sql_lit(str(novo))}, {_ator()}, "
        f"cast({AGORA} AS STRING))", want_rows=False)
    _bump_gen()
    return {"ok": True, "contador": novo}


class GestaoData(BaseModel):
    entity: str
    id: str
    campo: str                 # inicio | fim_conversao | fim
    valor: str | None = None   # "YYYY-MM-DD" ou null (limpa)


@app.patch("/api/gestao/datas")
def gestao_set_data(p: GestaoData):
    """Grava uma data da Gestão (MERGE por entity+id em sas_gestao_datas) + auditoria
    em sas_pipeline_audit (funil 'gestao') quando o valor muda.

    entity='egp_atualizado' (pedido cliente BV 2026-09): MESMA tabela/mecanismo dos EGPs/
    Inputs, reaproveitado pela aba EGPs Atualizados — id = egp_key (não versao_id), pra
    sobreviver a novas versões da mesma troca, igual ao funil etapa/status/responsável já
    existente em sas_egp_atualizados_pipeline (grão egp_key). Leitura em egps_atualizados.py."""
    if (p.entity not in ("egp", "input", "egp_atualizado")
            or p.campo not in ("inicio", "fim_conversao", "fim")):
        raise HTTPException(400, "entity/campo inválido")
    if p.valor is not None and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", p.valor):
        raise HTTPException(400, "valor deve ser YYYY-MM-DD ou null")
    _ensure_gestao_tables()
    cur = run_sql(f"SELECT {p.campo} AS v FROM {T_GDT} WHERE entity = {sql_lit(p.entity)} "
                  f"AND entity_id = {sql_lit(p.id)}")
    old = (cur[0].get("v") if cur else None) or None
    v_lit = "NULL" if p.valor is None else sql_lit(p.valor)
    run_sql(
        f"MERGE INTO {T_GDT} t USING (SELECT {sql_lit(p.entity)} AS entity, "
        f"{sql_lit(p.id)} AS entity_id) s "
        f"ON t.entity = s.entity AND t.entity_id = s.entity_id "
        f"WHEN MATCHED THEN UPDATE SET {p.campo} = {v_lit}, updated_by = {_ator()}, "
        f"updated_at = cast({AGORA} AS STRING) "
        f"WHEN NOT MATCHED THEN INSERT (entity, entity_id, {p.campo}, updated_by, updated_at) "
        f"VALUES (s.entity, s.entity_id, {v_lit}, {_ator()}, "
        f"cast({AGORA} AS STRING))", want_rows=False)
    if old != (p.valor or None):
        run_sql(
            f"INSERT INTO {T_PIPE_AUD} (id, projeto, funil, campo, valor_antigo, valor_novo, ator, ts) "
            f"VALUES ({sql_lit(uuid.uuid4().hex)}, {sql_lit(p.id)}, 'gestao', {sql_lit(p.campo)}, "
            f"{sql_lit(old or '')}, {sql_lit(p.valor or '')}, {_ator()}, "
            f"cast({AGORA} AS STRING))", want_rows=False)
    _bump_gen()   # fim_conversao/datas aparecem na aba EGPs e na Gestão (payloads cacheados)
    return {"ok": True}


# ---- Checklist de pré-working dos Inputs (preenchimento manual pelas áreas) ----
# Tabela própria (CREATE IF NOT EXISTS, nunca dropada, FORA do publish — mesmo espírito
# das tabelas de Gestão acima): sas_inputs_preworking, 1 linha por chave_canonica já
# tocada. Edições reaproveitam a tabela de auditoria do Monitoramento (T_AUD/sas_inputs_
# audit, a mesma de patch_input) com campo="preworking.<nome>" — assim a mudança aparece
# de graça na seção "Histórico de alterações" do InputDrawer (filtra por chave_canonica).

PREWORKING_CAMPOS = ("origem_arquivo", "frequencia", "horario", "tipo_carga",
                     "pos_processamento", "dados_sensiveis", "recebido", "data_recebimento")
# "Modernizado pelo BV": marcação manual e OPCIONAL (input que o banco já modernizou fora
# da nossa esteira) — de propósito FORA de PREWORKING_CAMPOS: não conta pro % de completude
# do checklist nem participa do auto-avanço p/ Ingestão UAT (_preworking_completo só itera
# PREWORKING_CAMPOS). Lido/gravado à parte via PREWORKING_CAMPOS_BV. Ver
# /api/inputs-recebidos-serie (coluna "Modernizados (BV)").
PREWORKING_CAMPOS_BV = ("modernizado_bv", "data_modernizado_bv")
PREWORKING_OPCOES = {
    "frequencia": PREWORKING_FREQUENCIA, "tipo_carga": PREWORKING_TIPO_CARGA,
    "pos_processamento": PREWORKING_POS_PROC, "dados_sensiveis": PREWORKING_DADOS_SENSIVEIS,
    "recebido": ("true", "false"),   # checkbox "Recebimento do Arquivo" (front manda string)
    "modernizado_bv": ("true", "false"),   # checkbox "Modernizado pelo BV" (front manda string)
}


def _preworking_completo(vals: dict) -> bool:
    """100% = todos os campos do checklist preenchidos; `recebido` só conta marcado
    (o arquivo precisa ter chegado de fato, não basta ter "tocado" no campo)."""
    for campo in PREWORKING_CAMPOS:
        v = vals.get(campo)
        if campo == "recebido":
            if v != "true":
                return False
        elif not (v or "").strip():
            return False
    return True


@functools.lru_cache(maxsize=1)
def _ensure_preworking_table():
    if dialeto.PG:  # no Postgres o schema vem das migrações (db/migrations), nunca do app
        return True
    run_sql(f"CREATE TABLE IF NOT EXISTS {T_PWK} ("
            f"chave_canonica STRING, origem_arquivo STRING, frequencia STRING, "
            f"horario STRING, tipo_carga STRING, pos_processamento STRING, "
            f"dados_sensiveis STRING, updated_by STRING, updated_at STRING) USING DELTA",
            want_rows=False)
    # self-heal aditivo (mesmo padrão de _ensure_input_pipeline_cols): cobre o caso de
    # a tabela já existir de uma versão anterior do checklist, sem estas colunas.
    try:
        run_sql(f"SELECT recebido, data_recebimento FROM {T_PWK} LIMIT 0")
    except HTTPException:
        run_sql(f"ALTER TABLE {T_PWK} ADD COLUMNS (recebido STRING, data_recebimento STRING)",
                want_rows=False)
    # modernizado_bv/data_modernizado_bv (2026-08): marcação manual opcional, ver
    # PREWORKING_CAMPOS_BV acima — mesmo padrão self-heal aditivo.
    try:
        run_sql(f"SELECT modernizado_bv, data_modernizado_bv FROM {T_PWK} LIMIT 0")
    except HTTPException:
        run_sql(f"ALTER TABLE {T_PWK} ADD COLUMNS (modernizado_bv STRING, data_modernizado_bv STRING)",
                want_rows=False)
    # iniciado_em = 1º toque no checklist (setado só no INSERT do MERGE); concluido_em =
    # 1ª vez que o checklist bateu 100% (setado 1x no PATCH, nunca reescrito depois) —
    # dão a "duração do pré-working" (pedido 2026-08): concluido_em - iniciado_em.
    try:
        run_sql(f"SELECT iniciado_em, concluido_em FROM {T_PWK} LIMIT 0")
    except HTTPException:
        run_sql(f"ALTER TABLE {T_PWK} ADD COLUMNS (iniciado_em STRING, concluido_em STRING)",
                want_rows=False)
    return True


def _pwk_herdadas(rows, familia_de):
    """Linhas SINTÉTICAS de checklist para as chaves de FAMÍLIA, herdando o preenchimento
    que já existe numa safra.

    O checklist é config de INGESTÃO (origem do arquivo, frequência, horário, tipo de
    carga): uma por família, não uma por carga — é o que `_chaves_para_leitura` já diz
    sobre as tabelas de anotação. Com a aba Inputs no grão família, a linha passou a
    procurar o checklist pela chave `familia::...` e os 22 (de 75, em 18/09/2026) que
    tinham sido preenchidos numa safra sumiam da tela, convidando a refazer o trabalho.

    Herança é só de LEITURA e só quando a família NÃO tem linha própria: assim que
    alguém salva na família, ela manda e a herança para. Entre duas safras preenchidas
    vence a de `updated_at` mais recente, com desempate pela chave para o resultado não
    alternar entre requests."""
    ja = {r.get("chave_canonica") for r in rows}
    melhor = {}
    for r in rows:
        fam = familia_de.get(r.get("chave_canonica"))
        if not fam or fam in ja:
            continue
        ordem = (str(r.get("updated_at") or ""), str(r.get("chave_canonica") or ""))
        if fam not in melhor or ordem > melhor[fam][0]:
            melhor[fam] = (ordem, r)
    return [dict(r, chave_canonica=fam, herdado_de=r.get("chave_canonica"))
            for fam, (_ordem, r) in sorted(melhor.items())]


def _pwk_familia_de(chaves):
    """{chave de safra -> chave da família} para as chaves que pertencem a uma família.
    Um SELECT por bloco de 400 chaves (a tabela de checklist é pequena; hoje ~75 linhas)."""
    if not chaves:
        return {}
    corpus = _familias_corpus()
    mapa, membros = corpus["chave"], corpus["membros"]
    out = {}
    for i in range(0, len(chaves), 400):
        inl = ", ".join(sql_lit(c) for c in chaves[i:i + 400])
        for r in run_sql(f"SELECT chave_canonica, categoria, artifact FROM {T_IN} "
                         f"WHERE chave_canonica IN ({inl})"):
            cat = (r.get("categoria") or "").strip()
            art = (r.get("artifact") or "").strip().upper()
            eff = mapa.get((cat, art), art)
            if len(membros.get((cat, eff), ())) > 1:
                out[r["chave_canonica"]] = _chave_familia(cat, eff)
    return out


@app.get("/api/inputs/fragilidade")
def inputs_fragilidade():
    """Quanto da fila está fora dela só porque parte do corpus está fora do escopo.

    Aviso PERMANENTE da aba Inputs (§3.4.16/17): a sanitização derivada mede
    exclusividade contra o escopo ativo, então chaves podem voltar sozinhas quando um
    EGP entra no recorte. `por_egp` é o rollup inverso, ordenado — a lista de quem, se
    entrar, devolve quantas chaves. Read-only e derivado: nada aqui é gravado."""
    return _fragilidade_sanitizacao()


@app.get("/api/inputs/preworking")
def preworking_rows():
    """Checklist de pré-working de todos os inputs já tocados. Tabela pequena — sem
    paginação; o frontend monta um Map client-side (mesmo padrão de /api/gestao/rows),
    reusado tanto pelo badge de completude na tabela de Inputs quanto pela seção dentro
    do InputDrawer."""
    _ensure_preworking_table()
    rows = run_sql(
        f"SELECT chave_canonica, {', '.join(PREWORKING_CAMPOS + PREWORKING_CAMPOS_BV)}, updated_by, "
        f"CAST(updated_at AS STRING) AS updated_at, CAST(iniciado_em AS STRING) AS iniciado_em, "
        f"CAST(concluido_em AS STRING) AS concluido_em FROM {T_PWK}")
    if FAMILIAS_ON:
        # a linha de família herda o checklist da safra enquanto não tiver o seu (_pwk_herdadas)
        rows = rows + _pwk_herdadas(rows, _pwk_familia_de(
            [r["chave_canonica"] for r in rows
             if not str(r.get("chave_canonica") or "").startswith(FAMILIA_PREFIX)]))
    return {"rows": rows}


class PreworkingPatch(BaseModel):
    chave_canonica: str
    origem_arquivo: str | None = None
    frequencia: str | None = None
    horario: str | None = None
    tipo_carga: str | None = None
    pos_processamento: str | None = None
    dados_sensiveis: str | None = None
    recebido: str | None = None            # "true"/"false" (checkbox "Recebimento do Arquivo")
    data_recebimento: str | None = None    # "YYYY-MM-DD"
    modernizado_bv: str | None = None      # "true"/"false" (checkbox "Modernizado pelo BV")
    data_modernizado_bv: str | None = None # "YYYY-MM-DD"


@app.patch("/api/inputs/preworking")
def preworking_patch(p: PreworkingPatch):
    """Grava o checklist (MERGE upsert em sas_inputs_preworking, só os campos enviados e
    mudados) + 1 linha de auditoria por campo em sas_inputs_audit (T_AUD, campo=
    "preworking.<nome>"). Campo enviado como "" grava NULL (limpa), igual à convenção do
    PATCH /api/inputs; campo ausente (None) não é tocado.

    Ao bater 100% (todos os campos preenchidos, incluindo `recebido`=true), avança
    automaticamente o input p/ etapa="Ingestão UAT"/status="A Iniciar" em sas_inputs_monitor
    — só p/ frente: se o input já passou de "Pré-Working" (edição manual anterior), não mexe.
    `modernizado_bv`/`data_modernizado_bv` são gravados aqui mas ficam FORA de
    PREWORKING_CAMPOS: não contam pro % de completude nem pro auto-avanço acima (ver
    PREWORKING_CAMPOS_BV) — marcação opcional, pode nunca ser preenchida.

    `iniciado_em` grava sozinho no 1º toque (linha ainda não existia); `concluido_em`
    grava sozinho na 1ª vez que o checklist bate 100% e nunca é reescrito depois (mesmo
    se o input for reaberto e o checklist "desbatido" e refeito) — os dois juntos dão a
    duração do pré-working exibida no InputDetailPanel (pedido 2026-08).
    """
    global _lineage_gen
    _ensure_preworking_table()
    for campo, opcoes in PREWORKING_OPCOES.items():
        valor = getattr(p, campo)
        if valor not in (None, "") and valor not in opcoes:
            raise HTTPException(400, f"{campo} inválido: {valor}")
    if p.data_recebimento not in (None, "") and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", p.data_recebimento):
        raise HTTPException(400, "data_recebimento deve ser YYYY-MM-DD")
    if p.data_modernizado_bv not in (None, "") and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", p.data_modernizado_bv):
        raise HTTPException(400, "data_modernizado_bv deve ser YYYY-MM-DD")
    cur = run_sql(f"SELECT {', '.join(PREWORKING_CAMPOS + PREWORKING_CAMPOS_BV)}, iniciado_em, concluido_em "
                  f"FROM {T_PWK} WHERE chave_canonica = {sql_lit(p.chave_canonica)}")
    old = cur[0] if cur else {}
    sets, audits = [], []
    for campo in PREWORKING_CAMPOS + PREWORKING_CAMPOS_BV:
        raw = getattr(p, campo)
        if raw is None:
            continue  # não enviado -> não mexe
        novo = raw or None  # "" vira NULL (limpa)
        if _norm(novo) == _norm(old.get(campo)):
            continue  # sem mudança real -> não audita
        sets.append((campo, novo))
        audits.append((campo, _norm(old.get(campo)), _norm(novo)))
    if not sets:
        raise HTTPException(400, "nada para atualizar (valores idênticos)")
    src_cols = ", ".join(f"{sql_lit(v)} AS {c}" for c, v in sets)
    upd = ", ".join(f"{c} = s.{c}" for c, _ in sets)
    ins_cols = ", ".join(c for c, _ in sets)
    ins_vals = ", ".join(f"s.{c}" for c, _ in sets)
    run_sql(
        f"MERGE INTO {T_PWK} t USING (SELECT {sql_lit(p.chave_canonica)} AS chave_canonica, "
        f"{src_cols}) s "
        f"ON t.chave_canonica = s.chave_canonica "
        f"WHEN MATCHED THEN UPDATE SET {upd}, updated_by = {_ator()}, "
        f"updated_at = cast({AGORA} AS STRING) "
        f"WHEN NOT MATCHED THEN INSERT (chave_canonica, {ins_cols}, updated_by, updated_at, iniciado_em) "
        f"VALUES (s.chave_canonica, {ins_vals}, {_ator()}, cast({AGORA} AS STRING), "
        f"cast({AGORA} AS STRING))",
        want_rows=False)
    vals = ",\n".join(
        f"({sql_lit(p.chave_canonica)}, {sql_lit('preworking.' + c)}, {sql_lit(va)}, "
        f"{sql_lit(vn)}, {_ator()}, {AGORA})" for c, va, vn in audits)
    run_sql(f"INSERT INTO {T_AUD} (chave_canonica, campo, valor_antigo, valor_novo, "
            f"updated_by, updated_at) VALUES\n{vals}", want_rows=False)
    result = dict(old)
    result["chave_canonica"] = p.chave_canonica
    for campo, novo in sets:
        result[campo] = novo

    # checklist 100% pela 1ª vez -> grava concluido_em (setado só 1x; edições posteriores,
    # mesmo que reabram e refechem o checklist, não reescrevem a data de conclusão original).
    # Exige iniciado_em já presente: linhas criadas ANTES desta feature não têm ponto de
    # partida conhecido, então gravar concluido_em nelas daria uma duração fabricada (a
    # data do próximo toque, não a data real de conclusão) — melhor deixar as 2 em branco.
    if _preworking_completo(result) and not old.get("concluido_em") and old.get("iniciado_em"):
        run_sql(f"UPDATE {T_PWK} SET concluido_em = cast({AGORA} AS STRING) "
                f"WHERE chave_canonica = {sql_lit(p.chave_canonica)}", want_rows=False)

    # checklist 100% -> libera p/ Ingestão UAT (só avança; nunca rebaixa etapa já mais adiantada)
    auto_avancado = False
    if _preworking_completo(result):
        # O MERGE no T_PWK acima é gravado na chave da FAMÍLIA de propósito (checklist é
        # config de ingestão, uma por família — ADR 0002). Já etapa/status é estado
        # CONTADO e mora nas SAFRAS: `familia::…` não casa linha nenhuma em T_IN, então
        # ler/escrever com ela aqui fazia o checklist completar sem avançar input algum,
        # e ainda devolvia `auto_avancado: false` sem erro. Fan-out, como `_patch_familia`.
        alvos = _chaves_estado(p.chave_canonica)
        cur_in = run_sql(
            f"SELECT chave_canonica, etapa, status FROM {T_IN} WHERE chave_canonica IN "
            f"({', '.join(sql_lit(k) for k in alvos)})") if alvos else []
        lim_pwk = PIPELINE_INPUT.index("Pré-Working")
        # só avança quem ainda não passou de Pré-Working; numa família mista, as safras
        # já adiantadas ficam como estão (mesma regra de antes, agora linha a linha).
        avancar = []
        for linha in cur_in:
            et = linha.get("etapa")
            idx = PIPELINE_INPUT.index(et) if et in PIPELINE_INPUT else -1
            if idx <= lim_pwk:
                avancar.append((linha["chave_canonica"], et, linha.get("status")))
        if avancar:
            run_sql(
                f"UPDATE {T_IN} SET etapa = {sql_lit('Ingestão UAT')}, status = {sql_lit('A Iniciar')}, "
                f"updated_at = {AGORA}, updated_by = {_ator()} "
                f"WHERE chave_canonica IN ({', '.join(sql_lit(k) for k, _, _ in avancar)})",
                want_rows=False)
            run_sql(
                f"INSERT INTO {T_AUD} (chave_canonica, campo, valor_antigo, valor_novo, "
                f"updated_by, updated_at) VALUES " + ", ".join(
                    f"({sql_lit(k)}, 'etapa', {sql_lit(et or '')}, 'Ingestão UAT', "
                    f"{_ator()}, {AGORA}), "
                    f"({sql_lit(k)}, 'status', {sql_lit(st or '')}, 'A Iniciar', "
                    f"{_ator()}, {AGORA})" for k, et, st in avancar),
                want_rows=False)
            auto_avancado = True
            _lineage_gen += 1

    # refresh leve de iniciado_em/concluido_em (cobre o 1º insert e a conclusão recém-
    # gravada acima, nenhum dos dois estava disponível em `old` antes desta request).
    ts = run_sql(f"SELECT CAST(iniciado_em AS STRING) AS iniciado_em, "
                 f"CAST(concluido_em AS STRING) AS concluido_em FROM {T_PWK} "
                 f"WHERE chave_canonica = {sql_lit(p.chave_canonica)}")
    if ts:
        result["iniciado_em"] = ts[0]["iniciado_em"]
        result["concluido_em"] = ts[0]["concluido_em"]
    result["auto_avancado"] = auto_avancado
    return result


# ---- aba Prioridades (lista curada de EGPs priorizados pela Indicium) ----
@functools.lru_cache(maxsize=1)
def _ensure_prio_table():
    if dialeto.PG:  # no Postgres o schema vem das migrações (db/migrations), nunca do app
        return True
    run_sql(
        f"CREATE TABLE IF NOT EXISTS {T_PRIO} ("
        f"id STRING, ordem INT, projeto STRING, vinculado BOOLEAN, "
        f"status STRING, responsavel STRING, justificativa STRING, "
        f"created_by STRING, created_at TIMESTAMP, updated_by STRING, updated_at TIMESTAMP"
        f") USING DELTA", want_rows=False)
    return True


def _prio_out(r):
    return {
        "id": r["id"], "ordem": int(r.get("ordem") or 0), "projeto": r.get("projeto"),
        "vinculado": str(r.get("vinculado")).lower() == "true",
        "status": r.get("status"), "responsavel": r.get("responsavel"),
        "justificativa": r.get("justificativa"),
        "created_by": r.get("created_by"), "created_at": r.get("created_at"),
        "updated_by": r.get("updated_by"), "updated_at": r.get("updated_at"),
        "area": r.get("area"), "onda": r.get("onda"),
    }


_PRIO_SELECT = (
    "SELECT p.id, p.ordem, p.projeto, p.vinculado, p.status, p.responsavel, p.justificativa, "
    "p.created_by, CAST(p.created_at AS STRING) AS created_at, "
    "p.updated_by, CAST(p.updated_at AS STRING) AS updated_at, nd.area AS area, nd.onda AS onda "
    f"FROM {T_PRIO} p LEFT JOIN {T_ND} nd ON nd.projeto = p.projeto AND p.vinculado = true")


class PrioIn(BaseModel):
    projeto: str
    vinculado: bool = False
    status: str = "A fazer"
    responsavel: str | None = None
    justificativa: str | None = None


class PrioPatch(BaseModel):
    projeto: str | None = None
    vinculado: bool | None = None
    status: str | None = None
    responsavel: str | None = None
    justificativa: str | None = None


class PrioMove(BaseModel):
    dir: str


@app.get("/api/prioridades")
def prioridades_list():
    _ensure_prio_table()
    rows = run_sql(_PRIO_SELECT + " ORDER BY p.ordem ASC, p.created_at ASC")
    return {"rows": [_prio_out(r) for r in rows]}


@app.post("/api/prioridades")
def prioridades_create(p: PrioIn):
    _ensure_prio_table()
    projeto = (p.projeto or "").strip()
    if not projeto:
        raise HTTPException(400, "projeto vazio")
    if not valid_status(p.status):
        raise HTTPException(400, f"status inválido: {p.status}")
    m = run_sql(f"SELECT COALESCE(MAX(ordem), 0) AS m FROM {T_PRIO}")
    ordem = next_ordem(int(m[0]["m"]) if m and m[0].get("m") is not None else 0)
    pid = uuid.uuid4().hex
    run_sql(
        f"INSERT INTO {T_PRIO} (id, ordem, projeto, vinculado, status, responsavel, justificativa, "
        f"created_by, created_at, updated_by, updated_at) VALUES ("
        f"{sql_lit(pid)}, {ordem}, {sql_lit(projeto)}, {'true' if p.vinculado else 'false'}, "
        f"{sql_lit(p.status)}, {sql_lit(p.responsavel)}, {sql_lit(p.justificativa)}, "
        f"{_ator()}, {AGORA}, {_ator()}, {AGORA})", want_rows=False)
    rows = run_sql(_PRIO_SELECT + f" WHERE p.id = {sql_lit(pid)}")
    if not rows:
        raise HTTPException(502, "falha ao criar a prioridade")
    return _prio_out(rows[0])


@app.patch("/api/prioridades/{pid}")
def prioridades_patch(pid: str, p: PrioPatch):
    _ensure_prio_table()
    cur = run_sql(f"SELECT id FROM {T_PRIO} WHERE id = {sql_lit(pid)}")
    if not cur:
        raise HTTPException(404, "prioridade não encontrada")
    sets = []
    if p.projeto is not None:
        pj = p.projeto.strip()
        if not pj:
            raise HTTPException(400, "projeto vazio")
        sets.append(f"projeto = {sql_lit(pj)}")
    if p.vinculado is not None:
        sets.append(f"vinculado = {'true' if p.vinculado else 'false'}")
    if p.status is not None:
        if not valid_status(p.status):
            raise HTTPException(400, f"status inválido: {p.status}")
        sets.append(f"status = {sql_lit(p.status)}")
    if p.responsavel is not None:
        sets.append(f"responsavel = {sql_lit(p.responsavel)}")
    if p.justificativa is not None:
        sets.append(f"justificativa = {sql_lit(p.justificativa)}")
    if not sets:
        raise HTTPException(400, "nada para atualizar")
    sets.append(f"updated_by = {_ator()}")
    sets.append(f"updated_at = {AGORA}")
    run_sql(f"UPDATE {T_PRIO} SET {', '.join(sets)} WHERE id = {sql_lit(pid)}", want_rows=False)
    rows = run_sql(_PRIO_SELECT + f" WHERE p.id = {sql_lit(pid)}")
    return _prio_out(rows[0])


@app.post("/api/prioridades/{pid}/move")
def prioridades_move(pid: str, body: PrioMove):
    _ensure_prio_table()
    if body.dir not in ("up", "down"):
        raise HTTPException(400, "dir deve ser 'up' ou 'down'")
    raw = run_sql(f"SELECT id, ordem FROM {T_PRIO}")
    rows = [{"id": r["id"], "ordem": int(r["ordem"])} for r in raw]
    pair = neighbor_swap(rows, pid, body.dir)
    if pair is None:
        return {"ok": True}  # já é a ponta ou id ausente -> no-op
    cur, nb = pair
    run_sql(f"UPDATE {T_PRIO} SET ordem = {nb['ordem']} WHERE id = {sql_lit(cur['id'])}", want_rows=False)
    run_sql(f"UPDATE {T_PRIO} SET ordem = {cur['ordem']} WHERE id = {sql_lit(nb['id'])}", want_rows=False)
    return {"ok": True}


@app.delete("/api/prioridades/{pid}")
def prioridades_delete(pid: str):
    _ensure_prio_table()
    cur = run_sql(f"SELECT id FROM {T_PRIO} WHERE id = {sql_lit(pid)}")
    if not cur:
        raise HTTPException(404, "prioridade não encontrada")
    run_sql(f"DELETE FROM {T_PRIO} WHERE id = {sql_lit(pid)}", want_rows=False)
    return {"ok": True}


# predicado "input resolvido" idêntico ao das demais abas (_modern), renderizado sobre
# os aliases do módulo: i = sas_inputs_monitor, ma = agregado de modernizada_auto.
egps_atualizados.register(
    app, run_sql, FQ,
    modern_expr=_modern("i.etapa", "ma.auto", "i.status"),
    http_exc=HTTPException,
    enrich_contexto=_enrich_egp_contexto,
    familia_por_chave=_familia_por_chave,
    on_write=_bump_gen,
    ator=_ator, agora=AGORA)


# ---- consulta: o app grava o que calcula (ADR 0004) ----------------------------------
# O agente de consulta (Genie, aba Perguntas) não passa pelo app: lê tabelas. Para ele
# responder "por que a tela A mostra N e a B mostra M" apontando os itens, o resultado das
# MESMAS funções das telas é gravado aqui — uma linha por EGP da aba EGPs e uma por unidade
# de input do Recorte, com uma coluna `conta_*` por tela. Nenhuma régua nova: consulta.py
# só transcreve; a paridade (soma das colunas = número da tela) é conferida a cada gravação
# e, se divergir, NADA é gravado. Retrato atual + um por dia (`*_dia`, o último do dia).
T_CONS_EGP = f"{FQ}.sas_consulta_egp"
T_CONS_EGP_DIA = f"{FQ}.sas_consulta_egp_dia"
T_CONS_IN = f"{FQ}.sas_consulta_input"
T_CONS_IN_DIA = f"{FQ}.sas_consulta_input_dia"
# Desligada por padrão (testes, scripts, app local); app.yaml/app.dev.yaml ligam.
CONSULTA_ON = os.environ.get("CONSULTA_SNAPSHOT", "").strip().lower() in ("1", "true", "yes")
CONSULTA_INTERVALO_S = 15 * 60   # no máximo 1 recálculo a cada 15 min
CONSULTA_ATIVIDADE_S = 10 * 60   # "app em uso" = request em /api/* nos últimos 10 min
CONSULTA_HORA_DIARIA = 6         # rodada diária (horário de Brasília) — pega publish feito fora
# Tabelas cuja escrita muda o que as telas contam. `last_altered` delas é a sonda de
# mudança: 1 statement detecta edição pelo app E carga feita fora dele (publish).
_CONSULTA_FONTES = (T_IN, T_ND, T_ED, T_EGP, T_PIPE, T_ESC, T_LINK, T_CHOICE, T_CFG,
                    T_PRIO_SNAP, T_DEPM, T_OUT, T_EGP_OUT)
_consulta_estado = {"assinatura": None, "dia_gravado": None, "ultima_sonda": float("-inf"),
                    "ultimo_ok": None, "ultimo_erro": None, "divergencias": [],
                    "n_egp": None, "n_input": None, "duracao_s": None}
_consulta_lock = threading.Lock()


def _consulta_lit(v, tipo):
    if v is None:
        return "NULL"
    if tipo == "BOOLEAN":
        return "TRUE" if v else "FALSE"
    if tipo == "INT":
        return str(int(v))
    if tipo == "TIMESTAMP":
        return f"TIMESTAMP {sql_lit(v)}"
    return sql_lit(v)


def _consulta_calcula():
    """(linhas_egp, linhas_input, divergencias) a partir das funções das telas."""
    agora = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    frontier, _b = _frontier_egps("indi_deps", [])
    readiness = egp_readiness("indi_deps")["rows"]
    # pipe-etapa-status: real — vira as colunas etapa_gravada/status_gravado, que existem
    # justamente para mostrar o estado GRAVADO ao lado do exibido (que vem da readiness).
    pipe_real = {r["projeto"]: (r.get("etapa_migracao"), r.get("status_migracao"))
                 for r in run_sql(f"SELECT projeto, etapa_migracao, status_migracao FROM {T_PIPE}")}
    mes = {}
    snap = _read_prio_snapshot()
    if snap:
        for m in _poda_fora_da_linha_base(snap).get("meses") or []:
            for e in m.get("egps") or []:
                mes[e.get("projeto")] = m.get("mes")
    g_egp = _gestao_rows_uncached("egp")["rows"]
    g_in = _gestao_rows_uncached("input")["rows"]
    egp_rows = consulta.linhas_egp(
        readiness, _linha_base(), pipe_real, frontier, _extras_no_recorte(),
        {r["id"] for r in g_egp}, mes, PIPELINE_PROJETO["migracao"],
        set(PHANTOM_ETAPAS_MIGRACAO), agora)

    ds_deps = _dataset_escopo("indi_deps", [])
    ds_indi = {r["chave_canonica"]: r for r in _universo_contagem(_dataset_escopo("indi", []))}
    cons = {}
    if frontier:
        fin = ", ".join(sql_lit(p) for p in frontier)
        for r in run_sql(f"SELECT e.chave_canonica AS ch, e.projeto AS pj FROM {T_EGP} e "
                         f"LEFT JOIN {T_LINK} l ON l.projeto = e.projeto "
                         f"AND l.chave_canonica = e.chave_canonica "
                         f"WHERE e.projeto IN ({fin}) AND NOT coalesce(l.link_broken, false)"):
            cons.setdefault(r["ch"], set()).add(r["pj"])
    egps_por_chave = {}
    for r in ds_deps:
        k = r["chave_canonica"]
        egps_por_chave[k] = set().union(*(cons.get(m, set()) for m in ([k] + list(r.get("membros") or []))))
    in_rows = consulta.linhas_input(
        ds_deps, set(ds_indi), ds_indi, {r["id"] for r in g_in}, egps_por_chave,
        py_eff_etapa, py_eff_status, py_modern, py_aingerir, _universo_contagem, agora)

    div = consulta.confere(egp_rows, in_rows, landing(), funis(), len(g_egp), len(g_in))
    return egp_rows, in_rows, div


def _consulta_ensure():
    for t in (T_CONS_EGP, T_CONS_IN):
        cols = consulta.COLUNAS_EGP if t == T_CONS_EGP else consulta.COLUNAS_INPUT
        ddl = ", ".join(f"{c} {tp}" for c, tp in cols)
        _run_sp(f"CREATE TABLE IF NOT EXISTS {t} ({ddl}) USING DELTA")
        _run_sp(f"CREATE TABLE IF NOT EXISTS {t}_dia (dia DATE, {ddl}) USING DELTA")


def _consulta_grava(egp_rows, in_rows):
    """INSERT OVERWRITE do retrato atual (atômico no Delta) + troca do retrato do dia."""
    _consulta_ensure()
    hoje = datetime.datetime.now(datetime.timezone.utc).date().isoformat()
    for tabela, cols, linhas in ((T_CONS_EGP, consulta.COLUNAS_EGP, egp_rows),
                                 (T_CONS_IN, consulta.COLUNAS_INPUT, in_rows)):
        if not linhas:
            raise RuntimeError(f"consulta: 0 linhas para {tabela} — não sobrescrevo com vazio")
        nomes = ", ".join(c for c, _ in cols)
        valores = ",\n".join("(" + ", ".join(_consulta_lit(r.get(c), tp) for c, tp in cols) + ")"
                             for r in linhas)
        _run_sp(f"INSERT OVERWRITE {tabela} ({nomes}) VALUES {valores}")
        # REPLACE WHERE troca o retrato do dia num statement só (atômico no Delta). Eram
        # DELETE + INSERT: falha entre os dois deixava o dia sem retrato até a próxima passada.
        _run_sp(f"INSERT INTO {tabela}_dia REPLACE WHERE dia = DATE {sql_lit(hoje)} "
                f"SELECT DATE {sql_lit(hoje)} AS dia, {nomes} FROM {tabela}")


def _consulta_assinatura():
    """max(last_altered) das tabelas-fonte: muda com qualquer escrita, de dentro ou de fora."""
    nomes = ", ".join(sql_lit(t.rsplit(".", 1)[-1]) for t in _CONSULTA_FONTES)
    r = run_sql(f"SELECT CAST(max(last_altered) AS STRING) AS m FROM {CATALOG}.information_schema.tables "
                f"WHERE table_schema = {sql_lit(SCHEMA)} AND table_name IN ({nomes})")
    return (r[0].get("m") if r else None)


def _consulta_atualiza(forcar=False):
    """Uma passada: sonda, e se mudou (ou `forcar`), calcula, confere e grava. Devolve o
    estado. Roda como service principal (ver _rotina_sistema) — só a rotina chama."""
    tok = _rotina_sistema.set(True)
    try:
        with _consulta_lock:
            _consulta_estado["ultima_sonda"] = time.monotonic()
            assin = _consulta_assinatura()
            if not forcar and assin == _consulta_estado["assinatura"]:
                return _consulta_estado
            t0 = time.monotonic()
            egp_rows, in_rows, div = _consulta_calcula()
            _consulta_estado["divergencias"] = [list(d) for d in div]
            if div:
                # falha barulhenta: tabela com número que a tela não mostra é pior que velha
                _consulta_estado["ultimo_erro"] = f"paridade: {len(div)} divergência(s)"
                print(f"[consulta] NÃO gravado — paridade divergiu: {div}", flush=True)
                return _consulta_estado
            _consulta_grava(egp_rows, in_rows)
            _consulta_estado.update(
                assinatura=assin, ultimo_ok=datetime.datetime.now(datetime.timezone.utc).isoformat(),
                ultimo_erro=None, n_egp=len(egp_rows), n_input=len(in_rows),
                duracao_s=round(time.monotonic() - t0, 1),
                dia_gravado=_hoje_brt())
            print(f"[consulta] gravado: {len(egp_rows)} EGPs, {len(in_rows)} inputs "
                  f"em {_consulta_estado['duracao_s']}s", flush=True)
            return _consulta_estado
    finally:
        _rotina_sistema.reset(tok)


def _hoje_brt():
    return (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=3)).date().isoformat()


def _consulta_decide(agora, hora_brt, hoje, dia_gravado, ultima_sonda, ultimo_request):
    """(rodar, forcar). O intervalo mínimo vale para TODA tentativa — inclusive a diária e a
    que falhou: sem isso, uma passada diária que não grava (permissão, paridade) ficaria
    "pendente" e seria refeita a cada minuto, recalculando ~40 s e mantendo o warehouse
    acordado o dia inteiro. `ultima_sonda` marca o INÍCIO de cada tentativa, deu certo ou não."""
    if agora - ultima_sonda < CONSULTA_INTERVALO_S:
        return False, False
    diaria = hora_brt >= CONSULTA_HORA_DIARIA and dia_gravado != hoje
    em_uso = agora - ultimo_request < CONSULTA_ATIVIDADE_S
    return (diaria or em_uso), diaria


def _consulta_rotina():
    """Laço da thread (só com CONSULTA_SNAPSHOT ligada, só no servidor de verdade). Sonda
    apenas com o app em uso — o warehouse desliga sozinho em 10 min e uma sonda periódica
    o manteria acordado — e força uma passada por dia a partir das 6h (Brasília)."""
    while True:
        time.sleep(60)
        try:
            hora_brt = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=3)).hour
            rodar, forcar = _consulta_decide(
                time.monotonic(), hora_brt, _hoje_brt(), _consulta_estado["dia_gravado"],
                _consulta_estado["ultima_sonda"], _ultimo_request_mono)
            if rodar:
                _consulta_atualiza(forcar=forcar)
        except Exception as e:   # a rotina nunca derruba o app; o erro fica no estado e no log
            _consulta_estado["ultimo_erro"] = repr(e)[:500]
            print(f"[consulta] erro na rotina: {e!r}", flush=True)


@app.get("/api/consulta/status")
def consulta_status():
    """Estado da rotina de consulta (só gestão): última gravação, divergências de paridade."""
    _require_gestao()
    return {"ligada": CONSULTA_ON, **{k: v for k, v in _consulta_estado.items() if k != "ultima_sonda"}}


# ---- estáticos (SPA) — montados por último para não capturar /api ----
class _SPAStaticFiles(StaticFiles):
    """Serve os arquivos do bundle; para caminhos que NÃO são arquivos reais
    (rotas client-side do SPA, ex. /prontidao), devolve index.html para que
    deep links e refresh funcionem. As rotas /api/* são declaradas antes do
    mount (têm precedência) — uma /api/* inexistente segue como 404, não HTML.

    Montado com html=False de propósito: esta subclasse já cobre o fallback
    para index.html em qualquer 404 (inclusive a raiz "."), e html=True
    introduziria um 307-redirect para paths que casem com diretório."""

    async def get_response(self, path, scope):
        # Cache-Control: `assets/*` têm hash do Vite no nome (conteúdo novo = nome novo),
        # então são imutáveis; o index.html (e o fallback de rota do SPA) revalida sempre,
        # senão um deploy novo ficaria preso no bundle antigo.
        try:
            resp = await super().get_response(path, scope)
        except StarletteHTTPException as exc:
            is_api = path == "api" or path.startswith("api/")
            if exc.status_code == 404 and not is_api:
                resp = await super().get_response("index.html", scope)
                resp.headers["Cache-Control"] = "no-cache"
                return resp
            raise
        if path.startswith("assets/"):
            resp.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        elif path in ("", ".", "index.html"):
            resp.headers["Cache-Control"] = "no-cache"
        return resp


if os.path.isdir(STATIC_DIR):
    app.mount("/", _SPAStaticFiles(directory=STATIC_DIR, html=False), name="static")
else:
    @app.get("/")
    def _nostatic():
        return JSONResponse({"msg": "frontend não compilado — rode `npm run build` em frontend/"}, status_code=200)


if __name__ == "__main__":
    import uvicorn
    if CONSULTA_ON:
        # só aqui, no servidor de verdade: importar o módulo (testes, scripts) não sobe a rotina
        threading.Thread(target=_consulta_rotina, name="consulta", daemon=True).start()
    uvicorn.run(app, host="0.0.0.0", port=PORT)
