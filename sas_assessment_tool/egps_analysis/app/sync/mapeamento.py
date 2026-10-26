# -*- coding: utf-8 -*-
"""De-para das tabelas Delta para o schema novo — Fase 1, cópia FIEL (ADR 0005).

Entrada: linhas como o Databricks devolve (texto ou None). Saída: tuplas na ordem de
COLUNAS[destino]. Valor fora do previsto LEVANTA ValorInesperado: a sincronização para e
alarma em vez de gravar um palpite. Correções de dado (etapa_migracao, e-mails .tech) são
da Fase 2 — aqui nada muda de sentido, só de tipo.

Sentinela: estado de input que ninguém editou (updated_by vazio, linha criada pelo
publish com os valores padrão) vai com atualizado_por = 'publish'; a view compat devolve
NULL nesse caso, como o Databricks.
"""
import datetime
import decimal
import uuid

SENTINELA_PUBLISH = "publish"

COLUNAS = {
    "corpus.egp": (
        "projeto", "area", "onda", "ciclo_id", "casca", "n_inputs", "n_outputs", "loc",
        "code_tasks_count", "n_outputs_avaliados", "n_outputs_consumidos_por_outro_egp",
        "pct_outputs_consumidos_por_outro_egp", "n_egps_consumidores", "n_exports_arquivos",
        "flag_output_100pct_egp", "flag_algum_output_egp", "flag_sem_export_arquivo",
        "flag_output_unico", "flag_hub_multiplos_consumidores", "orfao", "publicado_em"),
    "corpus.input": (
        "chave", "categoria", "artefato", "origem", "source_types", "areas", "qtd_projetos",
        "disponivel_auto", "paths_fisicos", "orfao", "publicado_em"),
    "trabalho.estado_input": (
        "chave", "etapa", "status", "responsavel", "observacao", "atualizado_em", "atualizado_por"),
    "corpus.egp_input": ("projeto", "input_chave", "artefato", "source_types"),
    "trabalho.escopo_item": (
        "id", "egp_dor1", "area", "status_extracao", "projeto", "origem", "ativo",
        "criado_em", "criado_por"),
}

# Colunas que a sincronização LÊ de cada tabela Delta (ordem livre; vão por nome).
ORIGEM = {
    "sas_lineage_nodes": (
        "projeto", "area", "onda", "n_inputs", "n_outputs", "ciclo_id", "loc", "code_tasks_count",
        "n_outputs_avaliados", "n_outputs_consumidos_por_outro_egp",
        "pct_outputs_consumidos_por_outro_egp", "n_egps_consumidores", "n_exports_arquivos",
        "flag_output_100pct_egp", "flag_algum_output_egp", "flag_sem_export_arquivo",
        "flag_output_unico", "flag_hub_multiplos_consumidores"),
    "sas_inputs_monitor": (
        "chave_canonica", "artifact", "categoria", "source_types", "qtd_projetos", "areas",
        "modernizada_auto", "responsavel", "observacao", "updated_at", "updated_by", "orfao",
        "refreshed_at", "origem", "paths_fisicos", "etapa", "status"),
    "sas_egp_inputs": ("projeto", "chave_canonica", "artifact", "categoria", "source_types"),
    "sas_escopo": (
        "id", "egp_dor1", "area", "status_extracao", "projeto", "origem", "created_by",
        "created_at", "ativo"),
    "sas_analistas": ("email", "nome", "ativo", "organograma", "papel"),
}


class ValorInesperado(ValueError):
    pass


def _bool(v):
    if v is None:
        return None
    if v in ("true", "false"):
        return v == "true"
    raise ValorInesperado(f"booleano inesperado: {v!r}")


def _int(v):
    return None if v in (None, "") else int(v)


def _num(v):
    return None if v in (None, "") else decimal.Decimal(v)


def _txt(v):
    """Texto vazio vira NULL — as telas já tratam os dois igual (ver consulta._sem_vazio)."""
    return None if v is None or not str(v).strip() else v


