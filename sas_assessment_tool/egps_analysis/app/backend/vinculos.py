# -*- coding: utf-8 -*-
"""Lógica pura do vínculo antecessor -> sucessor (EGPs Atualizados).

Sem DB e sem FastAPI, no padrão de priorizacao_logic.py / prioridades_logic.py: dá para
testar offline e o main.py só injeta os dados. As regras vivem em
app/docs/superpowers/specs/2026-09-24-egps-atualizados-unificacao-design.md.

Tudo aqui é DERIVADO. Nada de status gravado: o status real do antecessor fica intacto no
banco e reaparece se o vínculo for desfeito (§3.2.6 da spec).
"""

TIPOS_VINCULO = ("Atualizado", "Substituído", "Unificado")
# Atualizado/Unificado: o trabalho migrou para o sucessor, então o antecessor herda a etapa
# dele e para de editá-la. Substituído não espelha — o antecessor fecha como Despriorizado
# e Contabilizado e o sucessor começa do zero, trajetórias independentes (§3.2).
TIPOS_QUE_ESPELHAM = ("Atualizado", "Unificado")

# Marcador da CASCA em sas_escopo (§3.6 regra 23): a linha existe só p/ o
# recompute_escopo() não apagar o escopo_indi dela — nunca para contar (regra 24).
ORIGEM_CASCA = "casca"
# Por que um EGP é `extra` (só no detalhe; o filtro tem um valor só). São DOIS, e são a
# ENUMERAÇÃO INTEIRA — não existe um motivo "resto do corpus".
MOTIVO_SUCESSOR = "sucessor"
MOTIVO_CASCA = "casca"
# Terceiro motivo, DECLARADO À MÃO (decisão da gestão, 29/09/2026 — caso do `Cobranças__ROI`:
# "entra como um a mais mesmo"). Não confundir com o `novo` que o ticket 19 criou e o 21
# apagou: aquele era DEFINIÇÃO POR EXCLUSÃO (`recorte − linha_base`) e varria junto as 16
# ex-dependências que ninguém pretendia rotular. Este é uma LISTA, como as outras duas
# pernas da enumeração — ninguém entra sem ter sido nomeado.
MOTIVO_NOVO = "novo"
# Quarto motivo (decisão da gestão, 13/10/2026: "os 193 estão fechados; dependência que vier
# vira extra"). É a DEPENDÊNCIA que apareceu depois do congelamento — o grafo a puxa porque
# um EGP da linha de base lê o que ela produz. Antes ela ficava fora de tudo como EGP, mas
# os inputs dela entravam no card de dependências: o número de EGPs dizia 11 e os inputs
# contavam um EGP a mais. Também é uma LISTA (quem o chamador apurou no grafo), não uma
# definição por exclusão — a ex-dependência continua vetada em `extras`.
MOTIVO_DEPENDENCIA = "dependencia"

STATUS_DESATUALIZADO = "Desatualizado"
STATUS_DESPRIORIZADO = "Despriorizado e Contabilizado"


def tipo_valido(tipo):
    return tipo in TIPOS_VINCULO


def espelha(tipo):
    return tipo in TIPOS_QUE_ESPELHAM


def mapa_vinculos(pipe_rows):
    """{antecessor: {"tipo", "sucessor"}} a partir das linhas de sas_egp_pipeline.

    Vínculo pela metade não é vínculo: sem tipo válido OU sem sucessor, a linha é ignorada
    — senão um tipo salvo antes do ponteiro já espelharia etapa de lugar nenhum.
    """
    mapa = {}
    for r in pipe_rows or []:
        projeto = (r.get("projeto") or "").strip()
        tipo = (r.get("egp_vinculo_tipo") or "").strip()
        sucessor = (r.get("egp_sucessor") or "").strip()
        if projeto and sucessor and tipo_valido(tipo):
            mapa[projeto] = {"tipo": tipo, "sucessor": sucessor}
    return mapa


