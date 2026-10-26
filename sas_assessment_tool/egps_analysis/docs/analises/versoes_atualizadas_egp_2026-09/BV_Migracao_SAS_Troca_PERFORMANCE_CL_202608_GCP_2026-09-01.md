# Troca de EGP — PERFORMANCE_CL_202608_GCP.egp

**Antecessor(es) (2):** `PERFORMANCE_CL_202603.egp + PERFORMANCE_CL_202603_REPROC_HIST_EDU.egp` · área Cobranças · pareamento alerta (overlap 68%)

**Valor 43.3 · Esforço 30.2 · razão 1.43 → Não trocar (veto)**

## Vetos

- 1 output(s) removidos com 2+ consumidores externos: PERF_CL.CL_TABLEAU (7 consumidores)

## Alertas (pedem confirmação humana)

- "Cobranças__PERFORMANCE_CL_202603_REPROC_HIST_EDU" está despriorizado: trocar significa devolvê-lo ao backlog — decisão de escopo
- o novo consolida 2 EGPs (Cobranças__PERFORMANCE_CL_202603, Cobranças__PERFORMANCE_CL_202603_REPROC_HIST_EDU): inventário e alcance são a união
- pareamento de confiança média (overlap 69%): confirme que é substituição antes de decidir

## Inventário

| Categoria | Antigo | Novo |
|---|---|---|
| `table_in` total | 50 | 63 |
| ... que exigem ingestão | 46 | 46 |
| ... já disponíveis no destino | 4 | 17 |
| `file_in` | 13 | 4 |
| `script_in` | 0 | 0 |
| outputs | 84 | 98 |
| LOC | 5375 | 7081 |

Churn: +1718 / -12 linhas, 16 tasks novas.

Alcance do antigo: 8 EGPs (8 por dependência, 8 por output).

## Composição do score

| Eixo | Peso | Fração | Pontos |
|---|---|---|---|
| Valor · menos_table_in_a_ingerir | 30 | 0.00 | 0.0 |
| Valor · menos_file_in | 25 | 0.69 | 17.3 |
| Valor · mais_input_disponivel | 20 | 1.00 | 20.0 |
| Valor · alcance | 15 | 0.40 | 6.0 |
| Valor · menos_script_in | 5 | 0.00 | 0.0 |
| Valor · simplificacao | 5 | 0.00 | 0.0 |
| Esforço · churn_codigo | 40 | 0.32 | 12.9 |
| Esforço · inputs_novos_a_ingerir | 30 | 0.00 | 0.0 |
| Esforço · outputs_novos_renomeados | 15 | 0.36 | 5.4 |
| Esforço · deps_novas_egp | 15 | 0.80 | 12.0 |

## Outputs removidos com consumidor

- `PERF_CL.CL_TABLEAU`
