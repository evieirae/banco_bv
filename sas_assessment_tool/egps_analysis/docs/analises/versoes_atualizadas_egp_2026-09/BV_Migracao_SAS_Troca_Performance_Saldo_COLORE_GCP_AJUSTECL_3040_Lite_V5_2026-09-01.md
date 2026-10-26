# Troca de EGP — Performance_Saldo_COLORE_GCP_AJUSTECL_3040_Lite_V5.egp

**Antecessor(es) (1):** `Performance_Saldo_COLORE_GCP_AJUSTECL_3040_Lite_V5.egp` · área Cobranças · pareamento nome_igual (overlap 86%)

**Valor 20.9 · Esforço 19.4 · razão 1.08 → Não trocar (veto)**

## Vetos

- 1 output(s) removidos com 2+ consumidores externos: PAGOSCBR.PAGOS_CYBER_202603 (3 consumidores)

## Inventário

| Categoria | Antigo | Novo |
|---|---|---|
| `table_in` total | 65 | 74 |
| ... que exigem ingestão | 54 | 63 |
| ... já disponíveis no destino | 11 | 11 |
| `file_in` | 21 | 6 |
| `script_in` | 0 | 0 |
| outputs | 75 | 80 |
| LOC | 8526 | 9240 |

Churn: +807 / -93 linhas, 6 tasks novas.

Alcance do antigo: 4 EGPs (4 por dependência, 4 por output).

## Composição do score

| Eixo | Peso | Fração | Pontos |
|---|---|---|---|
| Valor · menos_table_in_a_ingerir | 30 | 0.00 | 0.0 |
| Valor · menos_file_in | 25 | 0.71 | 17.8 |
| Valor · mais_input_disponivel | 20 | 0.00 | 0.0 |
| Valor · alcance | 15 | 0.20 | 3.0 |
| Valor · menos_script_in | 5 | 0.00 | 0.0 |
| Valor · simplificacao | 5 | 0.00 | 0.0 |
| Esforço · churn_codigo | 40 | 0.11 | 4.2 |
| Esforço · inputs_novos_a_ingerir | 30 | 0.17 | 5.0 |
| Esforço · outputs_novos_renomeados | 15 | 0.08 | 1.2 |
| Esforço · deps_novas_egp | 15 | 0.60 | 9.0 |

## Outputs removidos com consumidor

- `PAGOSCBR.PAGOS_CYBER_202603`
