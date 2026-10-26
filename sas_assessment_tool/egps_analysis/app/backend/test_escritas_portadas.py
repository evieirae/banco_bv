# -*- coding: utf-8 -*-
"""Guarda do porte das escritas (Fase 2, ADR 0005), sem banco: rota de escrita nova precisa
de teste no Postgres (test_escritas_pg.py), e SQL de escrita não volta ao dialeto do
Databricks — no Postgres ele quebraria só na hora de gravar."""
import os
import pathlib
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from backend import main as m  # noqa: E402

AQUI = pathlib.Path(__file__).resolve().parent

# Rotas de escrita sem teste no Postgres, com o motivo. Rota nova entra no teste ou aqui.
FORA_DO_TESTE = {
    ("POST", "/api/priorizacao/preview"): "não grava: só calcula a prévia",
    ("POST", "/api/prioridades"): "sas_egp_prioridades não migra (spec): rotas sem tela",
    ("PATCH", "/api/prioridades/{}"): "idem",
    ("POST", "/api/prioridades/{}/move"): "idem",
    ("DELETE", "/api/prioridades/{}"): "idem",
}


def _normaliza(caminho):
    return re.sub(r"\{[^}]*\}", "{}", caminho)


def _rotas_de_escrita():
    rotas = set()
    for r in m.app.routes:
        caminho = getattr(r, "path", "")
        for metodo in getattr(r, "methods", set()) & {"POST", "PATCH", "PUT", "DELETE"}:
            if caminho.startswith("/api/"):
                rotas.add((metodo, _normaliza(caminho)))
    return rotas


def test_toda_rota_de_escrita_tem_teste_no_postgres_ou_motivo():
    fonte = (AQUI / "test_escritas_pg.py").read_text(encoding="utf-8")
    testadas = {(metodo, _normaliza(caminho)) for metodo, caminho in
                re.findall(r'chama\(app, "(POST|PATCH|PUT|DELETE)", f?"(/api/[^"?]+)', fonte)}
    rotas = _rotas_de_escrita()
    assert len(rotas) >= 25                      # o filtro ainda acha as rotas (sanidade do teste)
    assert not set(FORA_DO_TESTE) - rotas, "motivo para rota que não existe mais"
    sem_teste = rotas - testadas - set(FORA_DO_TESTE)
    assert not sem_teste, f"rota de escrita sem teste no Postgres: {sorted(sem_teste)}"


# Onde o dialeto do Databricks pode aparecer em f-string: o caminho só-Databricks da sessão
# OBO. (Nada de `register` aqui: as rotas do egps_atualizados.py são aninhadas nele, e
# liberá-lo isentava o arquivo inteiro.)
LIBERADAS = {"_sessao"}


def _ocorrencias_em_fstring(caminho, padrao):
    achadas, funcao = [], "<módulo>"
    for n, linha in enumerate(caminho.read_text(encoding="utf-8").splitlines(), 1):
        d = re.match(r"(?:async )?def ([A-Za-z0-9_]+)", linha)
        if d:
            funcao = d.group(1)
        if linha.lstrip().startswith("#") or funcao in LIBERADAS:
            continue
        for achado in re.finditer(padrao, linha):
            antes = linha[:achado.start()]
            if 'f"' in antes or "f'" in antes:
                achadas.append(f"{caminho.name}:{n} [{funcao}] {linha.strip()[:90]}")
    return achadas


def test_ddl_do_backend_so_roda_fora_do_postgres():
    """No Postgres o schema vem das migrações e o papel do app não tem CREATE: um CREATE/ALTER
    sem a checagem de dialeto falha só na hora de gravar, e às vezes calado (o log diário de
    sanitização engolia o erro). Vale como protegido: um `if dialeto.PG:` com `return` logo
    depois, antes do DDL na mesma função (os `_ensure_*`), ou o DDL dentro do bloco de um
    `if not dialeto.PG` a até 8 linhas acima. A polaridade conta: `if dialeto.PG:` acima (ou o
    DDL logo depois do bloco do `if not`) rodaria o DDL justamente no Postgres. A rotina de
    consulta é só do Databricks e sai na virada (plano 2c)."""
    soltos = _ddl_sem_protecao(AQUI / "main.py")
    assert not soltos, "\n".join(soltos)


def _ddl_sem_protecao(caminho):
    linhas_fonte = caminho.read_text(encoding="utf-8").splitlines()
    soltos, funcao, inicio = [], "<módulo>", 0
    for n, linha in enumerate(linhas_fonte):
        d = re.match(r"(?:async )?def ([A-Za-z0-9_]+)", linha)
        if d:
            funcao, inicio = d.group(1), n
        if re.search(r'f"(?:"")?\s*(CREATE TABLE|ALTER TABLE)', linha) and not funcao.startswith("_consulta"):
            antes = linhas_fonte[inicio:n]
            retorna_no_pg = any("if dialeto.PG:" in x and "return" in " ".join(antes[i:i + 2])
                                for i, x in enumerate(antes))
            if not retorna_no_pg and not _no_bloco_do_if_not_pg(antes[-8:], linha):
                soltos.append(f"{caminho.name}:{n + 1} [{funcao}] {linha.strip()[:80]}")
    return soltos


def _recuo(linha):
    return len(linha) - len(linha.lstrip())


def _no_bloco_do_if_not_pg(acima, linha):
    """O DDL está DENTRO de um `if not dialeto.PG` das linhas `acima`: tudo do if até o DDL
    (ele incluído) mais recuado que o if. Só estar perto do if não basta."""
    return any("if not dialeto.PG" in x
               and all(_recuo(y) > _recuo(x) for y in acima[i + 1:] + [linha] if y.strip())
               for i, x in enumerate(acima))


def test_sql_de_escrita_nao_usa_o_dialeto_do_databricks():
    """current_user()/current_timestamp()/current_date() não existem no Postgres (use
    _ator()/AGORA/current_date, sem parênteses), e lá a coluna-alvo de SET não pode vir
    qualificada (`SET t.col` -> `SET col`)."""
    padrao = r"current_user\(\)|current_timestamp\(\)|current_date\(\)|SET t\.|\bt\.\{"
    achadas = []
    for nome in ("main.py", "egps_atualizados.py"):
        achadas += _ocorrencias_em_fstring(AQUI / nome, padrao)
    assert not achadas, "\n".join(achadas)