def _lista(v):
    """'a | b | c' -> ['a', 'b', 'c']; vazio -> []."""
    if v is None or not str(v).strip():
        return []
    return [p.strip() for p in str(v).split("|") if p.strip()]


def _instante(v):
    """Texto de data/hora (TIMESTAMP do Databricks ou STRING gravada pelo app) -> UTC.
    Sem fuso = UTC (a sessão do warehouse grava em UTC)."""
    if v is None or not str(v).strip():
        return None
    s = str(v).strip().replace("Z", "+00:00")
    d = datetime.datetime.fromisoformat(s)
    if d.tzinfo is None:
        d = d.replace(tzinfo=datetime.timezone.utc)
    return d


def egp(r, orfao=False):
    return (r["projeto"], r.get("area"), r.get("onda"), _int(r.get("ciclo_id")) or 0, False,
            _int(r.get("n_inputs")), _int(r.get("n_outputs")), _int(r.get("loc")),
            _int(r.get("code_tasks_count")), _int(r.get("n_outputs_avaliados")),
            _int(r.get("n_outputs_consumidos_por_outro_egp")),
            _num(r.get("pct_outputs_consumidos_por_outro_egp")),
            _int(r.get("n_egps_consumidores")), _int(r.get("n_exports_arquivos")),
            _bool(r.get("flag_output_100pct_egp")), _bool(r.get("flag_algum_output_egp")),
            _bool(r.get("flag_sem_export_arquivo")), _bool(r.get("flag_output_unico")),
            _bool(r.get("flag_hub_multiplos_consumidores")), orfao,
            datetime.datetime.now(datetime.timezone.utc))


def _disponivel(v):
    if v == "Disponível":
        return True
    if v == "A ingerir":
        return False
    if v is None:
        return None
    raise ValorInesperado(f"modernizada_auto inesperado: {v!r}")


def input_(r):
    return (r["chave_canonica"], r["categoria"], r["artifact"], _txt(r.get("origem")),
            _lista(r.get("source_types")), _lista(r.get("areas")), _int(r.get("qtd_projetos")),
            _disponivel(r.get("modernizada_auto")), _lista(r.get("paths_fisicos")),
            bool(_bool(r.get("orfao"))),
            _instante(r.get("refreshed_at")) or datetime.datetime.now(datetime.timezone.utc))


def estado_input(r):
    """None quando não há estado nenhum (a linha não é criada)."""
    etapa, status = _txt(r.get("etapa")), _txt(r.get("status"))
    resp, obs = _txt(r.get("responsavel")), _txt(r.get("observacao"))
    if not any((etapa, status, resp, obs)):
        return None
    por = _txt(r.get("updated_by"))
    em = _instante(r.get("updated_at")) if por else None
    return (r["chave_canonica"], etapa, status, resp.lower() if resp else None, obs,
            em or _instante(r.get("refreshed_at")) or datetime.datetime.now(datetime.timezone.utc),
            por or SENTINELA_PUBLISH)


def egp_input(r):
    return (r["projeto"], r["chave_canonica"], r["artifact"], _lista(r.get("source_types")))


def escopo_item(r):
    criado = r.get("created_at")
    return (str(uuid.UUID(hex=r["id"])), r["egp_dor1"], _txt(r.get("area")), r["status_extracao"],
            _txt(r.get("projeto")), r["origem"], bool(_bool(r.get("ativo"))),
            None if criado == "seed" else _instante(criado), _txt(r.get("created_by")) or "seed")


def ancora_input_ausente(chave, categoria, artefato):
    """Input citado por um par mas ausente do monitor: entra como âncora órfã (as FKs do
    estado humano precisam do pai; o drift atual vira contagem no relatório)."""
    return (chave, categoria, artefato, None, [], [], None, None, [], True,
            datetime.datetime.now(datetime.timezone.utc))
