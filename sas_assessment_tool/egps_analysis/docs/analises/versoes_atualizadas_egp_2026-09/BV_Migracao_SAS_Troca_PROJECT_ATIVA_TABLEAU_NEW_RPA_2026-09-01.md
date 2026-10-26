# Troca de EGP — PROJECT_ATIVA_TABLEAU_NEW_RPA.egp

**Antecessor(es) (2):** `PROJECT_ATIVA_TABLEAU_NEW_V2_4_vigente.egp + PROJECT_ATIVA_GCP_V2.egp` · área Cobranças · pareamento ok (overlap 90%)

**Valor 37.5 · Esforço 8.0 · razão 4.69 → Não trocar (veto)**

## Vetos

- 1 output(s) removidos com 2+ consumidores externos: ATIVA.BASE_ATIVA_202510 (2 consumidores)

## Alertas (pedem confirmação humana)

- "Cobranças__PROJECT_ATIVA_TABLEAU_NEW_V2_4_vigente" está despriorizado: trocar significa devolvê-lo ao backlog — decisão de escopo
- o novo consolida 2 EGPs (Cobranças__PROJECT_ATIVA_GCP_V2, Cobranças__PROJECT_ATIVA_TABLEAU_NEW_V2_4_vigente): inventário e alcance são a união
- 1 input(s) novos em caminho de rede (normal neste corpus, mas confira se não é planilha manual nova): \\PTA-DFSPRD02\GLOBAL\DVMD\COBRANCA\MIS\COLABORADORES\EDUARDO\MIGRACAO_GCP\CONSULTAS\00_RPA\CREDENCIAIS.CSV

## Inventário

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

## Composição do score

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

## Outputs removidos com consumidor

- `ATIVA.BASE_ATIVA_202510`
