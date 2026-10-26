# Evolução do escopo + dependências: de 189 para 205, a redução até 192, e o ajuste para 193

**Data:** 2026-08-12 (atualizado em 2026-08-13 — ver seções 4 e 5)

> **Número vigente: 193** (168 escopo direto + 17 dependências + 8 ex-dependências contabilizadas). As seções 1–3 abaixo descrevem a evolução até 192 no dia 12/08; as seções 4 e 5 registram os dois ajustes seguintes (192 → 191 → 193).

## O que aconteceu, em ordem

O total de EGPs do plano (escopo Indicium + dependências) passou por três movimentos no dia 12/08. A composição do número é sempre a mesma: 168 EGPs do escopo direto, mais as dependências transitivas, mais 6 ex-dependências contabilizadas (EGPs que já foram dependência, saíram do fecho vivo, mas têm etapa real de migração e por isso seguem nos totais).

**1) 189 → 205: a linhagem completa entrou no ar.** Até então, produção operava com uma linhagem parcial: a última publicação integral era antiga, e as atualizações recentes tinham entrado por um overlay incremental que só adicionava inputs, sem reprocessar as arestas de dependência. Com a publicação completa do inventário reprocessado, dependências reais que estavam invisíveis passaram a contar (por exemplo, os produtores das tabelas `CONTATOS.*` e da família `COLCHAO_ACORDO`). As dependências foram de 15 para 31, e o total exibido foi de 189 para 205 (168 + 31 + 6).

**2) 205 → 203: a regra do criador.** Passamos a exigir que uma dependência exista apenas quando o EGP produtor de fato **cria** a tabela consumida (`DATA lib.membro`, `CREATE TABLE`, `OUT=`). Quem apenas insere linhas (`INSERT INTO`, `PROC APPEND`) ou atualiza registros (`UPDATE`) é contribuinte, não produtor. Isso removeu do plano dois EGPs de Trilha que só apensavam num registro compartilhado de bloqueios (`ZBLOQ.BLOQUEIO_REGUAS_INTERSEC`, tabela que nenhum EGP cria: dez inserem e um faz limpeza).

**3) 203 → 192: escolha do produtor canônico.** Várias tabelas do plano têm mais de uma versão do mesmo processo como criadora (cópias `__v2`/`__v3`, cópias de teste, o mesmo projeto salvo em duas áreas). Com base na evidência das extrações (recência do código, versão vigente, presença no escopo), foram definidos 8 produtores canônicos, e as versões concorrentes deixaram de ser puxadas como dependência. As dependências caíram de 29 para 18, e o total de 203 para 192 (168 + 18 + 6).

## 4) 192 → 191: mais uma poda de produtor canônico (Jurídico sai das dependências)

Ainda em 12/08 (21:16), foi registrada mais uma escolha de produtor canônico: a tabela `COMPJUR.TBL1351BASEFULL` passou a ter como produtor o EGP `Riscos__1351-SAS_v20201209_V2`, e não mais o `Jurídico__1351-SAS_v20201209_V2`. Com isso o Jurídico deixou de ser dependência do plano — e, como não tem etapa real de migração registrada, também não entra como ex-dependência contabilizada (critério da seção 5 abaixo). O total caiu de 192 para 191 (168 + 17 + 6): as dependências foram de 18 para 17, e o Jurídico saiu da lista "Entraram (8)" descrita mais abaixo sem ser substituído.

## 5) 191 → 193: retenção manual de duas ex-dependências

Em 13/08 foi implementada, a pedido da BV, a retenção manual de ex-dependências: EGPs que já foram dependência do plano, saíram do fecho vivo (por exemplo, por terem sido despriorizados) e não têm etapa real de migração — portanto não seriam contabilizados pelo critério automático da seção anterior — mas que a BV quer manter contados porque representam esforço real já reconhecido. Dois EGPs foram marcados assim (config `ex_deps_manuais`, editável pela gestão): `Cobranças__Painel_Desconto_Perf_Solar` e `Cobranças__Project_Rolagem v8`. O total foi de 191 para 193 (168 + 17 + 8): as ex-dependências contabilizadas passaram de 6 (só critério automático) para 8 (6 automáticas + 2 retidas manualmente).

## A questão dos outputs: o problema no script de extração e a correção

