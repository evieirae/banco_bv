# EGPs que geram os próprios inputs

Análise do inventário de migração SAS, 06/08/2026. Complementa o arquivo `egps_auto_alimentados.csv`, enviado junto.

## Contexto

Durante a análise do backlog de ingestão, notamos um padrão que distorce a contagem de pendências: EGPs que leem tabelas produzidas por eles mesmos. O processo grava uma tabela em uma biblioteca permanente e, em outra etapa (ou na execução seguinte), lê essa mesma tabela como se fosse um insumo externo. Para o inventário, ela aparece como um input a ingerir. Na prática, boa parte desses casos não precisa de ingestão nenhuma: quando o EGP for migrado, a tabela vira uma etapa intermediária do próprio pipeline novo.

O mesmo padrão pode acontecer com arquivos: o EGP exporta um csv ou xlsx e depois lê esse mesmo arquivo como insumo. A análise cobriu as duas situações.

Este relatório mapeia todos os casos dentro do escopo Indicium e das dependências transitivas.

## Números

O recorte analisado tem 184 EGPs (168 do escopo e 16 dependências). Nele encontramos:

| Indicador | Valor |
|---|---|
| Casos EGP x insumo auto-alimentados | 438 (416 tabelas, 22 arquivos) |
| EGPs envolvidos | 112 |
| Casos em que o EGP recria a tabela | 405 |
| Casos em que o EGP só apensa (acumuladoras) | 11 |
| Casos de arquivo exportado e relido | 22 |
| Tabelas ainda marcadas como "A receber" | 327 |
| Tabelas que ninguém mais produz nem consome | 223 |

O cruzamento desses filtros é o resultado mais útil: **168 tabelas** são recriadas pelo próprio EGP, não têm nenhum outro produtor ou consumidor no corpus e ainda constam como pendentes de ingestão. São as candidatas naturais a sair do backlog via sanitização, porque o dado nunca precisará existir no lake: ele nasce e morre dentro do próprio processo.

## Onde os casos se concentram

Os dez EGPs com mais tabelas auto-alimentadas:

| EGP | Tipo | Tabelas |
|---|---|---|
| SALDO_REMANESCENTE_V2 | dependência | 30 |
| Project_Atualiza_Bases_Auxiliares_GCP_Inc_Desconto_ORAHASH | escopo | 23 |
| PERFORMANCE_CL_202603_REPROC_HIST_EDU | escopo | 18 |
| ALIMENTAR DASH - NPSv10 - copia | escopo | 17 |
| Consulta_NPS_202602 | escopo | 17 |
| PROJECT_PJ_PRIVADO_DISTRIBUIDOR_RPA | escopo | 16 |
| Carta_Cartoraria_REAPONTADO_v2 | escopo | 15 |
| PERFORMANCE_CL_202603 | escopo | 14 |
| PROJECT_ROLAGEM_NEW | escopo | 12 |
| GESTAO_BNDU | escopo | 11 |

Chama atenção o primeiro da lista ser uma dependência: 30 das tabelas que o SALDO_REMANESCENTE_V2 "precisa receber" são geradas por ele mesmo.

## Dois comportamentos diferentes

Vale separar os 416 casos de tabela em dois grupos, porque o tratamento na migração é oposto.

No primeiro grupo, com 405 casos, o EGP recria a tabela quando roda. Ela funciona como área de trabalho persistida. Se ninguém mais consome, não precisa ser ingerida no lake: no pipeline migrado, vira um modelo intermediário.

No segundo grupo, com 11 casos, o EGP apensa linhas na tabela a cada execução e depende do que já foi acumulado. Esses casos pedem o caminho contrário: o histórico tem que estar disponível no destino antes de o EGP ser migrado, senão o processo novo começa do zero. O exemplo mais relevante é a EFETIVACOES_HIST da família de acordos de cartões, consumida por 20 EGPs.

## Arquivos exportados e relidos

Dos 184 EGPs do recorte, 106 exportam arquivos (csv, xlsx, txt). Cruzando essas exportações com os insumos de cada um, apenas 3 EGPs releem arquivos que eles mesmos geram, num total de 22 casos:

| EGP | Arquivos | Situação |
|---|---|---|
| ATUALIZACAO BASE PROJURIS | 20 csv da família DASHBOARD_AJUIZAMENTO | Todos já sanitizados no monitoramento |
| Geracao_carteira_91_120d | BASE_ANTECIPACAO_DESC_PESADOS_20251023.TXT | A receber |
| SERASAFEIRAO_V7GCP | FEIRAOSERASA.CSV | A receber |

O grosso do problema já foi tratado: os 20 arquivos do ATUALIZACAO BASE PROJURIS estão marcados como sanitizados e ninguém mais os produz ou consome. Restam os 2 pendentes. O txt do Geracao_carteira_91_120d tem um outro consumidor fora do recorte, e o FEIRAOSERASA.CSV também é gerado por uma segunda versão do mesmo processo (SERASAFEIRAO_V7GCP__v2) e lido por mais 2 EGPs, um deles dentro do recorte. Esses 2 merecem a mesma revisão caso a caso descrita acima antes de qualquer mudança de status.

Vale registrar que a maioria das exportações não volta para dentro dos processos: os arquivos alimentam Power BI e pastas de rede. Por isso o número é pequeno perto dos casos de tabela.

## Uma ressalva antes de sanitizar em lote

A classificação "recria" indica que existe um comando de criação da tabela em algum script do EGP. O que a extração de código não consegue garantir é a ordem: se a leitura acontece antes da recriação (o processo lê o resultado da execução anterior e depois reconstrói), a tabela se comporta como acumuladora mesmo criando do zero. Por isso a recomendação é revisar caso a caso no arquivo antes de mudar status, começando pelos EGPs com mais tabelas. A revisão tende a ser rápida: quem conhece o processo sabe dizer se ele depende da rodada anterior.

## Como usar o arquivo

O `egps_auto_alimentados.csv` abre direto no Excel (separador ponto e vírgula). Cada linha é um par EGP x insumo, com as colunas:

- `projeto`, `area`, `tipo` (escopo ou dependência), `status_migracao` e `etapa_migracao` do EGP
- `insumo` e `tipo_insumo` (tabela ou arquivo)
- `modo_escrita`: recria ou apensa para tabelas, exporta para arquivos
- `status_input` e `origem_input`: como o insumo está classificado hoje no monitoramento
- `vinculo_quebrado`: se o vínculo entre o EGP e o input já foi desfeito por analista
- `n_outros_produtores` e `outros_produtores`: quem mais grava o mesmo insumo
- `n_outros_consumidores` e `n_outros_consumidores_frontier`: quem mais lê, no corpus todo e dentro do recorte

Filtros sugeridos:

1. Candidatas a sanitização: `n_outros_produtores = 0`, `n_outros_consumidores = 0`, `modo_escrita = recria`, `status_input = A receber`. São as 168 citadas acima.
2. Acumuladoras que precisam de plano de histórico: `modo_escrita = apensa`.
3. Tabelas compartilhadas (exigem mais cuidado): `n_outros_consumidores_frontier > 0`.
4. Arquivos exportados e relidos: `tipo_insumo = arquivo`.

## Próximo passo sugerido

Revisar as 168 tabelas candidatas e os 2 arquivos pendentes com os responsáveis pelos processos e marcar os confirmados como sanitizados no painel de monitoramento. Isso retira ruído do funil de ingestão e deixa o número de pendências mais próximo do esforço real que resta.
