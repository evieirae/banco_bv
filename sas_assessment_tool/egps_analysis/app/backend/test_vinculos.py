# -*- coding: utf-8 -*-
"""Testes da lógica pura do vínculo antecessor -> sucessor (sem DB, sem rede)."""
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
import vinculos as v


def test_tipo_valido():
    assert v.tipo_valido("Atualizado")
    assert v.tipo_valido("Substituído")
    assert v.tipo_valido("Unificado")
    assert not v.tipo_valido("atualizado")      # case-sensitive de propósito
    assert not v.tipo_valido("Desatualizado")   # status, não tipo de vínculo
    assert not v.tipo_valido("")
    assert not v.tipo_valido(None)


def test_espelha_so_atualizado_e_unificado():
    # Substituído NÃO espelha: o antecessor fecha e o sucessor começa do zero.
    assert v.espelha("Atualizado")
    assert v.espelha("Unificado")
    assert not v.espelha("Substituído")
    assert not v.espelha(None)


def test_mapa_vinculos_exige_tipo_e_sucessor():
    rows = [
        {"projeto": "A__x", "egp_vinculo_tipo": "Atualizado", "egp_sucessor": "A__x__ATU20260923"},
        {"projeto": "A__y", "egp_vinculo_tipo": "Atualizado", "egp_sucessor": ""},      # sem sucessor
        {"projeto": "A__z", "egp_vinculo_tipo": "", "egp_sucessor": "A__z__ATU20260923"},  # sem tipo
        {"projeto": "A__w", "egp_vinculo_tipo": "Invalido", "egp_sucessor": "A__q"},    # tipo inválido
        {"projeto": "", "egp_vinculo_tipo": "Atualizado", "egp_sucessor": "A__k"},      # sem projeto
    ]
    m = v.mapa_vinculos(rows)
    assert set(m) == {"A__x"}
    assert m["A__x"] == {"tipo": "Atualizado", "sucessor": "A__x__ATU20260923"}


def test_mapa_vinculos_tolera_none_e_espacos():
    assert v.mapa_vinculos(None) == {}
    m = v.mapa_vinculos([
        {"projeto": " A__x ", "egp_vinculo_tipo": " Unificado ", "egp_sucessor": " A__novo "}])
    assert m == {"A__x": {"tipo": "Unificado", "sucessor": "A__novo"}}


def test_sucessores_espelhados_ficam_fora_do_denominador():
    vin = {
        "A__um": {"tipo": "Atualizado", "sucessor": "A__novo"},
        "A__dois": {"tipo": "Unificado", "sucessor": "A__novo"},      # N:1, mesmo sucessor
        "A__tres": {"tipo": "Substituído", "sucessor": "A__outro"},
    }
    # Substituído conta (o antecessor saiu do fluxo); Atualizado/Unificado não.
    assert v.sucessores_espelhados(vin) == {"A__novo"}


def test_status_exibido_despriorizado_vence():
    # Decisão de gestão não é sobrescrita por fato derivado.
    assert v.status_exibido("Despriorizado e Contabilizado", "Atualizado") \
        == "Despriorizado e Contabilizado"


def test_status_exibido_vira_desatualizado_quando_espelha():
    assert v.status_exibido("Em Andamento", "Atualizado") == "Desatualizado"
    assert v.status_exibido("Block", "Unificado") == "Desatualizado"


def test_status_exibido_intacto_sem_vinculo_e_em_substituido():
    assert v.status_exibido("Em Andamento", None) == "Em Andamento"
    assert v.status_exibido("Em Andamento", "Substituído") == "Em Andamento"


def test_etapa_exibida_espelha_a_do_sucessor():
    assert v.etapa_exibida("Pré-conversão", "Atualizado", "Validação em DES") == "Validação em DES"
    assert v.etapa_exibida("Pré-conversão", "Unificado", None) is None
    assert v.etapa_exibida("Pré-conversão", "Substituído", "Validação em DES") == "Pré-conversão"
    assert v.etapa_exibida("Pré-conversão", None, "Validação em DES") == "Pré-conversão"


def test_pode_editar_etapa():
    assert not v.pode_editar_etapa("Atualizado")
    assert not v.pode_editar_etapa("Unificado")
    assert v.pode_editar_etapa("Substituído")
    assert v.pode_editar_etapa(None)


