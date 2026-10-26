# 17: Migrar o estado editável do funil próprio (BLOQUEADO pelo 01)

**O que é:** O ticket 11 aposentou a aba EGPs Atualizados. Sobrou estado editável que vivia no funil próprio dela e ainda **não tem para onde ir**.

**Medido em prod, 28/09/2026 (somente leitura):**
- `sas_egp_pipeline` tem **10** linhas com `egp_atualizado_key` preenchido (o vínculo da aba antiga)
- `sas_egp_atualizados_pipeline` tem **5** linhas, das quais **3 com etapa/status reais**:
  - `Cobranças__Project_Fyf_Reneg_BQ_202608 1` — Validação da Área / Em Andamento
  - `Cobranças__First_Loss_GCP_2026` — Migrado / Migrado
  - `Cobranças__ROI` — Migrado / Migrado
- e **2** com `tipo_vinculo = 'atualizacao'` (coluna do PR #136): `PERF_REVISIONAIS_RPA` e `ACORDO_AMIGAVEL_v1_RPA`

**Por que está bloqueado:** **nenhum dos 5 existe em `sas_lineage_nodes`.** São versões recebidas que ainda não entraram no corpus — o limbo que o contador do ticket 10 mede. Não há linha de destino em `sas_egp_pipeline` para receber o estado; criá-la seria inventar projeto fora do corpus.

A spec §5 chama esta migração de "trivial". **Ela não é** — depende do ticket 01 (entrada no corpus), que por sua vez está bloqueado por insumo: não há `.egp` posterior a 01/09 no checkout.

**Nada foi perdido:** as 5 tabelas continuam existindo, write-isolated (ADR 0001), e o script de carga está intocado. O que se perde enquanto isso é a **visibilidade** do estado editável de 3 versões — coberta em parte pelo contador "Aguardando corpus".

**Blocked by:** 01 (entrada do sucessor no corpus)

**Status:** destravado NO CLONE; em PROD segue BLOQUEADO pelo ticket 01 (medido 01/10/2026 — ver §Correção)

- [ ] Os 5 sucessores entraram no corpus (ticket 01)
- [ ] Etapa/status das 3 linhas preenchidas foram para `sas_egp_pipeline` do projeto correspondente
- [ ] Os 2 `tipo_vinculo='atualizacao'` viraram `egp_vinculo_tipo='Atualizado'` + `egp_sucessor` apontando para o projeto do corpus
- [ ] Os 10 `egp_atualizado_key` foram reconciliados com o vínculo novo ou descartados conscientemente
- [ ] A escrita em prod foi autorizada explicitamente e o SQL revisado antes de rodar

---

## SQL pronto para revisão humana

Levantado em 28/09 contra prod (somente leitura). **Rodar só DEPOIS do ticket 01**, uma vez por versão — `<projeto_sucessor>` é a chave `Área__nome__ATU<data>` que o ticket 01 vai criar. **Escrita em prod exige autorização explícita.**

```sql
-- 1) etapa/status/responsável da versão -> funil de migração do SUCESSOR
MERGE INTO bv_dev_db.monitoramento_sas.sas_egp_pipeline t
USING (
  SELECT '<projeto_sucessor>' AS projeto,
         p.etapa, p.status, p.responsavel, p.responsavel_bv
  FROM bv_dev_db.monitoramento_sas.sas_egp_atualizados_pipeline p
  WHERE p.egp_key = 'Cobranças__ROI'        -- idem p/ 'Cobranças__First_Loss_GCP_2026'
) s ON t.projeto = s.projeto                 --  e 'Cobranças__Project_Fyf_Reneg_BQ_202608 1'
WHEN MATCHED THEN UPDATE SET
  t.etapa_migracao = s.etapa, t.status_migracao = s.status,
  t.responsavel = s.responsavel, t.responsavel_bv = s.responsavel_bv,
  t.updated_by = current_user(), t.updated_at = cast(current_timestamp() AS STRING)
WHEN NOT MATCHED THEN INSERT
  (projeto, etapa_migracao, status_migracao, responsavel, responsavel_bv, updated_by, updated_at)
VALUES
  (s.projeto, s.etapa, s.status, s.responsavel, s.responsavel_bv,
   current_user(), cast(current_timestamp() AS STRING));

-- 2) os 2 tipo_vinculo='atualizacao' viram o vínculo novo, no ANTECESSOR
UPDATE bv_dev_db.monitoramento_sas.sas_egp_pipeline
SET egp_vinculo_tipo = 'Atualizado', egp_sucessor = '<projeto_sucessor>',
    updated_by = current_user(), updated_at = cast(current_timestamp() AS STRING)
WHERE projeto = '<projeto_antecessor>';   -- Cobranças__REVISIONAIS_V1 / Cobranças__ACORDO_AMIGAVEL_v1__v2

-- 3) conferência antes e depois (não destrutiva)
SELECT projeto, egp_atualizado_key, egp_vinculo_tipo, egp_sucessor
FROM bv_dev_db.monitoramento_sas.sas_egp_pipeline
WHERE egp_atualizado_key IS NOT NULL OR egp_sucessor IS NOT NULL;
```

**Os 10 `egp_atualizado_key` NÃO devem ser sobrescritos pelo passo 2** — são chaves diferentes (chave da aba × projeto do corpus).

**Medido junto:** `egp_vinculo_tipo` e `egp_sucessor` têm **0 valores** em prod hoje; `sas_egp_atualizados` tem 41 versões, **nenhuma** nos quadrantes de pendência — a guarda implementada é para o futuro, sem caso vivo. A auditoria da aba tem 44 eventos / 7 EGPs / 3 autores (último 28/09 18:38), contra 30 na medição da spec.


---

## ⚠️ ARMADILHA DESCOBERTA AO RODAR (29/09/2026)

**O SQL acima, sozinho, PERDE a etapa do antecessor.** Descoberto migrando o primeiro caso
de verdade.

A cópia de etapa/mês/JIRA/responsável para o sucessor (§3.3.11, ticket 07) mora no
**`PATCH /api/egp-pipeline`**. Um `UPDATE` direto no `sas_egp_pipeline` grava o vínculo e
**pula a cópia** — e aí o antecessor passa a espelhar a etapa **vazia** do sucessor
recém-criado e cai para "sem etapa". É exatamente o bug que o ticket 07 existe para
corrigir, reintroduzido pela porta dos fundos.

**Duas saídas, nesta ordem de preferência:**

1. **Fazer a migração pela UI do vínculo** (ticket 20, já entregue) ou por uma chamada ao
   `PATCH`. Aí a cópia acontece sozinha, é auditada em `sas_pipeline_audit` na linha do
   sucessor, e as 4 guardas são exercitadas. **É o caminho certo.**
2. Se tiver mesmo de ser SQL, **replicar a cópia explicitamente** logo depois do UPDATE do
   vínculo — só nos campos vazios do sucessor, e criando a linha dele se não existir.

**Estado em 29/09:** o caso `Cobranças__ACORDO_AMIGAVEL_v1__v2` → `…_RPA__ATU20260910` foi
migrado no ambiente descartável pelo caminho 2, com a cópia replicada à mão. Verificado
depois: antecessor com `status='Desatualizado'` (derivado), `etapa_editavel=False`,
`etapa='Pré-conversão'` espelhada de um sucessor que agora tem etapa de verdade; sucessor
com `e_extra=True`, motivo `sucessor`. Total seguiu **193**; extras foram para **11**.

**Os outros 4 seguem bloqueados por arquivo faltando**, não por decisão: `First_Loss_GCP_2026`,
`ROI`, `Project_Fyf_Reneg_BQ_202608 1` e `PERF_REVISIONAIS_RPA` não vieram em nenhuma das
duas pastas processadas (01/09 e 10/09).

---

## Estado em 29/09, fim do dia

A pasta `Documents/EGPs Atualizados` trouxe os que faltavam. Dos 5 registros do funil proprio:

- **`ACORDO_AMIGAVEL_v1_RPA`** — migrado no ambiente descartavel e verificado ponta a ponta
- **`First_Loss_GCP_2026`**, **`Project_Fyf_Reneg_BQ_202608 1`**, **`PERF_REVISIONAIS_RPA`** — ja estao no corpus, prontos para migrar
- **`ROI`** — **nao se aplica**: o arquivo e SQL do BigQuery (nao SAS) e a linha esta em `Migrado/Migrado`. E o RESULTADO da migracao, nao backlog.

E os **12 `egp_atualizado_key`** agora tem sucessor no corpus (12 de 12), entao a UI do ticket 20 pre-preenche todos.

**O que falta e so a escrita em prod**, que exige autorizacao explicita — e deve ser feita **pela UI**, nao por SQL (ver a armadilha acima).

---

## Correção do status (01/10/2026, leitura em prod)

O status anterior dizia "4 de 5 destravados; escrita em PROD pendente de autorização".
**A autorização não é o bloqueio.** Medido em prod, somente leitura:

| | prod | clone `…_atualizados_dev` |
|---|---|---|
| projetos no corpus | **1229** | **1274** |
| `Cobranças__ROI` | ausente | presente |
| `Cobranças__First_Loss_GCP_2026` | ausente | presente |
| `Cobranças__Project_Fyf_Reneg_BQ_202608 1` | ausente | presente |
| `Cobranças__PERF_REVISIONAIS_RPA` | ausente | presente |
| `Cobranças__ACORDO_AMIGAVEL_v1_RPA` | ausente | presente |

Os cinco sucessores entraram **só no clone**. Em prod, `sas_egp_pipeline` tem as 10 linhas
com `egp_atualizado_key` e **0** com `egp_sucessor` — nenhum vínculo novo.

**Consequência:** mesmo com autorização, a migração falharia agora. O `PATCH
/api/egp-pipeline` recusa com 404 (*"sucessor … não está no corpus — rode o pipeline
antes de vincular"*), que é a guarda certa fazendo o trabalho dela. O caminho por SQL
contornaria a guarda e cairia direto na armadilha documentada acima (perde a etapa do
antecessor).

**A ordem real é:** (1) publish em prod levando os 5 ao corpus → (2) então autorizar e
migrar **pela UI do vínculo** (ticket 20). Pedir autorização antes do passo 1 seria pedir
permissão para uma operação que o servidor recusaria.

O ticket volta a depender do **01**, como estava antes — o que mudou em 29/09 foi o clone,
não prod.
