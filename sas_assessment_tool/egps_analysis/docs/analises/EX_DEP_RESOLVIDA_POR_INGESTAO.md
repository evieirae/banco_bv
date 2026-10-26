# Ex-dependência resolvida por ingestão

*2026-09-25*

## O caso

Um EGP entra no recorte só porque produz uma tabela que alguém do escopo lê. A tabela é
**ingerida**. A partir daí a aresta morre (via resolvida não gera dependência), o produtor
sai do frontier e vira **ex-dependência** — com o agravante de que, se alguém já tinha
feito a **pré-conversão** dele, esse esforço fica órfão: `Pré-conversão` é etapa fantasma e
o critério "189" só contabiliza ex-dependência com etapa real.

O ponto é que **"a tabela foi ingerida" não diz sozinho o que aconteceu com o produtor**.
São dois desfechos opostos e o app não conseguia distingui-los:

- **Foi dispensado.** A ingestão cobre o que os consumidores precisavam; migrar o produtor
  deixou de fazer sentido. Saída: `Despriorizado e Contabilizado`.
- **Ainda é necessário.** A ingestão não cobre o que o consumidor lê — carga única sem
  refresh, recorte parcial, ou o consumidor depende do produtor por algo que a tabela
  ingerida não entrega. Saída: **botão "ainda é dependência"**, que reabre a aresta.

Em prod (25/09/2026) são **5 ex-dependências** classificadas como resolvidas por ingestão.
Das 5, **3 nunca entraram na esteira** (sem etapa — não há esforço a reconhecer nem decisão
a tomar) e **2 têm pré-conversão concluída**: `Cobranças__CRIAR_MARCACAO_SEGMENTACAO_reap_1`
e `Cobranças__Valida_carga_v1_cp`. Essas duas são do segundo tipo — **seguem sendo
dependência**.

## Por que "resolvida por ingestão" ≠ "via sanitizada"

Antes, o app dizia a mesma coisa para as duas (`via resolvida/desvinculada`). São
desfechos diferentes:

| | o que aconteceu com a tabela | houve entrega? |
|---|---|---|
| **resolvida por ingestão** | entrou no lake (Modernizado / Autoprodutor) | **sim** |
| **via descartada/desvinculada** | saiu do escopo (Sanitizado), vínculo quebrado, ou a aresta caiu por produtor canônico | não |

O teste em `_ex_deps` é `vias ⊆ resolvidas AND vias ∩ sanitizadas = ∅` — **todas** as vias
resolvidas e **nenhuma** por descarte. Via ainda aberta (aresta podada por escolha de
produtor canônico, não pelo dado) não é entrega deste EGP: daí o `⊆`, não o `∩`.

## As peças

### 1. Detecção — derivada, sem tabela nova

`app/backend/main.py::_ex_deps` classifica o motivo a cada leitura, do estado vivo dos
inputs. Nada é escrito, nada cascateia. O motivo aparece no tooltip do badge
"ex-dependência" (`ReadinessView.tsx`), então o caso é achável na tela.

Relatório re-rodável: `egps_analysis/scripts/ex_deps_resolvidas_por_ingestao.py`, que
**importa** `_ex_deps` em vez de reimplementar a regra.

### 2a. Desfecho "ainda é dependência" — override por par

Tabela `sas_egp_dep_mantida` (+ `_audit`), espelho exato do `link_broken`: enquanto
`link_broken` diz *"este EGP não precisa deste input"*, aqui o consumidor diz *"eu ainda
preciso do PRODUTOR deste input, mesmo com a tabela no lake"*.

**Tabela separada, e não uma 2ª coluna em `sas_egp_input_link`**, de propósito: T_LINK tem
a invariante "linha ausente ≡ linkado" e `_link_escreve` **apaga** a linha ao restaurar —
uma segunda flag ali seria apagada junto, em silêncio.

O botão age no **produtor** (é ele que se vê sumindo do recorte) mas **grava por par**
(consumidor, input), com fan-out explícito na resposta. Por isso marcar um consumidor não
ressuscita a dependência para os outros consumidores da mesma tabela.