def test_anexa_vinculo_espelha_etapa_e_status():
    """A função que o main injeta nas linhas do readiness: etapa vem do sucessor,
    status vira Desatualizado, e o sucessor é marcado como tal."""
    linhas = [
        {"projeto": "A__velho", "etapa": "Pré-conversão", "status": "Em Andamento"},
        {"projeto": "A__novo", "etapa": "Validação em DES", "status": "Em Andamento"},
        {"projeto": "A__solto", "etapa": "Pré-conversão", "status": "Block"},
    ]
    vin = {"A__velho": {"tipo": "Atualizado", "sucessor": "A__novo"}}
    v.anexa_vinculo(linhas, vin, linha_base={"A__velho": "base", "A__solto": "base"})
    velho, novo, solto = linhas
    assert velho["etapa"] == "Validação em DES"      # espelhada
    assert velho["status"] == "Desatualizado"
    assert velho["etapa_editavel"] is False
    assert velho["vinculo_tipo"] == "Atualizado"
    assert velho["sucessor"] == "A__novo"
    assert novo["e_sucessor"] is True
    assert novo["etapa"] == "Validação em DES"       # o sucessor é quem tem a etapa de verdade
    assert solto["status"] == "Block"                # sem vínculo, nada muda
    assert solto["etapa_editavel"] is True
    assert solto.get("e_sucessor") is False


def test_anexa_vinculo_sucessor_ausente_nao_espelha_etapa_fantasma():
    """Sucessor fora do recorte carregado: a etapa espelhada fica vazia em vez de manter a
    velha — mostrar a etapa antiga como se fosse a nova é a falha silenciosa a evitar."""
    linhas = [{"projeto": "A__velho", "etapa": "Pré-conversão", "status": "Em Andamento"}]
    v.anexa_vinculo(linhas, {"A__velho": {"tipo": "Atualizado", "sucessor": "A__fora"}},
                    linha_base={"A__velho": "base"})
    assert linhas[0]["etapa"] is None
    assert linhas[0]["status"] == "Desatualizado"


# --- régua CONGELADA (29/09/2026): o total é a LISTA, não uma conta ------------
# A linha de base é um dado versionado (src/linha_base_congelada_2026-09-29.csv). Aqui ela
# entra como um dicionário {projeto: classe} qualquer — a lógica é pura e não sabe de CSV.
# Congelado é QUEM conta; etapa/status/funis seguem vivos.

LB = {"A__velho": "base", "A__dep": "dependencia", "A__ex": "ex_dependencia"}


def test_total_e_o_tamanho_da_lista_congelada():
    """O total não olha para o recorte: venha o que vier no corpus, é o tamanho da lista."""
    assert v.total_egps(LB) == 3
    assert v.total_egps({}) == 0


VIN = {"A__velho": {"tipo": "Atualizado", "sucessor": "A__novo"}}
CASCAS = {"A__casca"}


def test_extra_e_quem_tem_vinculo_de_atualizacao():
    """ENUMERAÇÃO (29/09/2026): sucessor + casca, e só. `A__dep_nova` está fora da lista
    — logo não conta — mas não é extra: nunca teve vínculo com ninguém. Contar e rotular
    voltaram a ser duas perguntas."""
    recorte = {"A__velho", "A__dep", "A__novo", "A__casca", "A__dep_nova"}
    assert v.extras(recorte, LB, VIN, CASCAS) == {"A__novo", "A__casca"}
    assert v.extras(set(), LB, VIN, CASCAS) == set()
    # sem vínculo e sem casca não há extra nenhum, por maior que o recorte fique
    assert v.extras(recorte, LB) == set()


def test_dependencia_nova_e_extra_quando_o_chamador_a_nomeia():
    """13/10/2026: "os 193 estão fechados; dependência que vier vira extra". A função
    continua sem definir nada por exclusão — quem apura a dependência nova no grafo é o
    chamador (`main._deps_novas`) e passa a lista. Sem a lista, nada muda (teste acima)."""
    recorte = {"A__velho", "A__dep", "A__novo", "A__casca", "A__dep_nova"}
    assert v.extras(recorte, LB, VIN, CASCAS, deps_novas={"A__dep_nova"}) == {
        "A__novo", "A__casca", "A__dep_nova"}
    assert v.motivo_extra("A__dep_nova", LB, VIN, CASCAS,
                          deps_novas={"A__dep_nova"}) == v.MOTIVO_DEPENDENCIA
    assert v.tipos_do_extra("A__dep_nova", VIN, CASCAS,
                            deps_novas={"A__dep_nova"}) == [v.MOTIVO_DEPENDENCIA]
    # quem está na linha de base nunca é extra, mesmo que alguém o passe como dep nova
    assert "A__dep" not in v.extras(recorte, LB, VIN, CASCAS, deps_novas={"A__dep"})
    # e a ex-dependência segue vetada
    assert v.extras({"A__dep_nova"}, LB, deps_novas={"A__dep_nova"},
                    ex_dependencias={"A__dep_nova"}) == set()


def test_ex_dependencia_nunca_e_extra():
    """O badge de ex-dependência já basta. Era daqui que vinha a discordância entre a
    TELA (que lista as ex) e o CONTADOR (que conta sobre o frontier, onde ex não está)."""
    recorte = {"A__novo", "A__casca", "A__ex_fora"}
    assert v.extras(recorte, LB, VIN, CASCAS, ex_dependencias={"A__ex_fora"}) == {
        "A__novo", "A__casca"}
    # e mesmo uma ex que fosse sucessor de alguém continua sem o 2º rótulo
    assert v.extras(recorte, LB, VIN, CASCAS, ex_dependencias={"A__novo"}) == {"A__casca"}


