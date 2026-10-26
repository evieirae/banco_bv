# Inputs auto-gerados: 243 tabelas que os próprios EGPs recriam e dispensam ingestão (−14% da fila)

**Data:** 2026-08-12
**Base:** inventário do monitoramento, extração de 2026-08-12
**Escopo:** Indicium + dependências transitivas (186 EGPs)

Arquivos desta análise:

| Arquivo | Conteúdo |
|---|---|
| `BV_Migracao_SAS_Inputs_Autogerados_Triagem_2026-08-12.csv` | Lista de triagem: 243 inputs em 2 tiers, com ação sugerida |
| `BV_Migracao_SAS_Inputs_Autogerados_Detalhado_2026-08-12.csv` | Base completa: 363 pares (input × EGP) com tipo de escrita e evidência |

---

## 1. O que é um "input auto-gerado"

É o par (input × EGP) em que o mesmo EGP consome e produz a tabela ou arquivo: o artefato aparece ao mesmo tempo no inventário de inputs e no de outputs do projeto.

Na prática, se o EGP recria a tabela toda vez que roda, ela é um intermediário do próprio fluxo. Quando o EGP for migrado, essa tabela vira um modelo interno no destino (tabela intermediária ou CTE). Ingerir o dado atual dela não agrega nada, porque a lógica migrada vai regenerá-lo.

## 2. Critério de produção usado

Consideramos que um EGP "produz" uma tabela quando o código SAS tem uma escrita de criação no próprio alvo: `DATA lib.membro`, `CREATE TABLE lib.membro`, `OUT=lib.membro`, ou `PROC EXPORT` no caso de arquivos. Nomes montados via macro `%let` são resolvidos antes da verificação.

Escritas de outra natureza não tornam o EGP um criador e são classificadas à parte:

- `INSERT INTO` e `PROC APPEND`: o EGP apensa, isto é, contribui com linhas para uma tabela que já existe;
- `UPDATE`, `MODIFY` e `DELETE`: o EGP atualiza registros de uma base existente.

Essa distinção vem do próprio inventário de extração, que classifica cada escrita permanente, e aparece na coluna "Tipo de escrita (próprio EGP)" do CSV base. Cópias para a WORK (`DATA X; SET LIB.X;`) são temporárias da sessão e não contam como produção. Pela mesma lógica, a exclusividade de um criador é medida só entre criadores: quem apenas apensa não torna a tabela "compartilhada", e uma tabela com produtor canônico já definido não tem concorrentes a considerar.

## 3. Números (escopo Indicium + dependências)

São 363 pares de auto-produção, de 97 EGPs sobre 333 inputs distintos. A fila de ingestão pendente do recorte tem 1.719 inputs.

Distribuição dos pares por tipo de escrita:

| Tipo de escrita | Pares | Significado |
|---|---|---|
| cria (DATA / CREATE TABLE / OUT=) | 328 | Regenera a tabela do zero a cada execução |
| cria (export de arquivo) | 22 | PROC EXPORT do arquivo que depois relê |
| apensa/atualiza (nunca cria) | 13 | Só contribui com INSERT/APPEND/UPDATE; acumulador compartilhado |

## 4. Recomendação

O CSV de triagem (`BV_Migracao_SAS_Inputs_Autogerados_Triagem_2026-08-12.csv`) traz 243 inputs, separados pela coluna `Tier`.

O Tier 1 tem 200 inputs (11,6% da fila) de descarte direto: o EGP cria a tabela e é o único criador. A ação é marcar Sanitizado na aba Inputs, sem pré-condição.

O Tier 2 tem 43 inputs de descarte condicionado: o EGP cria a tabela, mas outros EGPs também a criam. Esses inputs tampouco precisam de ingestão, desde que ao menos um dos criadores esteja no plano de migração. Aqui a ação é definir o produtor canônico primeiro (aba Outputs) e só então marcar Sanitizado.

Somando os dois tiers, até 243 inputs (14,1% dos 1.719 pendentes) podem sair da fila de ingestão.

## 5. Dúvidas prováveis

**Descartar não perde o histórico da tabela?**
Para os tiers 1 e 2, não: são tabelas que o fluxo recria (o CREATE TABLE ou DATA step sobrescreve tudo), então o dado vivo é derivável dos insumos do EGP. Os casos em que o histórico importa ficaram deliberadamente fora da lista; são os "apensa" e "atualiza" descritos a seguir.

**E as tabelas de append (`ZBLOQ.*`, `AUX_HIST_*`, `RATINHO_UNIFICADO`)?**
Essas não são descartáveis. São registros de acumulação compartilhados: vários EGPs inserem e nenhum cria. No caso de `ZBLOQ.BLOQUEIO_REGUAS_INTERSEC`, por exemplo, dez EGPs fazem `INSERT INTO` e um faz `DELETE` de limpeza. Verificamos inclusive por identidade física que não há criador sob outro libname ou path. Para essas tabelas, o histórico existente precisa de uma carga inicial no destino, e a tabela passa a ser infraestrutura compartilhada da onda (uma tabela Delta de append alimentada por vários jobs), não um handoff entre EGPs. Também não faz sentido eleger produtor canônico entre EGPs que só apensam.

**Sanitizado é irreversível?**
Não. É um status editável na aba Inputs. Se for revertido, o input e as dependências ligadas a ele voltam na hora, porque o fecho de dependências e as vias resolvidas são recalculados do status a cada leitura. Nada é cascateado ou apagado.

**Por que o Tier 2 exige produtor canônico antes?**
Mais de um criador vivo costuma indicar versões concorrentes do mesmo processo. Se o input for descartado sem definir qual versão migra, a tabela pode ficar órfã caso a versão escolhida seja despriorizada depois. Com a escolha feita e o produtor no plano, o descarte é seguro.

**Esses inputs já aparecem em algum card do app?**
Não como recorte pronto; a triagem é feita por este CSV. Uma vez marcados como Sanitizado, os efeitos aparecem em todo o app (funis, prontidão por EGP, priorização, bloqueios) pelo mecanismo de vias resolvidas.

## 6. Reprodutibilidade

A detecção cruza os inventários de inputs e outputs por EGP (chave canônica) e classifica o tipo de escrita varrendo o código extraído dos projetos (`text_egps/`), com resolução de macros `%let`. Script: `docs/analises/script_inputs_autogerados.py`.
