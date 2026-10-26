# Pós-deploy — branch `feature/updated-egps-unification`

> **Escrito em 30/09/2026.** A branch foi validada num schema descartável
> (`bv_dev_db.monitoramento_sas_atualizados_dev`). Além do CÓDIGO, ela produziu **decisões
> de gestão que são dado** e não viajam no `databricks sync`. Prod tem **zero** vínculos.
> Este é o roteiro para levá-las, na ordem que importa.

## A ordem importa

Cada passo é pré-requisito do seguinte. Pular o 2 faz o 3 recusar com 404 — corretamente.

### 1. Merge + deploy do código

Pelo caminho normal (PR → `main` → Bitbucket Pipelines, `app/docs/DEPLOY.md`). Nada aqui
depende de dado.

### 2. Publicar o corpus em prod

Os EGPs atualizados **não estão no corpus de prod**: 1.229 nós lá contra 1.270 no ambiente.
Sem eles, nenhum vínculo do passo 3 tem sucessor para apontar.

```bash
cd egps_analysis && venv/bin/python publish_to_databricks.py --apply \
    --schema monitoramento_sas --prod-confirm --profile bv --warehouse-id <id>
```

**O publish agora reaplica e confere a identidade sozinho** (ticket 25): ele reaplica os
colapsos de `sas_input_alias_canonico` que o full-replace desfaz e **sai 1** se sobrar
alguma decisão desfeita ou flag derivada defasada. Se ele falhar aí, leia a mensagem antes
de seguir — os números estarão errados.

**Verifica:** `venv/bin/python identidade_guard.py --schema monitoramento_sas` diz
`OK — 101 colapso(s) do mapa seguem aplicados`.

### 3. Replicar os ajustes de classificação

```bash
cd egps_analysis && venv/bin/python scripts/pos_deploy_ajustes.py            # dry-run
cd egps_analysis && venv/bin/python scripts/pos_deploy_ajustes.py --aplica
```

Lê do ambiente de validação em vez de carregar lista no código — reconstruir 23 vínculos à
mão depois seria frágil. Aplica pelo ENDPOINT, nunca por SQL: as guardas do §3.2.7 e a
cópia do §3.3.11 moram no PATCH, e migrar vínculo por UPDATE cru já reintroduziu o bug do
ticket 07 uma vez. Idempotente.

Leva: **23 vínculos**, a declaração do `Cobranças__ROI` como EGP novo (`egps_novos`) e **2
acertos de etapa/status** do `Reneg_Remunerav3`, que estão explícitos no topo do script
porque são julgamento, não derivação.

### 4. Reparar a etapa espelhada

```bash
cd egps_analysis && venv/bin/python scripts/copia_vinculo_retroativa.py --schema monitoramento_sas
cd egps_analysis && venv/bin/python scripts/copia_vinculo_retroativa.py --schema monitoramento_sas --aplica
```

Antecessor cuja etapa EXIBIDA ficou vazia porque o sucessor não tem etapa. Roda a cópia do
§3.3.11 pela MESMA função do PATCH, mirando o FIM da cadeia de espelhamento. No ambiente
isso resolveu 10 EGPs — sem ele a tabela "Funil de migração por mês" marcava 183 dos 193.

Deve dar 0 se o passo 3 rodou limpo (a cópia acontece no ato do vínculo); serve de rede.

## Verificação final

| o que | onde | esperado |
|---|---|---|
| Total de EGPs | Visão geral | **193**, com `(+N extra)` ao lado |
| Funil de migração por mês | Resumo | soma **193** |
| Soma dos 3 grupos de input | Visão geral | escopo + deps + extras = Total |
| Identidade | `identidade_guard.py` | `OK`, exit 0 |
| Vínculos | `sas_egp_pipeline` | 23 com `egp_sucessor` preenchido |

```bash
cd .. && DATABRICKS_CONFIG_PROFILE=bv egps_analysis/venv/bin/python .scratch/egps-vinculo-sucessor/../medir_linha_base.py
```

## O que NÃO vai neste roteiro

- **Desmontar o ambiente descartável** (app `monitoramento-sas-atualizados` + schema
  `monitoramento_sas_atualizados_dev`) — só depois de a gestão conferir prod.
- **A classificação dos vínculos restantes.** Os 23 são os que a gestão já decidiu; o que
  chegar depois entra pela UI (ticket 20).
- **`ex_deps_manuais`** — já está igual nos dois schemas.

## Tickets abertos que este deploy não fecha

- **23** — contador "no corpus, sem vínculo". Sem ele, um EGP atualizado que chega sem
  vínculo é silenciosamente reclassificado como dependência e distorce o card que a gestão
  lê (aconteceu com 3 EGPs, medido em 30/09).
- **24** — UI para declarar EGP novo; hoje `egps_novos` só se edita por script.
- **25, camada 3** — colapso de identidade DERIVADO no backend. As camadas 1 e 2 reparam
  depois do publish; a 3 faz não haver o que reparar.
