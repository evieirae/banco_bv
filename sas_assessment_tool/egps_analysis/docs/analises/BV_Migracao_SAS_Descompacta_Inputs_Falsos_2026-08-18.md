# Inputs de `%DESCOMPACTA` que nunca são lidos (varredura do corpus)

**Data:** 2026-08-18 · **Corpus:** 1.740 `.txt` em `text_egps/` · **Prod:** `bv_dev_db.monitoramento_sas`

## Pergunta

O extractor registra `LIB.MEMBER` como input toda vez que um EGP chama uma macro estilo
`%DESCOMPACTA(lib, base)` — `x cp …sas7*` + `x gunzip` (ver `_collect_descompacta_style_reads`
em `egps_extractor.py:1066`). O racional é legítimo: depois da cópia a leitura vira
*unqualified* (WORK) e o scan de FROM/JOIN não a apanharia. Mas a regra **não checa se a
base descompactada chega a ser lida**. Ela é input de verdade ou manutenção de disco?

## Método

`docs/analises/descompacta_varredura.py`: para cada entrada com `%DESCOMPACTA` no
`TABLE_READ_PROVENANCE`, procura o membro no corpo do programa em contexto de LEITURA
(`SET`, `FROM`, `JOIN`, `DATA=`, `MERGE`, `UPDATE`, `IN=`, `BASE=`), ignorando as linhas
da própria mecânica (`x cp/gunzip/gzip`, `%DESCOMPACTA(...)`, `%compacta*`, `%let/%macro`).
Segunda passada: quantas vezes o membro aparece em QUALQUER contexto não-mecânico.

## Resultado

| | pares (EGP, input) |
|---|---|
| inputs vindos de `%DESCOMPACTA` | **409** (51 EGPs, 351 tabelas) |
| **nunca lidos** | **321 (78%)** |
| — desses, o nome só existe na mecânica | 271 |
| — desses, aparece em outro contexto (revisar) | 50 |
| lidos depois (input real) | 70 |
| indeterminado (nome com `&macro`) | 18 |

### Impacto em produção

Os 321 pares falsos **estão todos** em `sas_egp_inputs` (291 chaves distintas):

- **313 ainda pendentes** — 305 `A Receber` + 8 `Recebido`; só 8 modernizados.
- **263 exclusivos** do próprio EGP (nenhum outro consumidor) → **261 pendentes e exclusivos**:
  fila de ingestão que existe só por causa da regra.
- Concentração: `Cobranças__Teste_Carta_Cartoraria - Simplificação CP_GCP_V3` sozinho responde
  por 214 — o programa tem **432 chamadas** de `%DESCOMPACTA`, uma para cada safra
  `SATIE.CARTA_TESTE_AAAAMMDD`, num bloco de manutenção de disco.

### Caso examinado à mão (`Cobranças__base_carta_EVG_v4_saidarisco_v2`)

- `PRETER.EMP_2024_BASE_COBRANCA` — descompactada na linha 137, nome não reaparece no programa.
- `SATIE.CAMPANHA_H_EMP_80` — dentro da task "Compacta Bases" (gunzip + gzip de volta), nunca lida.
- `/riscosbv/cobranca/satie/depara_assessoria.sas7bdat` — o gunzip existe, mas o join usa
  `WORK.'DE_PARA_ASSESSORIA 1'n`, vindo do **xlsx**. (Esse é input de ARQUIVO, fora da contagem acima.)

## Recomendação

1. **Extractor** — em `_collect_descompacta_style_reads`, só registrar `LIB.MEMBER` quando o
   membro aparecer depois em contexto de leitura. Vale nas duas cópias (`egps_extractor.py` e
   `app/pipeline/egps_extractor.py`); cobrir com caso novo em `test_descompacta_inputs.py`.
2. **Dado já publicado** — desvincular os 321 pares (link quebrado por (EGP, input)), que é o
   mecanismo existente para "não é input deste EGP" e não depende de re-extração.
3. Revisar à mão os 50 em que o nome aparece fora da mecânica antes de incluí-los no lote.

## Artefatos

- `BV_Migracao_SAS_Descompacta_Inputs_Falsos_2026-08-18.csv` — veredito por (EGP, tabela).
- `BV_Migracao_SAS_Descompacta_Impacto_Prod_2026-08-18.csv` — os 321 pares com etapa e nº de consumidores.
- `descompacta_varredura.py` — script da varredura.
