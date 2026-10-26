# Fila de ingestão do escopo: o que dispensa ingestão, o que exige carga inicial e o que falta verificar

**Data:** 2026-08-17
**Base:** painel de monitoramento SAS, produção, leitura de 2026-08-17
**Escopo:** Indicium + dependências transitivas + ex-dependências contabilizadas — **193 EGPs** (168 + 17 + 8)

Arquivos desta análise:

| Arquivo | Conteúdo |
|---|---|
| `BV_Migracao_SAS_Inputs_Sem_Ingestao_2026-08-17.csv` | 824 tabelas do recorte, em tiers, com o trecho de código que sustenta cada veredito |

**Os números batem com os cards do painel.** O recorte é o mesmo do app (aba Inputs, escopo
"Escopo + dependências"): **2.592 inputs no universo dos cards, dos quais 1.699 estão como
"A receber"**.

> Para conferência: a *tabela* da aba lista 2.829 linhas, mais que os 2.592 dos cards. A diferença
> são inputs consumidos apenas por ex-dependências, que aparecem na listagem mas não entram nas
> contagens. Use o número do card.

---

## 1. A pergunta e a correção de método

A pergunta é: da fila de ingestão do escopo, quanto **não precisa ser ingerido** porque o dado vem
de outro passo do próprio processo SAS, e não de um sistema-fonte.

Detectar que "o EGP escreve e lê a mesma tabela" não basta para concluir que ela é descartável,
porque **a ordem importa**. Este padrão passa por aquele teste sendo o oposto:

```sas
DATA CONSIG.CARTEIRA_GERAL;  SET CONSIG.CARTEIRA_GERAL;  WHERE SAFRA <> &SAFRA.;  RUN;
DATA CONSIG.CARTEIRA_GERAL;  SET CONSIG.CARTEIRA_GERAL  CARTEIRA;                 RUN;
```

A tabela guarda **todas as safras**. Cada execução remove a safra corrente do histórico e reinsere
a versão nova. O conteúdo anterior é obrigatório: descartar essa tabela apaga o histórico e a
primeira execução no destino não tem de onde ler.

Por isso esta análise auditou o **código SAS de cada caso**, não apenas o inventário. Para cada
tabela, o código é fatiado em passos na ordem de execução, e verificamos se a criação vem antes ou
depois da leitura. Duas ressalvas entram nessa conta: auto-referência precedida de uma criação
legítima é só transformação in-place, e não conta como risco; e quando o nome da tabela é montado
em tempo de execução, as macros `%let` são expandidas antes da auditoria. O CSV traz o veredito e o
trecho de código que o sustenta, caso a caso.

**377 das 824 tabelas analisadas dependem do conteúdo de uma execução anterior** e foram
reclassificadas como carga inicial. Nomes como `NEGATIVA.BASE_HISTORICA_NEGATIVADOS`,
`PRIVADO.BA_HIST_ENCARGOS`, `RELAT.CART_CL_MENSAL` e `DB1351.TBL1351BASEFULLHIST` confirmam a
leitura.

## 2. Critério de produção

Um EGP "produz" uma tabela quando o código tem escrita de **criação** no próprio alvo:
`DATA lib.membro`, `CREATE TABLE lib.membro` ou `OUT=lib.membro`. Nomes montados por macro `%let`
são resolvidos antes da verificação.

Escritas de outra natureza não tornam o EGP um criador: `INSERT INTO` e `PROC APPEND` **apensam**;
`UPDATE`, `MODIFY` e `DELETE` **atualizam**. Cópias para a WORK (`DATA X; SET LIB.X;`) são
temporárias da sessão.

A identidade de cada tabela é o **caminho físico + nome do membro**, não o apelido do libname: o
mesmo diretório recebe apelidos diferentes em projetos diferentes, e o mesmo apelido às vezes
aponta para dois diretórios.

## 3. Números (escopo + dependências, 193 EGPs)

Das 1.699 tabelas e arquivos pendentes, **824 tabelas** foram classificadas. As demais são
ingestão real de sistema-fonte, arquivos de rede ou tabelas já disponíveis.

| Tier | Situação | Tabelas | Hoje "A receber" |
|---|---|---:|---:|
| **1** | Dispensa ingestão — ordem verificada no código | 125 | 97 |
| **1c** | Calendário — conteúdo derivável | 8 | 6 |
| **1v** | **A verificar** — leitura não localizável no código | 25 | 20 |
| **2** | Dispensa ingestão se o produtor migrar | 286 | 215 |
| **3** | **Exige carga inicial** — não descartar | 380 | 334 |

