# Inputs declarados que a lógica não usa — verificação automática

**Data:** 2026-08-18 · **Demanda:** Michelli — "cada pessoa abre o EGP e confere se todos os
inputs são realmente usados pela lógica" · **Base:** 1.740 EGPs extraídos (`text_egps/`) +
inventário de produção (`bv_dev_db.monitoramento_sas`)

## Resumo

Parte dessa conferência dá para fazer por código, e já foi feita: **106 inputs de tabela do
escopo, em 15 EGPs, são declarados como input mas nunca lidos pela lógica**. Eles entram na
fila de ingestão sem necessidade. Tirar esses vínculos reduz em **31% as pendências desses
15 EGPs** (330 → 225) e deixa **2 EGPs com zero pendência**.

A conferência manual continua necessária, mas deve mirar onde o código não alcança: os
**771 inputs de arquivo** cujo import vem de task wizard do EG e não aparece no texto extraído.

## Como a verificação automática funciona

O extractor registra, para cada input, **como** ele foi detectado (`TABLE_READ_PROVENANCE`).
Levantamos os 53 rótulos existentes no corpus: todos são contexto de leitura — `PROC SQL - FROM`,
`DATA Step - SET`, `PROC SORT - DATA=`, `MERGE`, `PROC EXPORT - DATA=`, pass-through nativo,
`Resolved dynamic lib.member&macro (%LET)` etc. — **com uma exceção**: a família
`%DESCOMPACTA` / `%COPIA_DESCOMPACTA`, que só copia arquivo (`x cp` + `x gunzip`) para a WORK.

Daí o critério, sem heurística: **input cuja única proveniência é essa cópia mecânica e cujo
nome não reaparece em nenhum `SET`/`FROM`/`JOIN`/`DATA=`/`MERGE` do programa não é usado.**

## Resultados

### Escopo Indicium (168 EGPs)

**106 inputs não usados, em 15 EGPs** — 105 ainda pendentes, 48 exclusivos (nenhum outro EGP os
consome, então somem do corpus ao desvincular).

| EGP | não usados | pendências antes → depois |
|---|---|---|
| Código Elegibilidade Acima de 120D | 36 | 71 → 35 |
| 1.REG_CARTEIRA_WO | 12 | 18 → 6 |
| Fase Administrativa - Novo Processo_v20260227_GCP | 10 | 90 → 80 |
| 2. ESTUDO_CUSTAS_TOTAL | 9 | 15 → 6 |
| 3.ESTUDO_ISENC_CUSTAS_TOTAL | 9 | 15 → 6 |
| 8.2 VEIC_ALTO_VLR_V3 | 9 | 15 → 6 |
| 16. PROTESTOS_VS_AJU | 5 | 11 → 6 |
| Construcao_carteira_Risco | 4 | 30 → 26 |
| Safra e Carteira Ajuizamento Reapontado | 3 | 7 → 4 |
| PROJECT_LINHAS_QIKVIEW_V5_RPA · Painel_Desconto_3040_Edu · base_carta_EVG_v4_saidarisco_v2 | 2 cada | — |
| Avaliacao_modelos_v3 · Elegibilidade menor que 90_GCP_v4 · Rastreador_v8_corr_tb_taylor_vf | 1 cada | — |

**Total: 330 → 225 pendências (−105, −31%).** Zeram a pendência: `Avaliacao_modelos_v3` e
`base_carta_EVG_v4_saidarisco_v2` — os dois estavam travados só por inputs que o código não lê.

### Corpus inteiro

409 inputs vêm da família `%DESCOMPACTA`, em 51 EGPs. **321 (78%) nunca são lidos** — 271 deles
sequer aparecem fora das linhas de `x cp`/`gunzip`. Os 321 estão todos no inventário de produção;
313 seguem pendentes.

Concentração: `Teste_Carta_Cartoraria - Simplificação CP_GCP_V3` responde por 214, com **432
chamadas** de `%DESCOMPACTA` — uma por safra `SATIE.CARTA_TESTE_AAAAMMDD`, num bloco de
manutenção de disco.

