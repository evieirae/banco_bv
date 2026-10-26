# Insumos gerados pelo próprio EGP e referências via macro

Análise do inventário de migração SAS, 07/08/2026. Acompanham este documento dois arquivos para revisão no Excel: `egps_auto_alimentados.csv` e `macro_refs_validacao.csv`.

## Por que investigamos isso

O backlog de ingestão é montado a partir do que cada EGP lê. Duas situações fazem esse número parecer maior do que o esforço real:

1. O EGP lê uma tabela ou arquivo que ele mesmo gera. Para o inventário é um insumo a receber; na prática, quando o processo for migrado, vira uma etapa intermediária do pipeline novo e não precisa de ingestão.
2. O EGP referencia tabelas por nome dinâmico, montado com variável de macro (`LIB.BASE_&SAFRA`). Como o nome nunca existe literalmente no código, essas referências ou viram pendências que nunca fecham, ou simplesmente não aparecem no mapa de dependências.

O recorte analisado tem 184 EGPs: 168 do escopo Indicium e 16 dependências transitivas.

## Parte 1: EGPs que geram os próprios insumos

Encontramos 438 casos de EGP lendo algo que ele mesmo grava, envolvendo 112 EGPs. A lista completa está no `egps_auto_alimentados.csv` (a coluna `tipo_insumo` separa tabela de arquivo).

| Indicador | Valor |
|---|---|
| Casos EGP x insumo auto-alimentados | 438 (416 tabelas, 22 arquivos) |
| EGPs envolvidos | 112 |
| Casos em que o EGP recria a tabela do zero | 405 |
| Casos em que o EGP só apensa linhas (acumuladoras) | 11 |
| Casos de arquivo exportado e relido | 22 |
| Insumos ainda marcados como "A receber" | 327 |
| Insumos que ninguém mais produz nem consome | 223 |

O cruzamento mais útil: 168 tabelas são recriadas pelo próprio EGP, não têm outro produtor ou consumidor no corpus e ainda constam como pendentes. São as candidatas naturais a sair do backlog via sanitização, porque o dado nasce e morre dentro do próprio processo.

O comportamento importa para o tratamento. Quando o EGP recria a tabela a cada execução (405 casos), ela é área de trabalho persistida e não precisa ir para o lake se ninguém mais consome. Quando o EGP apensa e depende do acumulado (11 casos), o caminho é o contrário: o histórico precisa estar no destino antes da migração, senão o processo novo começa do zero. O caso mais relevante desse grupo é a EFETIVACOES_HIST da família de acordos de cartões, consumida por 20 EGPs.

Do lado dos arquivos, 106 dos 184 EGPs exportam csv, xlsx ou txt, mas quase nada volta para dentro dos processos: só 3 EGPs releem o que exportam, em 22 casos. Vinte deles (os csv da família DASHBOARD_AJUIZAMENTO, do ATUALIZACAO BASE PROJURIS) já estão sanitizados. Restam 2 pendentes: o txt do Geracao_carteira_91_120d e o FEIRAOSERASA.CSV do SERASAFEIRAO_V7GCP.

Uma ressalva antes de sanitizar em lote: a classificação "recria" indica que existe um comando de criação da tabela no código, mas a extração não garante a ordem. Se a leitura acontece antes da recriação, o processo depende do resultado da rodada anterior e se comporta como acumuladora. Por isso recomendamos revisar caso a caso com quem conhece o processo, começando pelos EGPs com mais tabelas. A revisão tende a ser rápida.

## Parte 2: referências via macro

Quando o código monta o nome da tabela com variável de macro, o inventário trata a referência de três formas, e cada uma tem um efeito diferente:

1. Arquivos com macro no nome viram insumos literais, com o `&` na chave (ex.: `BA_ACORDO_&SAFRA..CSV`). Como esse nome nunca vai existir de verdade, ficam pendentes para sempre. No corpus são 181 insumos assim, 170 deles "A receber"; dentro do recorte são 25, sendo 18 pendentes. É ruído de backlog e pode ser tratado em lote.
2. Tabelas com macro não viram insumo nenhum. A extração as registra numa seção separada, marcada como ambígua, fora do mapa de dependências. É aqui que mora o risco: uma dependência real entre dois EGPs pode estar invisível.
3. Saídas com macro ficam registradas com o `&` preservado (223 projetos têm outputs assim).

### Existe EGP usando a saída de outro via macro? Existe