def sucessores_espelhados(vinculos):
    """Sucessores cuja etapa é ESPELHADA na linha do antecessor (eixo do espelhamento).

    Não decide categoria nem denominador — para isso existe `extras()`. Sucessor de
    Substituído não entra aqui porque ali o antecessor fecha e o sucessor começa do zero:
    trajetórias independentes (§3.2).
    """
    return {v["sucessor"] for v in (vinculos or {}).values() if espelha(v["tipo"])}


def sucessores(vinculos):
    """TODOS os sucessores, de qualquer tipo de vínculo (eixo da CATEGORIA)."""
    return {v["sucessor"] for v in (vinculos or {}).values()}


def cadeia_de_sucessores(vinculos, a_partir_de):
    """FECHO dos sucessores alcançáveis a partir de `a_partir_de` — v1 -> v2 -> v3 inteira.

    O recorte fazia UMA passada só (`{v["sucessor"] for p in level}`), e com isso a segunda
    versão de uma cadeia era gravada, aparecia no vínculo e **não entrava em tela nenhuma**:
    o BV mandou `…score_solar_set_26` depois de `…jul_26`, o vínculo foi criado, e o EGP
    seguiu invisível (29/09/2026). Vínculo declarado que não puxa nada é dado quebrado em
    silêncio — a cadeia já era prevista pelo desenho (§3.2.7 e `campos_copiados_no_vinculo`).

    Devolve só os sucessores, SEM `a_partir_de`. Ciclo (A -> B -> A, que o app não deveria
    permitir mas não recusa hoje) termina: cada projeto entra no resultado uma única vez.
    """
    vinc = vinculos or {}
    fecho, fronteira = set(), set(a_partir_de)
    while fronteira:
        novos = {vinc[p]["sucessor"] for p in fronteira if p in vinc and vinc[p].get("sucessor")}
        fronteira = novos - fecho - set(a_partir_de)
        fecho |= fronteira
    return fecho


def candidatos_extra(vinculos=None, cascas=(), novos=(), deps_novas=()):
    """De onde `extra` pode sair — TRÊS listas, nenhuma definição por exclusão:
    o sucessor apontado por um vínculo (`egp_sucessor`), a casca (que tem `unificado_em`)
    e o EGP NOVO declarado à mão (`novos`), que não substitui ninguém e por isso nunca
    seria alcançado por vínculo."""
    return (sucessores(vinculos) | set(cascas or ()) | set(novos or ())
            | set(deps_novas or ()))


def extras(recorte, linha_base, vinculos=None, cascas=(), ex_dependencias=(), novos=(),
           deps_novas=()):
    """Categoria `extra`: **o EGP do recorte que chegou depois do congelamento e foi
    NOMEADO** — sucessor, casca ou novo declarado — e não está na linha de base.

    *(ENUMERAÇÃO, restaurada em 29/09/2026. O ticket 19 trocou isto por uma definição —
    `recorte − linha_base` — que era mais simples e varria junto uma terceira categoria
    que ninguém pretendia: a ex-dependência que não entra na contagem. Em produção ela
    marcou 16 ex-dependências como `extra · novo`, afirmando "chegou depois do
    congelamento" sobre EGPs que estão no corpus desde junho. Estar fora da lista é um
    fato do DENOMINADOR; `extra` é um RÓTULO, e os dois deixaram de ser a mesma coisa.)*

    Três recusas deliberadas:

    - **ex-dependência nunca é extra** (`ex_dependencias`): o badge de ex-dependência já
      diz o que ela é, e um segundo rótulo só mentiria sobre quando ela chegou. Ela
      também não está no frontier por definição — era daí que vinha a discordância entre
      a TELA (que lista as ex) e o CONTADOR (que contava sobre o frontier): 37 × 18;
    - **quem não foi nomeado não é extra**, mesmo fora da lista. É por isso que o EGP
      que não substitui ninguém precisa de `novos`: sem ele, um EGP que entrou no escopo
      de verdade — o `Cobranças__ROI` — não cabia em lugar algum, nem nos 193
      (congelados) nem em `extra` (que só conhecia vínculo). A dependência que apareceu
      depois do congelamento É nomeada desde 13/10/2026 (`deps_novas`, apurada pelo
      chamador no grafo): até ali ela não ganhava rótulo, mas os inputs dela contavam no
      card de dependências — um EGP fora de tudo que mexia num número da linha de base;
    - **quem ESTÁ na lista nunca é extra**, mesmo sendo sucessor: ele já conta no
      denominador, e marcá-lo seria contá-lo duas vezes — uma no total e outra ao lado.

    Extra é listado no recorte e traz os inputs dele, mas fica FORA do total, com contador
    próprio ao lado: misturar os dois apagaria a diferença entre "o escopo cresceu" e
    "chegou trabalho novo depois do congelamento".

    Categoria e espelhamento são eixos INDEPENDENTES — não reunir com
    `sucessores_espelhados()`, que decide o outro eixo.
    """
    return ((set(recorte or ()) & candidatos_extra(vinculos, cascas, novos, deps_novas))
            - set(linha_base or ()) - set(ex_dependencias or ()))


