---
name: analise-egp-atualizado
description: Use when the BV sends an updated .egp (a "EGP Atualizado" folder, a new version of a project already in the corpus) and you must measure the downstream impact of adopting it — which outputs disappear and who consumed them, which inputs enter or leave the ingestion queue, which EGPs it consolidates, and whether the predecessor was already converted. Produces the impact table plus the Valor x Esforço score used to triage and sequence the work. Also use to rank several updated EGPs, to find the predecessor of an updated EGP, or to explain why a given adoption was flagged or blocked.
---

# Análise de EGP atualizado

Mede o **impacto de adotar** a versão nova de um `.egp`. Produz a tabela de impacto
(inputs, outputs, consumidores, antecessores), dois scores (Valor e Esforço), um
quadrante e a lista de vetos.

## Contexto: a adoção já está decidida

Direcionamento do BV em 21/08/2026 (email da Michelli Martins, "Alinhamento EGPs com
Novas Versões | Direcionamento para a Migração SAS"):

> "as versões mais recentes aprovadas pelo negócio serão adotadas como referência
> oficial, **sem a necessidade de comparações detalhadas com versões anteriores**.
> Entendeu-se que o esforço para validações históricas não agregaria valor proporcional
> ao projeto, uma vez que a versão vigente já representa a regra de negócio atual."

O mesmo email exige o que esta skill de fato entrega:

> "avaliar os impactos nas **dependências downstream**, considerando que diversos EGPs e
> interfaces consomem os outputs desses processos. Para isso, será utilizada a
> rastreabilidade e a linhagem já disponível"
> "**Manter o registro das dependências identificadas** para suportar as próximas ondas"

**Consequência prática:** não pergunte "vale a pena trocar?" — isso está decidido, é
sempre a versão nova. O que você entrega é (a) o impacto downstream, (b) o que precisa
ser validado com o negócio antes de produtizar, e (c) a ordem de trabalho. O score serve
para **triar e sequenciar**, não para aprovar ou recusar a troca.

**Os números vêm do script, não de você.** Rode
`egps_analysis/compare_egp_versions.py` e cite o output dele. Você nunca afirma
contagem de input, LOC, churn ou alcance que não esteja no CSV. Seu trabalho é o
julgamento que o script não faz: se o código ficou de fato mais simples, se a
mudança de modernização é real ou cosmética, e o que recomendar.

## Regra dura

Nunca rode `orchestrator_inventory.py` no diretório de trabalho. Ele sobrescreve
`01_*.csv`…`06_*.csv` in place e esses arquivos são versionados. O Nível 2 roda em
git worktree descartável (ver abaixo).

## Passo 1 — Snapshot do pipeline

Sem ele o eixo de veto fica cego e todo quadrante sai provisório.

```bash
cd egps_analysis && venv/bin/python pipeline_status_snapshot.py
```

O `compare_egp_versions.py` recusa snapshot com mais de 7 dias. Se falhar por auth,
diga isso e siga — mas marque **todos** os quadrantes como provisórios no relatório.

## Passo 2 — Nível 1: comparação isolada

```bash
cd egps_analysis && venv/bin/python compare_egp_versions.py \
    --novo "/caminho/da/pasta/EGP Atualizado"
```

Um `.egp` só, com antecessor conhecido:

```bash
venv/bin/python compare_egp_versions.py --novo novo.egp \
    --antigo "Cobranças/PERFORMANCE_CL_202603.egp"
```

Saída: CSV consolidado e markdowns em
`docs/analises/versoes_atualizadas_egp_2026-09/` (default do script; há um `README.md`
lá indexando o estudo). Markdown detalhado só para os vetados e os de "Avaliar caso a
caso". **Rodada nova vai para uma pasta própria com a sua data** via `--out`/`--md-dir`;
não sobrescreva a de outra rodada.

Ao **re-rodar a mesma rodada** (corrigiu um bug e quer regerar), passe `--data` com a
data original. Sem isso o nome dos arquivos usa a data de hoje e você fica com dois
conjuntos paralelos na mesma pasta, um com o bug e outro sem — que é pior que só ter o
com bug, porque não dá para saber qual é qual de relance.

O script re-extrai **os dois lados** com o extrator atual. Não substitua isso por
leitura dos `.txt` de `text_egps/` — eles vieram de versões diferentes do extrator e
o delta sairia falso.

### Um EGP novo pode substituir vários antigos

Confirmado por escrito pelo BV em 26/08/2026: *"Precisaremos substituir os EGPs
PROJECT_ATIVA_GCP_V2 e PROJECT_ATIVA_TABLEAU_NEW_V2_4_vigente, pelo EGP
PROJECT_ATIVA_TABLEAU_NEW_RPA"*.

O script trata isso: qualquer outro EGP do corpus com overlap ≥ 70% entra como
co-antecessor, e o lado "antigo" passa a ser a **união** dos inventários — os inputs que
o novo tem de cobrir e os outputs que ele tem de manter são a soma. Exceção: o churn de
código é medido contra o antecessor primário, porque diff de linha contra uma união não
significa nada.

Isso não é detalhe: no `PROJECT_ATIVA` o pareamento 1:1 escondia o output
`ATIVA.BASE_ATIVA_202510`, que tem 2 consumidores externos e pertence ao segundo
antecessor. Com N:1 ele aparece como veto.

Se a área informar os antecessores, passe todos: `--antigo "a.egp,b.egp"`.

### Faixas de pareamento

O antecessor é achado por overlap de hash das tasks de código:

| Overlap | Confiança | O que fazer |
|---|---|---|
| ≥ 70% | `ok` | segue |
| 40–70% | `alerta` | confirme com o usuário que é substituição antes de decidir |
| < 40% | `recusado` | **pare** e peça `--antigo`; overlap baixo geralmente é biblioteca compartilhada |
| zero | `sem_par` | EGP inédito: não tem troca a avaliar, só entrada nova no corpus |

Par recusado ou de confiança média não é erro do script — é pergunta para o humano.
Não invente o par.

## Passo 3 — Seu julgamento

O script mede quantidade. Você lê o código das tasks que mudaram e responde:

0. **Modernizou ou só encolheu?** Esta é a pergunta mais importante e o score NÃO
   responde. Quando inputs e outputs caem juntos — e principalmente quando os inputs
   *já disponíveis* também caem — o EGP pode ter sido modernizado, partido em dois, ou
   ter tido escopo cortado. Nos números as três coisas são idênticas. Na 1ª rodada
   4 dos 5 "Trocar agora" tinham essa assinatura, e um se chamava literalmente
   "_Reduzido". Confirme com a área que o EGP novo faz o mesmo trabalho; se faz menos,
   ache onde foi o resto e traga isso para o escopo.
1. **A modernização é real?** Um `table_in` que saiu de `SAS/Local` para
   `BV-PDBD-PRD.*` é ganho verdadeiro. Um que só trocou de alias de libname não é.
   Confira o delta de `disponivel_novo` contra o código, não contra o número.
2. **A simplificação é real?** Menos LOC pode ser código movido para um `%INCLUDE`
   (piora o acoplamento, e aí `script_in` sobe) ou lógica de verdade removida.
   O eixo de simplificação pesa só 5 — se você achar que ele está subestimando um
   caso, diga isso em vez de mexer no peso.
3. **Os outputs removidos são morte de tabela ou limpeza?** O script veta quando há
   consumidor externo. Confirme que o consumidor é real e não auto-consumo.
4. **Os inputs novos pioram a alcançabilidade?** Caminho de rede novo e macro não
   resolvido são regressão direta no gargalo do projeto.

## Passo 4 — Nível 2 (só para quem passou do corte)

Confirma o impacto de escopo com o corpus recomposto. Custa ~5,5 min por rodada e
**exige** worktree:

```bash
cd /home/lucasmuller_ind/bv/sas_assessment_tool
git worktree add /tmp/egp-nivel2 HEAD
cp "novo.egp" /tmp/egp-nivel2/egps_analysis/received_egps/<Area>/
cd /tmp/egp-nivel2/egps_analysis && python egps_extractor.py && python orchestrator_inventory.py
# compare os 01-06 do worktree com os da árvore principal
cd - && git worktree remove /tmp/egp-nivel2 --force
```

Rode uma vez com todos os EGPs aprovados juntos, não um por um: 14 rodadas são 77
minutos e os efeitos se misturam de qualquer jeito quando eles compartilham input.

## Como ler o resultado

Os nomes dos quadrantes vêm da especificação original, quando a pergunta ainda era
"vale a pena trocar". Como a adoção passou a ser obrigatória, leia-os como **prioridade
e risco**, não como aprovação:

| Quadrante | Valor | Esforço | Leitura sob o direcionamento do BV |
|---|---|---|---|
| Trocar agora | ≥20 | <20 | adotar primeiro: ganho claro, pouco a validar |
| Avaliar caso a caso | ≥20 | ≥20 | adotar, mas com validação conjunta negócio + migração |
| Trocar depois | <20 | <20 | adotar na vaga seguinte: nada muda de relevante |
| Não trocar | <20 | ≥20 | adotar com cautela: custo alto e sem ganho de inventário |
| Não trocar (veto) | — | — | **não produtizar antes de resolver o impacto apontado** |
| Sem mudança (descartar) | — | — | código idêntico ao corpus: nada a fazer |

"Não trocar (veto)" não contraria o cliente: o próprio direcionamento exige avaliar
impacto downstream antes de produtizar. O veto é justamente esse impacto não resolvido.

Ordene por `razao` (Valor/Esforço). Dentro do mesmo quadrante, `alcance_total` maior
vai primeiro e merece revisão mais cuidadosa — é blast radius.

## Vetos e alertas

**Veto** (decisão técnica, bloqueia):
- antigo em `Conversão do Código` ou etapa posterior **com** status `Em Andamento`,
  `Concluído` ou `Migrado` — trocar joga conversão fora;
- output removido com **2 ou mais** consumidores externos no corpus;
- input novo com **macro não resolvido** no caminho (nem dá para identificar o arquivo).

**Alerta** (pede confirmação, não bloqueia):
- pareamento de confiança média;
- antigo em `Pré-conversão` em andamento — não veta, mas soma 10 pontos de Esforço,
  porque existe código a refazer;
- antigo com status `Despriorizado e Contabilizado` — trocar devolve o EGP ao
  backlog, e isso é decisão de escopo;
- antigo no plano do mês com pin absoluto — fricção de processo, não impedimento;
- output removido com **exatamente 1** consumidor externo — quase sempre rascunho de
  analista em libname pessoal;
- input novo em **caminho de rede** — é o estado normal deste corpus, não regressão
  (vetava 6 de 30 na 1ª rodada por version bump de planilha).

Não veta: `Projetos Habilitados`, `Pré-Working`, `Pré-conversão`, nem status
`A Iniciar` ou `Block` em qualquer etapa. Etapa sem status não decide nada — leia
os dois juntos, sempre.

## Relatório

Entregue, nessa ordem:

1. **O impacto downstream primeiro** — é o que o cliente pediu: outputs que
   desaparecem e quem os consome, EGPs afetados por alcance, dependências novas. Este
   bloco é o registro que o direcionamento do BV manda manter.
2. **Os bloqueados (veto)**, com o motivo concreto e o que precisa acontecer para
   liberar a produtização.
3. **Uma linha por EGP**: quadrante, Valor, Esforço, razão, nº de antecessores.
4. **O que precisa de validação conjunta** com o negócio, com sua leitura do Passo 3.
5. **O que você não conseguiu verificar** — snapshot velho, par não resolvido,
   Nível 2 não rodado. Nunca apresente quadrante provisório como definitivo.

Delta zero sai cedo, sem score: "sem mudança, descartar".

## Limites conhecidos

- O alerta de "áreas diferentes" é inerte hoje: `sas_egp_pipeline` não tem coluna
  `area`, e a área do EGP novo é inferida da pasta do antecessor. Para um `.egp` que
  chega solto numa pasta de download não há área para comparar.
- O eixo de alcance usa `01_prioridade_ingestao.csv` e `03_matriz_dependencias.csv`
  da árvore atual. Se esses CSVs estiverem defasados, o alcance também está.
- LOC pode vir inflado por MPRINT gerado dentro do `code.sas`. Na 1ª rodada o
  `PROJECT_ATIVA_TABLEAU_NEW_RPA` reportou 1.655.577 linhas. Quando o LOC for
  implausível, ignore o eixo de churn e decida pelos deltas de input e output.
- O piso de ruído (2 inputs, 200 linhas) faz um EGP pequeno com `file_in` 2→0
  saturar um eixo de 25 pontos. É intencional, mas confira se o caso não é trivial.

## Contexto que você precisa ter lido

- `egps_analysis/docs/CLASSIFICACAO_INPUTS_SAS.md` — o que conta como input e por quê
- `CLAUDE.md` §"Decisões de design & armadilhas" — o que não reverter
- `egps_analysis/docs/PIPELINE_INVENTARIO_MIGRACAO_SAS.md` — o pipeline completo