Para responder isso, transformamos cada referência dinâmica em um padrão com curinga (ex.: `PRETER.BASE_COBRANCA_&SAFRA` casa com `PRETER.BASE_COBRANCA_202412`) e cruzamos com as saídas concretas de todos os EGPs do corpus. Depois, para tirar a ambiguidade, voltamos ao código de cada consumidor e classificamos cada ocorrência: leitura (`FROM`, `JOIN`, `SET`, `MERGE`) ou escrita (`CREATE TABLE`, `DATA lib.x`, `PROC APPEND`). O resultado, com a linha de código que serve de evidência em cada caso, está no `macro_refs_validacao.csv`.

No recorte, 39 pares consumidor x produtor foram validados:

| Veredito | Casos | Significado |
|---|---|---|
| Dependência provável | 24 | O EGP só lê o padrão; a família de tabelas é gravada por outro EGP |
| Lê e grava | 13 | O EGP lê e grava o mesmo padrão (auto-alimentado dinâmico, em 6 EGPs) |
| Produção própria | 2 | O EGP só grava; era falso positivo de dependência |

Descontando os pares em que o produtor é o próprio EGP, ficam 20 dependências prováveis que hoje não existem no mapa, ligando 11 consumidores a 15 produtores. Alguns exemplos:

| Consumidor | Referência via macro | Quem grava a família |
|---|---|---|
| Apuracao_recorrente_GCP | `PRETER.BASE_COBRANCA_&SAFRA_M0` | Reneg_Over30e90_Ever30_v2 |
| Consulta_NPS_202602 | `ATIVA.BASE_ATIVA_&SAFRA1` | PROJECT_ATIVA_GCP_V2 |
| Reneg_Over30e90_Ever30_v2 | `MARCACAO.MARCACAO_RENEG_TESCON_&SAFRA_RENEG` | Elegibilidade menor que 90_GCP_v4 |
| Reneg_Remunerav3 | `RENEG.RENEG_IMP_&SAFRA` | Reneg_Remunera e suas versões v2/GCP |

Um padrão que se repete: várias dessas ligações são entre versões do mesmo processo (v1, v2, v3) compartilhando tabelas safradas. Isso conversa com o trabalho de definição de produtor canônico que já está em andamento no monitoramento.

Os 13 casos de "lê e grava" merecem menção à parte: são a versão dinâmica do problema da Parte 1. O EGP lê `IPF.ANALITICO_&DATA` e ele mesmo grava `IPF.ANALITICO_20260102`. Esses casos não aparecem no `egps_auto_alimentados.csv` justamente porque a referência com macro nunca vira insumo.

### Limites do método

Dois pontos para calibrar a confiança na leitura do `macro_refs_validacao.csv`:

- Quase todas as variáveis de macro são calculadas em tempo de execução (datas derivadas), então raramente dá para confirmar o nome exato. A evidência forte é o contexto de leitura no código, que está na coluna `evidencia_leitura`.
- Famílias de tabelas com sufixo (`EMP_8_&REF` e `EMP_8_&REF._GCP`, por exemplo) podem misturar ocorrências de tabelas parecidas. As colunas de evidência mostram a linha exata para o revisor conferir.

## Como usar os arquivos

`egps_auto_alimentados.csv` (separador ponto e vírgula): cada linha é um par EGP x insumo. Filtros sugeridos:

1. Candidatas a sanitização: `n_outros_produtores = 0`, `n_outros_consumidores = 0`, `modo_escrita = recria`, `status_input = A receber`. São as 168 citadas acima.
2. Acumuladoras que precisam de plano de histórico: `modo_escrita = apensa`.
3. Arquivos exportados e relidos: `tipo_insumo = arquivo`.

`macro_refs_validacao.csv` (mesmo separador): cada linha é um par consumidor x padrão x produtor candidato. Filtros sugeridos:

1. Dependências novas para revisar: `veredito = dependencia_provavel` e `produtor_eh_o_proprio` vazio, priorizando `no_recorte` preenchido.
2. Auto-alimentados dinâmicos: `veredito = le_e_grava`.
3. A coluna `evidencia_leitura` traz a linha de código que justifica o veredito.

## Próximos passos sugeridos

1. Revisar as 168 tabelas candidatas e os 2 arquivos pendentes com os responsáveis pelos processos e marcar os confirmados como sanitizados no painel de monitoramento.
2. Revisar as 20 dependências prováveis via macro e, confirmadas, registrar os vínculos no monitoramento para que o mapa de dependências fique completo.
3. Tratar em lote os 18 insumos de arquivo com macro no nome que seguem "A receber" no recorte, já que nunca casarão com um arquivo real.