def contaveis(recorte, linha_base):
    """Os EGPs do recorte que CONTAM: a interseção com a linha de base.

    Não confundir com o TOTAL: o total é `total_egps()`, o tamanho da lista inteira. Quem
    saiu do escopo sai daqui (não está mais no recorte) e continua no denominador — é o
    "congelado nos dois lados".

    Também **não é o complemento de `extras()`** desde 29/09/2026: quem está fora da lista
    sem ter vínculo não conta e não é extra. Contagem e rótulo são perguntas diferentes —
    tratá-las como uma só foi o defeito do ticket 19."""
    return set(recorte or ()) & set(linha_base or ())


def total_egps(linha_base):
    """O denominador: o TAMANHO DA LISTA congelada, não uma conta sobre o recorte.

    É o ponto da régua nova. Venha o que vier no corpus — versão nova, casca, dependência
    inédita, dedup, remoção —, este número não se mexe. O que se mexe é o numerador: etapa,
    status, barras dos funis e migrados seguem derivados do estado atual a cada leitura."""
    return len(set(linha_base or ()))


def motivo_extra(projeto, linha_base, vinculos=None, cascas=(), ex_dependencia=False,
                 novos=(), deps_novas=()):
    """Por que este EGP é extra: 'casca' | 'sucessor' | None. O FILTRO tem um valor só
    (`extra`); a distinção fica no detalhe do EGP (§3.1.2).

    `None` NÃO quer dizer "conta no total": quer dizer "não é extra". Quem conta é quem
    está na linha de base — ver `contaveis()`. São duas perguntas, desde 29/09/2026."""
    if projeto in set(linha_base or ()):
        return None
    if ex_dependencia:
        return None       # o badge de ex-dependência já basta (ver `extras`)
    if projeto in set(cascas or ()):
        return MOTIVO_CASCA
    if projeto in sucessores(vinculos):
        return MOTIVO_SUCESSOR
    if projeto in set(novos or ()):
        return MOTIVO_NOVO
    if projeto in set(deps_novas or ()):
        return MOTIVO_DEPENDENCIA
    return None


def tipos_do_extra(projeto, vinculos=None, cascas=(), novos=(), deps_novas=()):
    """POR QUE este EGP é extra, no grão que a gestão pergunta: `["Atualizado"]`,
    `["Unificado"]`, `["casca"]`, `["novo"]`… — ordenado e **sem duplicata**.

    LISTA, não um valor. Um sucessor pode ter vários antecessores com tipos DIFERENTES, e
    isso não é hipótese: em 29/09/2026 o `Project_Fyf_Reneg_BQ_202608 1` é `Atualizado` por
    um antecessor e `Substituído` por outro. Inventar uma categoria "misto" o esconderia de
    quem filtra por qualquer um dos dois; com lista, ele aparece nos dois filtros, que é o
    que a pergunta "me mostra os unificados" quer dizer.

    Mais fino que `motivo_extra`, e de propósito: aquele responde "é extra?" com um rótulo
    só (`sucessor`) e este abre o `sucessor` nos três tipos de vínculo. Os dois convivem —
    quem decide CONTAGEM continua sendo `extras()`.
    """
    tipos = set()
    if projeto in set(cascas or ()):
        tipos.add(MOTIVO_CASCA)
    for v in (vinculos or {}).values():
        if v.get("sucessor") == projeto and v.get("tipo"):
            tipos.add(v["tipo"])
    if projeto in set(novos or ()):
        tipos.add(MOTIVO_NOVO)
    if projeto in set(deps_novas or ()):
        tipos.add(MOTIVO_DEPENDENCIA)
    return sorted(tipos)


