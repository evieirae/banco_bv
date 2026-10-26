# -*- coding: utf-8 -*-
"""Sanitização DERIVADA de input: a fila de ingestão para de pedir o que ninguém vivo lê.

Sem DB e sem FastAPI, no padrão de vinculos.py / priorizacao_logic.py: o main.py só faz a
query e injeta os dados. As regras vivem em
app/docs/superpowers/specs/2026-09-24-egps-atualizados-unificacao-design.md §3.4.

A régua é UMA (§3.4.17, decisão da gestão de 28/09/2026): a chave sai da fila quando
TODOS os consumidores dela no recorte ativo estão resolvidos, somando as duas origens —

- §3.4.18 — EGP despriorizado;
- §3.4.15 — antecessor de um vínculo: o que vale depois do vínculo é o inventário da
  versão NOVA.

— e o MOTIVO diz qual das duas (ou a mistura) tirou a chave da fila. O SUCESSOR não
está em nenhum dos conjuntos: é consumidor vivo e segura o input sozinho.

Tudo é DERIVADO. Nada de status gravado: o status real fica intacto no banco (e é
devolvido na linha como `status_real`), então repriorizar um EGP devolve os inputs dele à
fila sozinho, sem ninguém rodar nada — mesma invariante do vínculo (§3.2.6).
"""

STATUS_SANITIZADO = "Sanitizado"
# Etapa EXIBIDA do input sanitizado por derivação (decisão da gestão, 14/10/2026): ele
# aparece como Modernizado + Sanitizado. Com a etapa gravada à vista ("A Receber"), o time
# lia pendência e marcava Modernizado à mão — o que tirava o input da derivação (ela só
# vale para chave pendente) e o fazia contar como modernizado, com o status cru do publish.
ETAPA_SANITIZADO = "Modernizado"

# O MOTIVO é campo, não string fixa: §3.4.18 (só despriorizados) e §3.4.15 (só o
# antecessor de um vínculo) são regras IRMÃS, entram pelo MESMO caminho e se distinguem
# só aqui — quem lê a linha sabe qual das duas a tirou da fila.
MOTIVO_SO_DESPRIORIZADOS = "so_despriorizados"
MOTIVO_SO_ANTECESSOR = "so_antecessor"
# §3.4.17 (28/09/2026): as duas origens se SOMAM, então existe um terceiro caso — a
# chave cujos consumidores misturam os dois. Ele tem motivo PRÓPRIO de propósito:
# rotulá-lo como uma das origens esconderia a outra do analista que abre a linha.
MOTIVO_MISTO = "so_resolvidos"

MOTIVO_LABEL = {
    MOTIVO_SO_DESPRIORIZADOS: "só consumidores despriorizados",
    MOTIVO_SO_ANTECESSOR: "só o antecessor, que tem sucessor",
    MOTIVO_MISTO: "só consumidores despriorizados e antecessores",
}

# §3.4.26: o input sintético da casca (`casco::<projeto>`) é placeholder para o EGP casca
# aparecer na aba EGPs, não input de verdade. Aplicar a régua de exclusividade sobre ele
# seria agir sobre o vazio.
PREFIXO_CASCA = "casco::"


def e_casca(chave):
    """Chave do input sintético de um EGP casca (§3.4.26)."""
    return str(chave or "").startswith(PREFIXO_CASCA)


def motivos_derivados(consumidores_por_chave, despriorizados, antecessores, pendentes):
    """As duas origens numa régua só — é este dicionário que alimenta os contadores.

    **§3.4.17, decisão da gestão de 28/09/2026: as origens se SOMAM.** A chave sai da
    fila quando TODOS os consumidores dela no recorte ativo estão resolvidos — seja por
    despriorização (§3.4.18), seja por serem antecessores com sucessor (§3.4.15) —,
    inclusive MISTURANDO as duas. A régua é uma só: *input que só quem não vai trabalhar
    lê não é trabalho*. Aplicá-las separadamente (o desenho até 28/09) deixava na fila a
    chave lida por um despriorizado E um antecessor: cada régua sozinha recusava, porque
    nenhuma via "todos os seus consumidores" dentro do próprio conjunto.

    **A trava:** o SUCESSOR não entra em conjunto nenhum. Ele está no recorte e não é
    antecessor, logo conta como consumidor VIVO — se a versão nova também lê a chave,
    ela continua na fila por mais resolvidos que estejam os demais. É o que impede a
    régua de sanitizar justamente o inventário que passou a valer.

    O MOTIVO sai da composição do conjunto de consumidores, e não do que a régua fez:

    - todos despriorizados                       -> `so_despriorizados`
    - todos antecessores                         -> `so_antecessor`
    - mistura das duas                           -> `so_resolvidos` (nomeia as duas)

    Precedência no empate (consumidor que é despriorizado E antecessor ao mesmo tempo):
    **despriorizado vence**, a mesma do §3.2.9 no EGP ("continua despriorizado, e o
    vínculo vira badge"). Como o teste é por SUBCONJUNTO, o empate cai naturalmente no
    primeiro ramo — não é caso especial.
    """
    desp = {p for p in (despriorizados or ()) if p}
    ante = {p for p in (antecessores or ()) if p}
    pend = set(pendentes or ())
    out = {}
    for chave, projetos in (consumidores_por_chave or {}).items():
        if not chave or e_casca(chave) or chave not in pend:
            continue
        cons = {p for p in (projetos or ()) if p}
        if not cons or not cons <= (desp | ante):
            continue
        if cons <= desp:
            out[chave] = MOTIVO_SO_DESPRIORIZADOS
        elif cons <= ante:
            out[chave] = MOTIVO_SO_ANTECESSOR
        else:
            out[chave] = MOTIVO_MISTO
    return out