def test_sucessor_que_ESTA_na_lista_nao_e_extra():
    """Marcá-lo seria contá-lo duas vezes: uma no total e outra no contador ao lado."""
    lb = dict(LB, **{"A__novo": "base"})
    assert v.extras({"A__velho", "A__novo"}, lb, VIN, CASCAS) == set()


def test_contaveis_e_a_intersecao_com_a_linha_de_base():
    recorte = {"A__velho", "A__novo"}
    assert v.contaveis(recorte, LB) == {"A__velho"}


def test_quem_sai_do_escopo_continua_no_denominador():
    """Congelado nos DOIS lados: o recorte encolheu, o total não se mexeu."""
    assert v.total_egps(LB) == 3
    assert v.contaveis({"A__velho"}, LB) == {"A__velho"}   # o recorte perdeu 2
    assert v.total_egps(LB) == 3                            # o denominador, não


def test_motivo_extra_tem_dois_valores_e_so():
    """A distinção some do FILTRO (um valor só) mas continua no detalhe do EGP. São DOIS
    motivos: não existe um "novo" — quem não tem vínculo simplesmente não é extra."""
    vin = {"A__velho": {"tipo": "Atualizado", "sucessor": "A__novo"}}
    cascas = {"A__casca"}
    assert v.motivo_extra("A__novo", LB, vin, cascas) == "sucessor"
    assert v.motivo_extra("A__casca", LB, vin, cascas) == "casca"
    assert v.motivo_extra("A__qualquer", LB, vin, cascas) is None   # fora da lista, sem vínculo
    assert v.motivo_extra("A__velho", LB, vin, cascas) is None      # está na lista
    # ex-dependência: mesmo sendo sucessor, o badge dela já basta
    assert v.motivo_extra("A__novo", LB, vin, cascas, ex_dependencia=True) is None


def test_extra_nunca_volta_a_ser_definicao_por_exclusao():
    """A guarda que importa. Aqui morava `assert not hasattr(v, "MOTIVO_NOVO")`, e o nome
    do motivo não era o invariante: o `novo` do ticket 19 era `recorte − linha_base`, uma
    DEFINIÇÃO, e foi ela que rotulou 16 ex-dependências de "chegou depois do congelamento"
    em produção. O `novo` que voltou em 29/09 (caso `Cobranças__ROI`) é uma LISTA, igual às
    outras duas pernas.

    O que não pode voltar é estar-fora-da-lista virar rótulo sozinho."""
    lb = {"A__conta"}
    # ninguém nomeado: fora da lista e sem vínculo, casca ou declaração -> NÃO é extra
    assert v.extras({"A__conta", "A__fora"}, lb) == set()
    assert v.motivo_extra("A__fora", lb) is None
    # cada perna nomeia o seu, e só o seu
    assert v.extras({"A__fora"}, lb, novos={"A__fora"}) == {"A__fora"}
    assert v.motivo_extra("A__fora", lb, novos={"A__fora"}) == v.MOTIVO_NOVO
    # declarar novo quem JÁ conta não o duplica: a linha de base vence
    assert v.extras({"A__conta"}, lb, novos={"A__conta"}) == set()
    assert v.motivo_extra("A__conta", lb, novos={"A__conta"}) is None
    # vínculo vence declaração: quem é sucessor é rotulado como sucessor
    vin = {"A__velho": {"tipo": "Atualizado", "sucessor": "A__fora"}}
    assert v.motivo_extra("A__fora", lb, vin, novos={"A__fora"}) == v.MOTIVO_SUCESSOR
    # ex-dependência declarada novo continua sem rótulo: o badge dela basta
    assert v.motivo_extra("A__fora", lb, novos={"A__fora"}, ex_dependencia=True) is None


def test_tela_e_contador_leem_a_mesma_lista_de_novos():
    """O bug do ticket 21 em uma linha: `anexa_vinculo` (TELA) e `extras` (CONTADOR)
    discordando — 37 × 18. Se `novos` chegar num e não no outro, volta."""
    lb = {"A__conta"}
    linhas = [{"projeto": "A__fora", "etapa": None, "status": None}]
    v.anexa_vinculo(linhas, {}, linha_base=lb, novos={"A__fora"})
    assert linhas[0]["e_extra"] is True
    assert linhas[0]["extra_motivo"] == v.MOTIVO_NOVO
    assert v.extras({"A__fora"}, lb, novos={"A__fora"}) == {"A__fora"}


def test_sucessores_pega_todo_tipo_de_vinculo():
    vin = {
        "A__um": {"tipo": "Atualizado", "sucessor": "A__novo"},
        "A__dois": {"tipo": "Unificado", "sucessor": "A__novo"},
        "A__tres": {"tipo": "Substituído", "sucessor": "A__outro"},
    }
    assert v.sucessores(vin) == {"A__novo", "A__outro"}
    # o outro eixo, intocado: só Atualizado/Unificado espelham.
    assert v.sucessores_espelhados(vin) == {"A__novo"}