**Saem da fila com verificação: 318 tabelas** (97 do tier 1 + 6 de calendário + 215 do tier 2), ou
**18,7% dos 1.699 pendentes**. Outras 149 tabelas desta lista já estão marcadas como Sanitizado e
portanto já saíram da conta — mas 44 delas são tier 3, ver seção 6.

A concentração é quase total em **Cobrança** (817 das 824); Jurídico responde por 7.

## 4. O maior grupo: 380 tabelas que exigem carga inicial

**Mais tabelas exigem carga inicial do que dispensam ingestão.** São dados que atravessam
execuções e que ninguém no destino vai regenerar.

| Motivo | Tabelas |
|---|---:|
| Nenhum EGP do plano cria esta safra — foi gerada por execução anterior do produtor | 177 |
| Lê o conteúdo da execução anterior da própria tabela (auto-referência) | 77 |
| Lida sem nenhuma criação no fluxo — vem de execução anterior | 73 |
| Lê antes de qualquer criação no fluxo | 50 |
| Cria a safra do mês lendo a safra anterior que ela mesma gerou | 3 |

Os motivos se agrupam em três padrões, cada um com um tratamento diferente no destino.

**Safras específicas sem criador no plano (177 + 3).** O EGP lê `BASE_ACAO_PESADOS_202509` e cria
`BASE_ACAO_PESADOS_202510`. A safra lida foi gerada numa execução passada e ninguém a recria. É
**backfill único de histórico**, não ingestão recorrente. Concentra em
`processo_carga_score_solar_jul_25_REAPONTADO_PJeOFENS` (97 tabelas),
`gradativo_202507_SOLAR_IDEAL_NTEC` (96), `Programa_Marcação_Encargos_Sem_Flex` (86).

**Acumuladores com purga e reinserção (77 + 50).** O padrão da seção 1: a tabela guarda o histórico
completo e cada execução substitui a fatia corrente. No destino isso deixa de ser uma tabela
sobrescrita e passa a ser tabela incremental (`merge`/`insert_overwrite` por partição), com o
histórico carregado uma vez.

**Acumuladores compartilhados (8, dentro dos 73 acima).** Vários EGPs fazem `INSERT INTO` ou
`PROC APPEND` e **nenhum cria** a tabela. Em `ZBLOQ.BLOQUEIO_REGUAS_INTERSEC`, dez EGPs inserem e um
faz limpeza. Verificamos por identidade física que não existe criador sob outro apelido de libname
ou outro caminho. São infraestrutura compartilhada da onda, não repasse entre EGPs — no destino,
tabela de append alimentada por vários jobs. Os outros casos:
`RATINHO.RATINHO_UNIFICADO`, `RG_AGRAC.AUX_HIST_ENVIO_AC`, `ZSHARE.AUX_BASE_ACORDOS_DIA` e a
família `CONTATOS.AUX_HIST_*`.

## 5. Tier 2: sequenciamento importa

As 286 tabelas do tier 2 não exigem ingestão — o produtor as gera —, mas o descarte depende de o
produtor migrar. Cruzando com o mês de cada EGP no plano:

| | Tabelas |
|---|---:|
| Produtor migra no mesmo mês ou antes do consumidor — ok | 225 |
| **Consumidor migra antes do produtor** | **48** |
| Produtor sem mês atribuído no plano | 13 |

Nos **48 invertidos** (43 ainda "A receber") o consumidor entra em produção no destino antes de a
fonte existir. A classificação está certa; o que existe é um vão operacional que precisa de decisão:
adiantar o produtor, atrasar o consumidor, ou manter uma tabela-ponte durante o intervalo. Os saltos
maiores são `KEVIN.SOLAR_ENCARGOS_20260213` (consumidor M1, produtor M5),
`JOAO.BASE_ESTUDO_PERFORMANCE_MIX` (M1 para M4) e `MARINA.TESTE_PROTESTO_*` (M2 para M4).

Nos **13 sem produtor com mês** o produtor está fora do plano: ou entra no escopo, ou a tabela passa
a ser ingestão de verdade. São principalmente as safras `RENEG.BASE_ELEG_CONT_2025*` e a família
`PRIVADO.CARGA_*`.

A coluna `Sequenciamento` do CSV traz esse veredito por tabela, com os meses de produtor e
consumidor.

## 6. Pontos que pedem revisão antes de agir

**44 tabelas do tier 3 já estão marcadas como Sanitizado.** São tabelas que exigem carga inicial e
que hoje constam como resolvidas. A marcação foi manual e nenhuma tem disponibilidade detectada
automaticamente. Uma tem justificativa registrada e válida (o processo que a consumia foi
despriorizado); as demais não têm observação, então o histórico do painel não permite confirmar se
a decisão considerou este ponto. Se algum desses processos estiver ativo no plano, a primeira
execução no destino falhará por tabela vazia.

