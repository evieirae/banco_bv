# Troca de EGP — Oportunidade Protesto_20260703.egp

**Antecessor(es) (1):** `Oportunidade Protesto - Piloto de Ajuizamento_GCP.egp` · área Cobranças · pareamento ok (overlap 86%)

**Valor 26.9 · Esforço 8.3 · razão 3.24 → Não trocar (veto)**

## Vetos

- 1 output(s) removidos com 2+ consumidores externos: KEVIN.PUBLICO_PROTESTO_20260210 (2 consumidores)

## Inventário

| Categoria | Antigo | Novo |
|---|---|---|
| `table_in` total | 5 | 4 |
| ... que exigem ingestão | 1 | 1 |
| ... já disponíveis no destino | 4 | 3 |
| `file_in` | 2 | 0 |
| `script_in` | 0 | 0 |
| outputs | 17 | 13 |
| LOC | 1706 | 1585 |

Churn: +7 / -128 linhas, 0 tasks novas.

Alcance do antigo: 2 EGPs (2 por dependência, 2 por output).

## Composição do score

| Eixo | Peso | Fração | Pontos |
|---|---|---|---|
| Valor · menos_table_in_a_ingerir | 30 | 0.00 | 0.0 |
| Valor · menos_file_in | 25 | 1.00 | 25.0 |
| Valor · mais_input_disponivel | 20 | 0.00 | 0.0 |
| Valor · alcance | 15 | 0.10 | 1.5 |
| Valor · menos_script_in | 5 | 0.00 | 0.0 |
| Valor · simplificacao | 5 | 0.08 | 0.4 |
| Esforço · churn_codigo | 40 | 0.00 | 0.0 |
| Esforço · inputs_novos_a_ingerir | 30 | 0.00 | 0.0 |
| Esforço · outputs_novos_renomeados | 15 | 0.35 | 5.3 |
| Esforço · deps_novas_egp | 15 | 0.20 | 3.0 |

## Outputs removidos com consumidor

- `KEVIN.PUBLICO_PROTESTO_20260210`
