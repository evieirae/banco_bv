# Troca de EGP — processo_carga_score_solar_jul_26_REAPONTADO_PJeOFENS.egp

**Antecessor(es) (1):** `processo_carga_score_solar_jul_25_REAPONTADO_PJeOFENS.egp` · área Cobranças · pareamento alerta (overlap 60%)

**Valor 2.9 · Esforço 12.5 · razão 0.23 → Não trocar (veto)**

## Vetos

- 1 output(s) removidos com 2+ consumidores externos: GRIMALDI.SOLAR_FLEX_MASSIFICADOS_20250211 (3 consumidores)

## Alertas (pedem confirmação humana)

- pareamento de confiança média (overlap 60%): confirme que é substituição antes de decidir

## Inventário

| Categoria | Antigo | Novo |
|---|---|---|
| `table_in` total | 126 | 123 |
| ... que exigem ingestão | 109 | 109 |
| ... já disponíveis no destino | 17 | 14 |
| `file_in` | 3 | 3 |
| `script_in` | 0 | 0 |
| outputs | 137 | 110 |
| LOC | 6892 | 5525 |

Churn: +118 / -1485 linhas, 1 tasks novas.

Alcance do antigo: 3 EGPs (3 por dependência, 3 por output).

## Composição do score

| Eixo | Peso | Fração | Pontos |
|---|---|---|---|
| Valor · menos_table_in_a_ingerir | 30 | 0.00 | 0.0 |
| Valor · menos_file_in | 25 | 0.00 | 0.0 |
| Valor · mais_input_disponivel | 20 | 0.00 | 0.0 |
| Valor · alcance | 15 | 0.15 | 2.2 |
| Valor · menos_script_in | 5 | 0.00 | 0.0 |
| Valor · simplificacao | 5 | 0.13 | 0.7 |
| Esforço · churn_codigo | 40 | 0.23 | 9.3 |
| Esforço · inputs_novos_a_ingerir | 30 | 0.00 | 0.0 |
| Esforço · outputs_novos_renomeados | 15 | 0.01 | 0.2 |
| Esforço · deps_novas_egp | 15 | 0.20 | 3.0 |

## Outputs removidos com consumidor

- `GRIMALDI.SOLAR_FLEX_MASSIFICADOS_20250211`