def test_anexa_vinculo_marca_extra_sem_mexer_no_espelhamento():
    linhas = [
        {"projeto": "A__velho", "etapa": "Pré-conversão", "status": "Em Andamento"},
        {"projeto": "A__novo", "etapa": "Validação em DES", "status": "Em Andamento"},
        {"projeto": "A__subst", "etapa": "Conversão do Código", "status": "Em Andamento"},
        {"projeto": "A__casca", "etapa": None, "status": "A Iniciar"},
    ]
    vin = {"A__velho": {"tipo": "Atualizado", "sucessor": "A__novo"},
           "A__outro": {"tipo": "Substituído", "sucessor": "A__subst"}}
    v.anexa_vinculo(linhas, vin, {"A__casca"}, linha_base={"A__velho": "base"})
    velho, novo, subst, casca = linhas
    # extra = tem vínculo de atualização com outro EGP e está fora da linha de base:
    # sucessor (de qualquer tipo de vínculo) e casca, nesta ordem de precedência.
    assert (novo["e_extra"], novo["extra_motivo"]) == (True, "sucessor")
    assert (subst["e_extra"], subst["extra_motivo"]) == (True, "sucessor")
    assert (casca["e_extra"], casca["extra_motivo"]) == (True, "casca")
    assert (velho["e_extra"], velho["extra_motivo"]) == (False, None)
    # espelhamento intocado: decidido pelo TIPO, não pela categoria.
    assert velho["status"] == "Desatualizado" and velho["etapa"] == "Validação em DES"
    assert novo["e_sucessor"] is True and subst["e_sucessor"] is False


def test_anexa_vinculo_exige_a_linha_de_base():
    """Sem a lista não há como dizer quem é extra. Esquecer o argumento explode em vez de
    marcar o corpus inteiro como extra."""
    import pytest
    with pytest.raises(TypeError):
        v.anexa_vinculo([{"projeto": "A__velho"}], {})


def test_anexa_vinculo_nao_marca_extra_quem_nunca_teve_vinculo():
    """O EGP que simplesmente apareceu no corpus sem vínculo e sem ser casca fica FORA do
    total (não está na lista) e SEM rótulo de extra. Contagem e rótulo são eixos
    separados: `na_linha_base` responde um, `e_extra` responde o outro."""
    linhas = [{"projeto": "A__recem_chegado", "etapa": "Conversão do Código",
               "status": "Em Andamento"}]
    v.anexa_vinculo(linhas, {}, (), linha_base={"A__velho": "base"})
    assert (linhas[0]["e_extra"], linhas[0]["extra_motivo"]) == (False, None)
    assert linhas[0]["na_linha_base"] is False


def test_anexa_vinculo_veta_o_extra_na_ex_dependencia():
    """A linha já chega marcada `ex_dependencia` pelo recorte; o rótulo de extra não se
    acumula em cima. Em produção eram 16 linhas dizendo `extra · novo` sobre EGPs que
    estão no corpus desde junho."""
    linhas = [{"projeto": "A__ex", "etapa": "", "status": "A Iniciar",
               "ex_dependencia": True},
              {"projeto": "A__casca", "etapa": None, "status": "A Iniciar"}]
    v.anexa_vinculo(linhas, {}, {"A__ex", "A__casca"}, linha_base={"A__velho": "base"})
    ex, casca = linhas
    assert (ex["e_extra"], ex["extra_motivo"]) == (False, None)
    assert (casca["e_extra"], casca["extra_motivo"]) == (True, "casca")


def test_anexa_vinculo_diz_quem_conta_no_total():
    """`na_linha_base` é o critério de CONTAGEM servido por linha — o front lê a mesma
    lista congelada do card em vez de reaplicar o critério "189" sobre a etapa viva."""
    linhas = [{"projeto": "A__velho", "etapa": "", "status": ""},
              {"projeto": "A__fora", "etapa": "", "status": ""}]
    v.anexa_vinculo(linhas, {}, (), linha_base={"A__velho": "base"})
    assert linhas[0]["na_linha_base"] is True
    assert linhas[1]["na_linha_base"] is False


# ---- cópia do trabalho de gestão no ato do vínculo (ticket 07, spec §3.3.11) ----

def test_copia_leva_etapa_mes_jira_e_responsavel():
    copia = v.campos_copiados_no_vinculo(
        {"etapa": "Validação em DES", "mes_prioridade": 3, "jira_id": "UDAA-4825",
         "responsavel": "alguem@indicium.tech"},
        {})
    assert copia == {"etapa": "Validação em DES", "mes_prioridade": 3,
                     "jira_id": "UDAA-4825", "responsavel": "alguem@indicium.tech"}


