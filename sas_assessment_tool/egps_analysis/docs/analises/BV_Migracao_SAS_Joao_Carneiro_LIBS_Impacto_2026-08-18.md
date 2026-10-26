# Impacto da triagem de inputs do João Carneiro (LIBS) nas métricas do projeto

**Data:** 2026-08-18
**Fonte:** `João Carneiro_LIBS - Planilha1.csv` (153 linhas, 9 EGPs, área Cobrança, todos sob
responsabilidade de Joao Carneiro)
**Base de comparação:** painel de monitoramento SAS, produção (`bv_dev_db.monitoramento_sas`),
leitura de 2026-08-18
**Arquivo desta análise:** `BV_Migracao_SAS_Joao_Carneiro_LIBS_Impacto_2026-08-18.csv` — as 153
linhas do CSV original, com o status atual do painel, quantos EGPs leem cada tabela, quais áreas a
consomem, o tier da auditoria de 17/08 quando existe, e uma coluna `Risco` com os alertas descritos
abaixo.

## 0. O que é o CSV

João Carneiro (responsável pelos 9 EGPs) triou, tabela a tabela, os inputs "SAS/Local" (dependência
ou externo) de cada um dos seus EGPs: `Atualiza_UF_Cartoes`, `Carteira_CA_COMPLETA_GCP_2`,
`Carteira_Envio_Protesto_Solar_GCP`, `CPF_Contrato`, `Estrategia_Reneg_Solar_180_v20250305_GCP`,
`Marcacao_Teste_IOF_GCP`, `Oportunidade Protesto - Piloto de Ajuizamento_GCP`,
`processo_carga_score_solar_jul_25_REAPONTADO_PJeOFENS` e `Regularizacao_Mensal_EDU_GCP`. Todos os
9 já estão no escopo do plano (`escopo_indi = true`), com mês 1/2/3 (Julho/Agosto/Setembro) batendo
exatamente com a coluna "Priorização" do CSV e `responsavel_bv = "Joao Carneiro"` no painel — não há
dúvida de identidade dos EGPs.

Para cada tabela ele decidiu **Ingerir? SIM/NÃO** e, quando NÃO, descreveu o comportamento esperado
do EGP sem aquele input.

## 1. Números

| | |
|---|---:|
| Linhas do CSV | 153 |
| Artefatos distintos | 145 |
| SIM (ingerir) | 32 |
| NÃO (não ingerir) | 121 (117 artefatos distintos) |

**Dos 117 artefatos marcados NÃO, 116 estão hoje "A receber" no painel** (1 já "Recebido"). Ou
seja, **nenhuma dessas decisões foi refletida ainda no `status_humano`** — a triagem existe só no
CSV. Se aplicada tal como está, ela tira até **116 tabelas físicas da fila de pendências**, hoje em
**1.578 "A receber"** no escopo do plano — **7,3% da fila inteira**, vindos da revisão de apenas 9
EGPs de um único responsável.

## 2. As justificativas do "NÃO" não são todas a mesma coisa

| Justificativa | Linhas | Significado |
|---|---:|---|
| "Deixar somente últimos 12M" | 80 | Janela de retenção — carga inicial limitada, não descarte |
| "Deixar somente últimos 3M" | 19 | Idem, janela mais curta |
| "Ignorar" | 14 | Dispensa real, sem contrapartida |
| "Não é necessário nesse processo" | 5 | Dispensa específica deste EGP consumidor |
| "Base não é da cobrança, consumimos em alguns processos" | 2 | Compartilhado com outras áreas |
| "Consumimos outra base de Renda para SOLAR (GCP)" | 1 | Fonte trocada, não é mais dependência real |

**99 das 121 linhas "NÃO" (82%) são janela de retenção, não "não precisa nunca".** O comportamento
descrito por João para essas tabelas é: ingerir só os últimos 12 (ou 3) meses de safra, e as safras
mais antigas que a janela — não a tabela inteira — é que ficam de fora. Isso aparece na prática: a
família `GRIMALDI.SOLAR_(FLEX_)MASSIFICADOS_AAAAMMDD` tem **as mesmas tabelas** com **SIM** para as
safras dos últimos 12 meses e **NÃO** para as safras mais antigas — é uma política de retenção
aplicada tabela a tabela, não uma dispensa da família inteira.

## 3. Isso confirma e refina a auditoria de ordem de código de 17/08

O relatório `BV_Migracao_SAS_Inputs_Sem_Ingestao_2026-08-17.md` já tinha identificado, por auditoria
automática do código SAS, que `processo_carga_score_solar_jul_25_REAPONTADO_PJeOFENS` era a maior
concentração de tabelas Tier 3 ("exige carga inicial", 97 tabelas) — casos em que a tabela carrega
histórico e nenhum EGP do plano a recria do zero. A pergunta que ficava em aberto era **quanto** de
histórico essa carga inicial precisa.

