

# JOIN do nível externo a uma tabela real (não subquery, não CONNECTION TO).
_OUTER_SAS_JOIN_AT_POS_RE = re.compile(
    r'\b(?:NATURAL\s+)?(?:(?:LEFT|RIGHT|FULL|INNER|OUTER|CROSS)\s+)*JOIN\s+'
    r'(?!\()(?!CONNECTION\b)([A-Za-z0-9_&][\w.&\-]*)',
    re.IGNORECASE,
)
_FROM_CONNECTION_OPEN_RE = re.compile(
    r'\bFROM\s+CONNECTION\s+TO\s+[A-Za-z0-9_]+\s*\(', re.IGNORECASE
)


def _collect_proc_sql_outer_joins_after_passthrough(text_clean, inputs, work_reads, provenance):
    """
    Captura tabelas REAIS (lib.membro) em JOINs do NÍVEL EXTERNO de um SELECT cujo
    FROM principal é um pass-through ``FROM CONNECTION TO alias (...)``.

    _sql_from_join_in_fragment ignora a cláusula FROM inteira nesse caso (lookahead
    ``(?!CONNECTION TO)``); a cadeia de JOINs externos a tabelas SAS (ex.:
    ``FROM CONNECTION TO PERM (...) AS A LEFT JOIN B_GERAL.DIAS_UTEIS AS DU``) só era
    apanhada por transbordo acidental do corpo de um FROM interno sem WHERE/GROUP —
    quando os blocos pass-through têm WHERE/GROUP BY, a tabela externa some.

    Anda em profundidade de parênteses a partir do '(' do pass-through: só regista
    JOINs a depth 0 (fora de qualquer pass-through), pára no ';' do statement, ignora
    ``JOIN (subquery)`` e ``JOIN CONNECTION TO``. Aditivo (inputs/provenance são sets).
    """
    n = len(text_clean)
    for fm in _FROM_CONNECTION_OPEN_RE.finditer(text_clean):
        i = fm.end() - 1  # posição do '(' do pass-through
        depth = 0
        in_squote = False
        while i < n:
            c = text_clean[i]
            if in_squote:
                if c == "'":
                    in_squote = False
                i += 1
                continue
            if c == "'":
                in_squote = True
                i += 1
                continue
            if c == '(':
                depth += 1
                i += 1
                continue
            if c == ')':
                depth = max(0, depth - 1)
                i += 1
                continue
            if depth == 0:
                if c == ';':
                    break
                jm = _OUTER_SAS_JOIN_AT_POS_RE.match(text_clean, i)
                if jm:
                    _register_qualified_table_read(
                        jm.group(1), 'PROC SQL - JOIN', inputs, work_reads, provenance
                    )
                    i = jm.end()
                    continue
            i += 1
