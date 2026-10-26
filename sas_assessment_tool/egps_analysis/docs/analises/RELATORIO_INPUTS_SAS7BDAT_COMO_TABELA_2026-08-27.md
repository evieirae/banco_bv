# Inputs `.sas7bdat` classificados como "arquivo" — são tabelas SAS

**Fonte:** prod `bv_dev_db.monitoramento_sas` (read-only) · 2026-08-27
**Script:** `levantamento_sas7bdat_arquivo_vs_tabela.py` · **Detalhe:** `BV_Migracao_SAS_Inputs_sas7bdat_como_Tabela_2026-08-27.csv`

`.sas7bdat` é o arquivo físico de um dataset SAS. Todo input com essa extensão que está
classificado como `categoria='arquivo'` é, por definição, uma **tabela SAS** — e está no
lugar errado do inventário.

> **Correção da 1ª versão deste relatório.** A primeira passagem tratou as 280 linhas como
> um bloco só. Elas se dividem exatamente em **158 vivas** e **122 órfãs** (`orfao=true`,
> sem nenhuma linha em `sas_egp_inputs` — resíduo do publish de 2026-07-06). O bucket C
> ("duplicatas", que eu apresentei como o maior ganho, 391 pares) é **94% órfão**: cai de
> 122 para **7 linhas vivas / 14 pares**. Aquilo não é um problema a resolver — é o rastro
> de um dedup que o publish já fez. Os números abaixo são os corrigidos.

---

## 1. Causa raiz — é estrutural, não sujeira de dado

### 1.1 `.sas7bdat` nunca é testado contra modernização

`orchestrator_inventory.py:1270`:

```python
if cat in ('table_in', 'table_out'):
    # Chameleon → RepMap → Inventário Transacional → override autoritativo
```

Toda a árvore de decisão de modernização está sob esse `if`. Um `file_in` terminado em
`.sas7bdat` não entra: `status` fica `"Não Encontrado"` → `modernizada_auto = 'A ingerir'`
**permanentemente**, mesmo quando aquela tabela SAS já existe modernizada no BigQuery.

**Confirmado empiricamente:** dos 280 inputs `.sas7bdat` em prod, **0 têm
`modernizada_auto='Disponível'`**. Não é que ainda não casaram — é que nunca são consultados.

### 1.2 O dedup arquivo↔tabela só vale dentro do mesmo EGP

`publish_to_databricks.py:366` (`_sas7bdat_dedup_members`) colapsa `file_in '<membro>.sas7bdat'`
no `table_in 'lib.membro'` apenas quando ambos estão **no mesmo projeto**. Arquivo lido no
EGP A + tabela via libname no EGP B ⇒ duas chaves canônicas para o mesmo dataset físico.

### 1.3 Efeito no funil por origem

`origem_input()` (`publish_to_databricks.py:108`) devolve `"Arquivo"` para `categoria='arquivo'`,
então essas linhas caem no bucket **Arquivo** do Resumo em vez de **SAS/Local**.

---

## 2. Vivos vs. órfãos — a divisão que muda a leitura

| | total | vivos | órfãos |
|---|---:|---:|---:|
| `.sas7bdat` como `arquivo` | 280 | **158** | 122 |
| └ pendentes | 276 | **156** | 120 |

Órfão = `orfao=true` **e** sem nenhuma linha em `sas_egp_inputs` — a divisão é exata, não há
caso intermediário. São linhas que sumiram do pipeline num publish anterior
(`refreshed_at` 2026-07-06) e ficaram na tabela para reconciliação. Não alimentam nenhuma
contagem voltada a EGP.

Isso não é específico do `.sas7bdat`: o monitor tem **887 `arquivo` + 384 `tabela` órfãos**
no total.

### Escopo — os três recortes do app

| recorte | EGPs | inputs `.sas7bdat` pendentes | pares (EGP,input) |
|---|---:|---:|---:|
| `indi` (escopo estrito) | 168 | 35 | 40 |
| **`indi_deps`** (escopo + dependências) — visão de trabalho | 185 | **39** | 44 |
| `base` (corpus inteiro) | 1.221 | 156 | 175 |

Abrir de `indi` para `indi_deps` acrescenta **+4 inputs**. O tema não escala com o escopo.

**Por área** (156 pendentes vivos): Cobrança e Riscos concentram quase tudo; as 35 do escopo
são **todas de Cobrança**.

---

## 3. Buckets

| bucket | total | vivos | órfãos | pares (vivos) | ação |
|---|---:|---:|---:|---:|---|
| **0.** já resolvido | 4 | 2 | 2 | 0 | nenhuma |
| **A.** modernizada invisível | 4 | 2 | 2 | 2 | reclassificar → vira Disponível |
| **B.** gêmeo `tabela` já resolvido | 5 | 2 | 3 | 4 | **Sanitizar** o arquivo |
| **C.** gêmeo `tabela` pendente | 122 | **7** | 115 | 14 | desduplicar (quase todo já feito) |
| **D.** produzida no corpus | 12 | 12 | 0 | 14 | é dependência EGP→EGP |
| **F.** tabela SAS externa | 133 | **133** | 0 | **141** | reclassificar + esteira de ingestão |

**F é o único bucket que sobrevive inteiro à divisão vivos/órfãos** — e é o único que é
trabalho real. Dos 39 pendentes no `indi_deps`, **35 são F**.

### A — modernizadas invisíveis (2 vivas)

Casam no Chameleon como tabela já no BigQuery, mas o app mostra "A ingerir". As 4 detectadas,
com as duas órfãs marcadas:

