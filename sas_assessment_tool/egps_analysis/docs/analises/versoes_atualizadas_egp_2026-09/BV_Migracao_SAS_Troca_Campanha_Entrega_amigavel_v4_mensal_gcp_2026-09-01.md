# Troca de EGP — Campanha_Entrega_amigavel_v4_mensal_gcp.egp

**Antecessor(es) (1):** `Campanha_Entrega_amigavel_v4_mensal_gcp.egp` · área Cobranças · pareamento nome_igual (overlap 92%)

**Valor 1.5 · Esforço 8.8 · razão 0.17 → Não trocar (veto)**

## Vetos

- 1 output(s) removidos com 2+ consumidores externos: ENTREGA.BASE_ELEG_110226 (2 consumidores)

## Inventário

| Categoria | Antigo | Novo |
|---|---|---|
| `table_in` total | 32 | 32 |
| ... que exigem ingestão | 19 | 19 |
| ... já disponíveis no destino | 13 | 13 |
| `file_in` | 8 | 8 |
| `script_in` | 0 | 0 |
| outputs | 70 | 70 |
| LOC | 8512 | 9921 |

Churn: +1526 / -117 linhas, 1 tasks novas.

Alcance do antigo: 2 EGPs (2 por dependência, 2 por output).

## Composição do score

| Eixo | Peso | Fração | Pontos |
|---|---|---|---|
| Valor · menos_table_in_a_ingerir | 30 | 0.00 | 0.0 |
| Valor · menos_file_in | 25 | 0.00 | 0.0 |
| Valor · mais_input_disponivel | 20 | 0.00 | 0.0 |
| Valor · alcance | 15 | 0.10 | 1.5 |
| Valor · menos_script_in | 5 | 0.00 | 0.0 |
| Valor · simplificacao | 5 | 0.00 | 0.0 |
| Esforço · churn_codigo | 40 | 0.19 | 7.7 |
| Esforço · inputs_novos_a_ingerir | 30 | 0.00 | 0.0 |
| Esforço · outputs_novos_renomeados | 15 | 0.07 | 1.1 |
| Esforço · deps_novas_egp | 15 | 0.00 | 0.0 |

## Outputs removidos com consumidor

- `ENTREGA.BASE_ELEG_110226`