def fragilidade(motivos, consumidores_fora_escopo):
    """Quanto da fila está fora dela SÓ porque parte do corpus está fora do escopo.

    A exclusividade é medida contra o ESCOPO ATIVO, não contra o corpus (§3.4.16) — uma
    decisão consciente da gestão, ciente de que chaves voltam sozinhas. Esta função põe
    o preço dessa decisão na tela: `consumidores_fora_escopo` é {chave: projetos do
    corpus que consomem a chave e NÃO estão no recorte ativo}; se qualquer um deles
    entrar no escopo, ele vira consumidor vivo e a chave volta à fila.

    Devolve os dois lados da conta:
      - `n_chaves`/`chaves` — quantas (e quais) estão fora da fila por essa razão;
      - `por_egp` — o rollup INVERSO (EGP fora -> chaves que voltariam), ordenado do
        maior para o menor, que é a pergunta acionável: "quem é o EGP que, se entrar,
        me devolve 40 chaves". Cada entrada leva as chaves, não só o número.

    Nada aqui altera a régua: é leitura sobre o resultado dela.
    """
    motivos = motivos or {}
    chaves, por_egp = [], {}
    for chave, projetos in (consumidores_fora_escopo or {}).items():
        if not chave or e_casca(chave) or chave not in motivos:
            continue
        fora = sorted({p for p in (projetos or ()) if p})
        if not fora:
            continue
        chaves.append(chave)
        for pj in fora:
            por_egp.setdefault(pj, []).append(chave)
    return {
        "n_chaves": len(chaves),
        "n_egps": len(por_egp),
        "chaves": sorted(chaves),
        "por_egp": [{"projeto": pj, "n_chaves": len(cs), "chaves": sorted(cs)}
                    for pj, cs in sorted(por_egp.items(),
                                         key=lambda kv: (-len(kv[1]), kv[0]))],
    }


def contadores(motivos, n_frageis, data):
    """A linha do log diário: SÓ contador, NUNCA o estado derivado.

    O log é o passado (histórico não se reconstrói); o presente é sempre recalculado.
    Se uma chave vazasse para cá, o log viraria fonte de verdade em algum caminho e a
    reversibilidade morreria — e a reversibilidade é a razão de o desenho inteiro ser
    derivado. Por isso só saem inteiros e a data.
    """
    vals = list((motivos or {}).values())
    return {
        "data": data,
        "total": len(vals),
        "n_frageis": int(n_frageis or 0),
        MOTIVO_SO_DESPRIORIZADOS: vals.count(MOTIVO_SO_DESPRIORIZADOS),
        MOTIVO_SO_ANTECESSOR: vals.count(MOTIVO_SO_ANTECESSOR),
        MOTIVO_MISTO: vals.count(MOTIVO_MISTO),
    }


def aplica_em_linhas(rows, motivos):
    """Aplica o overlay IN-PLACE nas linhas de input servidas pela API.

    Escreve `sanitizado_derivado` (o motivo, em código), `sanitizado_motivo` (o rótulo
    legível), `status_real` e `etapa_real` (o que está gravado no banco), e SOBRESCREVE
    `status` por 'Sanitizado' e `etapa` por 'Modernizado' (ETAPA_SANITIZADO). É derivação
    de leitura, igual a `vinculos.anexa_vinculo`: o banco segue com o real e a linha
    continua visível na aba — e volta ao real sozinha quando a condição deixa de valer.

    A etapa exibida não muda contagem: Sanitizado já resolvia o input em toda régua
    (`py_modern`/`py_aingerir`/`py_sanitizado`) e sai do coorte do funil antes de a etapa
    ser lida. Até 13/10/2026 a etapa ficava intocada ("posição no funil é fato do input");
    a gestão trocou porque a etapa crua à vista induzia a marcação manual (ETAPA_SANITIZADO).

    Linha fora de `motivos` não ganha campo nenhum — quem lê distingue "não se aplica" de
    "derivado e falso" pela ausência.
    """
    for r in rows or []:
        motivo = (motivos or {}).get(r.get("chave_canonica"))
        if not motivo:
            continue
        r["sanitizado_derivado"] = motivo
        r["sanitizado_motivo"] = MOTIVO_LABEL.get(motivo, motivo)
        r.setdefault("status_real", r.get("status"))
        r.setdefault("etapa_real", r.get("etapa"))
        r["status"] = STATUS_SANITIZADO
        r["etapa"] = ETAPA_SANITIZADO
    return rows
