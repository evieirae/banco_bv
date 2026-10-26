# Comparativo de esforço entre versões de um EGP — metodologia e cálculo de pesos

> **Pergunta que este documento responde:** quando o cliente entrega uma versão atualizada de um EGP que já está no escopo de migração (versão antiga), vale a pena o retrabalho de converter a versão nova no lugar da antiga?
>
> **Critério:** exclusivamente o **esforço de entrega do time de migração**. Qualidade/benefício para o cliente **não entra no cálculo** (escopo fechado — o que foi alinhado é o que vale; a troca só se justifica se reduzir o nosso trabalho).
>
> **Caso de origem:** `Project_Atualiza_Bases_Auxiliares_GCP_Inc_Desconto_ORAHASH` (antigo, no escopo) vs `Project_Atualiza_Bases_Auxiliares_GCP_Inc_Cadu_HUB` (novo, 2026-08-06). Números reais na §6.

---

## 1. Visão geral do método

1. Extrair as duas versões com `egps_extractor.py` (saída em `text_egps/*.txt`, header `START_METADATA…END_METADATA`).
2. Medir **8 dimensões de esforço** (§3) a partir do header da extração + CSVs do orquestrador + tabelas do app.
3. Converter as contagens em **pontos de esforço** via pesos (§4).
4. Somar um **custo fixo de troca** ao EGP que não está no escopo.
5. Aplicar os **gates** (bloqueadores que não são compensáveis por pontuação, §4.3).
6. Decidir pela regra da §5.

O modelo é aditivo de propósito: cada unidade de trabalho (uma ingestão, uma query a traduzir, um EGP produtor a coordenar) vira pontos, e pontos são comparáveis entre versões. Os pesos default foram calibrados no caso de origem e devem ser re-calibrados conforme o time medir esforço real (ver §7).

---

## 2. Fontes de dados (de onde sai cada métrica)

| Fonte | O que fornece | Observações |
|---|---|---|
| `text_egps/<egp>.txt` — header `START_METADATA` | `EXTERNAL INPUTS` (com tag de origem `[BIGQUERY]`, `[SAS/Local]`, `[SYBASEIQ]`…), `IMPORTED FILES`, `CONNECTION_LIBS`, `DETECTED_MACROS_USED`, `LINES_OF_CODE`, `CODE_TASKS_COUNT`, `TRIGGERS`, `PERMANENT OUTPUTS`, `EXPORTED FILES`, `SAME-SCRIPT RE-READS` | É a fonte canônica de inputs/outputs. **Não** usar `TABLE_READ_PROVENANCE` nem `INTERNAL READS` para contar ingestão (incluem leituras internas). |
| Headers de **todos os outros** `text_egps/*.txt` (`PERMANENT OUTPUTS`) | Quem **produz** cada input → separa "dependência EGP" de "ingestão real" | Match por `LIB.MEMBER` exige conferir que o **path físico** da lib é o mesmo nos dois lados (identidade canônica é `(path, member)` — ver `REFAZ_LINHAGEM_PATH.md`). |
| `06_prontidao_tabela.csv` (orquestrador) | `status_validacao` por tabela: `Nativa BigQuery`, `[Modernizada]`, `[Modernizada via replica]` (RepMap), `Não Encontrado` + destino chameleon | Atenção: `category=table_in` inclui leituras internas e refs dinâmicas de macro — cruzar com `EXTERNAL INPUTS` do header. |
| `src/chameleon.csv` + `src/inputs_modernizados.csv` | Vínculo tabela SAS/Sybase → tabela BigQuery já ingerida | Alimentam o `status_validacao` acima; consultar direto em caso de dúvida. |
| App (prod): `bv_dev_db.monitoramento_sas.sas_inputs_monitor` | `modernizada_auto`, `status_humano` (ex.: `Sanitizado`, `Concluído`, `A receber`), `responsavel`, `observacao` | Um input **Sanitizado** ou já **Concluído** sai da conta de ingestão. Chave: `tabela::LIB.MEMBER` / `arquivo::NOME`. |
| `01_prioridade_ingestao.csv` | `Tipo_Origem` (`Requer Ingestão Externa` vs `Gerado Internamente (<EGP>)`) e projetos impactados | Confirma o split ingestão × dependência. |