### Bloqueio: sem efeito

105 dos 106 são `SAS/Local (externo)`, sem produtor e não modernizados — perfil de input que
trava o EGP. Ainda assim, só 2 EGPs deixam de ser folha bloqueante e **nenhum desbloqueio se
propaga** (160 bloqueados antes e depois, no recorte de 206). Os outros 13 seguem travados por
inputs SAS/Local legítimos. O ganho é de fila e de precisão do inventário, não de funil.

> Cálculo feito sobre o grafo bruto de produção, sem a poda de produtor canônico/vias resolvidas
> que o app aplica — o total absoluto difere do que a tela mostra; o **delta** é o que vale.

## O ponto cego: inputs de arquivo (xlsx/csv)

No recorte escopo + dependências (206 EGPs), dos 874 inputs de arquivo:

| | |
|---|---|
| **indecidíveis** — import não está no código (task wizard do EG) | **771 (88%)** |
| usados (alvo WORK lido depois · grava tabela permanente · INFILE/libname xlsx) | 75 |
| scripts `%INCLUDE` | 26 |
| não usados | 2 (ambos fora do escopo e já modernizados) |

O `PROC IMPORT` grava com nome próprio — em `Distribuidor_PF`, `Filtro_PV_INSS.xlsx` vira
`CARGAPF.FILTRO_PRIVADO_INSS`, biblioteca permanente. Onde o import está no código, o parse de
`OUT=`/`DATAFILE=` resolve. Onde ele veio do wizard, **não há texto para julgar**: no
`base_carta_EVG_v4_saidarisco_v2`, `Base_RS.xlsx` vira uma tabela e a string `Base_RS` não
aparece uma única vez no corpo do programa.

**É aqui que a conferência manual rende.** Automatizar exige o extractor emitir o código das
tasks de import (o par arquivo→tabela está no `project.xml` do `.egp`).

## Roteiro para quem for abrir o EGP

1. Abra o `.txt` em `text_egps/<Área>__<Projeto>.txt` — é o programa inteiro, na ordem de execução.
2. Pegue a lista de `IMPORTED FILES (Requires Ingestion)` no cabeçalho: são os arquivos.
3. Para cada um, procure no corpo o `PROC IMPORT` correspondente e anote o `OUT=`.
   - Sem `PROC IMPORT` no texto → o import é wizard; abra a task no EG para ver o destino.
4. Procure esse destino (`OUT=`) em `SET`/`FROM`/`JOIN`/`DATA=`/`MERGE`.
   - Não achou, e o destino é `WORK.` → **input não usado**, registre.
   - Destino em biblioteca permanente → é usado (materializa tabela).
5. As tabelas já foram conferidas por código — não precisa refazer.

## O que fazer com o resultado

1. **Desvincular** os 106 pares no app (vínculo quebrado por EGP+input) — mecanismo que já existe,
   não depende de re-extração. Sai da fila sem apagar nada.
2. **Corrigir o extractor**: `_collect_descompacta_style_reads` (`egps_extractor.py:1066`) só deve
   registrar `LIB.MEMBER` quando a base descompactada for lida depois. Vale nas duas cópias
   (canônica e `app/pipeline/`), com caso novo em `test_descompacta_inputs.py`.
3. **Emitir as tasks de import** no extractor, para tirar os 771 do ponto cego.

## Anexos

- `BV_Migracao_SAS_Escopo_Inputs_Nao_Usados_2026-08-18.csv` — os 106 do escopo, com etapa, nº de consumidores e vínculo.
- `BV_Migracao_SAS_Inputs_Nao_Usados_2026-08-18.csv` — os 321 do corpus inteiro.
- `BV_Migracao_SAS_Recorte_Arquivos_Nao_Usados_2026-08-18.csv` — a rodada de arquivos.
- `BV_Migracao_SAS_Descompacta_Impacto_Prod_2026-08-18.csv` — impacto em produção por par.
- `descompacta_varredura.py` — script da varredura.