| artifact | destino no BQ | EGPs | homônimas | |
|---|---|---:|---:|---|
| `tbsimulacoes.sas7bdat` | `TRUSTED_NEGC_RODAS.TBSIMULACOES` | 5 | 3 | órfã |
| `tbpotencialrodas.sas7bdat` | `TRUSTED_NEGC_RODAS.TBPOTENCIALRODAS` | 2 | 6 | viva |
| `tboriginacao.sas7bdat` | `TRUSTED_NEGC_RODAS.TBORIGINACAO` | 1 | 9 | órfã |
| `tbproducao.sas7bdat` | `TRUSTED_CLIE_MKT.TBPRODUCAO` | 1 | 14 | viva |

⚠️ **Confirmar antes de aplicar.** Os quatro têm de 3 a 14 tabelas homônimas no corpus
(`TBPRODUCAO` aparece sob 14 libnames). O match do Chameleon aqui é por nome nu do membro —
e o invariante do projeto é que **mesmo nome ≠ mesma tabela** (identidade é por
`(path físico, membro)`, ver `docs/analises/REFAZ_LINHAGEM_PATH.md`).

### C — o bucket que evaporou

115 das 122 são órfãs, incluindo as 75 de `POLITICA_ACORDO_GH16_<data>` (gêmeo
`GH16.POLITICA_ACORDO_GH16_<data>`). O publish já colapsou essas no `lib.membro`; a linha
`arquivo` ficou como resíduo. **Restam 7 linhas vivas / 14 pares** — trabalho de sanitização
marginal.

### F — tabelas SAS externas (133 vivas; 35 no `indi_deps`)

Nenhuma aparece como output do corpus, nem como contribuição — são genuinamente externas.
Famílias dominantes: `TB_TRANSFORM_RWA` (22), `TB_EXTRACAO_RWA` (12), `BASECUBO` (10),
`EMPILHA_RENEG_FINAL` (10), `TESTE_ENC_1PMT` (10), `MARCACAO_RENEG_TESCON` (8).

As **35 do escopo são todas de Cobrança** e todas são snapshots datados consumidos por 1 EGP
cada — exceto `&arquivo..sas7bdat`, que não é tabela (ver §4).

---

## 4. Achado secundário — macro-variável não resolvida + entidade XML não desescapada

**22 dos pendentes** não são tabelas nem arquivos: são referências parametrizadas que o
extrator não resolveu — `&arquivo..sas7bdat`, `ESTOQUE_&DSRefModel.sas7bdat`,
`molicar_&SafraM2..sas7bdat`, `hist_anal_cart_&anomes_ini._&anomes_fim..sas7bdat`…

O pior deles, `&arquivo..sas7bdat`, está **vivo, no escopo, com 5 EGPs**.

Dois problemas somados:

1. **`is_noise_table()` não cobre `file_in`.** O guard `if "&" in a` (`publish_to_databricks.py:261`)
   descarta artefato com macro só quando é *tabela*. Como `arquivo`, passa direto.
2. **Entidade XML não desescapada.** Em prod, **180 dos 181** inputs `arquivo` com macro estão
   gravados com `&amp;` literal (`&amp;Diretorio.`, `&amp;base_robbu`, `&amp;NmFile.`) — o
   extrator lê o XML do `.egp` e não aplica `html.unescape`. Só 1 tem `&` cru.

Fora do recorte `.sas7bdat`, isso afeta **181 inputs `arquivo`** no corpus, vários com 5–7 EGPs.

---

## 5. Recomendação — reordenada pelos números corrigidos

1. **Corrigir o unescape de `&amp;` no extrator** e estender o guard de macro do
   `is_noise_table()` para `file_in`. É correção de código pequena, sem ambiguidade, e é o
   único item com impacto **dentro do escopo hoje** (`&arquivo..sas7bdat`, vivo, 5 EGPs).
   Alcance total: 181 pseudo-inputs.
2. **Estender a árvore de modernização a `file_in` `.sas7bdat`.** O impacto imediato é pequeno
   (2 linhas vivas no bucket A, nenhuma no escopo), mas é o que impede o problema de voltar:
   hoje, **todo** `.sas7bdat` que entrar no corpus entra cego, sem chance de auto-detecção.
   É prevenção, não limpeza. Exige decidir a chave de match — nome nu do membro é frágil; o
   correto é `(path físico, membro)`.
3. **Decidir com Cobrança o formato das 35 do bucket F no escopo.** É o único volume real de
   trabalho. São safras datadas de 1 EGP cada — vale definir se entram como N tabelas
   independentes ou como uma tabela particionada, antes de empurrar 35 itens para a esteira.
4. **Sanitizar B + C vivos** (9 linhas, 18 pares). Ganho pequeno; fazer junto com a próxima
   limpeza, não como frente própria. Ferramenta:
   `docs/analises/aplica_acao_sanitizar_desvincular.py`.
5. **Decidir o destino das 122 órfãs.** Não afetam contagem, mas poluem a lista de Inputs.
   É uma decisão de reconciliação, comum aos 1.271 órfãos do monitor — não específica deste
   recorte.

> **Nota de escopo.** Sanitizar segue sendo o caminho para "input que já tem equivalente
> moderno": `Sanitizado` = removido do escopo (sai das contagens, continua visível e
> reversível), e o status humano **sempre prevalece** sobre `modernizada_auto` — a divergência
> vira ⚠, nunca sobrescreve.