---

## 3. As 8 dimensões de esforço

Para **cada versão** do EGP, medir:

### D1 — Ingestões reais (tabela SAS/Local sem produtor)
`EXTERNAL INPUTS` com tag `[SAS/Local]` que: (a) não têm produtor em nenhum outro EGP do corpus; (b) não estão modernizadas (sem vínculo chameleon/inputs_modernizados); (c) não estão `Sanitizado`/`Concluído` no monitor.
**Exclusões fixas:** `DICTIONARY.TABLES` (metadado de sessão SAS), refs dinâmicas com macro no membro (`{DT_ARQ}` etc. — normalmente releitura do próprio output), `SAME-SCRIPT RE-READS`.
*Por que pesa muito:* cada uma exige o cliente entregar dado (`A receber`), definição de refresh e pipeline de carga — é o item de maior lead time.

### D2 — Arquivos a ingerir (CSV/XLSX/INFILE)
Linhas de `IMPORTED FILES` que apontam para arquivo físico (paths `N:\`, `C:\`, xlsx/csv), excluindo `.sas7bdat` com macro (são D1/releitura). Arquivo é mais barato que tabela SAS por unidade (upload direto, ex.: aba Ingestão do app), mas cada um é uma fonte recorrente a mais.
**Dica:** verificar se o mesmo dado circula como arquivo **e** tabela (ex.: `concessao_indevida.xlsx` ↔ `CAINDV.CONCESSAO_INDEVIDA`) — uma ingestão única pode quitar as duas pendências.

### D3 — Dependências de outros EGPs
Nº de **EGPs produtores distintos** dos inputs `[SAS/Local]` que têm produtor no corpus. Não é ingestão, mas é coordenação: esses EGPs precisam ser migrados antes (ou a tabela ingerida como está, temporariamente). Contar **produtores distintos**, não tabelas — o custo é por EGP a coordenar.

### D4 — Reescrita de pass-through de banco legado (Sybase IQ/ASE, Oracle…)
Split dos inputs `[SYBASEIQ]`/`[SYBASE_ASE]` etc. em:
- **mapeados** — `status_validacao` = `[Modernizada]`/`[Modernizada via replica]`: trocar a referência pelo destino trusted BQ + traduzir dialeto. Custo baixo/unidade.
- **não mapeados** — `Não Encontrado` (tipicamente views `VWTB*`): investigar equivalente na mão. Custo alto/unidade.
Somar o custo de **expurgo de credenciais**: `CONNECTION_LIBS` além de `DBCON`/`PERM` e macros `User_*`/`pw_*` em `DETECTED_MACROS_USED` (política de dado sensível, `sensitive_data_types.yaml`).
Pass-through **BigQuery nativo não pontua** — é quase transcrição para o alvo.

### D5 — Volume de conversão
`CODE_TASKS_COUNT` (proxy principal — o pipeline converter/ trabalha por task: spec → draft → gate → auditoria). `LINES_OF_CODE` e nº de `EXPORTED FILES` como sanity-check. `TRIGGERS` (HASH, TRANSPOSE, DATA \_NULL\_) indicam dificuldade por task, útil no desempate.

### D6 — Custo fixo de troca (só na versão fora do escopo)
Trabalho único para trocar o alvo: mover o `.egp` para `received_egps/<Área>/`, re-extração com área, re-run do orquestrador (~5,5 min), re-publish no app, entrada no `registry/egp_catalog.yaml`, ajuste de plano/pin/ondas, comunicação da mudança.

### D7 — Risco de escopo aberto (GATE, não pontua)
Inputs da versão candidata cujo **único produtor no corpus é a outra versão** (ou nenhum produtor + tabela claramente recalculada com frequência, não ingerível como snapshot). Enquanto o cliente não apontar quem gera esse dado no ambiente alvo, a candidata está **bloqueada** — o risco é acabar convertendo a lógica da versão antiga mesmo assim, anulando a economia.

### D8 — Status no monitor (ajuste, normalmente neutro)
Inputs `Sanitizado`/`Concluído`/com vínculo ativo **saem** de D1/D2 antes da pontuação. Se as duas versões compartilham os mesmos inputs pendentes (caso comum), esta dimensão não muda a comparação — mas precisa ser checada, porque um lado pode ter input já quitado.

---

## 4. Modelo de pontuação

### 4.1 Fórmula

```
Esforco(egp) =  W_ING_SAS   × D1
             +  W_ING_FILE  × D2
             +  W_DEP_EGP   × D3        (produtores distintos)
             +  W_PT_MAP    × D4a       (legado mapeado)
             +  W_PT_UNMAP  × D4b       (legado não mapeado)
             +  W_CRED      × D4c       (connection libs com credenciais)
             +  W_TASK      × D5        (tasks)

EsforcoTotal(candidata) = Esforco(candidata) + C_TROCA
EsforcoTotal(escopo)    = Esforco(escopo)
```

### 4.2 Pesos default (calibrados no caso de origem — revisar com dados reais)

| Peso | Valor | Racional |
|---|---|---|
| `W_ING_SAS` | **5** | Maior lead time: depende do cliente entregar dado + pipeline de carga + refresh |
| `W_ING_FILE` | **2** | Upload direto; barato por unidade, mas é fonte recorrente |
| `W_DEP_EGP` | **3** | Coordenação/sequenciamento por EGP produtor |
| `W_PT_MAP` | **1** | Trocar referência pelo destino trusted + traduzir dialeto |
| `W_PT_UNMAP` | **4** | Investigação manual de equivalente (views etc.) |
| `W_CRED` | **2** | Expurgo de credenciais + conexão a re-plumbar |
| `W_TASK` | **0.5** | Custo marginal por task no pipeline de conversão |
| `C_TROCA` | **8** | ~1 dia de retrabalho de processo (re-extração, orquestrador, app, registry, plano) |

### 4.3 Gates (avaliar ANTES da pontuação — não são compensáveis)

| Gate | Condição | Efeito |
|---|---|---|
| **G1 — Produtor órfão** | A candidata tem input cujo único produtor é a versão que seria abandonada (D7 > 0) e o cliente **não confirmou** produtor/feed no ambiente alvo | Candidata **bloqueada** até resposta do cliente. Registrar a pergunta (ex.: *"quem passa a gerar X no GCP?"*) |
| **G2 — Consumidor órfão** | Outputs exclusivos da versão do escopo têm consumidores no corpus **que estão no nosso escopo** | Somar ao candidato o custo de suprir esses consumidores (ou bloquear). Consumidores fora do escopo não pesam. |
| **G3 — Paridade funcional mínima** | Interseção de `PERMANENT OUTPUTS` + `EXPORTED FILES` entre as versões < ~80% | As versões não são substitutas — comparação inválida, escalar para PM. |

### 4.4 Interpretação das entradas condicionais

Input em G1 tem duas resoluções possíveis; recalcular o placar nos dois cenários:
- **Cliente confirma feed** → o input vira D3 (dependência externa resolvida) ou some da conta.
- **Cliente não confirma** → contar como `W_ING_SAS × 2` (ingestão + risco de refresh) **ou** somar o custo de converter a lógica produtora da versão antiga (o que praticamente devolve o placar para a versão do escopo).

---

## 5. Regra de decisão

```
1. G3 falhou?           → não são substitutas; manter escopo e encerrar.
2. G1/G2 pendentes?     → decisão condicionada; enviar pergunta ao cliente
                          e reportar o placar nos dois cenários.
3. EsforcoTotal(candidata) < EsforcoTotal(escopo) × 0.8
                        → recomendar TROCAR (margem de 20% protege contra
                          erro de calibração dos pesos).
4. Caso contrário       → manter a versão do escopo.
```

A margem de 20% existe porque a versão do escopo tem valor de opção (já alinhada, já no plano) e os pesos são estimativas. Só vale trocar quando a economia é robusta a erro de peso.

---

## 6. Caso aplicado: ORAHASH (escopo) vs Cadu_HUB (candidata)

### 6.1 Métricas medidas (2026-08-06)

| Métrica | ORAHASH | Cadu_HUB | Fonte |
|---|---|---|---|
| Inputs externos totais | 59 | 26 | header `EXTERNAL INPUTS` |
| — BigQuery nativo (custo 0) | 9* | 15 | idem (tag `[BIGQUERY]`) |
| **D1** ingestões SAS reais | **8** | **4** (subconjunto das 8) | header + produtores + monitor |
| **D2** arquivos (CSV/XLSX) | **5** + 1 INFILE | **0** | `IMPORTED FILES` |
| **D3** EGPs produtores distintos | **12** (13 tabelas) | **5** (6 tabelas; 2 delas ← ORAHASH) | varredura `PERMANENT OUTPUTS` do corpus |
| **D4a** legado mapeado (trusted BQ) | **23** (15 ASE + 8 IQ) | **0** | `06_prontidao_tabela.csv` |
| **D4b** legado não mapeado | **3** (`DBA.VWTBCONTRATO`, `VWTBCONTRATOFINANCEIRO`, `VWTBPARCELA`) | **0** | idem (`Não Encontrado`) |
| **D4c** connection libs c/ credenciais | **4** (SYBASE, SYNAPSE, SYNAPSE2, SYNAPSE3; macros `User_*`/`pw_*` ×3 pares) | **0** (só DBCON/PERM) | header `CONNECTION_LIBS`/`MACROS_USED` |
| **D5** tasks / LOC | **49** / 5.163 | **24** / 3.201 | header |
| Outputs permanentes / exports | 33 / 29 | 27 / 22 | header |
| **D7** inputs com produtor órfão | 0 (autocontido) | **2** (`CONTATOS.AUX_FATURA_DETAIL`, `CONTATOS.AUX_IQ_OFERTA_PARC_FATURA` — único produtor: ORAHASH) | análise de produtores |
| **D8** sanitizados/modernizados entre os pendentes | 0 | 0 | `sas_inputs_monitor` (todos `A receber`/`A ingerir`); chameleon sem match |
| G2 — consumidores dos outputs exclusivos do ORAHASH | `AUX_CYBER_ALCADAS` → darkpost_v15; `AUX_IQ_MODELO` → Jornada_e_Mailing_RENEG | n/a | varredura de inputs do corpus |
| G3 — paridade de outputs | 26 de 33 em comum (~79%+`CONTROL_TEMP_REGUAS` extra no HUB); exports core idênticos | ✔ substitutas | diff de headers |

\* No CSV de prontidão; o header lista 10 com o split BQ/Sybase levemente diferente do CSV — usar o CSV (pós-guards do orquestrador) como oficial.

Detalhe das 8 ingestões ORAHASH (D1): `AUX_DU.BASE_AUX_DU`, `CAINDV.CONCESSAO_INDEVIDA`, `CART_HST.PERF_AMIGAVEL`, `CONTATOS.AUX_BASE_SEGM_ATIVA`, `CONTATOS.AUX_CARRINHO_ABAND`, `DESDOBRO.BA_ELEG_POSTERG_RODAS`, `TCONFIG.CONFIG_TPENTRADA_RENEG`, `ZBADBANK.BASE_CORTADOS_2023`. As 4 do Cadu_HUB são as marcadas em negrito no relatório de origem: `CONCESSAO_INDEVIDA`, `AUX_BASE_SEGM_ATIVA`, `BA_ELEG_POSTERG_RODAS`, `CONFIG_TPENTRADA_RENEG` — **subconjunto**: ingestão feita para um serve ao outro.

### 6.2 Pontuação

| Parcela | ORAHASH | Cadu_HUB |
|---|---|---|
| D1 × 5 | 8 × 5 = **40** | 4 × 5 = **20** |
| D2 × 2 | 5 × 2 = **10** | 0 |
| D3 × 3 | 12 × 3 = **36** | 5 × 3 = **15** |
| D4a × 1 | 23 × 1 = **23** | 0 |
| D4b × 4 | 3 × 4 = **12** | 0 |
| D4c × 2 | 4 × 2 = **8** | 0 |
| D5 × 0.5 | 49 × 0.5 = **24.5** | 24 × 0.5 = **12** |
| C_TROCA | — | **8** |
| **Total** | **153.5** | **55** |

**Cenário G1 pessimista** (cliente não confirma feed das 2 tabelas de fatura): Cadu_HUB += 2 × 5 × 2 = 20 → **75**. Ainda 49% do ORAHASH.

### 6.3 Decisão

`55 (ou 75) < 153.5 × 0.8 = 122.8` → **trocar para o Cadu_HUB**, condicionado ao **G1**: obter do cliente quem gera `AUX_FATURA_DETAIL` e `AUX_IQ_OFERTA_PARC_FATURA` no GCP. O G2 só pesa se `darkpost_v15`/`Jornada_e_Mailing_RENEG` estiverem no nosso escopo. A economia dominante é o eixo Sybase (D4: 43 pts vs 0) somado à metade do volume e das ingestões.

---

## 7. Automação — esqueleto

```python
# Entradas: caminhos dos 2 .txt (extração), pasta text_egps/, 06_prontidao_tabela.csv,
#           (opcional) conexão ao sas_inputs_monitor para D8.

def parse_header(txt_path) -> dict:
    """Lê START_METADATA..END_METADATA; retorna listas tipadas:
    external_inputs [(tabela, origem)], imported_files, connection_libs,
    macros_used, tasks, loc, permanent_outputs, exported_files, reread."""

def producers_index(text_egps_dir) -> dict[str, list[str]]:
    """tabela LIB.MEMBER -> [egp_key produtores], varrendo PERMANENT OUTPUTS.
    ATENÇÃO: validar path físico da lib (DETECTED_LIBNAMES) antes de aceitar o match."""

def classify_inputs(header, producers, prontidao, monitor):
    # 1. filtra external_inputs: remove DICTIONARY.TABLES, macro-membro, rereads
    # 2. remove Sanitizado/Concluído/vínculo ativo (D8)
    # 3. tag BIGQUERY -> custo 0
    # 4. tag SAS/Local: tem produtor? -> D3 (agrupar por egp produtor) : -> D1
    # 5. tag SYBASE*: status_validacao Modernizada? -> D4a : -> D4b
    # 6. imported_files (não-sas7bdat-macro) -> D2
    # 7. D4c = connection_libs - {DBCON, PERM} se houver macros User_*/pw_*
    # 8. D7 = inputs cujo único produtor é a OUTRA versão

W = dict(ing_sas=5, ing_file=2, dep_egp=3, pt_map=1, pt_unmap=4, cred=2, task=0.5)
C_TROCA = 8
MARGEM = 0.8

def score(m):  # m = métricas classificadas
    return (W['ing_sas']*m.d1 + W['ing_file']*m.d2 + W['dep_egp']*m.d3
            + W['pt_map']*m.d4a + W['pt_unmap']*m.d4b + W['cred']*m.d4c
            + W['task']*m.d5)

def decide(escopo, candidata):
    if paridade_outputs(escopo, candidata) < 0.8: return "G3: não substitutas"
    gates = g1_produtor_orfao(candidata, escopo) + g2_consumidor_orfao(escopo)
    s_e, s_c = score(escopo), score(candidata) + C_TROCA
    veredito = "TROCAR" if s_c < s_e * MARGEM else "MANTER ESCOPO"
    return veredito, s_e, s_c, gates   # sempre reportar gates pendentes
```

Recomendações para a automação:
- **Reportar sempre os dois cenários de G1** (otimista/pessimista) quando houver produtor órfão.
- **Log de exclusões**: listar o que foi filtrado (DICTIONARY, sanitizados, rereads) — auditabilidade do número final.
- **Calibração**: guardar `(métricas, pesos, decisão, esforço real medido depois)` por caso e ajustar `W` por regressão simples quando houver ≥5 casos.

## 8. Limitações e armadilhas conhecidas

- **Match de produtor por nome é insuficiente em geral** — a identidade canônica do corpus é `(path físico, member)`; a mesma lib alias pode apontar para dirs diferentes entre EGPs. No caso de origem os paths batiam; a automação deve validar sempre.
- **`06_prontidao_tabela.csv` mistura leituras internas em `table_in`** — o filtro pelo `EXTERNAL INPUTS` do header é obrigatório.
- **Snapshot ≠ ingestão** para tabelas recalculadas com frequência (caso das aux de fatura): tratar como G1, não como D1 comum.
- **Pesos são estimativas** de um único caso — a margem de 20% na decisão é o amortecedor até haver calibração.
- O extractor tem correções recentes (snapshots de autosave, BQ pass-through over-capture) — comparar versões **extraídas com a mesma versão do extractor**; se a extração do escopo for antiga, re-extrair antes de medir.