def test_copia_nao_leva_status():
    """Classificar nunca muda status sozinho (§3.5.21): no Substituído a tela SUGERE
    fechar o antecessor e quem clica é a gestão."""
    copia = v.campos_copiados_no_vinculo(
        {"etapa": "Validação em DES", "status": "Em Andamento"}, {})
    assert "status" not in copia


def test_copia_nao_sobrescreve_o_que_o_sucessor_ja_tem():
    """Vincular -> desvincular -> vincular de novo não pode atropelar o trabalho que já
    andou no sucessor."""
    copia = v.campos_copiados_no_vinculo(
        {"etapa": "Pré-conversão", "jira_id": "UDAA-1", "responsavel": "velho@x"},
        {"etapa": "Conversão do Código", "jira_id": None, "responsavel": ""})
    assert copia == {"jira_id": "UDAA-1", "responsavel": "velho@x"}


def test_copia_ignora_campo_vazio_no_antecessor():
    copia = v.campos_copiados_no_vinculo(
        {"etapa": None, "mes_prioridade": None, "jira_id": "", "responsavel": "x@y"}, {})
    assert copia == {"responsavel": "x@y"}


def test_copia_respeita_a_guarda_da_etapa_espelhada():
    """Cadeia v1 -> v2 -> v3: a etapa do v2 já é espelho do v3 e o servidor recusa
    escrevê-la (§3.2.7). A cópia não pode furar a própria guarda."""
    copia = v.campos_copiados_no_vinculo(
        {"etapa": "Validação em DES", "jira_id": "UDAA-1"}, {},
        sucessor_espelha_etapa=True)
    assert copia == {"jira_id": "UDAA-1"}


def test_copia_e_evento_nao_sincronizacao():
    # vínculo novo -> copia
    assert v.vinculo_criado_agora("Atualizado", "A__novo", None, None) is True
    # trocou o ponteiro -> copia de novo (é outro vínculo)
    assert v.vinculo_criado_agora("Atualizado", "A__novo2", "Atualizado", "A__novo") is True
    # mesma classificação re-salva -> NÃO copia (senão campo apagado de propósito voltaria)
    assert v.vinculo_criado_agora("Atualizado", "A__novo", "Atualizado", "A__novo") is False
    # vínculo pela metade não é vínculo
    assert v.vinculo_criado_agora("Atualizado", None, None, None) is False
    assert v.vinculo_criado_agora(None, "A__novo", None, None) is False
    assert v.vinculo_criado_agora("Trocado", "A__novo", None, None) is False


def _distribuicao_funil_deps(linhas, linha_base):
    """Distribuição por etapa do funil `+deps`, na régua de /api/funis: universo = a LINHA
    DE BASE congelada, e EGP sem etapa fica fora do coorte. A distribuição é VIVA — só o
    conjunto de quem conta é que está congelado."""
    conta = v.contaveis({l["projeto"] for l in linhas}, linha_base)
    dist = {}
    for linha in linhas:
        if linha["projeto"] not in conta or not linha.get("etapa"):
            continue
        dist[linha["etapa"]] = dist.get(linha["etapa"], 0) + 1
    return dist


def _corpus():
    """Antecessor com trabalho andado + sucessor recém-chegado ao corpus (sem etapa)."""
    return [{"projeto": "A__velho", "etapa": "Validação em DES", "status": "Em Andamento",
             "mes_prioridade": 3, "jira_id": "UDAA-1", "responsavel": "x@y"},
            {"projeto": "A__novo", "etapa": None, "status": None,
             "mes_prioridade": None, "jira_id": None, "responsavel": None}]


def test_funil_deps_nao_perde_egp_de_coluna_ao_vincular():
    """Critério do ticket 07: criar o vínculo não pode esvaziar nenhuma coluna do funil."""
    lb = {"A__velho": "base"}
    antes = _distribuicao_funil_deps(v.anexa_vinculo(_corpus(), {}, linha_base=lb), lb)
    assert antes == {"Validação em DES": 1}

    linhas = _corpus()
    antecessor, sucessor = linhas
    copia = v.campos_copiados_no_vinculo(antecessor, sucessor)
    sucessor.update(copia)                       # a cópia acontece no ATO do vínculo
    vin = {"A__velho": {"tipo": "Atualizado", "sucessor": "A__novo"}}
    depois = _distribuicao_funil_deps(v.anexa_vinculo(linhas, vin, linha_base=lb), lb)

    assert depois == antes, "o vínculo tirou um EGP da coluna do funil +deps"


def test_denominador_congelado_numerador_vivo():
    """A correção de 29/09: congelado é QUEM conta, não o que cada um está fazendo.
    Mudar a etapa de um dos contáveis tem de mexer a distribuição e NÃO mexer o total."""
    lb = {"A__velho": "base", "A__dep": "dependencia"}
    linhas = [{"projeto": "A__velho", "etapa": "Validação em DES"},
              {"projeto": "A__dep", "etapa": "Conversão do Código"}]
    assert v.total_egps(lb) == 2
    assert _distribuicao_funil_deps(linhas, lb) == {"Validação em DES": 1,
                                                    "Conversão do Código": 1}
    linhas[1]["etapa"] = "Validação em DES"      # o trabalho andou
    assert _distribuicao_funil_deps(linhas, lb) == {"Validação em DES": 2}
    assert v.total_egps(lb) == 2                  # o denominador, parado