def status_exibido(status_real, tipo):
    """Status que a tela mostra. Despriorizado VENCE: é decisão de gestão e não pode ser
    apagada por um fato derivado (§3.2.9)."""
    if status_real == STATUS_DESPRIORIZADO:
        return status_real
    if espelha(tipo):
        return STATUS_DESATUALIZADO
    return status_real


def fim_do_espelho(projeto, vinculos):
    """O ÚLTIMO EGP da cadeia de espelhamento que começa em `projeto` — é dele que sai a
    etapa exibida (§3.2.7). Sem cadeia, devolve o próprio `projeto`.

    O espelho parava no 1º salto: numa cadeia v1 → v2 → v3, o v1 lia a etapa CRUA do v2,
    que é vazia porque o v2 também espelha. Resultado medido em 29/09: 2 EGPs da linha de
    base com etapa real gravada (`Projetos Habilitados`, `Pré-conversão`) exibindo nada e
    caindo fora do coorte do funil e da tabela por mês — trabalho feito sumindo da tela
    por causa de um vínculo. Mesmo defeito de uma passada só que o recorte tinha (ver
    `cadeia_de_sucessores`).

    Para em vínculo que NÃO espelha: `Substituído` encerra a cadeia porque ali o sucessor
    começa do zero, trajetória independente. Ciclo (que o app não deveria permitir) para
    no 1º repetido em vez de travar.
    """
    vinc, visto = vinculos or {}, {projeto}
    atual = projeto
    while True:
        v = vinc.get(atual)
        if not v or not v.get("sucessor") or not espelha(v.get("tipo")):
            return atual
        prox = v["sucessor"]
        if prox in visto:
            return atual
        visto.add(prox)
        atual = prox


def etapa_exibida(etapa_real, tipo, etapa_sucessor):
    """Etapa que a tela mostra: espelho do sucessor quando o tipo espelha (§3.2.7).

    `etapa_sucessor` deve ser a etapa do FIM da cadeia (`fim_do_espelho`), não a do
    sucessor direto — senão a cadeia exibe vazio."""
    return etapa_sucessor if espelha(tipo) else etapa_real


def mapa_exibido(pipe_por_projeto, vinculos_por_antecessor):
    """{projeto: (etapa, status)} REAIS -> {projeto: (etapa, status)} EXIBIDOS.

    Mesma regra de `anexa_vinculo` (as duas chamam `etapa_exibida`/`status_exibido`), só
    que no formato de MAPA: é o que as superfícies que não são o readiness consomem —
    funis do Resumo, drawer do EGP, drawer do input, Gestão, Priorização. Existe para que
    a derivação não fique num lugar só: era isso que fazia a aba EGPs e o Resumo
    discordarem sobre a etapa do mesmo antecessor.

    Ao contrário de `anexa_vinculo`, aqui o mapa é a TABELA INTEIRA, então a etapa do
    sucessor está sempre presente; sucessor sem linha no funil vira None (sem etapa), que
    é o estado honesto.

    A etapa vem do FIM da cadeia de espelhamento (`fim_do_espelho`), não do sucessor
    direto: quando o sucessor também espelha, a etapa crua dele é vazia por construção.
    """
    vincs = vinculos_por_antecessor or {}
    pipe = pipe_por_projeto or {}
    if not vincs:
        return dict(pipe)
    out = {}
    for projeto, par in pipe.items():
        etapa, status = par
        vinc = vincs.get(projeto)
        if not vinc:
            out[projeto] = (etapa, status)
            continue
        fim = fim_do_espelho(projeto, vincs)
        out[projeto] = (etapa_exibida(etapa, vinc["tipo"], (pipe.get(fim) or (None, None))[0]),
                        status_exibido(status, vinc["tipo"]))
    return out