Durante a análise, identificamos que o script de extração classificava como "output permanente" alguns alvos que na verdade eram cópias de trabalho. O padrão SAS `DATA X; SET LIB.X;` copia uma tabela permanente para a área temporária (WORK) da sessão; a heurística de qualificação antiga, ao encontrar `LIB.X` em qualquer ponto do código, promovia a cópia `X` a `LIB.X` — ou seja, registrava uma **escrita** onde havia apenas uma **leitura**. O efeito colateral era grave para a linhagem: EGPs que só liam uma tabela apareciam como produtores dela, gerando dependências que não existiam. A tabela `B_GERAL.DIAS_UTEIS`, por exemplo, aparecia com 7 produtores, quando o corpus tem exatamente 1 EGP que a cria.

A correção foi tornar a regra estrita: um output permanente exige a escrita qualificada no próprio alvo (`DATA lib.membro`, `CREATE TABLE lib.membro`, `OUT=`), com resolução de macros `%let` e um guarda conservador para escritas feitas sob outro alias de libname do mesmo diretório (nesses casos a linhagem preserva a aresta em vez de arriscar removê-la). O corpus foi reextraído por completo e o inventário republicado. Na sequência, o mesmo mecanismo passou a distinguir, entre os escritores legítimos de cada tabela, quem cria e quem só contribui — distinção que hoje aparece na aba Outputs (contagem "criadores" ao lado de "escritores") e sustenta a regra do criador na linhagem.

## Diferença entre o plano de 189 e o de 192

*(Retrato do dia 12/08, antes dos ajustes das seções 4 e 5. O número vigente é 193 — ver nota no topo.)*

Os 168 EGPs do escopo direto e as 6 ex-dependências contabilizadas são os mesmos nos dois retratos. A diferença está nas dependências: eram 15, são 18 — mas não são "3 a mais", e sim uma troca: 10 permaneceram, 5 saíram e 8 entraram.

**Saíram (5):**

| EGP | Motivo |
|---|---|
| `20250918_darkpost_v15` | Dependência fantasma (era "produtor" só pela cópia para WORK) |
| `Entrada_em_Cob_Geral_REAPONTADO_V2` | Dependência fantasma (mesmo padrão) |
| `Painel_Desconto_Perf_Solar` | Dependência fantasma (mesmo padrão) |
| `COLCHAO_ACORDO_CL__v2` | Versão antiga; o produtor canônico definido é o `COLCHAO_ACORDO_CL` (código mais recente) |
| `Project_Rolagem v8` | Versão antiga; o produtor canônico é o `Project_Rolagem v10`, que já está no escopo |

**Entraram (8):** dependências reais que a linhagem parcial não enxergava — `PERF_AMIGAVEL_gcp` (a mais relevante: duas tabelas consumidas por 13 EGPs do escopo), `Performance Solar`, `Processo_NPS_UNICO_Novo_produto`, `Fechamento_Contabil_RPDD_3040`, `Elegibilidade_Gradativo (Expansao_custas)`, `COLCHAO_ACORDO_CL` (a versão vigente, no lugar da `__v2` que saiu), `1351-SAS_v20201209_V2` (Jurídico) e `PROJECT_MASSIFICADOS_202507 - Copia`. **Atenção:** o Jurídico é uma dessas 8, mas saiu de novo horas depois — ver seção 4. Das 8 entradas, 7 permanecem vigentes.

Em resumo: o plano antigo de 189 subestimava o trabalho (faltavam dependências reais) e ao mesmo tempo carregava itens que não eram trabalho (fantasmas e versões duplicadas). O de 192 (e, após os ajustes das seções 4–5, o de 193) é um pouco maior no número, porém com composição correta: cada dependência listada é um EGP que comprovadamente cria uma tabela que o escopo consome.

**Observação de fila:** entre as 17 dependências atuais ainda há candidatas a redução — a `PROJECT_MASSIFICADOS_202507 - Copia` (a versão operacionalizada `_RPA` já está no escopo; a escolha não surtiu efeito porque produtor e consumidores referenciam a tabela por aliases diferentes de libname, caso em revisão) e a via `LUCAS.PASTA1`, tabela de rascunho pessoal que conecta os projetos de Rolagem e pode ser descartada pela área.