def test_sem_a_copia_o_antecessor_cairia_para_sem_etapa():
    """O bug que a cópia corrige, escrito por extenso: sem ela o antecessor passa a
    espelhar a etapa VAZIA do sucessor recém-chegado e some da coluna."""
    linhas = _corpus()
    vin = {"A__velho": {"tipo": "Atualizado", "sucessor": "A__novo"}}
    lb = {"A__velho": "base"}
    sem_copia = _distribuicao_funil_deps(v.anexa_vinculo(linhas, vin, linha_base=lb), lb)
    assert sem_copia == {}, "cenário do bug mudou — revise o porquê da cópia da etapa"


def test_copia_nao_liga_os_dois_campos_depois_do_ato():
    """Depois da cópia cada um segue sozinho: editar o sucessor não volta ao antecessor."""
    linhas = _corpus()
    antecessor, sucessor = linhas
    sucessor.update(v.campos_copiados_no_vinculo(antecessor, sucessor))
    sucessor["jira_id"] = "UDAA-999"             # trabalho andando só no sucessor
    sucessor["responsavel"] = "outro@z"
    assert antecessor["jira_id"] == "UDAA-1"
    assert antecessor["responsavel"] == "x@y"
    # e uma 2ª passada do vínculo não re-sincroniza
    assert v.campos_copiados_no_vinculo(antecessor, sucessor) == {}


# ---- cadeia de sucessores (29/09/2026) --------------------------------------------

def _v(pares):
    return {a: {"tipo": "Atualizado", "sucessor": s} for a, s in pares}


def test_cadeia_alcanca_a_terceira_versao():
    """O bug de 29/09: o BV mandou `set_26` depois de `jul_26`, o vínculo foi criado e o
    EGP seguiu invisível — o recorte fazia UMA passada sobre os sucessores."""
    vinc = _v([("v1", "v2"), ("v2", "v3")])
    assert v.cadeia_de_sucessores(vinc, {"v1"}) == {"v2", "v3"}


def test_cadeia_nao_devolve_o_ponto_de_partida():
    assert v.cadeia_de_sucessores(_v([("v1", "v2")]), {"v1"}) == {"v2"}


def test_cadeia_de_antecessor_fora_do_recorte_nao_puxa_nada():
    """Regra preservada: sucessor só entra pela porta de um antecessor JÁ no recorte."""
    assert v.cadeia_de_sucessores(_v([("fora", "novo")]), {"v1"}) == set()


def test_cadeia_com_ciclo_termina():
    """A -> B -> A não deveria existir, mas o app não recusa hoje; o fecho não pode travar."""
    assert v.cadeia_de_sucessores(_v([("a", "b"), ("b", "a")]), {"a"}) == {"b"}


def test_cadeia_sem_vinculo_algum():
    assert v.cadeia_de_sucessores({}, {"v1"}) == set()
    assert v.cadeia_de_sucessores(None, {"v1"}) == set()


# ---- fim da cadeia de espelhamento (29/09/2026) -----------------------------------

def test_fim_do_espelho_atravessa_a_cadeia():
    """v1 → v2 → v3: a etapa exibida do v1 sai do v3, não do v2 (que também espelha)."""
    vin = _v([("v1", "v2"), ("v2", "v3")])
    assert v.fim_do_espelho("v1", vin) == "v3"
    assert v.fim_do_espelho("v2", vin) == "v3"
    assert v.fim_do_espelho("v3", vin) == "v3"


def test_fim_do_espelho_para_em_substituido():
    """`Substituído` encerra a cadeia: ali o sucessor começa do zero (§3.2)."""
    vin = {"v1": {"tipo": "Atualizado", "sucessor": "v2"},
           "v2": {"tipo": "Substituído", "sucessor": "v3"}}
    assert v.fim_do_espelho("v1", vin) == "v2"


def test_fim_do_espelho_sem_vinculo_devolve_o_proprio():
    assert v.fim_do_espelho("v1", {}) == "v1"
    assert v.fim_do_espelho("v1", None) == "v1"


def test_fim_do_espelho_com_ciclo_nao_trava():
    assert v.fim_do_espelho("a", _v([("a", "b"), ("b", "a")])) in {"a", "b"}


def test_cadeia_exibe_a_etapa_do_fim_e_nao_vazio():
    """O defeito de 29/09 em uma asserção: o v1 tinha etapa real, o v2 (espelho) tinha
    vazio, e o v1 aparecia sem etapa — fora do coorte do funil e da tabela por mês."""
    vin = _v([("v1", "v2"), ("v2", "v3")])
    pipe = {"v1": ("Pré-conversão", "Concluído"), "v2": (None, None),
            "v3": ("Conversão do Código", "Em Andamento")}
    exib = v.mapa_exibido(pipe, vin)
    assert exib["v1"][0] == "Conversão do Código"     # veio do FIM, não do v2
    assert exib["v1"][1] == v.STATUS_DESATUALIZADO
    assert exib["v2"][0] == "Conversão do Código"