def mapa_contagem(pipe_por_projeto, vinculos_por_antecessor):
    """{projeto: status} para CONTAR terminais (migrados) — irmão de `mapa_exibido`.

    Igual ao exibido em tudo, menos num ponto: o antecessor que ESPELHA não recebe
    `Desatualizado`, e sim o status do FIM da cadeia de espelhamento — o mesmo EGP de onde
    ele já tira a etapa exibida.

    Por que existe: `Desatualizado` é um rótulo de RELAÇÃO ("alguém tomou meu lugar"), não
    uma posição de trabalho, e ele ocupa o mesmo campo que os status terminais. Quem conta
    por status perdia o antecessor cujo sucessor já migrou — ele aparecia DENTRO da coluna
    "Migrado" do gráfico (a etapa já é espelhada) e fora do "X/Y" logo acima dela. Medido
    em prod 05/10/2026: 95/193 onde a coluna Migrado tinha 96 (o
    `Oportunidade Protesto - Piloto de Ajuizamento_GCP`, cujo sucessor
    `Oportunidade Protesto_20260703` está Migrado/Migrado).

    Não é "etapa vira status": a etapa do fim da cadeia continua irrelevante aqui. O que o
    antecessor herda é o STATUS de quem o substituiu, que é a mesma régua do espelho —
    se o sucessor ainda está Em Andamento, o antecessor também não conta.

    `Despriorizado e Contabilizado` do próprio antecessor continua vencendo, como em
    `status_exibido`: é decisão de gestão e não pode ser apagada por um fato derivado.

    Quem NÃO espelha (`Substituído`) fica com o status real: ali as trajetórias são
    independentes por definição, e herdar o terminal do sucessor contaria duas vezes o
    mesmo trabalho.
    """
    vincs = vinculos_por_antecessor or {}
    pipe = pipe_por_projeto or {}
    if not vincs:
        return {p: st for p, (_et, st) in pipe.items()}
    out = {}
    for projeto, (_etapa, status) in pipe.items():
        vinc = vincs.get(projeto)
        if not vinc or status == STATUS_DESPRIORIZADO or not espelha(vinc.get("tipo")):
            out[projeto] = status
            continue
        fim = fim_do_espelho(projeto, vincs)
        out[projeto] = status if fim == projeto else (pipe.get(fim) or (None, None))[1]
    return out


def pode_editar_etapa(tipo):
    """Falso quando a etapa é espelho — o backend recusa a escrita, não só a tela."""
    return not espelha(tipo)


def antecessores_por_sucessor(vinculos_por_antecessor):
    """Inverte o mapa do vínculo: {sucessor: [{"projeto", "tipo"}, ...]}.

    O vínculo é gravado no ANTECESSOR (`egp_sucessor` aponta para frente), então o
    sucessor não sabe quem ele substitui sem esta inversão — e um unificador substitui
    VÁRIOS, por isso lista e não campo. Ordenada por projeto para a tela não trocar a
    ordem entre dois carregamentos do mesmo dado."""
    inv = {}
    for antecessor, v in (vinculos_por_antecessor or {}).items():
        suc = (v or {}).get("sucessor")
        if not suc:
            continue
        inv.setdefault(suc, []).append({"projeto": antecessor, "tipo": (v or {}).get("tipo")})
    for lista in inv.values():
        lista.sort(key=lambda x: x["projeto"])
    return inv


