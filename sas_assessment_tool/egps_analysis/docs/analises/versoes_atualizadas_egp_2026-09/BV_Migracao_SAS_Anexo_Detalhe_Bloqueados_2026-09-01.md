# Anexo — detalhe dos EGPs bloqueados e do par não resolvido

Rodada de 01/09/2026. Um bloco por EGP, do impacto maior para o menor: os 7 vetados e o 1 com antecessor desconhecido. EGPs sem veto não têm bloco aqui — o CSV consolidado tem a linha completa dos 30.

---

## PERFORMANCE_CL_202608_GCP.egp

**Antecessor(es) (2):** `PERFORMANCE_CL_202603.egp + PERFORMANCE_CL_202603_REPROC_HIST_EDU.egp` · área Cobranças · pareamento alerta (overlap 68%)

**Valor 43.3 · Esforço 30.2 · razão 1.43 → Não trocar (veto)**

### Vetos

- 1 output(s) removidos com 2+ consumidores externos: PERF_CL.CL_TABLEAU (7 consumidores)

### Alertas (pedem confirmação humana)

- "Cobranças__PERFORMANCE_CL_202603_REPROC_HIST_EDU" está despriorizado: trocar significa devolvê-lo ao backlog — decisão de escopo
- o novo consolida 2 EGPs (Cobranças__PERFORMANCE_CL_202603, Cobranças__PERFORMANCE_CL_202603_REPROC_HIST_EDU): inventário e alcance são a união
- pareamento de confiança média (overlap 69%): confirme que é substituição antes de decidir

### Inventário

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

### Composição do score

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

### Outputs removidos com consumidor

- `PERF_CL.CL_TABLEAU`

---

## Performance_Saldo_COLORE_GCP_AJUSTECL_3040_Lite_V5.egp

**Antecessor(es) (1):** `Performance_Saldo_COLORE_GCP_AJUSTECL_3040_Lite_V5.egp` · área Cobranças · pareamento nome_igual (overlap 86%)

**Valor 20.9 · Esforço 19.4 · razão 1.08 → Não trocar (veto)**

### Vetos

- 1 output(s) removidos com 2+ consumidores externos: PAGOSCBR.PAGOS_CYBER_202603 (3 consumidores)

### Inventário

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

### Composição do score

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

### Outputs removidos com consumidor

- `PAGOSCBR.PAGOS_CYBER_202603`

---

## processo_carga_score_solar_jul_26_REAPONTADO_PJeOFENS.egp

**Antecessor(es) (1):** `processo_carga_score_solar_jul_25_REAPONTADO_PJeOFENS.egp` · área Cobranças · pareamento alerta (overlap 60%)

**Valor 2.9 · Esforço 12.5 · razão 0.23 → Não trocar (veto)**

### Vetos

- 1 output(s) removidos com 2+ consumidores externos: GRIMALDI.SOLAR_FLEX_MASSIFICADOS_20250211 (3 consumidores)

### Alertas (pedem confirmação humana)

- pareamento de confiança média (overlap 60%): confirme que é substituição antes de decidir

### Inventário

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

### Composição do score

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

### Outputs removidos com consumidor

- `GRIMALDI.SOLAR_FLEX_MASSIFICADOS_20250211`

---

## Campanha_Entrega_amigavel_v4_mensal_gcp.egp

**Antecessor(es) (1):** `Campanha_Entrega_amigavel_v4_mensal_gcp.egp` · área Cobranças · pareamento nome_igual (overlap 92%)

**Valor 1.5 · Esforço 8.8 · razão 0.17 → Não trocar (veto)**

### Vetos

- 1 output(s) removidos com 2+ consumidores externos: ENTREGA.BASE_ELEG_110226 (2 consumidores)

### Inventário

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

### Composição do score

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

### Outputs removidos com consumidor

- `ENTREGA.BASE_ELEG_110226`

---

## Oportunidade Protesto_20260703.egp

**Antecessor(es) (1):** `Oportunidade Protesto - Piloto de Ajuizamento_GCP.egp` · área Cobranças · pareamento ok (overlap 86%)

**Valor 26.9 · Esforço 8.3 · razão 3.24 → Não trocar (veto)**

### Vetos

- 1 output(s) removidos com 2+ consumidores externos: KEVIN.PUBLICO_PROTESTO_20260210 (2 consumidores)

### Inventário

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

### Composição do score

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

### Outputs removidos com consumidor

- `KEVIN.PUBLICO_PROTESTO_20260210`

---

## PROJECT_ATIVA_TABLEAU_NEW_RPA.egp

**Antecessor(es) (2):** `PROJECT_ATIVA_TABLEAU_NEW_V2_4_vigente.egp + PROJECT_ATIVA_GCP_V2.egp` · área Cobranças · pareamento ok (overlap 90%)

**Valor 37.5 · Esforço 8.0 · razão 4.69 → Não trocar (veto)**