# ---- tipos do extra (29/09/2026) --------------------------------------------------

def test_tipos_do_extra_abre_o_sucessor_nos_tres_vinculos():
    vin = {"a": {"tipo": "Atualizado", "sucessor": "novo"},
           "b": {"tipo": "Unificado", "sucessor": "hub"},
           "c": {"tipo": "Substituído", "sucessor": "subst"}}
    assert v.tipos_do_extra("novo", vin) == ["Atualizado"]
    assert v.tipos_do_extra("hub", vin) == ["Unificado"]
    assert v.tipos_do_extra("subst", vin) == ["Substituído"]


def test_tipos_do_extra_e_LISTA_quando_os_antecessores_divergem():
    """Caso real de 29/09: `Project_Fyf_Reneg_BQ_202608 1` é Atualizado por um antecessor e
    Substituído por outro. Uma categoria "misto" o esconderia dos dois filtros."""
    vin = {"a": {"tipo": "Atualizado", "sucessor": "x"},
           "b": {"tipo": "Substituído", "sucessor": "x"}}
    assert v.tipos_do_extra("x", vin) == ["Atualizado", "Substituído"]


def test_tipos_do_extra_nao_duplica_o_mesmo_tipo():
    """Unificador com 4 antecessores, todos Unificado -> um valor só."""
    vin = {p: {"tipo": "Unificado", "sucessor": "hub"} for p in "abcd"}
    assert v.tipos_do_extra("hub", vin) == ["Unificado"]


def test_tipos_do_extra_casca_e_novo():
    assert v.tipos_do_extra("c", {}, cascas={"c"}) == [v.MOTIVO_CASCA]
    assert v.tipos_do_extra("n", {}, novos={"n"}) == [v.MOTIVO_NOVO]
    assert v.tipos_do_extra("x", {}) == []


def test_anexa_vinculo_so_poe_tipos_em_quem_E_extra():
    """Pôr em toda linha faria o front checar dois campos p/ a mesma pergunta."""
    lb = {"A__conta"}
    linhas = [{"projeto": "A__conta", "etapa": None, "status": None},
              {"projeto": "A__novo", "etapa": None, "status": None}]
    vin = {"A__velho": {"tipo": "Unificado", "sucessor": "A__novo"}}
    v.anexa_vinculo(linhas, vin, linha_base=lb)
    assert linhas[0]["extra_tipos"] == []            # está na linha de base: não é extra
    assert linhas[1]["extra_tipos"] == ["Unificado"]


def test_antecessores_por_sucessor_inverte_e_agrupa_o_unificador():
    """Um unificador substitui VÁRIOS: a inversão tem de devolver lista, ordenada."""
    vinc = {
        "A__Projecao": {"tipo": "Unificado", "sucessor": "A__Novo"},
        "A__Fechamento": {"tipo": "Unificado", "sucessor": "A__Novo"},
        "A__Velho": {"tipo": "Atualizado", "sucessor": "A__Outro"},
        "A__SemSucessor": {"tipo": "Atualizado", "sucessor": None},
    }
    inv = v.antecessores_por_sucessor(vinc)
    assert inv["A__Novo"] == [
        {"projeto": "A__Fechamento", "tipo": "Unificado"},
        {"projeto": "A__Projecao", "tipo": "Unificado"},
    ]
    assert inv["A__Outro"] == [{"projeto": "A__Velho", "tipo": "Atualizado"}]
    assert "A__SemSucessor" not in inv and None not in inv


def test_anexa_vinculo_poe_antecessores_mesmo_fora_do_recorte():
    """O antecessor pode não ter linha carregada (casca) e ainda assim precisa aparecer —
    é ele que explica por que o sucessor está no recorte."""
    linhas = [{"projeto": "A__Novo", "etapa": "Migrado", "status": "Concluído"}]
    vinc = {"A__CascaForaDoRecorte": {"tipo": "Unificado", "sucessor": "A__Novo"}}
    v.anexa_vinculo(linhas, vinc, ["A__CascaForaDoRecorte"], linha_base=["A__Novo"])
    assert linhas[0]["antecessores"] == [
        {"projeto": "A__CascaForaDoRecorte", "tipo": "Unificado"}]


def test_anexa_vinculo_antecessores_vazio_quando_ninguem_aponta():
    linhas = [{"projeto": "A__Sozinho", "etapa": None, "status": None}]
    v.anexa_vinculo(linhas, {}, [], linha_base=["A__Sozinho"])
    assert linhas[0]["antecessores"] == []


# ---- ticket 23: no corpus, sem vínculo ------------------------------------------------