def anexa_vinculo(linhas, vinculos_por_antecessor, cascas=(), *, linha_base, novos=(),
                  etapa_de=None, deps_novas=()):
    """Aplica o vínculo IN-PLACE nas linhas do readiness.

    Escreve em cada linha: vinculo_tipo, sucessor, e_sucessor (eixo do ESPELHAMENTO),
    e_extra/extra_motivo (eixo da CATEGORIA), na_linha_base (eixo da CONTAGEM) e
    etapa_editavel — e SOBRESCREVE etapa/status pelos valores exibidos. É derivação de
    leitura: o banco segue com o status real.

    Os três eixos são independentes e foi confundi-los que produziu o defeito do ticket
    19. `na_linha_base` é o critério de CONTAGEM servido por linha: com ele o front lê a
    mesma lista congelada do card em vez de reaplicar o critério "189" sobre a etapa viva
    (que deriva), e a tabela para de divergir do contador por drift de etapa.

    `linha_base` é keyword-only e OBRIGATÓRIA: sem a lista não há como dizer quem conta,
    e um default vazio deixaria o corpus inteiro fora do total em silêncio.

    `novos` é a 3ª perna da enumeração (EGP declarado novo, §3.1.2) e precisa chegar aqui
    pelo MESMO motivo que `cascas`: esta função é a TELA e `_extras` é o CONTADOR, e a
    última vez que as duas leram conjuntos diferentes a aba dizia 37 extras e o card, 18.

    `etapa_real` guarda a etapa GRAVADA antes da sobrescrita. Ela existe porque o critério
    189 (ex-dependência só conta com etapa real) é DENOMINADOR e o front também o aplica
    (`contaNoTotalEgp`): sem este campo o front contaria pela etapa espelhada enquanto o
    back conta pela gravada, e os dois diriam totais diferentes para o mesmo recorte.

    `etapa_de` ({projeto: etapa GRAVADA} da tabela INTEIRA) é de onde sai a etapa espelhada
    quando o sucessor não está entre `linhas`. Sem ela, o espelho só resolvia dentro do
    recorte carregado: no recorte "só Indicium" as 5 cascas aparecem (nascem com
    `escopo_indi=true`, regra 27) mas o unificador delas não (é sucessor, `escopo_indi=false`),
    e 27 linhas saíam com `etapa=None` — a tela mostrava "— etapa —" enquanto o drawer, que
    carrega o recorte `base`, mostrava `Pré-conversão` (medido 08/10/2026).

    O que o `.get` sem default protegia continua protegido: o fallback NUNCA é a etapa do
    próprio antecessor (exibir a velha como se fosse a nova), e sim a do sucessor lida de
    outro lugar. Sucessor que não existe em lugar nenhum segue virando `None`.
    """
    etapa_por_projeto = {**(etapa_de or {}),
                         **{r.get("projeto"): r.get("etapa") for r in linhas}}
    # Status de CONTAGEM, calculado ANTES da sobrescrita (o loop troca r["status"] pelo
    # exibido). Mesma função que o funil usa — a régua do antecessor espelhado mora num
    # lugar só, senão a tabela por sub-área e o funil discordam na mesma tela.
    contagem_por_projeto = mapa_contagem(
        {r.get("projeto"): (r.get("etapa"), r.get("status")) for r in linhas},
        vinculos_por_antecessor)
    espelhados = sucessores_espelhados(vinculos_por_antecessor)
    antecessores = antecessores_por_sucessor(vinculos_por_antecessor)
    cascas = set(cascas or ())
    lb = set(linha_base or ())
    for r in linhas:
        projeto = r.get("projeto")
        vinc = (vinculos_por_antecessor or {}).get(projeto)
        tipo = vinc["tipo"] if vinc else None
        r["vinculo_tipo"] = tipo
        r["sucessor"] = vinc["sucessor"] if vinc else None
        r["e_sucessor"] = projeto in espelhados
        # Quem este EGP substitui. Vem do mapa, não das linhas: o antecessor pode estar
        # fora do recorte carregado (casca, ou EGP que saiu do escopo) e mesmo assim é
        # ele que explica por que o sucessor está aqui.
        r["antecessores"] = antecessores.get(projeto, [])
        r["na_linha_base"] = projeto in lb
        # a marca de ex-dependência já veio do recorte (`_ex_deps`), e ela VETA o rótulo
        # de extra — as duas coisas não se acumulam na mesma linha.
        motivo = motivo_extra(projeto, linha_base, vinculos_por_antecessor, cascas,
                              bool(r.get("ex_dependencia")), novos=novos,
                              deps_novas=deps_novas)
        r["e_extra"] = motivo is not None
        r["extra_motivo"] = motivo
        # POR QUE é extra, no grão do filtro (ver `tipos_do_extra`). Só na linha que É
        # extra: pôr em todas faria o front ter de checar dois campos p/ a mesma pergunta.
        r["extra_tipos"] = (tipos_do_extra(projeto, vinculos_por_antecessor, cascas, novos,
                                           deps_novas)
                            if motivo else [])
        r["etapa_editavel"] = pode_editar_etapa(tipo)
        r["etapa_real"] = r.get("etapa")
        # Status que vale para CONTAR terminais (ver mapa_contagem). Difere de `status`
        # só no antecessor espelhado: lá `status` diz `Desatualizado` (a relação) e este
        # diz o que o fim da cadeia diz (o trabalho). Sucessor fora do recorte carregado
        # vira None — o mesmo "não sei" que a etapa já exibe, nunca um terminal chutado.
        r["status_contagem"] = contagem_por_projeto.get(projeto, r.get("status"))
        if vinc:
            # .get sem default: sucessor fora do recorte carregado vira None, e a tela
            # mostra "sem etapa" em vez de exibir a etapa VELHA como se fosse a nova.
            r["etapa"] = etapa_exibida(r.get("etapa"), tipo,
                                       etapa_por_projeto.get(
                                           fim_do_espelho(projeto, vinculos_por_antecessor)))
            r["status"] = status_exibido(r.get("status"), tipo)
    return linhas


