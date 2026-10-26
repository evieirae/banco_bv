#!/usr/bin/env python3
"""Auditoria de ORDEM no código SAS: a tabela é intermediária ou é estado entre execuções?

Motivação (2026-08-13). A classificação de auto-produção é de CONJUNTO — o EGP escreve e
lê a mesma tabela, logo "ele a recria, dispensa ingestão". Isso ignora a ORDEM, e há um
padrão SAS que passa pelo teste sendo o oposto:

    DATA CONSIG.CARTEIRA_GERAL; SET CONSIG.CARTEIRA_GERAL; WHERE SAFRA <> &SAFRA.; RUN;
    DATA CONSIG.CARTEIRA_GERAL; SET CONSIG.CARTEIRA_GERAL  CARTEIRA;               RUN;

É um acumulador de histórico com purga e reinserção: a tabela guarda todas as safras, o
EGP remove a corrente e reinsere a nova. O conteúdo anterior é OBRIGATÓRIO — sanitizar
apaga o histórico e a primeira execução no destino não tem de onde ler.

Vereditos:
  cria_depois_le      intermediária de verdade  -> pode sanitizar
  AUTO_REFERENCIA     lê o próprio conteúdo sem criação prévia de outra fonte -> carga inicial
  LE_ANTES_DE_CRIAR   lê antes de qualquer criação no fluxo -> carga inicial
  SO_LE               nenhuma criação encontrada -> carga inicial
  so_escreve          escreve e não lê no corpo -> sem risco de leitura
  nome_via_macro      nome só existe resolvido no inventário -> NÃO VERIFICÁVEL

Ordem textual == ordem de execução: o extractor emite as tasks em ordem topológica.
"""
import glob
import re
from collections import defaultdict

W_DATA = re.compile(r'(?is)^\s*data\s+([^;]*);')
W_CREATE = re.compile(r'(?is)create\s+table\s+([^\s(]+)')
W_OUT = re.compile(r'(?i)\bout\s*=\s*([\w.&]+)')
R_SET = re.compile(r'(?is)\b(set|merge|modify|update)\s+([^;]*);')
R_FROM = re.compile(r'(?is)\b(from|join)\s+([\w.&]+)')
APPEND = re.compile(r'(?is)proc\s+append\b([^;]*;[^;]*;)')
PURGA = re.compile(r'(?is)\b(where|if)\b[^;]{0,120}\b(<>|ne|not\s+in|delete)\b')

RISCO = {'AUTO_REFERENCIA', 'LE_ANTES_DE_CRIAR', 'SO_LE'}
NAO_VERIFICAVEL = {'nome_via_macro', 'sem_codigo'}


def carrega_codigo():
    """PROJECT -> corpo de código (sem o cabeçalho de metadados), tasks em ordem."""
    out = defaultdict(list)
    for f in sorted(glob.glob('text_egps/*.txt')):
        raw = open(f, encoding='utf-8', errors='replace').read()
        m = re.search(r'^PROJECT: (.*)$', raw, re.M)
        if not m:
            continue
        i = raw.find('END_METADATA')
        out[m.group(1).strip()].append(raw[i + 12:] if i > 0 else raw)
    return {k: '\n'.join(v) for k, v in out.items()}


def _passos(code):
    marks = [(m.start(), m.group(0).lower().strip())
             for m in re.finditer(r'(?im)^\s*(data\s|proc\s+\w+)', code)]
    for n, (pos, kind) in enumerate(marks):
        end = marks[n + 1][0] if n + 1 < len(marks) else len(code)
        yield pos, kind, code[pos:end]


def _rx(tabela):
    lib, _, mem = tabela.partition('.')
    return re.compile(r'(?<![\w.])' + re.escape(lib) + r'\s*\.\s*' + re.escape(mem)
                      + r'(?![\w.])', re.I)