def test_sem_vinculo_acha_quem_nao_aparece_em_lugar_nenhum():
    projetos = ["A__Base", "A__Dep", "A__Sucessor", "A__Antecessor", "A__Orfao"]
    vinc = {"A__Antecessor": {"tipo": "Atualizado", "sucessor": "A__Sucessor"}}
    assert v.sem_vinculo(projetos, linha_base=["A__Base"], frontier=["A__Base", "A__Dep"],
                         vinculos_por_antecessor=vinc) == ["A__Orfao"]


def test_sem_vinculo_nao_lista_quem_e_ponta_de_vinculo_fora_do_recorte():
    """Antecessor fora do recorte tem porta (o vínculo); quem não aparece é caso do
    `vinculos_orfaos`, não desta lista — senão o mesmo EGP sairia nas duas."""
    vinc = {"A__ForaDoRecorte": {"tipo": "Atualizado", "sucessor": "A__Suc"}}
    assert v.sem_vinculo(["A__ForaDoRecorte", "A__Suc"], linha_base=[], frontier=[],
                         vinculos_por_antecessor=vinc) == []


def test_sem_vinculo_ignora_vazio_e_espaco():
    assert v.sem_vinculo(["", "  ", None, "A__X"], linha_base=[], frontier=[],
                         vinculos_por_antecessor={}) == ["A__X"]


def test_vinculos_orfaos_olha_o_antecessor_nao_o_sucessor():
    """O sucessor pode estar no recorte por OUTRO antecessor — e aí o vínculo inerte
    continua inerte. Foi o caso medido do Project_Fyf_Reneg_v2."""
    vinc = {
        "A__Fora": {"tipo": "Atualizado", "sucessor": "A__Suc"},
        "A__Dentro": {"tipo": "Substituído", "sucessor": "A__Suc"},
    }
    assert v.vinculos_orfaos(vinc, frontier=["A__Dentro", "A__Suc"]) == [
        {"antecessor": "A__Fora", "sucessor": "A__Suc", "tipo": "Atualizado",
         "sucessor_em_tela": None}]


def test_vinculos_orfaos_separa_inerte_de_invisivel():
    """Medido em 01/10/2026: 3 dos 4 órfãos eram inertes (sucessor visível por outro
    caminho) e gritar nos 4 enterrava o único que pedia ação."""
    vinc = {
        "A__ForaInerte": {"tipo": "Atualizado", "sucessor": "A__SucVisivel"},
        "A__ForaInvisivel": {"tipo": "Atualizado", "sucessor": "A__SucSumido"},
    }
    r = v.vinculos_orfaos(vinc, frontier=[], em_tela=["A__SucVisivel"])
    por_ant = {x["antecessor"]: x for x in r}
    assert por_ant["A__ForaInerte"]["sucessor_em_tela"] is True
    assert por_ant["A__ForaInvisivel"]["sucessor_em_tela"] is False


def test_vinculos_orfaos_sem_recorte_nao_afirma_que_esta_em_tela():
    """Sem `em_tela` o campo é None, nunca True: dizer "aparece" sem ter olhado esconderia
    justamente o caso grave."""
    vinc = {"A__Fora": {"tipo": "Atualizado", "sucessor": "A__Suc"}}
    assert v.vinculos_orfaos(vinc, frontier=[])[0]["sucessor_em_tela"] is None


def test_vinculos_orfaos_ex_dependencia_conta_como_em_tela():
    """Ex-dependência está FORA do frontier por construção, mas aparece na aba com badge —
    classificá-la como invisível devolveria o ruído que o refino veio tirar."""
    vinc = {"A__ExDep": {"tipo": "Atualizado", "sucessor": "A__SucExDep"}}
    r = v.vinculos_orfaos(vinc, frontier=["A__Outro"],
                          em_tela=["A__Outro", "A__SucExDep"])
    assert r[0]["sucessor_em_tela"] is True


def test_vinculos_orfaos_ignora_vinculo_incompleto():
    vinc = {"A__Fora": {"tipo": "Atualizado", "sucessor": None}}
    assert v.vinculos_orfaos(vinc, frontier=[]) == []


def test_cadeia_de_sucessores_alcanca_o_sucessor_de_uma_casca():
    """A casca é tirada da base (regra 27) e devolvida ao recorte depois. Se a cadeia
    partir só da base, o UNIFICADOR dela — que só tem casca como antecessor — nunca é
    alcançado e fica invisível com os inputs fora de qualquer balde (medido 30/09/2026)."""
    vinc = {
        "A__Casca1": {"tipo": "Unificado", "sucessor": "A__Unificador"},
        "A__Casca2": {"tipo": "Unificado", "sucessor": "A__Unificador"},
    }
    assert v.cadeia_de_sucessores(vinc, ["A__Base"]) == set(), "sem a casca não alcança"
    assert v.cadeia_de_sucessores(vinc, {"A__Base", "A__Casca1"}) == {"A__Unificador"}