# Trabalho de gestão que ANDA JUNTO com o vínculo (§3.3.11): no ato do vínculo estes campos
# são COPIADOS do antecessor para o sucessor, uma vez só. Depois disso cada um segue
# sozinho — não é sincronização contínua.
#
# A ETAPA está na lista por causa do funil: sem ela, no instante do vínculo o antecessor
# passa a espelhar a etapa VAZIA de um sucessor recém-chegado ao corpus e cai para "sem
# etapa", sumindo da coluna do funil +deps sem que trabalho nenhum tenha sido desfeito.
#
# STATUS está FORA de propósito: classificar nunca muda status sozinho (§3.5.21). No
# Substituído a tela SUGERE fechar o antecessor e quem clica é a gestão.
CAMPOS_COPIADOS = ("etapa", "mes_prioridade", "jira_id", "responsavel")


def vinculo_criado_agora(tipo_novo, sucessor_novo, tipo_antigo=None, sucessor_antigo=None):
    """A escrita atual deixou um vínculo COMPLETO que antes não estava lá (ou apontava
    para outro sucessor)?

    A cópia é um EVENTO, não uma sincronização: re-salvar a mesma classificação não copia
    de novo, senão um campo que o sucessor apagou de propósito voltaria a cada escrita.
    """
    tipo_novo = (tipo_novo or "").strip()
    sucessor_novo = (sucessor_novo or "").strip()
    if not (tipo_valido(tipo_novo) and sucessor_novo):
        return False
    return (tipo_novo != (tipo_antigo or "").strip()
            or sucessor_novo != (sucessor_antigo or "").strip())


def campos_copiados_no_vinculo(antecessor, sucessor, sucessor_espelha_etapa=False):
    """{campo: valor} a gravar no SUCESSOR no ato do vínculo (§3.3.11).

    Duas recusas, as duas deliberadas:
    - campo que o SUCESSOR já tem fica como está (vincular → desvincular → vincular não
      pode atropelar o trabalho que já andou lá);
    - a etapa sai da cópia quando a etapa do próprio sucessor é espelho de um terceiro
      (cadeia v1 → v2 → v3): ali o servidor recusa a escrita (§3.2.7) e a cópia não fura a
      própria guarda.
    """
    copia = {}
    for campo in CAMPOS_COPIADOS:
        valor = (antecessor or {}).get(campo)
        if valor is None or valor == "":
            continue
        if campo == "etapa" and sucessor_espelha_etapa:
            continue
        atual = (sucessor or {}).get(campo)
        if atual is not None and atual != "":
            continue
        copia[campo] = valor
    return copia


