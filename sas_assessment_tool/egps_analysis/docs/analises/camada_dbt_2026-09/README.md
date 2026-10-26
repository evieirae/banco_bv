# Estudo: camada dbt dos EGPs (ago–set/2026)

Classificação de cada EGP na camada dbt provável do modelo final (stg / int / mart)
pela posição no grafo de dependências, e decomposição literal do que cada EGP do
escopo vira na conversão (int compartilhada, mart de BI, incremental com carga
inicial). Sessões de 2026-08-29 a 2026-09-02.

## Artefatos

| Arquivo | Conteúdo |
|---|---|
| `RELATORIO_CAMADA_DBT_ESCOPO_INDIDEPS_2026-08-29.md` | **Relatório principal**: metodologia, resultado por camada, efeito da despriorização, hubs, verificação dos 23 EGPs com 0 outputs (output comentado / guard de macro-var / task morta), caveats e reprodução |
| `BV_Migracao_SAS_Camada_DBT_por_EGP_2026-08-29.csv` | Corpus completo (1.245 EGPs): camada, profundidade no grafo, upstream/downstream, contagens de tabelas |
| `BV_Migracao_SAS_Camada_DBT_Escopo_IndiDeps_2026-08-29.csv` | Escopo indi+deps de prod (185 EGPs): camada, dep_nivel, origem (indicado/dependência), despriorizado, grau no subgrafo |
| `BV_Migracao_SAS_Stg_Decomposicao_Int_Mart_2026-09-02.csv` | Decomposição dos 32 "stg" do escopo: int compartilhadas × exports de BI × acumuladores (17 int pura / 15 int+mart) |
| `BV_Migracao_SAS_Decomposicao_Int_Mart_Ativos_2026-09-02.csv` | **Decomposição final dos 128 EGPs ativos** (sem despriorizados, arestas podadas como no app): forma de conversão (46 mart BI / 27 mart tabela / 26 int+mart / 16 consultivo / 13 int pura), consumidores ativos, cargas iniciais (33 EGPs, 66 tabelas) |

## Achados-chave

- ~70% do escopo termina em mart; a camada compartilhada inteira são 39 EGPs.
- Espinha dorsal: `PERF_AMIGAVEL_gcp` (11 consumidores), `..._ORAHASH` (10),
  `ACORDO_AMIGAVEL_v1__v2` (6).
- Nenhum EGP "stg" do grafo vira `stg_*` de dbt — todos são int pura ou int+mart.
- 33 EGPs têm 66 tabelas acumuladoras (lidas antes de gravadas) → modelos
  incrementais com backfill obrigatório do SAS.
- Consultivos (16): materializar como `view` (intermediários ephemeral); 5 deles
  aguardam verificação de output comentado (Marlon, Slack 2026-09-02).
- `Reneg_Over30e90_Ever30_v2` tem output real invisível no monitor (guard
  `'&' in a` do publish). Fix candidato: publicar o padrão com placeholder
  (`CUBO_OVER30_{SAFRA_M1}`, como os DYNAMIC REFS de leitura) — **não** resolver
  a macro: output safrado, nome resolvido = chave instável a cada Processar.

## Fonte dos dados

Grafo/status: `bv_dev_db.monitoramento_sas` (snapshot 2026-08-29 a 09-02, queries
read-only). Inventário/código: `text_egps/*.txt` + `.egp` brutos em `received_egps/`
(extração 2026-08-21, branch `fix/exporttask-files-not-outputs`).