### Vetos

- 1 output(s) removidos com 2+ consumidores externos: ATIVA.BASE_ATIVA_202510 (2 consumidores)

### Alertas (pedem confirmação humana)

- "Cobranças__PROJECT_ATIVA_TABLEAU_NEW_V2_4_vigente" está despriorizado: trocar significa devolvê-lo ao backlog — decisão de escopo
- o novo consolida 2 EGPs (Cobranças__PROJECT_ATIVA_GCP_V2, Cobranças__PROJECT_ATIVA_TABLEAU_NEW_V2_4_vigente): inventário e alcance são a união
- 1 input(s) novos em caminho de rede (normal neste corpus, mas confira se não é planilha manual nova): \\PTA-DFSPRD02\GLOBAL\DVMD\COBRANCA\MIS\COLABORADORES\EDUARDO\MIGRACAO_GCP\CONSULTAS\00_RPA\CREDENCIAIS.CSV

### Inventário

| Categoria | Antigo | Novo |
|---|---|---|
| `table_in` total | 28 | 11 |
| ... que exigem ingestão | 17 | 10 |
| ... já disponíveis no destino | 11 | 1 |
| `file_in` | 4 | 1 |
| `script_in` | 0 | 0 |
| outputs | 51 | 40 |
| LOC | 1654954 | 1655577 |

Churn: +768 / -145 linhas, 4 tasks novas.

Alcance do antigo: 8 EGPs (8 por dependência, 6 por output).

### Composição do score

| Eixo | Peso | Fração | Pontos |
|---|---|---|---|
| Valor · menos_table_in_a_ingerir | 30 | 0.41 | 12.4 |
| Valor · menos_file_in | 25 | 0.75 | 18.8 |
| Valor · mais_input_disponivel | 20 | 0.00 | 0.0 |
| Valor · alcance | 15 | 0.40 | 6.0 |
| Valor · menos_script_in | 5 | 0.00 | 0.0 |
| Valor · simplificacao | 5 | 0.07 | 0.4 |
| Esforço · churn_codigo | 40 | 0.00 | 0.0 |
| Esforço · inputs_novos_a_ingerir | 30 | 0.00 | 0.0 |
| Esforço · outputs_novos_renomeados | 15 | 0.33 | 5.0 |
| Esforço · deps_novas_egp | 15 | 0.20 | 3.0 |

### Outputs removidos com consumidor

- `ATIVA.BASE_ATIVA_202510`

---

## Project_Atualiza_Bases_Auxiliares_GCP_Inc_Cadu_HUB.egp

**Antecessor(es) (1):** `Project_Atualiza_Bases_Auxiliares_GCP_Inc_Desconto_ORAHASH.egp` · área — · pareamento recusado (overlap 31%)

**Par não resolvido** — sem score calculado, porque o inventário dos dois lados não pôde ser comparado.

### Alertas (pedem confirmação humana)

- overlap 31% < 40%: provável biblioteca compartilhada, não substituição. Informe --antigo se for par real.

---

## Project_Compensacao_Encargos_v1.egp

**Antecessor(es) (1):** `Project_Compensacao_Encargos_v1.egp` · área Cobranças · pareamento nome_igual (overlap 80%)

**Valor 0.0 · Esforço 0.0 · razão 0.0 → Não trocar (veto)**

### Vetos

- "Cobranças__Project_Compensacao_Encargos_v1" já convertido: etapa "Validação da Área" com status "Em Andamento" — trocar joga trabalho fora

### Inventário

| Categoria | Antigo | Novo |
|---|---|---|
| `table_in` total | 2 | 2 |
| ... que exigem ingestão | 0 | 0 |
| ... já disponíveis no destino | 2 | 2 |
| `file_in` | 1 | 1 |
| `script_in` | 0 | 0 |
| outputs | 1 | 1 |
| LOC | 616 | 616 |

Churn: +4 / -4 linhas, 0 tasks novas.

Alcance do antigo: 0 EGPs (0 por dependência, 0 por output).

### Composição do score

| Eixo | Peso | Fração | Pontos |
|---|---|---|---|
| Valor · menos_table_in_a_ingerir | 30 | 0.00 | 0.0 |
| Valor · menos_file_in | 25 | 0.00 | 0.0 |
| Valor · mais_input_disponivel | 20 | 0.00 | 0.0 |
| Valor · alcance | 15 | 0.00 | 0.0 |
| Valor · menos_script_in | 5 | 0.00 | 0.0 |
| Valor · simplificacao | 5 | 0.00 | 0.0 |
| Esforço · churn_codigo | 40 | 0.00 | 0.0 |
| Esforço · inputs_novos_a_ingerir | 30 | 0.00 | 0.0 |
| Esforço · outputs_novos_renomeados | 15 | 0.00 | 0.0 |
| Esforço · deps_novas_egp | 15 | 0.00 | 0.0 |

