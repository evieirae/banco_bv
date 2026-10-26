# Plano: junção produtor×consumidor via arquivos com macro

**Contexto (2026-08-07).** Handoffs EGP→EGP via arquivo exportado/importado estão quase todos invisíveis no grafo: no dev, 356 file-outs e 229 file-ins com macro no nome produzem **zero** matches exatos. Casos reais confirmados por análise manual: `desconto_cobranca_&DIA_EXEC._RODAS.csv` (produtor) lido como `desconto_cobranca_&dia._RODAS.csv` por 4+ consumidores; `ARQUIVO_BEHAVIOUR_&SAFRA..TXT` → `&SAFRAM1..TXT` (dependência temporal no mesmo EGP).

## Por que o match exato falha

1. **Escape divergente**: inputs guardam a macro HTML-escapada (`&AMP;DIA.`), outputs guardam crua (`&DIA_EXEC.`).
2. **Macros com nomes diferentes** que resolvem pro mesmo valor (`&DIA_EXEC.` vs `&DIA.`).
3. **Identidade por basename**: a chave `arquivo::BASENAME` perde o diretório → homônimos falsos (caso `REGRAS`: 44 pares cartesianos em Riscos) e impossibilidade de distinguir cópias em dirs distintos.
4. **Indireção por macro de caminho**: `INFILE "&base_robbu"` só se resolve com o `%LET` correspondente.

## O que a extração (.txt) já fornece — verificado, dispensa voltar ao .egp

| Fonte no .txt | O que dá |
|---|---|
| `EXPORTED FILES (Artifacts)` | caminho **completo** de cada export, macro literal preservada |
| `IMPORTED FILES` / `EXTERNAL FILE PATHS` | caminho completo dos imports (escapado com `&amp;`) |
| `[[ PROJECT LETS ]]` | `%LET` globais, inclusive macros de caminho (`%LET base_robbu=/riscosbv/...csv`) |
| Corpo das tasks | statements `OUTFILE=`/`INFILE`/`FILENAME` completos e `%LET` locais |
| `DYNAMIC REFS (Ambiguous)` | refs que o extractor já sabe que não resolveu |

Verificação feita no caso `desconto_cobranca`: produtor (`Elegibilidade_Gradativo_...Expansao_custas.txt` linha 41 e OUTFILEs 1687/1699) e consumidor (`Validacao_boletos - V6.txt` linhas 32/47) têm caminho completo e o %LET de indireção. **Fallback** (só se aparecer caso sem path no header): o corpo da task tem o statement; reabrir o `.egp` é último recurso e não deve ser necessário.

## Desenho da junção — camadas de confiança

**Normalização comum**: unescape `&AMP;`→`&`; uppercase; separar `dir` e `nome` pelo path do .txt; expandir macros **estáticas** (caminho/prefixo) via `%LET` do próprio EGP, iterativo até ponto fixo (PROJECT LETS + %LETs do corpo); macros **voláteis** (datas, sequenciais) viram curinga `#` no *skeleton* (`&MACRO.` → `#`).

| Nível | Chave | Confiança |
|---|---|---|
| 1 | `(dir_resolvido, skeleton_nome)` iguais nos dois lados | alta — vira aresta |
| 2 | `skeleton_nome` igual, dir de um lado não resolvido | média — aresta com flag |
| 3 | basename exato sem dir (match atual) | baixa — só exibição, flag |

**Guardas anti-falso-merge** (justificadas aqui porque a identidade é por nome, o caso análogo ao bloco basename `.sas7bdat` do orquestrador — que tem guardas — e não ao caso `(path, member)` que não precisa delas):
- skeleton com < 10 caracteres úteis (fora curingas) → rejeita;
- skeleton só-curinga ou sem extensão reconhecível (caso `REGRAS`) → rejeita nos níveis 1–2, marca `suspeito` no 3;
- fan-out cap por arquivo (ex.: > 10 produtores×consumidores) → rebaixa para nível 3.

## Onde implementar

