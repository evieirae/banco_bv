# Cruzando EGP produtor x EGP consumidor no Excel

A ideia é montar, a partir de dois exports do app Monitoramento SAS, uma planilha onde cada linha diz: o EGP A produz a tabela X, que o EGP B consome. Com isso dá pra ver as dependências entre projetos sem depender do app.

## Exportar os dois arquivos

Você vai precisar de dois CSVs:

1. Na aba *Monitoramento Outputs*, clique em "Exportar CSV". Esse arquivo tem uma linha por tabela x EGP produtor. As colunas que importam: `EGP` (quem produz), `Produtor correto?` (vem "sim" quando é o produtor oficial escolhido) e `Artefato` (o nome da tabela, ex.: `PERF_CL.CL_TABLEAU`).
2. Na aba *Inputs*, deixe o recorte em "Base" (sem filtro de escopo ou área) e aí sim clique em "Exportar CSV". Esse tem uma linha por tabela x EGP consumidor: `Artefato`, `EGP` (quem consome), `Status efetivo`, `Origem`.

O detalhe do recorte "Base" no Inputs não é frescura: o export respeita o filtro da tela, então se você exportar com o escopo filtrado, os consumidores de fora do filtro somem e o cruzamento sai incompleto. O export de Outputs já vem sempre com a base inteira.

A coluna que liga os dois arquivos é `Artefato`.

## Cruzar no Excel

Use Power Query, não PROCV. O motivo: uma tabela pode ter 2 produtores e 5 consumidores, o que dá 10 pares. PROCV e XLOOKUP devolvem só a primeira ocorrência que encontram, então os outros pares se perdem sem nenhum aviso. O Power Query gera todas as combinações.

Passo a passo:

1. Importe os dois CSVs em Dados > Obter Dados > De Texto/CSV. O separador é ponto-e-vírgula, o Excel em português detecta sozinho. Em cada um, clique em "Transformar Dados" (não em "Carregar").
2. Na consulta de Outputs, renomeie a coluna `EGP` para `EGP_produtor`. Na de Inputs, renomeie `EGP` para `EGP_consumidor`.
3. Com a consulta de Outputs aberta, vá em Página Inicial > Mesclar Consultas. Escolha a consulta de Inputs, clique na coluna `Artefato` nas duas tabelas e selecione junção do tipo Interna (só tabelas que existem nos dois lados).
4. Na coluna nova que apareceu, clique no ícone de expandir e traga `EGP_consumidor` e `Status efetivo`.
5. Página Inicial > Fechar e Carregar.

Cada linha do resultado é uma relação: `EGP_produtor` produz o `Artefato` que o `EGP_consumidor` lê.

## Limpezas depois do merge

Filtre fora as linhas onde `EGP_produtor` e `EGP_consumidor` são o mesmo projeto. São releituras internas, não dependência entre EGPs.

Se você quiser que a contagem bata com o número de dependências do app, filtre também o `Status efetivo` excluindo "Modernizado" e "Sanitizado". O app não conta como dependência as vias cuja tabela já foi resolvida, e o cruzamento cru mostra tudo.

Sobre tabelas com mais de um produtor: a coluna `Produtor correto?` marca "sim" no produtor escolhido como oficial. Dá pra filtrar por ela pra ter uma visão sem duplicidade, mas nem toda tabela passou por essa escolha ainda. As que não passaram mostram todos os candidatos.

## Como usar o resultado

Uma tabela dinâmica com `EGP_consumidor` em linhas e contagem de `Artefato` em valores mostra quantas dependências cada EGP tem. Invertendo (produtor em linhas), aparecem os EGPs mais críticos como fornecedores. E filtrando um EGP específico como consumidor, você tem a lista do que precisa existir antes de migrá-lo.

Dois avisos finais. Exporte os dois CSVs no mesmo dia, porque status e produtores mudam e exports de datas diferentes podem não fechar. E as tabelas que aparecem só no Inputs, sem par no Outputs, são fontes externas ao corpus de EGPs (sistemas, BigQuery, arquivos): a junção Interna deixa elas de fora de propósito. Se quiser enxergá-las, troque por junção Externa Esquerda partindo do Inputs.

Dúvidas: Lucas Müller (Indicium).
