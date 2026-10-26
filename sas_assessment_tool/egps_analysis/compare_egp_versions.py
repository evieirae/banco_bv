#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
compare_egp_versions.py — compara um .egp ATUALIZADO com a versão que já está no corpus
e produz o par de scores (Valor x Esforço) que decide se vale a pena trocar.

Rode da pasta egps_analysis/:

    python compare_egp_versions.py --novo "/mnt/c/.../EGP Atualizado"
    python compare_egp_versions.py --novo novo.egp --antigo "Cobranças/PERFORMANCE_CL_202603.egp"

O que este script FAZ (determinístico, sem LLM):
  1. Pareia o .egp novo com o antecessor no corpus (nome igual ou overlap de hash das
     tasks de código), em 3 faixas de confiança.
  2. Re-extrai OS DOIS LADOS com o extrator atual e compara o inventário de I/O.
  3. Calcula Valor (0-100), Esforço (0-100), a razão, o quadrante e os vetos/alertas.

O que este script NÃO faz: julgar se o código "está mais limpo". Isso é da skill
`analise-egp-atualizado`, que é obrigada a citar os números daqui como evidência.

Por que re-extrair os dois lados em vez de reusar text_egps/*.txt:
  o extrator mudou muito (descompacta, .sas7bdat como tabela, regra do criador,
  pass-through BQ). Comparar .txt de versões diferentes do extrator mede mudança de
  FERRAMENTA, não de EGP. Re-extração simétrica é a única leitura honesta do delta.

Fontes de verdade reusadas (não reimplementadas):
  egps_extractor.extract_code_from_egp   — extração
  orchestrator_inventory.parse_txt_metadata / load_chameleon_data /
  load_modernization_override            — inventário e modernização
  01_prioridade_ingestao.csv             — consumidores de output / alcance
  03_matriz_dependencias.csv             — dependências EGP->EGP
  snapshot de sas_egp_pipeline           — etapa/status do antigo (para o veto)

Contrato de decisão acordado (grilling 2026-09-01) — não mude sem reler:
  - redução entra em VALOR, adição entra em ESFORÇO, nunca nos dois;
  - eixos relativos com piso absoluto (delta < 2 inputs ou < 200 linhas = ruído = 0);
  - cortes de quadrante fixos em 50/50 (recalibrar quebra comparação entre rodadas);
  - veto != alerta: veto é decisão técnica, alerta pede confirmação humana.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
import unicodedata
import zipfile
from collections import defaultdict
from datetime import datetime, timezone

# ---------------------------------------------------------------------------
# Configuração (pesos e cortes acordados; mexer aqui é mexer na política)
# ---------------------------------------------------------------------------

PESOS_VALOR = {
    'menos_table_in_a_ingerir': 30,
    'menos_file_in':            25,
    'mais_input_disponivel':    20,
    'alcance':                  15,
    'simplificacao':             5,
    'menos_script_in':           5,
}

PESOS_ESFORCO = {
    'churn_codigo':             40,
    'inputs_novos_a_ingerir':   30,
    'outputs_novos_renomeados': 15,
    'deps_novas_egp':           15,
}

# Piso absoluto: abaixo disso o eixo é ruído e vale 0 (Q13 = relativo com piso).
PISO_INPUTS = 2
PISO_LINHAS = 200

# Faixas de confiança do pareamento por overlap de tasks de código (Q23).
CONF_REJEITA = 0.40   # abaixo: par recusado, exige --antigo explícito
CONF_ALERTA  = 0.70   # entre: par aceito com alerta

# Um EGP novo pode substituir MAIS DE UM antigo. Confirmado por escrito pelo BV em
# 26/08/2026: "Precisaremos substituir os EGPs PROJECT_ATIVA_GCP_V2 e
# PROJECT_ATIVA_TABLEAU_NEW_V2_4_vigente, pelo EGP PROJECT_ATIVA_TABLEAU_NEW_RPA".
# Qualquer outro EGP do corpus com overlap >= este corte entra como co-antecessor, e
# o lado "antigo" passa a ser a UNIÃO dos inventários.
# Calibrado contra fato conhecido, não contra palpite: no par que o BV confirmou por
# escrito (RPA substitui _V2_4_vigente E PROJECT_ATIVA_GCP_V2) o co-antecessor
# verdadeiro tem Jaccard 0,681; o candidato mais próximo que a Michelli NÃO citou
# (PROJECT_MASSIFICADOS_202507_RPA) tem 0,516. 0,60 separa os dois com folga.
CONF_COANTECESSOR = 0.60
# Consolidação real é de 2 ou 3 EGPs. Se aparecerem mais que isto, é irmandade de
# boilerplate, não consolidação: ignora os extras e emite alerta.
MAX_COANTECESSORES = 3

# Corte dos quadrantes (Q16: fixo, NÃO recalibrar por rodada).
# Ajuste único documentado — 2026-09-01: a 1ª rodada real (30 EGPs da pasta
# "EGP Atualizado") teve Valor máximo 44,1 e mediana ~1, então 50/50 jogou tudo em
# "Trocar depois"/veto e não separou nada. Rebaixado para 20/20, que separa a
# população observada. Se rebaixar de novo, registre aqui a data e o motivo — score
# que se recalibra a cada entrega não serve para comparar rodadas.
CORTE_VALOR   = 20
CORTE_ESFORCO = 20

# Alcance: nº de dependentes que já satura o eixo em 1.0.
ALCANCE_CAP = 20

# Etapas do funil de migração, em ordem. Cópia de app/backend/main.py:PIPELINE_PROJETO
# ["migracao"] (fonte de verdade — é o que grava etapa_migracao no snapshot), que por
# sua vez espelha app/frontend/src/pipeline.ts. As 3 cópias já divergiram uma vez em
# silêncio (idx virava -1 p/ "Aprv. PR + Validação Governança"/"Aplicação de Grant" e
# o veto de etapa era pulado sem aviso para EGP já convertido) — ao mexer em qualquer
# uma, mexa nas 3 juntas.
ETAPAS_MIGRACAO = [
    "Projetos Habilitados", "Pré-Working + Outputs", "Conversão do Código",
    "Validação em DES", "Aprv. PR + Validação Governança", "Implant. em PRD",
    "Aplicação de Grant", "Validação da Área", "Migrado",
]
ETAPA_FANTASMA = "Pré-conversão"
# Etapas fora do funil (PHANTOM_ETAPAS_MIGRACAO em main.py): não entram no índice acima
# por desenho, então idx=-1 para elas é esperado, não drift.
ETAPAS_FANTASMA_CONHECIDAS = {"Pré-conversão", "Conversão pela Área"}
# Veto começa aqui (Q21): "Conversão do Código" e tudo depois.
IDX_VETO_ETAPA = ETAPAS_MIGRACAO.index("Conversão do Código")
STATUS_QUE_VETAM = {"Em Andamento", "Concluído", "Migrado"}

SNAPSHOT_VALIDADE_DIAS = 7

# Saída consolidada do estudo. Rodada nova deve usar uma pasta própria com a sua data
# (--out/--md-dir) em vez de sobrescrever esta: os cortes de quadrante são fixos para as
# rodadas serem comparáveis entre si.
PASTA_ESTUDO = 'docs/analises/versoes_atualizadas_egp_2026-09'

CODE_SUFFIX = ('code.sas', 'query.sql')
# Script solto enviado pelo cliente (não é .egp): sem tasks e sem project.xml, entra
# como código único. Não tem par no corpus (que só tem .egp), então cai sempre em
# 'EGP inédito' — e aí o publish exige --area, porque não há antecessor de quem herdar.
SCRIPT_SUFFIX = ('.sas', '.sql', '.txt')

# ---------------------------------------------------------------------------
# Utilidades
# ---------------------------------------------------------------------------

def canon(s: str) -> str:
    """Chave de comparação: sem acento, sem aspas/backtick, upper, sem espaço nas bordas."""
    if s is None:
        return ""
    s = unicodedata.normalize('NFKD', str(s)).encode('ascii', 'ignore').decode()
    s = s.replace('`', '').replace('"', '').replace("'", '').strip()
    return re.sub(r'\s+', ' ', s).upper()


def rel_reducao(antigo: int, novo: int, piso: int) -> float:
    """Redução relativa 0..1 com piso absoluto. Aumento devolve 0 (vai para Esforço)."""
    delta = antigo - novo
    if delta < piso:
        return 0.0
    if antigo <= 0:
        return 0.0
    return min(1.0, delta / antigo)


def rel_aumento(antigo: int, novo: int, piso: int) -> float:
    """Aumento relativo 0..1 com piso absoluto, normalizado pela base antiga."""
    delta = novo - antigo
    if delta < piso:
        return 0.0
    base = antigo if antigo > 0 else delta
    return min(1.0, delta / base)


def eprint(*a):
    print(*a, file=sys.stderr)


def eh_script(path: str) -> bool:
    """Script solto (.sas/.sql/.txt) em vez de .egp — ver SCRIPT_SUFFIX."""
    return path.lower().endswith(SCRIPT_SUFFIX)


# ---------------------------------------------------------------------------
# Fingerprint das tasks de código dentro do .egp
# ---------------------------------------------------------------------------

def fingerprint_egp(path: str) -> dict:
    """Hashes das tasks de código + LOC. Dedup pelas 2 últimas componentes do caminho
    interno, porque o .egp guarda uma cópia espelhada sob <hash>/PFD-<id>/."""
    out = {'path': path, 'ok': True, 'codes': {}, 'loc': 0, 'n_code': 0}
    if eh_script(path):
        try:
            with open(path, 'rb') as f:
                raw = f.read()
        except OSError as e:
            out['ok'] = False
            out['err'] = str(e)
            return out
        out['codes'][os.path.basename(path)] = hashlib.md5(raw).hexdigest()
        out['loc'] = raw.decode('latin-1').count('\n') + 1
        out['n_code'] = 1
        return out
    try:
        z = zipfile.ZipFile(path)
    except Exception as e:
        out['ok'] = False
        out['err'] = str(e)
        return out
    with z:
        for info in z.infolist():
            if info.is_dir() or not info.filename.lower().endswith(CODE_SUFFIX):
                continue
            ident = '/'.join(info.filename.split('/')[-2:])
            if ident in out['codes']:
                continue
            try:
                raw = z.read(info)
            except Exception:
                continue
            out['codes'][ident] = hashlib.md5(raw).hexdigest()
            out['loc'] += raw.decode('latin-1').count('\n') + 1
    out['n_code'] = len(out['codes'])
    return out


def carrega_fingerprints_corpus(corpus_dir: str, cache_path: str) -> list:
    """Fingerprint de todos os .egp do corpus, com cache invalidado por (tamanho, mtime)."""
    alvos = []
    for raiz, _, arquivos in os.walk(corpus_dir):
        for nome in arquivos:
            if nome.lower().endswith('.egp'):
                p = os.path.join(raiz, nome)
                st = os.stat(p)
                alvos.append((p, st.st_size, int(st.st_mtime)))

    cache = {}
    if os.path.exists(cache_path):
        try:
            with open(cache_path, encoding='utf-8') as f:
                cache = json.load(f)
        except Exception:
            cache = {}

    res, novos = [], 0
    for p, size, mtime in alvos:
        chave = f"{p}|{size}|{mtime}"
        if chave in cache:
            res.append(cache[chave])
            continue
        fp = fingerprint_egp(p)
        # NÃO cacheia falha: a chave é (path, tamanho, mtime), então um erro transitório
        # (arquivo travado, mount de rede/WSL fora do ar) ficaria colado até o mtime
        # mudar — e um .egp do corpus marcado ok=False é excluído dos elegíveis em
        # parear(), fazendo o EGP novo ser classificado "inédito" quando na verdade o
        # antecessor existe e só não pôde ser lido.
        if fp.get('ok'):
            cache[chave] = fp
        res.append(fp)
        novos += 1

    if novos:
        os.makedirs(os.path.dirname(cache_path) or '.', exist_ok=True)
        with open(cache_path, 'w', encoding='utf-8') as f:
            json.dump(cache, f)
    ilegiveis = [r for r in res if not r.get('ok')]
    print(f"  corpus: {len(res)} .egp fingerprintados ({novos} novos, resto do cache)")
    if ilegiveis:
        # Descarte visível: cada um destes some de `elegiveis` em parear(), então um
        # EGP novo pode sair como "inédito" só porque o antecessor não abriu.
        eprint(f"  !! {len(ilegiveis)}/{len(res)} .egp do corpus ILEGÍVEIS "
               f"(ficam fora do pareamento):")
        for r in ilegiveis[:8]:
            eprint(f"     - {os.path.basename(r['path'])}: {r.get('err')}")
        if len(ilegiveis) > 8:
            eprint(f"     ... e mais {len(ilegiveis) - 8}")
    return res


def parear(fp_novo: dict, corpus: list, forcado: str | None) -> dict:
    """Acha o(s) antecessor(es). Devolve {antigos: [primário, ...], overlap, confianca,
    motivo}. `antigos` pode ter mais de um item: um EGP novo pode consolidar vários."""
    proprio = os.path.normpath(fp_novo['path'])
    elegiveis = [c for c in corpus
                 if c.get('ok') and os.path.normpath(c['path']) != proprio]

    def co_antecessores(primario):
        """Outros EGPs do corpus que o mesmo EGP novo também substitui.
        Devolve (lista, demais_ignorados) — Jaccard, não overlap assimétrico."""
        outros = []
        for c in elegiveis:
            if c['path'] == primario['path']:
                continue
            ov = overlap_simetrico(fp_novo, c)
            if ov >= CONF_COANTECESSOR:
                outros.append((ov, c))
        outros.sort(key=lambda t: -t[0])
        if len(outros) > MAX_COANTECESSORES:
            return [], len(outros)
        return [c for _, c in outros], 0

    if forcado:
        pedidos = [x.strip() for x in forcado.split(',') if x.strip()]
        achados, faltando = [], []
        for pedido in pedidos:
            hit = next((c for c in elegiveis
                        if os.path.normpath(c['path']).endswith(os.path.normpath(pedido))),
                       None)
            (achados.append(hit) if hit else faltando.append(pedido))
        if faltando:
            return {'antigos': [], 'overlap': 0.0, 'confianca': 'erro',
                    'motivo': f'--antigo não encontrado no corpus: {", ".join(faltando)}'}
        return {'antigos': achados, 'overlap': overlap(fp_novo, achados[0]),
                'confianca': 'manual',
                'motivo': f'{len(achados)} antecessor(es) informado(s) via --antigo'}

    base_novo = canon(os.path.basename(fp_novo['path']))
    por_nome = [c for c in elegiveis if canon(os.path.basename(c['path'])) == base_novo]
    if por_nome:
        primario = por_nome[0]
        extras, ignorados = co_antecessores(primario)
        motivo = 'mesmo nome de arquivo no corpus'
        if extras:
            motivo += (f' (+{len(extras)} co-antecessor(es) com Jaccard >= '
                       f'{CONF_COANTECESSOR:.0%})')
        if ignorados:
            motivo += (f' ({ignorados} candidatos a co-antecessor ignorados: acima de '
                       f'{MAX_COANTECESSORES} é irmandade de boilerplate, não consolidação)')
        return {'antigos': [primario] + extras, 'overlap': overlap(fp_novo, primario),
                'confianca': 'nome_igual', 'motivo': motivo}

    ranking = sorted(((overlap(fp_novo, c), c) for c in elegiveis), key=lambda t: -t[0])
    if not ranking or ranking[0][0] <= 0:
        return {'antigos': [], 'overlap': 0.0, 'confianca': 'sem_par',
                'motivo': 'nenhuma task de código em comum com o corpus: EGP inédito'}

    ov, primario = ranking[0]
    if ov < CONF_REJEITA:
        return {'antigos': [primario], 'overlap': ov, 'confianca': 'recusado',
                'motivo': f'overlap {ov:.0%} < {CONF_REJEITA:.0%}: provável biblioteca '
                          f'compartilhada, não substituição. Informe --antigo se for par real.'}

    extras, ignorados = co_antecessores(primario)
    conf = 'alerta' if ov < CONF_ALERTA else 'ok'
    motivo = f'overlap de {ov:.0%} das tasks de código'
    if extras:
        nomes = ', '.join(os.path.basename(c['path']) for c in extras[:3])
        motivo += f'; substitui também {len(extras)}: {nomes}'
    if ignorados:
        motivo += (f'; {ignorados} candidatos a co-antecessor ignorados (acima de '
                   f'{MAX_COANTECESSORES} é irmandade de boilerplate)')
    return {'antigos': [primario] + extras, 'overlap': ov, 'confianca': conf,
            'motivo': motivo}


def overlap(a: dict, b: dict) -> float:
    """Fração das tasks de código do NOVO que existem idênticas no antigo.

    ASSIMÉTRICO de propósito: é a medida do antecessor primário, e foi validada contra o
    email do BV de 26/08 (PROJECT_ATIVA_TABLEAU_NEW_RPA vs _V2_4_vigente = 54/60 = 90%).
    NÃO use para achar co-antecessor — ver overlap_simetrico()."""
    ha = set(a.get('codes', {}).values())
    hb = set(b.get('codes', {}).values())
    if not ha:
        return 0.0
    return len(ha & hb) / len(ha)


def overlap_simetrico(a: dict, b: dict) -> float:
    """Jaccard das tasks de código. Usado para co-antecessor.

    Por que não o assimétrico: um EGP antigo GRANDE que contenha todo o boilerplate de um
    EGP novo pequeno marca 100% no assimétrico. Na 1ª tentativa isso deu 14
    "co-antecessores" para o Atualiza_UF_Cartoes, que é byte-idêntico ao seu único par.
    Jaccard pune a diferença de tamanho e separa consolidação real de irmandade."""
    ha = set(a.get('codes', {}).values())
    hb = set(b.get('codes', {}).values())
    uniao = ha | hb
    if not uniao:
        return 0.0
    return len(ha & hb) / len(uniao)


# ---------------------------------------------------------------------------
# Extração simétrica + leitura do inventário
# ---------------------------------------------------------------------------

def extrai_inventario(egp_path: str, area: str, scratch: str) -> dict | None:
    """Extrai UM .egp para um dir isolado e devolve o dict de parse_txt_metadata.
    Isolado por chamada para o glob do .txt gerado ser inequívoco."""
    import egps_extractor
    import orchestrator_inventory

    destino = os.path.join(scratch, hashlib.md5(egp_path.encode()).hexdigest()[:12])
    os.makedirs(destino, exist_ok=True)
    try:
        if eh_script(egp_path):
            egps_extractor.extract_code_from_sas(egp_path, destino, business_area=area)
        else:
            egps_extractor.extract_code_from_egp(egp_path, destino, business_area=area)
    except Exception as e:
        eprint(f"  !! falha ao extrair {os.path.basename(egp_path)}: {e}")
        return None

    txts = [os.path.join(destino, f) for f in os.listdir(destino) if f.lower().endswith('.txt')]
    if not txts:
        eprint(f"  !! extrator não gerou .txt para {os.path.basename(egp_path)}")
        return None
    # Um .egp pode virar vários .txt (um por fluxo); consolida todos.
    partes = [orchestrator_inventory.parse_txt_metadata(t) for t in txts]
    for parte in partes:
        reclassifica_sas7bdat_sob_libname(parte)
    return consolida_partes(partes)


def reclassifica_sas7bdat_sob_libname(parte: dict) -> None:
    """Move .sas7bdat lido via caminho de LIBNAME de files_read para inputs, em
    lugar (mesma regra de orchestrator_inventory.main() — ver
    orchestrator_inventory._sas7bdat_as_libname_table). Precisa rodar por PARTE
    (antes de consolida_partes), porque libname_dict não sobrevive à consolidação.

    Sem isto, extrai_inventario chamava parse_txt_metadata cru e classificava esse
    input como 'arquivo' (file_in) aqui, enquanto o pipeline principal
    (orchestrator_inventory.main()) classifica a MESMA leitura física como 'tabela'
    (table_in) — os dois lados divergiam para o mesmo .sas7bdat, e a comparação de
    EGPs Atualizados nunca checava modernização para ele."""
    import orchestrator_inventory as oi
    libname_dict = parte.get('libname_dict') or {}
    files_read = parte.get('files_read') or []
    if not libname_dict or not files_read:
        return
    inputs = parte.setdefault('inputs', [])
    vistos = {canon(inp.get('table', '')) for inp in inputs}
    prefer_libs = {k.split('.', 1)[0] for k in vistos if '.' in k}
    restantes = []
    for item in files_read:
        tabela = oi._sas7bdat_as_libname_table(item, libname_dict, prefer_libs)
        if tabela:
            if canon(tabela) not in vistos:
                vistos.add(canon(tabela))
                inputs.append({'table': tabela, 'source': oi._SAS7BDAT_SRC_LABEL})
            continue
        restantes.append(item)
    parte['files_read'] = restantes


def consolida_partes(partes: list) -> dict:
    """Une os .txt de um mesmo .egp num inventário só."""
    base = {
        'project': partes[0].get('project', ''),
        'business_area': partes[0].get('business_area', ''),
        'inputs': [], 'outputs': [], 'files_read': [], 'included_scripts': [],
        'exports': [], 'libnames': [], 'non_creator': [],
    }
    vistos = defaultdict(set)
    for p in partes:
        for inp in p.get('inputs', []):
            k = canon(inp.get('table', ''))
            if k and k not in vistos['inputs']:
                vistos['inputs'].add(k)
                base['inputs'].append(inp)
        for campo in ('outputs', 'files_read', 'included_scripts', 'exports',
                      'libnames', 'non_creator'):
            for v in p.get(campo, []):
                k = canon(v if isinstance(v, str) else str(v))
                if k and k not in vistos[campo]:
                    vistos[campo].add(k)
                    base[campo].append(v)
    return base


# ---------------------------------------------------------------------------
# Modernização: o input já está disponível no destino?
# ---------------------------------------------------------------------------

def _indexa_chameleon(records: list) -> dict:
    """Índice que reproduz `orchestrator_inventory.is_strict_match` sem varrer os
    ~5.800 records a cada input. As 3 regras do matcher viram busca por chave:

      1. igualdade exata            -> set `exato`
      2. cham_val termina em '.'+art -> `por_sufixo[art]` existe
      3. art = 'prefixo.tabela', com prefixo como SUBSTRING de cham_val e cham_val
         terminando em '.tabela'     -> candidatos = `por_sufixo[tabela]`, aí sim
                                        testa a substring (lista curta)

    Só a regra 3 mantém varredura, e sobre o punhado de valores que já terminam no
    sufixo certo. Antes eram 8.672 artefatos × 5.772 records × 2 campos ≈ 100M
    comparações de string (29,6 s medidos no corpus real)."""
    exato = set()
    por_sufixo = defaultdict(list)
    for rec in records:
        for campo in ('NmTabelaDestino', 'NmTabelaOrigem'):
            val = (rec.get(campo) or '').strip()
            if not val:
                continue
            exato.add(val)
            partes = val.split('.')
            for i in range(1, len(partes)):
                por_sufixo['.'.join(partes[i:])].append(val)
    return {'exato': exato, 'por_sufixo': dict(por_sufixo)}


def _casa_chameleon(art_clean: str, idx: dict) -> bool:
    """Equivalente a any(is_strict_match(art_clean, v) for v in valores), via índice."""
    if not art_clean:
        return False
    if art_clean in idx['exato']:
        return True
    if art_clean in idx['por_sufixo']:
        return True
    if '.' in art_clean:
        prefixo, tabela = art_clean.split('.', 1)
        for val in idx['por_sufixo'].get(tabela, ()):
            if prefixo in val:
                return True
    return False


def _carrega_repmap(src_dir: str) -> dict | None:
    """Ponte RepMap (alias/destino IQ -> base de origem ASE), igual à do orquestrador.

    O Chameleon é chaveado pela ORIGEM (dbcred.dbo.tbproposta), mas o SAS costuma
    referenciar o alias do destino de réplica no IQ (DBA.TBPROPOSTA). Sem a ponte,
    a tabela não casa mesmo estando modernizada — ver orchestrator_inventory.main()
    §'[Modernizada via replica]'."""
    caminho = os.path.join(src_dir, 'RepMap.xlsx')
    if not os.path.exists(caminho):
        eprint(f"  aviso: {caminho} ausente; ponte de réplica desativada "
               f"(tabelas modernizadas via réplica contam como 'a ingerir')")
        return None
    try:
        from pathlib import Path
        from validate_table_in_vs_repmap import (
            load_repmap_rows, repmap_derived_keys, match_artifact, norm_upper)
        linhas = load_repmap_rows(Path(caminho))
        indice = {}
        for r in linhas:
            for k in repmap_derived_keys(r):
                indice.setdefault(k, []).append(r)
        return {'linhas': linhas, 'indice': indice, 'match': match_artifact,
                'nu': norm_upper, 'cache': {}}
    except Exception as e:
        eprint(f"  aviso: RepMap não carregado ({e}); ponte de réplica desativada")
        return None


def _repmap_chaves_origem(art_clean: str, rep: dict | None) -> set:
    """Chaves 'DBsource.tabela' das linhas RepMap que casam com o artefato."""
    if not rep or not rep['linhas']:
        return set()
    cache = rep['cache']
    if art_clean in cache:
        return cache[art_clean]
    chaves = set()
    try:
        lvl, _desc, hits = rep['match'](art_clean, rep['linhas'], rep['indice'])
        if lvl not in ('SKIP', 'NOT_FOUND'):
            for h in hits:
                dbs = rep['nu'](h['DBsource'])
                for tb in (rep['nu'](h['Tabela']), rep['nu'](h['TabRep'])):
                    if dbs and tb:
                        chaves.add(f'{dbs}.{tb}')
    except Exception:
        chaves = set()
    cache[art_clean] = chaves
    return chaves


def carrega_disponibilidade(src_dir: str) -> dict:
    """Decide se um table_in já existe no destino, reusando os loaders E as DUAS
    etapas do matcher do orquestrador (fonte de verdade única):

      1. casamento direto no Chameleon (is_strict_match em NmTabelaDestino/Origem)
      2. ponte RepMap: traduz alias/destino IQ -> origem ASE e re-sonda o Chameleon

    A etapa 2 é o que o orquestrador rotula '[Modernizada via replica]'. Ela existia
    lá e não aqui: 18 tabelas do corpus eram contadas como 'a ingerir' pelo compare
    enquanto o app as mostrava disponíveis.

    Guarda o ÍNDICE do chameleon, não os records crus: ver _indexa_chameleon."""
    import orchestrator_inventory as oi
    override = oi.load_modernization_override(os.path.join(src_dir, 'inputs_modernizados.csv'))
    chameleon = []
    try:
        chameleon = oi.load_chameleon_data(os.path.join(src_dir, 'chameleon.csv'))
    except Exception as e:
        eprint(f"  aviso: chameleon indisponível ({e}); eixo de disponibilidade fica conservador")
    if not chameleon:
        # load_chameleon_data engole a própria exceção e devolve [] (ver
        # orchestrator_inventory.py), então o `except` acima quase nunca dispara:
        # catálogo corrompido/renomeado chega aqui como lista vazia silenciosa, e
        # sem aviso TUDO viraria 'a ingerir' com cara de resultado legítimo.
        eprint(f"  !! chameleon VAZIO ({os.path.join(src_dir, 'chameleon.csv')}): "
               f"sem catálogo, todo table_in conta como 'a ingerir' — confira o arquivo")
    return {'override': {canon(k): v for k, v in override.items()},
            'chameleon_idx': _indexa_chameleon(chameleon),
            'n_chameleon': len(chameleon),
            'repmap': _carrega_repmap(src_dir),
            'cache': {}}


def eh_bq_nativo(tabela: str, source: str) -> bool:
    """Tabela já no BigQuery: tag [BIGQUERY] do extrator ou nome com projeto
    BV-PDBD-* totalmente qualificado.

    NÃO usa contagem de pontos: nomes de 3 partes de pass-through Sybase/SQL
    Server (`db..tabela`, `DBCOR.DBO.TBSUBPRODUTO`) também têm 2+ pontos e
    passavam por BigQuery nativo — 17 tabelas reais do corpus, ausentes de
    chameleon.csv e inputs_modernizados.csv, eram marcadas disponíveis quando
    ainda precisavam de ingestão."""
    if 'BIGQUERY' in (source or '').upper():
        return True
    return tabela.upper().startswith('BV-PDBD-')


def input_disponivel(tabela: str, source: str, disp: dict) -> bool:
    """Memoizado por (tabela, source): `classifica_inputs` roda até 4× sobre o mesmo
    artefato no caminho de analisa_par + comparar()."""
    memo = disp['cache']
    chave_memo = (tabela, source)
    if chave_memo in memo:
        return memo[chave_memo]
    memo[chave_memo] = r = _input_disponivel(tabela, source, disp)
    return r


def _input_disponivel(tabela: str, source: str, disp: dict) -> bool:
    k = canon(tabela)
    if not k:
        return False
    if eh_bq_nativo(tabela, source):
        return True
    if k in disp['override']:
        return True
    art_clean = (tabela or '').replace('`', '').replace('"', '').replace("'", '').strip().upper()
    if not art_clean:
        return False
    idx = disp['chameleon_idx']
    if _casa_chameleon(art_clean, idx):          # etapa 1: casamento direto
        return True
    for chave_src in _repmap_chaves_origem(art_clean, disp['repmap']):
        if _casa_chameleon(chave_src, idx):      # etapa 2: ponte de réplica
            return True
    return False


def classifica_inputs(inv: dict, disp: dict) -> dict:
    """Parte os table_in entre 'já disponível' e 'exige ingestão'."""
    disponiveis, a_ingerir = set(), set()
    for inp in inv.get('inputs', []):
        tab = inp.get('table', '')
        k = canon(tab)
        if not k:
            continue
        (disponiveis if input_disponivel(tab, inp.get('source', ''), disp) else a_ingerir).add(k)
    return {'disponiveis': disponiveis, 'a_ingerir': a_ingerir}


# ---------------------------------------------------------------------------
# Alcance e dependências (lidos do corpus já processado — não roda orquestrador)
# ---------------------------------------------------------------------------

def carrega_alcance(base_dir: str) -> dict:
    """{'consumidores_por_tabela': {tabela: {egps}}, 'deps_por_projeto': {proj: {deps}}}"""
    consumidores = defaultdict(set)
    p01 = os.path.join(base_dir, '01_prioridade_ingestao.csv')
    if os.path.exists(p01):
        with open(p01, encoding='utf-8-sig', newline='') as f:
            for row in csv.DictReader(f):
                tab = canon(row.get('Tabela', ''))
                brutos = (row.get('Projetos_Dependentes') or '').strip('() ')
                if tab and brutos:
                    consumidores[tab] = {x.strip() for x in brutos.split(',') if x.strip()}

    deps = defaultdict(set)
    dependentes = defaultdict(set)
    p03 = os.path.join(base_dir, '03_matriz_dependencias.csv')
    if os.path.exists(p03):
        with open(p03, encoding='utf-8-sig', newline='') as f:
            for row in csv.DictReader(f):
                alvo = (row.get('Projeto_Alvo (Precisa Migrar)') or '').strip()
                fonte = (row.get('Depende_Do_Projeto') or '').strip()
                if alvo and fonte:
                    deps[alvo].add(fonte)
                    dependentes[fonte].add(alvo)
    return {'consumidores': consumidores, 'deps': deps, 'dependentes': dependentes}


def calcula_alcance(projetos_antigos, outputs_antigos: set, alc: dict) -> dict:
    """Blast radius do(s) EGP(s) antigo(s): quem depende deles + quem consome os outputs.
    Com vários antecessores é a UNIÃO, e nenhum deles conta como seu próprio dependente."""
    if isinstance(projetos_antigos, str):
        projetos_antigos = {projetos_antigos}
    projetos_antigos = set(projetos_antigos)
    por_grafo = set()
    for pj in projetos_antigos:
        por_grafo |= alc['dependentes'].get(pj, set())
    por_grafo -= projetos_antigos
    por_output = set()
    for tab in outputs_antigos:
        por_output |= alc['consumidores'].get(tab, set())
    por_output -= projetos_antigos
    total = por_grafo | por_output
    return {'n': len(total), 'por_grafo': len(por_grafo), 'por_output': len(por_output),
            'egps': sorted(total)[:40]}


# ---------------------------------------------------------------------------
# Snapshot do pipeline (etapa/status do antigo) — base do veto
# ---------------------------------------------------------------------------

def carrega_snapshot(path_ou_linhas: 'str | list | None') -> dict:
    """Aceita o caminho do CSV (fluxo do CLI) ou as linhas já buscadas ao vivo
    (lista de dicts com 'projeto', 'etapa_migracao', ... — ver
    pipeline_status_snapshot.busca_linhas), caso em que a idade é 0."""
    if isinstance(path_ou_linhas, list):
        linhas = {}
        for row in path_ou_linhas:
            proj = (row.get('projeto') or row.get('Projeto') or '').strip()
            if proj:
                # NULL do warehouse vem como None; o resto do código assume strings
                # (contrato do csv.DictReader) — normaliza aqui, na fronteira.
                linhas[proj] = {k: ('' if v is None else v) for k, v in row.items()}
        return {'linhas': linhas, 'data': 0, 'ok': True, 'aviso': ''}
    path = path_ou_linhas
    if not path:
        return {'linhas': {}, 'data': None, 'ok': False,
                'aviso': 'sem --snapshot: veto por etapa/status NÃO foi avaliado'}
    if not os.path.exists(path):
        return {'linhas': {}, 'data': None, 'ok': False,
                'aviso': f'snapshot "{path}" não existe: veto por etapa/status NÃO avaliado'}
    idade = (datetime.now(timezone.utc)
             - datetime.fromtimestamp(os.path.getmtime(path), timezone.utc)).days
    linhas = {}
    with open(path, encoding='utf-8-sig', newline='') as f:
        for row in csv.DictReader(f):
            proj = (row.get('projeto') or row.get('Projeto') or '').strip()
            if proj:
                linhas[proj] = row
    aviso = ''
    if idade > SNAPSHOT_VALIDADE_DIAS:
        aviso = (f'snapshot tem {idade} dias (limite {SNAPSHOT_VALIDADE_DIAS}): '
                 f'REGERE antes de confiar no veto')
    return {'linhas': linhas, 'data': idade, 'ok': idade <= SNAPSHOT_VALIDADE_DIAS,
            'aviso': aviso}


def avalia_veto(projetos_antigos, snap: dict, outputs_compartilhados: dict,
                outputs_privados: dict, inputs_macro: set, inputs_rede: set,
                par: dict) -> dict:
    """Vetos (decisão técnica) e alertas (pedem confirmação humana)."""
    vetos, alertas = [], []

    if isinstance(projetos_antigos, str):
        projetos_antigos = {projetos_antigos}
    projetos_antigos = sorted(projetos_antigos)

    # Snapshot com mais de SNAPSHOT_VALIDADE_DIAS (carrega_snapshot['ok']=False): o
    # veto abaixo roda mesmo assim, mas sobre etapa/status desatualizados. Antes o
    # aviso de staleness só aparecia quando o snapshot vinha VAZIO — um snapshot
    # velho mas com linhas (o caso comum) publicava veto/ausência-de-veto sem
    # nenhum rastro de que os dados de origem estavam fora da validade.
    if snap.get('aviso'):
        alertas.append(snap['aviso'])

    if not snap['linhas']:
        if not snap.get('aviso'):
            alertas.append('estado do EGP antigo não verificado')
    else:
        for projeto_antigo in projetos_antigos:
            row = snap['linhas'].get(projeto_antigo)
            if not row:
                alertas.append(f'"{projeto_antigo}" não está no snapshot do pipeline: '
                               f'estado de conversão desconhecido')
                continue
            etapa = (row.get('etapa_migracao') or '').strip()
            status = (row.get('status_migracao') or '').strip()
            idx = ETAPAS_MIGRACAO.index(etapa) if etapa in ETAPAS_MIGRACAO else -1
            if idx == -1 and etapa and etapa not in ETAPAS_FANTASMA_CONHECIDAS:
                # Etapa fora da lista E fora das phantom conhecidas: ou é drift entre
                # ETAPAS_MIGRACAO e PIPELINE_PROJETO (ver comentário acima), ou uma
                # etapa nova ainda não catalogada aqui. Nos dois casos o veto de etapa
                # fica mudo por baixo — melhor alertar do que pular em silêncio.
                alertas.append(f'"{projeto_antigo}" está em etapa não reconhecida '
                               f'("{etapa}"): veto de etapa pode não ter sido avaliado, '
                               f'confira manualmente')
            if idx >= IDX_VETO_ETAPA and status in STATUS_QUE_VETAM:
                vetos.append(f'"{projeto_antigo}" já convertido: etapa "{etapa}" com '
                             f'status "{status}" — trocar joga trabalho fora')
            if etapa == ETAPA_FANTASMA and status == 'Em Andamento':
                alertas.append(f'"{projeto_antigo}" em Pré-conversão em andamento: existe '
                               f'código a refazer (penalidade no Esforço, sem veto)')
            if status == 'Despriorizado e Contabilizado':
                alertas.append(f'"{projeto_antigo}" está despriorizado: trocar significa '
                               f'devolvê-lo ao backlog — decisão de escopo')
    if len(projetos_antigos) > 1:
        alertas.append(f'o novo consolida {len(projetos_antigos)} EGPs '
                       f'({", ".join(projetos_antigos)}): inventário e alcance são a união')

    # Output removido: veta só com 2+ consumidores externos (mart compartilhado).
    # Com 1 consumidor é quase sempre rascunho de analista em libname pessoal
    # (KEVIN., TALITA., GRIMALDI. na 1ª rodada) — alerta, não bloqueio. Critério por
    # contagem em vez de lista de nomes: é dado, não palpite.
    if outputs_compartilhados:
        amostra = ', '.join(f'{t} ({n} consumidores)'
                            for t, n in sorted(outputs_compartilhados.items())[:5])
        vetos.append(f'{len(outputs_compartilhados)} output(s) removidos com 2+ '
                     f'consumidores externos: {amostra}')
    if outputs_privados:
        amostra = ', '.join(sorted(outputs_privados))[:200]
        alertas.append(f'{len(outputs_privados)} output(s) removidos com 1 consumidor '
                       f'externo (provável rascunho de analista): {amostra}')
    if inputs_macro:
        amostra = ', '.join(sorted(inputs_macro)[:5])
        vetos.append(f'{len(inputs_macro)} input(s) novos com macro não resolvido: '
                     f'nem dá para identificar o arquivo — {amostra}')
    if inputs_rede:
        amostra = ', '.join(sorted(inputs_rede)[:3])
        alertas.append(f'{len(inputs_rede)} input(s) novos em caminho de rede '
                       f'(normal neste corpus, mas confira se não é planilha manual nova): '
                       f'{amostra}')
    if par['confianca'] == 'alerta':
        alertas.append(f'pareamento de confiança média (overlap {par["overlap"]:.0%}): '
                       f'confirme que é substituição antes de decidir')
    return {'vetos': vetos, 'alertas': alertas}


# ---------------------------------------------------------------------------
# Churn de código (linhas alteradas entre as duas versões)
# ---------------------------------------------------------------------------

def calcula_churn(fp_novo: dict, fp_antigo: dict) -> dict:
    """Linhas adicionadas/removidas somando task a task, casadas pelo id interno.

    'ok': False quando um dos dois .egp não pôde ser relido (zip corrompido, arquivo
    travado/movido, permissão). Antes isto era engolido em silêncio e o churn saía
    zerado — corrompendo o eixo de Esforço/Valor sem nenhum sinal. O chamador
    (analisa_par) precisa checar 'ok' e sair com 'Falha na extração' em vez de
    publicar um score calculado sobre dado incompleto."""
    import difflib

    def corpo(path: str) -> tuple[dict, bool]:
        d = {}
        try:
            with zipfile.ZipFile(path) as z:
                for i in z.infolist():
                    if i.is_dir() or not i.filename.lower().endswith(CODE_SUFFIX):
                        continue
                    ident = '/'.join(i.filename.split('/')[-2:])
                    if ident not in d:
                        d[ident] = z.read(i).decode('latin-1').splitlines()
        except (zipfile.BadZipFile, OSError, KeyError) as e:
            eprint(f"  !! falha lendo {os.path.basename(path)} para cálculo de churn: {e}")
            return d, False
        return d, True

    (a, ok_a), (b, ok_b) = corpo(fp_antigo['path']), corpo(fp_novo['path'])
    add = rem = 0
    for k in set(a) | set(b):
        velho, novo = a.get(k, []), b.get(k, [])
        for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, velho, novo).get_opcodes():
            if tag in ('replace', 'delete'):
                rem += i2 - i1
            if tag in ('replace', 'insert'):
                add += j2 - j1
    return {
        'ok': ok_a and ok_b,
        'linhas_add': add, 'linhas_rem': rem,
        'tasks_novas': len(set(b) - set(a)),
        'tasks_removidas': len(set(a) - set(b)),
        'loc_antigo': sum(len(v) for v in a.values()),
        'loc_novo': sum(len(v) for v in b.values()),
    }


_RE_REDE = re.compile(r'^(\\\\|[A-Za-z]:[\\/])')


def eh_macro_nao_resolvido(caminho: str) -> bool:
    """Input cujo caminho tem macro não expandida: nem dá para identificar o arquivo.
    Isto é regressão real de alcançabilidade e continua sendo VETO.

    O `&` reusa publish_to_databricks.is_macro_artifact em vez de um `'&' in c` cru:
    o regex ali já foi ajustado para não vetar abreviação literal entre letras isoladas
    (P&L, P&C) — 'P&L_Cartoes_Real.v2.xlsx' é um arquivo real do corpus (status
    Concluído humano). Um `'&' in c` ingênuo reintroduz esse falso positivo e força
    VETO num EGP que na verdade não tem macro nenhuma."""
    c = (caminho or '').strip()
    if not c:
        return False
    if '%' in c:
        return True
    import publish_to_databricks as pub
    return pub.is_macro_artifact(c)


def eh_caminho_rede(caminho: str) -> bool:
    r"""Input em caminho de rede (N:/J:/M: = \\bvnet\global).

    2026-09-01: NÃO é mais veto, virou alerta. Na 1ª rodada real isto vetou 6 de 30
    EGPs — mas caminho de rede é o estado NORMAL deste corpus, não regressão. O caso
    que provou: em `tipos_acordo` os "regressivos" eram AGRTYPE_V2.XLSX / AGRVALQ_V2.XLSX
    / AGTPDSC_V2.XLSX, ou seja, version bump de planilha. Vetar isso bloqueia troca
    boa por mudança rotineira."""
    c = (caminho or '').strip()
    return bool(c) and bool(_RE_REDE.match(c))


# ---------------------------------------------------------------------------
# Score
# ---------------------------------------------------------------------------

def pontua(inv_a: dict, inv_b: dict, cls_a: dict, cls_b: dict, churn: dict,
           alcance: dict, deps_novas: int, outputs_novos: int,
           penalidade_preconversao: bool) -> dict:
    """Valor e Esforço, 0-100 cada. Redução -> Valor; adição -> Esforço; nunca os dois."""
    fa = {canon(x) for x in inv_a.get('files_read', [])}
    fb = {canon(x) for x in inv_b.get('files_read', [])}
    sa = {canon(x) for x in inv_a.get('included_scripts', [])}
    sb = {canon(x) for x in inv_b.get('included_scripts', [])}
    oa = {canon(x) for x in inv_a.get('outputs', [])}
    ob = {canon(x) for x in inv_b.get('outputs', [])}

    v = {}
    v['menos_table_in_a_ingerir'] = rel_reducao(len(cls_a['a_ingerir']), len(cls_b['a_ingerir']), PISO_INPUTS)
    v['menos_file_in'] = rel_reducao(len(fa), len(fb), PISO_INPUTS)
    v['mais_input_disponivel'] = rel_aumento(len(cls_a['disponiveis']), len(cls_b['disponiveis']), PISO_INPUTS)
    v['alcance'] = min(1.0, alcance['n'] / ALCANCE_CAP) if ALCANCE_CAP else 0.0
    v['menos_script_in'] = rel_reducao(len(sa), len(sb), PISO_INPUTS)
    # Simplificação: média dos sinais que de fato reduziram (LOC, tasks, libnames, outputs órfãos).
    sinais = [
        rel_reducao(churn['loc_antigo'], churn['loc_novo'], PISO_LINHAS),
        rel_reducao(len(inv_a.get('outputs', [])), len(inv_b.get('outputs', [])), PISO_INPUTS),
        rel_reducao(len(inv_a.get('libnames', [])), len(inv_b.get('libnames', [])), PISO_INPUTS),
    ]
    v['simplificacao'] = sum(sinais) / len(sinais)

    e = {}
    base_loc = max(churn['loc_antigo'], 1)
    churn_total = churn['linhas_add'] + churn['linhas_rem']
    e['churn_codigo'] = 0.0 if churn_total < PISO_LINHAS else min(1.0, churn_total / base_loc)
    e['inputs_novos_a_ingerir'] = rel_aumento(len(cls_a['a_ingerir']), len(cls_b['a_ingerir']), PISO_INPUTS)
    e['outputs_novos_renomeados'] = min(1.0, outputs_novos / max(len(oa), 1)) if outputs_novos else 0.0
    e['deps_novas_egp'] = min(1.0, deps_novas / 5.0) if deps_novas else 0.0

    valor = sum(v[k] * PESOS_VALOR[k] for k in PESOS_VALOR)
    esforco = sum(e[k] * PESOS_ESFORCO[k] for k in PESOS_ESFORCO)
    if penalidade_preconversao:
        # Pré-conversão em andamento: há código convertido a refazer (Q21, sem veto).
        esforco = min(100.0, esforco + 10.0)

    return {'valor': round(valor, 1), 'esforco': round(esforco, 1),
            'eixos_valor': {k: round(x, 3) for k, x in v.items()},
            'eixos_esforco': {k: round(x, 3) for k, x in e.items()}}


def quadrante(valor: float, esforco: float, tem_veto: bool) -> str:
    if tem_veto:
        return 'Não trocar (veto)'
    alto_v, alto_e = valor >= CORTE_VALOR, esforco >= CORTE_ESFORCO
    if alto_v and not alto_e:
        return 'Trocar agora'
    if alto_v and alto_e:
        return 'Avaliar caso a caso'
    if not alto_v and not alto_e:
        return 'Trocar depois'
    return 'Não trocar'


# ---------------------------------------------------------------------------
# Análise de um par
# ---------------------------------------------------------------------------

COLUNAS_CSV = [
    'egp_novo', 'egp_antigo', 'n_antecessores', 'area', 'confianca_par', 'overlap_tasks',
    'valor', 'esforco', 'razao', 'quadrante', 'n_vetos', 'vetos', 'alertas',
    'table_in_antigo', 'table_in_novo', 'a_ingerir_antigo', 'a_ingerir_novo',
    'disponivel_antigo', 'disponivel_novo', 'file_in_antigo', 'file_in_novo',
    'script_in_antigo', 'script_in_novo', 'outputs_antigo', 'outputs_novo',
    'outputs_removidos_com_consumidor', 'outputs_removidos_privados',
    'inputs_macro_nao_resolvido', 'inputs_rede_novos', 'deps_novas',
    'loc_antigo', 'loc_novo', 'linhas_add', 'linhas_rem', 'tasks_novas',
    'alcance_total', 'alcance_por_grafo', 'alcance_por_output',
]


def _com_aviso(alertas: str, snap: dict) -> str:
    """Anexa o aviso de snapshot vencido aos quadrantes de SAÍDA ANTECIPADA.

    Esses caminhos retornam antes de avalia_veto(), que é onde snap['aviso'] entra nos
    alertas — então uma rodada feita com snapshot fora da validade publicava essas
    linhas sem nenhum rastro disso. O aviso não muda a conclusão delas, mas diz ao
    leitor com que dado a rodada foi feita."""
    aviso = (snap or {}).get('aviso')
    if not aviso:
        return alertas
    return f'{alertas} | {aviso}' if alertas else aviso


def analisa_par(fp_novo, par, disp, alc, snap, scratch) -> dict | None:
    """Compara o EGP novo com o(s) antecessor(es).

    Com mais de um antecessor (o novo consolida vários), o lado "antigo" é a UNIÃO dos
    inventários: os inputs que o novo tem de cobrir e os outputs que ele tem de manter
    são a soma dos dois. Exceção: o churn de código é medido contra o antecessor
    PRIMÁRIO — diff de linha contra uma união não significa nada.
    """
    nome_novo = os.path.basename(fp_novo['path'])
    antigos = par.get('antigos') or []

    if par['confianca'] in ('sem_par', 'recusado', 'erro') or not antigos:
        return {'egp_novo': nome_novo,
                'egp_antigo': os.path.basename(antigos[0]['path']) if antigos else '',
                'confianca_par': par['confianca'], 'overlap_tasks': round(par['overlap'], 3),
                'n_antecessores': len(antigos),
                'quadrante': 'EGP inédito' if par['confianca'] == 'sem_par' else 'Par não resolvido',
                'alertas': _com_aviso(par['motivo'], snap), 'n_vetos': 0}

    primario = antigos[0]
    area = os.path.basename(os.path.dirname(primario['path']))
    nomes_antigos = ' + '.join(os.path.basename(a['path']) for a in antigos)

    # Delta zero contra o primário: sai cedo, sem score (acordado no grilling).
    # Independe de haver co-antecessores: código idêntico ao par direto significa que
    # nada mudou, e unir inventário de outros EGPs aqui inventaria output que o novo
    # nunca teve (foi o que quebrou o Atualiza_UF_Cartoes na 1ª tentativa de N:1).
    if fp_novo['codes'] == primario['codes']:
        return {'egp_novo': nome_novo, 'egp_antigo': nomes_antigos, 'area': area,
                'confianca_par': par['confianca'], 'overlap_tasks': 1.0,
                'n_antecessores': 1, 'quadrante': 'Sem mudança (descartar)',
                'alertas': _com_aviso('código idêntico ao que já está no corpus', snap), 'n_vetos': 0}

    brutos_a = [(a, extrai_inventario(a['path'], area, scratch)) for a in antigos]
    invs_a = [inv for _a, inv in brutos_a if inv]
    falhou_a = [os.path.basename(a['path']) for a, inv in brutos_a if not inv]
    inv_b = extrai_inventario(fp_novo['path'], area, scratch)
    if not invs_a or not inv_b:
        return {'egp_novo': nome_novo, 'egp_antigo': nomes_antigos, 'area': area,
                'n_antecessores': len(antigos), 'quadrante': 'Falha na extração',
                'alertas': _com_aviso('extrator não produziu inventário para um dos lados', snap), 'n_vetos': 0}
    if falhou_a:
        # Extração PARCIAL do lado antigo (N:1: o novo consolida vários antecessores).
        # Antes o descarte era mudo (`[x for x in invs_a if x]`) e a comparação seguia
        # com a união INCOMPLETA, ainda reportando n_antecessores cheio. O efeito não é
        # ruído: `removidos = out_a - out_b` perde os outputs do antecessor ilegível,
        # então `outputs_compartilhados` fica vazio e o VETO de "output removido com
        # 2+ consumidores externos" nunca dispara — o resultado diz "pode trocar"
        # justamente porque não conseguiu ler o que provaria o contrário. Falha alto.
        return {'egp_novo': nome_novo, 'egp_antigo': nomes_antigos, 'area': area,
                'n_antecessores': len(antigos), 'quadrante': 'Falha na extração',
                'alertas': _com_aviso(
                    f'{len(falhou_a)} de {len(antigos)} antecessor(es) não puderam ser '
                    f'extraídos ({", ".join(falhou_a)}): a comparação seria parcial e o '
                    f'veto de output removido não seria confiável', snap),
                'n_vetos': 0}

    inv_a = consolida_partes(invs_a) if len(invs_a) > 1 else invs_a[0]
    projetos_antigos = {(x.get('project') or '').strip() for x in invs_a if x.get('project')}
    if not projetos_antigos:
        projetos_antigos = {os.path.splitext(os.path.basename(primario['path']))[0]}

    cls_a, cls_b = classifica_inputs(inv_a, disp), classifica_inputs(inv_b, disp)
    churn = calcula_churn(fp_novo, primario)
    if not churn['ok']:
        # Aqui os DOIS inventários já foram extraídos com sucesso (só a releitura do
        # código para o diff falhou), então levam '_inventarios' junto. Sem isto o
        # comparar() cairia no ramo de saída antecipada, re-extrairia só o lado novo
        # e deixaria 'antigo': None — e o publish trataria como se não houvesse
        # antecessor (nenhum output marcado 'removido', todo input com novo=None),
        # exatamente o bug que a correção do 'Sem mudança (descartar)' eliminou.
        return {'egp_novo': nome_novo, 'egp_antigo': nomes_antigos, 'area': area,
                'n_antecessores': len(antigos), 'quadrante': 'Falha na extração',
                'alertas': _com_aviso('falha lendo código de um dos lados para cálculo '
                                      'de churn', snap),
                'n_vetos': 0,
                '_inventarios': {'novo': inv_b, 'antigo': inv_a, 'antigos': invs_a,
                                 'cls_novo': cls_b, 'cls_antigo': cls_a,
                                 'projetos_antigos': sorted(projetos_antigos),
                                 'consumidores_externos_removidos': {}}}

    out_a = {canon(x) for x in inv_a.get('outputs', [])}
    out_b = {canon(x) for x in inv_b.get('outputs', [])}
    removidos = out_a - out_b
    # Consumidor NÃO conta nenhum dos próprios antecessores: output que só eles releem é
    # input auto-gerado, não consumidor externo (ver ..._Inputs_Autogerados_...). Sem esta
    # exclusão o veto dispara em massa e falso.
    consumidores_externos = {
        t: len(alc['consumidores'].get(t, set()) - projetos_antigos) for t in removidos
    }
    outputs_compartilhados = {t: n for t, n in consumidores_externos.items() if n >= 2}
    outputs_privados = {t: n for t, n in consumidores_externos.items() if n == 1}
    outputs_novos = len(out_b - out_a)

    files_a = {canon(x) for x in inv_a.get('files_read', [])}
    files_b = {canon(x) for x in inv_b.get('files_read', [])}
    novos_files = files_b - files_a
    inputs_macro = {c for c in novos_files if eh_macro_nao_resolvido(c)}
    inputs_rede = {c for c in novos_files if eh_caminho_rede(c) and c not in inputs_macro}

    alcance = calcula_alcance(projetos_antigos, out_a, alc)

    par_ctx = dict(par)
    par_ctx['area_nova'] = area
    julg = avalia_veto(projetos_antigos, snap, outputs_compartilhados, outputs_privados,
                       inputs_macro, inputs_rede, par_ctx)

    # Penalidade de pré-conversão: basta UM antecessor com código já em conversão.
    penal = any((snap['linhas'].get(pj) or {}).get('etapa_migracao', '').strip() == ETAPA_FANTASMA
                and (snap['linhas'].get(pj) or {}).get('status_migracao', '').strip() == 'Em Andamento'
                for pj in projetos_antigos)

    ingerir_novos = cls_b['a_ingerir'] - cls_a['a_ingerir']
    # 'deps_novas': quantas das novas tabelas a ingerir têm outro EGP do corpus como
    # consumidor conhecido (sinal de que a ingestão não é isolada — tem fan-out real
    # para outros projetos).
    #
    # NÃO exclui as que já eram "dependência" do antecessor: fazer isso direito exige
    # um mapa tabela -> EGP-produtor, que nenhuma fonte carregada aqui tem
    # (01_prioridade_ingestao.csv lista tabela de ingestão EXTERNA + quem mais precisa
    # dela, não quem produz; 03_matriz_dependencias.csv/alc['deps'] é por PROJETO, não
    # por tabela). A versão anterior subtraía `alc['deps']` (nomes de PROJETO) de um
    # set de CHAVES DE TABELA — os tipos nunca batiam, então a subtração nunca removia
    # nada; era morta em silêncio. Documentando aqui em vez de reintroduzir uma
    # exclusão que não dá pra fazer direito com os dados disponíveis hoje.
    deps_novas = len({t for t in ingerir_novos
                      if (alc['consumidores'].get(t, set()) - projetos_antigos)})

    sc = pontua(inv_a, inv_b, cls_a, cls_b, churn, alcance, deps_novas, outputs_novos, penal)
    quad = quadrante(sc['valor'], sc['esforco'], bool(julg['vetos']))

    return {
        'egp_novo': nome_novo, 'egp_antigo': nomes_antigos, 'area': area,
        'n_antecessores': len(antigos),
        'confianca_par': par['confianca'], 'overlap_tasks': round(par['overlap'], 3),
        'valor': sc['valor'], 'esforco': sc['esforco'],
        'razao': round(sc['valor'] / max(sc['esforco'], 1.0), 2),
        'quadrante': quad, 'n_vetos': len(julg['vetos']),
        'vetos': ' | '.join(julg['vetos']), 'alertas': ' | '.join(julg['alertas']),
        'table_in_antigo': len(inv_a.get('inputs', [])), 'table_in_novo': len(inv_b.get('inputs', [])),
        'a_ingerir_antigo': len(cls_a['a_ingerir']), 'a_ingerir_novo': len(cls_b['a_ingerir']),
        'disponivel_antigo': len(cls_a['disponiveis']), 'disponivel_novo': len(cls_b['disponiveis']),
        'file_in_antigo': len(files_a), 'file_in_novo': len(files_b),
        'script_in_antigo': len(inv_a.get('included_scripts', [])),
        'script_in_novo': len(inv_b.get('included_scripts', [])),
        'outputs_antigo': len(out_a), 'outputs_novo': len(out_b),
        'outputs_removidos_com_consumidor': len(outputs_compartilhados),
        'outputs_removidos_privados': len(outputs_privados),
        'inputs_macro_nao_resolvido': len(inputs_macro),
        'inputs_rede_novos': len(inputs_rede), 'deps_novas': deps_novas,
        'loc_antigo': churn['loc_antigo'], 'loc_novo': churn['loc_novo'],
        'linhas_add': churn['linhas_add'], 'linhas_rem': churn['linhas_rem'],
        'tasks_novas': churn['tasks_novas'],
        'alcance_total': alcance['n'], 'alcance_por_grafo': alcance['por_grafo'],
        'alcance_por_output': alcance['por_output'],
        '_inventarios': {'novo': inv_b, 'antigo': inv_a, 'antigos': invs_a,
                         'cls_novo': cls_b, 'cls_antigo': cls_a,
                         'projetos_antigos': sorted(projetos_antigos),
                         # canon(output removido) -> nº de consumidores EXTERNOS (exclui
                         # os próprios antecessores) — quem publica precisa por output.
                         'consumidores_externos_removidos': consumidores_externos},
        '_detalhe': {'eixos': sc, 'alcance_egps': alcance['egps'],
                     'antecessores': [os.path.basename(a['path']) for a in antigos],
                     'outputs_removidos': sorted(outputs_compartilhados)[:20],
                     'regressivos': sorted(inputs_macro)[:20],
                     'rede': sorted(inputs_rede)[:20]},
    }


def escreve_markdown(res: dict, md_dir: str, hoje: str):
    """Markdown detalhado só para vetados e 'avaliar caso a caso' (acordado no grilling)."""
    nome = re.sub(r'[^A-Za-z0-9_.-]+', '_', os.path.splitext(res['egp_novo'])[0])[:80]
    caminho = os.path.join(md_dir, f'BV_Migracao_SAS_Troca_{nome}_{hoje}.md')
    d = res.get('_detalhe', {})
    eixos = d.get('eixos', {})
    tem_score = res.get('valor') is not None
    ant = res.get('egp_antigo') or '(nenhum)'
    L = [f"# Troca de EGP — {res['egp_novo']}", "",
         f"**Antecessor(es) ({res.get('n_antecessores', 1)}):** `{ant}` · área {res.get('area') or '—'} · "
         f"pareamento {res.get('confianca_par','')} (overlap {res.get('overlap_tasks',0):.0%})", ""]
    if tem_score:
        L += [f"**Valor {res.get('valor')} · Esforço {res.get('esforco')} · "
              f"razão {res.get('razao')} → {res['quadrante']}**", ""]
    else:
        # Sem par resolvido / sem mudança não há score: não emitir tabela de None.
        L += [f"**{res['quadrante']}** — sem score calculado, porque o inventário dos dois "
              f"lados não pôde ser comparado.", ""]
    if res.get('vetos'):
        L += ["## Vetos", ""] + [f"- {v}" for v in res['vetos'].split(' | ')] + [""]
    if res.get('alertas'):
        L += ["## Alertas (pedem confirmação humana)", ""] + \
             [f"- {a}" for a in res['alertas'].split(' | ')] + [""]
    if not tem_score:
        with open(caminho, 'w', encoding='utf-8') as f:
            f.write('\n'.join(L))
        return caminho

    L += ["## Inventário", "",
          "| Categoria | Antigo | Novo |", "|---|---|---|",
          f"| `table_in` total | {res.get('table_in_antigo')} | {res.get('table_in_novo')} |",
          f"| ... que exigem ingestão | {res.get('a_ingerir_antigo')} | {res.get('a_ingerir_novo')} |",
          f"| ... já disponíveis no destino | {res.get('disponivel_antigo')} | {res.get('disponivel_novo')} |",
          f"| `file_in` | {res.get('file_in_antigo')} | {res.get('file_in_novo')} |",
          f"| `script_in` | {res.get('script_in_antigo')} | {res.get('script_in_novo')} |",
          f"| outputs | {res.get('outputs_antigo')} | {res.get('outputs_novo')} |",
          f"| LOC | {res.get('loc_antigo')} | {res.get('loc_novo')} |", "",
          f"Churn: +{res.get('linhas_add')} / -{res.get('linhas_rem')} linhas, "
          f"{res.get('tasks_novas')} tasks novas.", "",
          f"Alcance do antigo: {res.get('alcance_total')} EGPs "
          f"({res.get('alcance_por_grafo')} por dependência, {res.get('alcance_por_output')} por output).", ""]
    if eixos:
        L += ["## Composição do score", "", "| Eixo | Peso | Fração | Pontos |", "|---|---|---|---|"]
        for k, frac in eixos.get('eixos_valor', {}).items():
            L.append(f"| Valor · {k} | {PESOS_VALOR[k]} | {frac:.2f} | {frac*PESOS_VALOR[k]:.1f} |")
        for k, frac in eixos.get('eixos_esforco', {}).items():
            L.append(f"| Esforço · {k} | {PESOS_ESFORCO[k]} | {frac:.2f} | {frac*PESOS_ESFORCO[k]:.1f} |")
        L.append("")
    if d.get('outputs_removidos'):
        L += ["## Outputs removidos com consumidor", ""] + \
             [f"- `{o}`" for o in d['outputs_removidos']] + [""]
    if d.get('regressivos'):
        L += ["## Inputs regressivos introduzidos", ""] + \
             [f"- `{o}`" for o in d['regressivos']] + [""]
    with open(caminho, 'w', encoding='utf-8') as f:
        f.write('\n'.join(L))
    return caminho


# ---------------------------------------------------------------------------
# API programática
# ---------------------------------------------------------------------------

def comparar(novos, corpus_dir='received_egps', src_dir='src',
             snapshot='src/pipeline_status_snapshot.csv', antigo=None,
             cache='.cache/egp_fingerprints.json', base_dir='.',
             incluir_inventarios=False, verbose=False) -> dict:
    """Compara .egp novos contra o corpus SEM escrever arquivo algum.

    novos: lista de caminhos .egp. snapshot: caminho do CSV OU as linhas já
    buscadas ao vivo (ver pipeline_status_snapshot.busca_linhas). base_dir:
    pasta dos relatórios 01/03 usados no alcance. Com incluir_inventarios, cada
    resultado carrega '_inventarios' (inventário e classificação dos dois lados)
    também nos casos de saída antecipada (inédito / sem mudança / par não
    resolvido), extraindo o lado novo sob demanda.

    Devolve {'resultados': [...], 'snapshot': snap}, resultados já ordenados por
    razão/valor como no CLI. Chaves privadas ('_inventarios', '_detalhe',
    '_egp_path') não entram no CSV (DictWriter ignora extras).
    """
    if verbose:
        print(f"comparando {len(novos)} EGP(s) contra o corpus em {corpus_dir}")
    corpus = carrega_fingerprints_corpus(corpus_dir, cache)
    disp = carrega_disponibilidade(src_dir)
    alc = carrega_alcance(base_dir)
    snap = carrega_snapshot(snapshot)
    if snap.get('aviso') and verbose:
        eprint(f"  ⚠  {snap['aviso']}")

    scratch = tempfile.mkdtemp(prefix='cmp_egp_')
    resultados = []
    # .egp de ENTRADA que não puderam ser lidos. Sem isto, comparar() devolvia menos
    # resultados que entradas sem dizer nada, e o publish imprimia "publicado: N
    # versão(ões)" sem pista de que M arquivos nunca chegaram lá.
    pulados = []
    try:
        for i, caminho in enumerate(novos, 1):
            if verbose:
                print(f"[{i}/{len(novos)}] {os.path.basename(caminho)}")
            fp = fingerprint_egp(caminho)
            if not fp['ok']:
                eprint(f"  !! não é um .egp legível: {fp.get('err')}")
                pulados.append((caminho, fp.get('err')))
                continue
            par = parear(fp, corpus, antigo)
            res = analisa_par(fp, par, disp, alc, snap, scratch)
            if res:
                if incluir_inventarios and '_inventarios' not in res:
                    # Saída antecipada: o lado novo ainda interessa a quem publica.
                    inv_b = extrai_inventario(caminho, res.get('area') or '', scratch)
                    # 'Sem mudança (descartar)' TEM um antecessor real e confiante
                    # (é por isso que o delta-zero foi detectado) — diferente de
                    # 'EGP inédito'/'Par não resolvido', onde não há par confiável.
                    # Zerar o antigo aqui também fazia publish_egps_atualizados.py
                    # tratar como se não houvesse antecessor (outputs nunca marcados
                    # 'removido', mesmo com o par real disponível em par['antigos']).
                    antigos = par.get('antigos') or []
                    inv_a, invs_a, projetos_antigos = None, [], []
                    if res.get('quadrante') == 'Sem mudança (descartar)' and antigos:
                        area_a = res.get('area') or ''
                        invs_a = [x for x in
                                  (extrai_inventario(a['path'], area_a, scratch) for a in antigos)
                                  if x]
                        if invs_a:
                            inv_a = consolida_partes(invs_a) if len(invs_a) > 1 else invs_a[0]
                            projetos_antigos = sorted({(x.get('project') or '').strip()
                                                       for x in invs_a if x.get('project')})
                    res['_inventarios'] = {
                        'novo': inv_b, 'antigo': inv_a, 'antigos': invs_a,
                        'cls_novo': classifica_inputs(inv_b, disp) if inv_b else None,
                        'cls_antigo': classifica_inputs(inv_a, disp) if inv_a else None,
                        'projetos_antigos': projetos_antigos,
                    }
                res['_egp_path'] = caminho
                resultados.append(res)
                if verbose:
                    print(f"    -> {res['quadrante']}"
                          + (f" · V{res.get('valor')} E{res.get('esforco')}"
                             if res.get('valor') is not None else ""))
    finally:
        shutil.rmtree(scratch, ignore_errors=True)

    resultados.sort(key=lambda r: (-(r.get('razao') or 0), -(r.get('valor') or 0)))
    return {'resultados': resultados, 'snapshot': snap, 'pulados': pulados}


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--novo', required=True, help='.egp novo ou pasta com vários')
    ap.add_argument('--antigo', default=None,
                    help='caminho(s) parcial(is) do(s) antecessor(es) no corpus, separados por vírgula (só com --novo arquivo único)')
    ap.add_argument('--corpus', default='received_egps')
    ap.add_argument('--src', default='src', help='pasta com chameleon.csv e inputs_modernizados.csv')
    ap.add_argument('--snapshot', default='src/pipeline_status_snapshot.csv',
                    help='snapshot de sas_egp_pipeline (projeto, etapa_migracao, status_migracao, area)')
    ap.add_argument('--out', default=None,
                    help=f'CSV consolidado (default: {PASTA_ESTUDO}/...)')
    ap.add_argument('--md-dir', default=PASTA_ESTUDO,
                    help='pasta dos markdowns de detalhe; use uma pasta por rodada')
    ap.add_argument('--cache', default='.cache/egp_fingerprints.json')
    ap.add_argument('--data', default=None,
                    help='data da RODADA usada no nome dos arquivos (YYYY-MM-DD). '
                         'Default: hoje. Passe a data original ao re-rodar uma rodada, '
                         'senão o re-run cria um segundo conjunto de arquivos em vez de '
                         'sobrescrever o primeiro.')
    args = ap.parse_args()

    # Data da rodada, não a de execução: re-rodar depois da meia-noite ou num dia
    # seguinte gerava um conjunto paralelo de arquivos (aconteceu em 02/09/2026).
    hoje = args.data or datetime.now().strftime('%Y-%m-%d')
    out_csv = args.out or os.path.join(args.md_dir, f'BV_Migracao_SAS_Troca_EGP_{hoje}.csv')

    if os.path.isdir(args.novo):
        novos = sorted(os.path.join(args.novo, f) for f in os.listdir(args.novo)
                       if f.lower().endswith('.egp'))
        if args.antigo:
            ap.error('--antigo só faz sentido com --novo apontando para um arquivo')
    else:
        novos = [args.novo]
    if not novos:
        ap.error(f'nenhum .egp em {args.novo}')

    cmp = comparar(novos, corpus_dir=args.corpus, src_dir=args.src,
                   snapshot=args.snapshot, antigo=args.antigo, cache=args.cache,
                   verbose=True)
    resultados, snap = cmp['resultados'], cmp['snapshot']

    os.makedirs(os.path.dirname(out_csv) or '.', exist_ok=True)
    with open(out_csv, 'w', encoding='utf-8-sig', newline='') as f:
        w = csv.DictWriter(f, fieldnames=COLUNAS_CSV, extrasaction='ignore')
        w.writeheader()
        for r in resultados:
            w.writerow(r)
    print(f"\nCSV consolidado: {out_csv}")

    os.makedirs(args.md_dir, exist_ok=True)
    detalhados = [r for r in resultados
                  if r.get('n_vetos') or r['quadrante'] in ('Avaliar caso a caso', 'Par não resolvido')]
    for r in detalhados:
        print(f"  markdown: {escreve_markdown(r, args.md_dir, hoje)}")

    print("\nresumo por quadrante:")
    tot = defaultdict(int)
    for r in resultados:
        tot[r['quadrante']] += 1
    for q, n in sorted(tot.items(), key=lambda t: -t[1]):
        print(f"  {n:3d}  {q}")
    if not snap['linhas']:
        eprint("\n⚠  Sem snapshot do pipeline: NENHUM veto por 'antigo já convertido' foi "
               "avaliado. Os quadrantes acima são provisórios.")


if __name__ == '__main__':
    main()