1. **`egps_extractor.py`** — emitir, por file in/out, campos adicionais: `path_bruto`, `dir_resolvido`, `nome_skeleton`, `macros_no_nome` (bloco novo no header ou colunas no inventário). Mudança **aditiva**; nada do formato atual muda.
2. **`orchestrator_inventory.py`** — nova passada de recuperação de arestas por arquivo, **aditiva** (mesmo espírito da recuperação por path físico — só adiciona, nunca remove), gerando pares com coluna `confianca` (1/2/3). Alimenta `03_matriz_dependencias` com `Via` tipo arquivo.
3. **Publish/app** — expor as arestas `categoria=arquivo` com `confianca`. Decisão de produto: **não** entram no fecho de bloqueio/dependência por default (só exibição), até a precisão ser validada em corpus real; promover nível 1 ao grafo é um segundo passo consciente.

## Validação (golden set + métricas)

- `desconto_cobranca_#_RODAS.CSV`: deve casar **só** a cópia `/ksilvestre/` com os consumidores (nível 1); a cópia `/gradativo/` fica sem consumidor.
- `ARQUIVO_BEHAVIOUR_#.TXT`: casa no mesmo dir, mesmo EGP → releitura temporal (não dependência).
- `REGRAS`: não pode gerar aresta nível 1–2; os 44 pares atuais têm que cair para nível 3/suspeito.
- Métricas de corpus: nº de arestas por nível; amostra manual de ~20 pares nível 1 (meta: 0 falso-positivo); diff das arestas de tabela antes/depois = **zero** (a passada é aditiva).

## Fases e esforço

1. **Levantamento** (½ dia): cobertura no corpus — % de EGPs com PROJECT LETS, % de file-refs com path completo, distribuição de macros voláteis vs estáticas.
2. **Extractor** (1 dia): campos novos + testes nos 3 casos golden.
3. **Orquestrador** (1 dia): passada aditiva + guardas + CSV com confiança.
4. **Validação manual** (½ dia) e decisão de promover nível 1 ao grafo/app.

## Execução (2026-08-10) — fases 1–3 concluídas

**Fase 1 (medida):** 1.741 EGPs; 7.652 file-refs únicas, **99% com path completo**;
15% com macro, das quais 51% resolvem 100% por %LET do próprio EGP (660 só
estáticas vs 450 só datas). Armadilha achada: `&C` (342x) é `&` literal em nomes
("M&C") — o parser exige terminador `.` ou nome ≥2 chars.

**Arquitetura (desvio consciente do plano):** a lógica vive num módulo
compartilhado `macro_file_refs.py` que parseia os headers dos **.txt existentes**
(EXPORTED/IMPORTED FILES + %LETs) — dispensa re-extração dos 1.741 EGPs. O
extractor também emite a seção `[[ FILE_REFS_MACRO ]]` p/ extrações futuras.
As arestas saem num **CSV novo** (`08_arestas_arquivo.csv`) em vez de coluna no
03 — schema do 03 intocado até a decisão de promoção.

**Fase 3 (resultado no corpus):** 201 pares — **145 nível 1** (51 cross-EGP em
22 arquivos distintos), 6 nível 2, 50 nível 3. Fan-out cap refinado na validação:
só conta pares SEM confirmação de diretório (nível 1 é isento — senão hubs
legítimos como o desconto_cobranca, 15 vias reais, eram rebaixados).

**Golden cases:** desconto_cobranca ✅ 15 pares N1 só na cópia `/ksilvestre/`;
REGRAS ✅ contido no N3 (20 pares, todos `generico`); ARQUIVO_BEHAVIOUR **revisado**
— a ref `&SafraM1.` é `x rm` (deleção), não leitura; a aresta NÃO deve existir e
não existe (o parser lê só IMPORTED FILES/EXTERNAL FILE PATHS de propósito —
`[CODE REF]` mistura reads/writes/deletes). Diff dos relatórios 01–06 baseline
vs novo: **zero**.

**Pendente:** fase 4 ampliada (revisão humana dos 51 pares N1 cross-EGP),
persistência no publish/app (aba Macros ainda calcula nível 2/3 on-the-fly) e
decisão de promover nível 1 ao grafo.

*Análise exploratória que originou este plano: cruzamento em `Downloads/cruzamento_produtor_consumidor_corrigido.csv` (linhas `arquivo (macro)`), sessão de 2026-08-07.*