# ---- ticket 23: o que entra no corpus e não aparece em tela --------------------------
# Um EGP pode ser extraído, publicado e ficar invisível em TODAS as telas: `extra` é
# enumeração por vínculo, então quem chega sem vínculo não é extra, não está na linha de
# base e não é dependência de ninguém. Medido em 30/09/2026, isso não é só sumiço: três
# EGPs atualizados sem vínculo produziam tabelas que a linha de base consome, o grafo os
# puxou como DEPENDÊNCIA, e 26 inputs foram parar no card de dependências da gestão
# (88 contra os 61 de prod). Um contador teria mostrado os três no dia em que entraram.


def sem_vinculo(projetos, linha_base, frontier, vinculos_por_antecessor):
    """Projetos do corpus que não aparecem em lugar nenhum: fora da linha de base, fora do
    recorte e sem vínculo em NENHUMA das duas direções.

    As duas direções importam. Sem antecessor (`projeto not in vinculos`) ele não é a ponta
    que saiu; sem ninguém apontando para ele (`projeto not in sucessores`) ele não é a ponta
    que entrou. Basta uma das duas existir para o EGP ter porta em alguma tela, e aí ele
    não é caso desta lista."""
    lb = set(linha_base or ())
    fr = set(frontier or ())
    vinc = vinculos_por_antecessor or {}
    sucs = {v.get("sucessor") for v in vinc.values() if (v or {}).get("sucessor")}
    return sorted(
        p for p in {(p or "").strip() for p in (projetos or ())} - {""}
        if p not in lb and p not in fr and p not in vinc and p not in sucs)


def vinculos_orfaos(vinculos_por_antecessor, frontier, em_tela=None):
    """Vínculos cujo ANTECESSOR está fora do recorte — o vínculo existe e não faz nada.

    O antecessor fora do recorte não exibe `Desatualizado`, não espelha etapa e não puxa o
    sucessor para dentro: a declaração da gestão fica gravada e inerte, em silêncio. Medido
    em 30/09/2026: `Project_Fyf_Reneg_v2 → Project_Fyf_Reneg_BQ_202608 1`. O sucessor
    aparecia assim mesmo, mas por causa de OUTRO antecessor (`PROJECT_ROLAGEM_NEW`), o que
    esconde o problema em vez de resolvê-lo — por isso a regra olha o antecessor.

    `em_tela` é o recorte que a aba EGPs de fato lista (frontier ∪ ex-dependências ∪ linha
    de base). Com ele cada órfão ganha `sucessor_em_tela`, que separa dois casos que
    estavam sendo gritados com a mesma força:

    - **inerte** (`True`): o vínculo não age, mas o sucessor aparece por outro caminho —
      outro antecessor dentro do recorte, ou badge de ex-dependência. Informativo;
    - **invisível** (`False`): nem antecessor nem sucessor aparecem. O EGP foi publicado e
      não existe em tela nenhuma, e este alerta é a ÚNICA coisa que o menciona (a lista
      "sem vínculo" não o pega, justamente porque ele TEM vínculo).

    Medido em 01/10/2026: dos 4 órfãos, 3 eram inertes — dois por ex-dependência (um deles
    criado por decisão explícita da gestão) e um por antecessor duplicado. Gritar nos 4
    enterrava o único que pedia ação (`Import_Excecoes__ATU20260930`)."""
    fr = set(frontier or ())
    tela = set(em_tela) if em_tela is not None else None
    linhas = []
    for a, v in (vinculos_por_antecessor or {}).items():
        suc = (v or {}).get("sucessor")
        if not suc or a in fr:
            continue
        r = {"antecessor": a, "sucessor": suc, "tipo": (v or {}).get("tipo")}
        # None (e não True) quando o chamador não informou o recorte: dizer "está em tela"
        # sem ter olhado esconderia justamente o caso grave.
        r["sucessor_em_tela"] = (suc in tela) if tela is not None else None
        linhas.append(r)
    return sorted(linhas, key=lambda r: (r["antecessor"], r["sucessor"] or ""))