**25 tabelas seguem sem veredito (tier 1v).** Em 21 delas o código escreve a tabela mas a leitura
não foi localizada, e em 4 o nome não pôde ser resolvido. Não são seguras nem inseguras: são
desconhecidas, e precisam de inspeção manual antes de qualquer descarte. Dessas, 5 já estão
marcadas como Sanitizado.

> Sem a **expansão de macros** (seção 8) este grupo seria de 84 tabelas. Em 59 delas o nome era
> montado em tempo de execução (`ADAMOR2.BASE_ATIVA_&DT_BASE.` com `%let DT_BASE = '202510'`), e com
> a substituição o código pôde ser auditado normalmente. Ao todo 101 tabelas do estudo tiveram o
> veredito obtido por essa via, e o CSV as marca na coluna `Nome resolvido por macro`.

**Os 8 calendários merecem tratamento próprio.** `DIAS_UTEIS`, `FERIADOS`,
`CONFIG_FERIADO_MUNICIPAL` e variantes aparecem sob vários apelidos de libname. Não precisam de
ingestão nem de carga de histórico: no destino, um único calendário com feriados atende todos os
consumidores. É a maior simplificação isolada da lista e independe de migrar qualquer EGP.

## 7. Dúvidas prováveis

**Descartar não perde o histórico da tabela?**
Nos tiers 1, 1c e 2, não: são tabelas que o fluxo recria a cada execução, ou cujo conteúdo é
derivável. É exatamente para separar os casos em que o histórico importa que existe o tier 3.

**`Sanitizado` é irreversível?**
Não. É um status editável na aba Inputs. Se for revertido, o input e as dependências ligadas a ele
voltam imediatamente, porque o fecho de dependências é recalculado a cada leitura. Nada é
cascateado nem apagado.

**Por que 824 e não as 1.699 da fila?**
As 1.699 incluem arquivos de rede (`.xlsx`, `.csv`), tabelas de sistemas transacionais e tabelas já
disponíveis no ambiente novo. Esta análise trata apenas de tabelas SAS/Local.

**Um EGP fora do plano lê alguma dessas tabelas?**
Pode ocorrer. A classificação considera os EGPs do plano, que é o universo da decisão. Se um EGP
hoje fora do plano entrar depois, vale reconferir os inputs dele — em especial os do tier 1, cuja
condição é que o leitor seja também o criador.

**A auditoria de código pode errar?**
Pode, em duas direções. A ordem textual das tasks é a ordem topológica que o extractor calcula, e
lógica condicional (`%if`) pode alterar o caminho de execução real. Além disso, 25 tabelas não
puderam ser auditadas e ficaram no tier 1v. Por isso o tier 1 é deliberadamente restritivo:
preferimos classificar como "a verificar" a assumir que é seguro.

## 8. Reprodutibilidade

A classificação cruza, para cada EGP, o inventário de inputs com o de outputs, identifica o tipo de
escrita e reconhece famílias de safra mascarando tokens de data (`AAAAMM` / `AAAAMMDD`) no nome do
membro. A auditoria de ordem fatia o código em passos e compara a posição da primeira criação com a
da primeira leitura, tratando separadamente auto-referência precedida de criação legítima (que é
transformação in-place, e não risco).

**Expansão de macros.** Boa parte das tabelas tem o nome montado em tempo de execução, como
`ADAMOR2.BASE_ATIVA_&DT_BASE.`. Para auditá-las, as atribuições `%let` são coletadas e substituídas
no código antes da análise: no exemplo, `%let DT_BASE = '202510'` resolve o nome para
`ADAMOR2.BASE_ATIVA_202510`. Isso permitiu emitir veredito para **101 tabelas** que de outro modo
ficariam sem classificação, e o CSV as identifica na coluna `Nome resolvido por macro`.

Duas limitações conhecidas do método. Quando a mesma variável recebe vários valores ao longo do
fluxo, usamos o último, o que pode resolver para a safra errada dentro de uma família (não afeta o
veredito de ordem, que depende da estrutura e não de qual safra). E a expansão não alcança nomes
construídos dentro de macro function ou trazidos por `%include`, que é a razão de 4 das 25 tabelas
do tier 1v seguirem sem nome resolvido.

Scripts: `docs/analises/revisao_autoprodutores_safra.py` (classificação),
`docs/analises/auditoria_ordem_codigo.py` (auditoria de ordem) e
`docs/analises/inputs_sem_ingestao_escopo_deps.py` (recorte do plano, cruzamento com o painel e
sequenciamento por mês).