O botão **não** mexe no status do input: a tabela segue `Modernizado` no funil de ingestão,
porque ela *está* no lake. O que se declara é outra coisa — que aquela ingestão não cobre
este consumidor. Se o certo for que a ingestão está incompleta, o lugar de corrigir é o
input, não aqui.

**Duas cópias da regra têm de saber disso**: `main.py::_filter_vias_resolvidas_res` (app) e
`publish_to_databricks.py::frontier_egps` (publish). Se só uma souber, o próximo publish
derruba do escopo exatamente os EGPs que alguém marcou para manter — e ninguém vê, porque
o app continua certo até o republish. `app/backend/test_dep_mantida.py` testa a paridade
das duas.

### 2b. Desfecho "foi dispensado" — status durável

`Despriorizado e Contabilizado` em `sas_egp_pipeline`: único estado de saída de backlog que
existe (`Removido` foi extinto em 07/2026) e diz exatamente o que aconteceu — saiu do
backlog, o esforço gasto fica contabilizado. Durável: o publish faz `CREATE TABLE IF NOT
EXISTS` nessa tabela, nunca a recria.

Por que status e não contagem automática a partir do motivo: "a tabela entrou no lake" é
fato **derivado** e reversível; "este EGP não vai ser migrado" é **decisão**.

### 3. Contagem — fora do funil, dentro do total

> Pré-conversão é antes de um projeto habilitado, é só a conversão de código sem ter as
> tabelas corretas nem nada pronto. Não é pra ir pro funil, mas é pra contar se um EGP foi
> despriorizado.

`PIPELINE_PROJETO` segue **sem** `Pré-conversão` — etapa fantasma, primeira coluna do
Kanban, coluna "Backlog" do funil por mês. Mudou só o critério "189":

```
ex-dependência conta nos totais se tem etapa REAL
                              OU  (etapa fantasma E status = 'Despriorizado e Contabilizado')
```

Três pontos que têm de andar juntos — `_ex_deps_contab`, `_prio_contabiliza`
(`app/backend/main.py`) e `contaNoTotalEgp` (`app/frontend/src/pipeline.ts`) — mais a cópia
inline de `ex_contab` dentro de `egp_readiness`.

A regra é **inerte até o status ser aplicado**, de propósito: ela não inventa contagem,
garante que a decisão humana apareça no número.

## Procedimento

1. Rodar o relatório (read-only):
   ```bash
   cd egps_analysis/app && DATABRICKS_CONFIG_PROFILE=bv \
       ../venv/bin/python ../scripts/ex_deps_resolvidas_por_ingestao.py
   ```
2. Para cada EGP do balde **[2] A DECIDIR**, perguntar a quem conhece o dado: *a ingestão
   cobre o que o consumidor lia?*
   - **Não cobre** → botão **"ainda é dependência"** na linha do EGP, aba EGPs. Ele volta ao
     frontier vivo e deixa de ser ex-dependência.
   - **Cobre** → status `Despriorizado e Contabilizado` (tela de Gestão, ou o UPDATE que o
     script imprime).
3. Re-rodar: o balde [2] tem que ficar vazio.

O balde [3] (sem etapa) não tem o que decidir — sem esforço gasto, não há o que reconhecer.

## Verificação

Unitária (`app/backend/test_dep_mantida.py`, 9 testes): o override preserva a aresta, é por
par e não por tabela, um par marcado não vale para outro, aresta multi-via mantém só a via
marcada, o default vazio não muda o comportamento legado, e **app e publish respondem igual**
em todos os casos.

Em prod, antes de qualquer aplicação (leitura apenas):

| checagem | resultado |
|---|---|
| `resolvida por ingestão` bate com o mapa medido à mão | 5/5 |
| total com a regra inerte | 180 + 12 = **192** |
| ex-dependências com etapa real (não podiam mudar) | 12, todas ainda contadas |

Aplicar o botão nos 2 EGPs os tira de "ex-dependência" e os devolve ao frontier — o total
passa a 194 por esse caminho, não pelo da despriorização.