Cruzando as 153 linhas do CSV do João com aquele relatório (128 das 153 aparecem lá): **86 das
linhas "NÃO" do João caem exatamente no Tier 3** do relatório automático. Não é contradição — é a
resposta que faltava. João está dizendo, tabela por tabela, exatamente qual profundidade de carga
inicial é suficiente (12 ou 3 meses) em vez do histórico completo. As outras 22 linhas "SIM" que
também caem em Tier 3 são precisamente as safras dentro da janela de retenção, que por isso precisam
mesmo ser ingeridas. Recomendo tratar esse CSV como **input direto para fechar a seção 4** daquele
relatório para os EGPs do João.

## 4. Dois riscos de aplicar o veredito ao pé da letra

O painel guarda `status_humano` **por artefato** (`chave_canonica`), não por par EGP×input. Uma
tabela lida por vários EGPs tem um único status global. Isso cria dois riscos concretos ao usar este
CSV para dar baixa em massa nos "NÃO":

**a) 5 artefatos "NÃO" são consumidos por áreas fora de Cobrança.** `BU.BU_NN` (Cobrança | Negócios
Transacionais Varejo e NaPista | Solar), `LDUARTE.HISTORICO_PROTESTO_SOLAR` (Cobrança | Negócios
Transacionais Varejo e NaPista) e `PERF_CL.PAGOS_CYBER_202501` / `_202412` / `_202401` (Cobrança |
Crédito) — o próprio João sinaliza isso na observação de `BU.BU_NN` ("Base não é da cobrança,
consumimos em alguns processos"). Marcar esses artefatos como resolvidos com base só na avaliação de
Cobrança fecharia a pendência também para EGPs de Crédito, Solar e Negócios Transacionais, que
ninguém aqui avaliou.

**b) 109 dos 117 artefatos "NÃO" são lidos por mais de um projeto**, e em 3 casos concretos a
decisão **varia por EGP** consumidor do mesmo artefato físico: `CARNEIRO.BASE_3040_202601` é "NÃO,
não é necessário" para `CPF_Contrato` mas "SIM, necessário ingestão de TODAS AS SAFRAS" para
`Marcacao_Teste_IOF_GCP`; `PERF_CL.CART_COB_DIST_CL_2025` e `_2026` são "SIM" para
`Carteira_CA_COMPLETA_GCP_2` mas "NÃO (últimos 3M)" para `Regularizacao_Mensal_EDU_GCP`. Nesses
casos o SIM tem que vencer — a tabela continua na fila — mas é a prova de que a granularidade
correta desta decisão é **por EGP**, não por artefato, e o painel hoje só guarda a segunda.

**Recomendação prática:** os únicos NÃO seguros para virar `Sanitizado` de forma ampla são os 14
"Ignorar" que não aparecem em nenhuma linha SIM do CSV e não cruzam área. As janelas de retenção (99
linhas) pedem um campo que hoje não existe no painel — algo como "ingestão parcial / últimos N
meses" — em vez de um simples A receber ↔ Sanitizado.

## 5. Fora do escopo do CSV: 8 inputs tipo arquivo ainda pendentes

O CSV cobre só `Origem = SAS/Local (dependência|externo)`, ou seja, tabelas. Comparando com o total
de inputs desses 9 EGPs no painel (243 no total, 153 no CSV), os 90 que ficaram de fora são quase
todos já `Disponível`/`Modernizado` (BigQuery) — corretamente fora do escopo da triagem. A exceção:
**8 arquivos (.xlsx/.csv)** em 4 desses EGPs seguem `A receber` ou `Em ingestão` e não entraram na
planilha do João — `protesto_flex.xlsx`, `mod000924_202511.csv`, `missing_asses_20250506.xlsx`,
`carga.xlsx`, `acao_contra_estoque_202402.xlsx`, `Piloto Retomadas - Reporte 02.04.24.xlsx`,
`ALCADAS_SOLAR_1.xlsx`, `ALCADAS_SOLAR_MULTA_MORA.xlsx`. Ficam sem veredito de negócio nesta rodada.

## 6. Reprodutibilidade

Consulta ao painel via `databricks experimental aitools tools query` (perfil `bv`), cruzando
`sas_egp_inputs` (auto) + `sas_inputs_monitor` (status humano, áreas, contagem de projetos) pelos
243 inputs dos 9 projetos, e `sas_egp_pipeline` para confirmar mês/responsável. Cruzamento linha a
linha com o CSV do João por `(EGP, artefato em maiúsculas)` — as 153 linhas casaram 1:1, sem ambiguidade.
Comparação de tiers com `docs/analises/BV_Migracao_SAS_Inputs_Sem_Ingestao_2026-08-17.csv`. Resultado
completo em `BV_Migracao_SAS_Joao_Carneiro_LIBS_Impacto_2026-08-18.csv`.