def audita(tabela, code):
    """(veredito, evidência) para uma tabela no código de um EGP."""
    if not code:
        return 'sem_codigo', ''
    rx = _rx(tabela)
    if not rx.search(code):
        return 'nome_via_macro', 'nome não aparece literalmente no código'
    criada_de_outra_fonte = False
    first_read = first_create = None
    for pos, kind, blk in _passos(code):
        escreve = False
        if kind.startswith('data'):
            m = W_DATA.match(blk)
            if m and rx.search(m.group(1)):
                escreve = True
        if any(rx.search(m.group(1)) for m in W_CREATE.finditer(blk)):
            escreve = True
        if any(rx.search(m.group(1)) for m in W_OUT.finditer(blk)):
            escreve = True
        corpo = blk
        if kind.startswith('data') and W_DATA.match(blk):
            corpo = blk[len(W_DATA.match(blk).group(0)):]
        le = (any(rx.search(m.group(2)) for m in R_SET.finditer(corpo))
              or any(rx.search(m.group(2)) for m in R_FROM.finditer(corpo)))
        if escreve and le and not criada_de_outra_fonte:
            ev = re.sub(r'\s+', ' ', blk[:170]).strip()
            purga = ' [purga-e-reinsere]' if PURGA.search(blk) else ''
            return 'AUTO_REFERENCIA', ev + purga
        if escreve and not le:
            criada_de_outra_fonte = True
        if escreve and first_create is None:
            first_create = pos
        if le and first_read is None:
            first_read = pos
    for m in APPEND.finditer(code):
        if len(rx.findall(m.group(1))) >= 2:
            return 'AUTO_REFERENCIA', re.sub(r'\s+', ' ', m.group(0)[:150])
    if first_read is None:
        return 'so_escreve', ''
    if first_create is None:
        return 'SO_LE', 'lê sem nenhuma criação no fluxo'
    if first_read < first_create:
        return 'LE_ANTES_DE_CRIAR', f'lê em @{first_read}, só cria em @{first_create}'
    return 'cria_depois_le', f'cria em @{first_create}, lê depois em @{first_read}'


def pior(vereditos):
    """Veredito mais conservador de uma lista."""
    ordem = ['AUTO_REFERENCIA', 'LE_ANTES_DE_CRIAR', 'SO_LE', 'nome_via_macro',
             'sem_codigo', 'so_escreve', 'cria_depois_le']
    return min(vereditos, key=lambda v: ordem.index(v[0])) if vereditos else ('sem_codigo', '')


# --------------------------------------------------------------------------- macros
_LET = re.compile(r'(?im)^[^\S\n]*%let\s+(\w+)\s*=\s*([^;]*);')


def mapa_macros(code):
    """VAR -> lista de valores atribuídos por %let, na ordem, sem aspas externas."""
    m = defaultdict(list)
    for mm in _LET.finditer(code):
        v = mm.group(2).strip()
        while len(v) > 1 and v[0] == v[-1] and v[0] in '"\'':
            v = v[1:-1].strip()
        if v and '&' not in v[:1]:
            m[mm.group(1).upper()].append(v)
    return m


def expande_macros(code, mapa=None, passes=3):
    """Substitui &VAR. / &VAR pelos valores de %let. Quando a variável recebe mais de
    um valor no fluxo, usa o ÚLTIMO (caso dominante: uma atribuição só)."""
    mapa = mapa if mapa is not None else mapa_macros(code)
    if not mapa:
        return code
    out = code
    for _ in range(passes):
        antes = out

        def sub(m):
            vals = mapa.get(m.group(1).upper())
            return vals[-1] if vals else m.group(0)

        out = re.sub(r'&(\w+)\.?', sub, out)
        if out == antes:
            break
    return out


def audita_com_macros(tabela, code):
    """audita() com fallback: se o nome não aparece literalmente, tenta no código com
    as macros expandidas. Devolve (veredito, evidência, resolvido_por_macro)."""
    vd, ev = audita(tabela, code)
    if vd != 'nome_via_macro':
        return vd, ev, False
    mapa = mapa_macros(code)
    if not mapa:
        return vd, ev, False
    exp = expande_macros(code, mapa)
    vd2, ev2 = audita(tabela, exp)
    if vd2 == 'nome_via_macro':
        return vd, ev, False
    return vd2, ev2, True
