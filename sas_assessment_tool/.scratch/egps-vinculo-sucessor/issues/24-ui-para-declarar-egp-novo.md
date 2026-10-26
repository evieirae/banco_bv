# 24 — UI para declarar "EGP novo" (a 3ª perna do `extra`)

**Status:** ENTREGUE (01/10/2026) — ver §Entregue

## O problema

O motivo `novo` entrou com a decisão do `Cobranças__ROI` (*"entra como um a mais mesmo"*),
e a lista que o alimenta é uma linha em `sas_app_config`:

```
chave = 'egps_novos'   valor = '["Cobranças__ROI"]'
```

**Escrita só por script.** Para o próximo EGP que chegar sem substituir ninguém, a gestão
depende de alguém com acesso ao warehouse. As outras duas pernas do `extra` não têm esse
problema: `sucessor` sai do vínculo, que tem painel (ticket 20), e `casca` é derivada do
publish.

Efeito colateral do mesmo buraco: `ex_deps_manuais` (a retenção manual de ex-dependência)
está exatamente na mesma situação, e por isso convém resolver as duas na mesma tela.

## O que fazer

**Onde:** aba **Gestão**, junto do CRUD de Responsáveis BV — é onde já mora a edição de
cadastro, e o gate é o mesmo (`bv_users`).

**Endpoint:** `PATCH /api/egps-novos`, espelhando `priorizacao_set_capacidade`
(`main.py:5917`), que é o precedente pronto para escrita em `sas_app_config`:

- `_require_gestao()` antes de qualquer leitura;
- `MERGE INTO {T_CFG}` por chave, gravando `updated_by = current_user()` e `updated_at`;
- auditoria em `{T_PIPE_AUD}` com o projeto sentinela `'(config)'`, campo `egps_novos`.

**Recusas que o endpoint deve fazer** (falha alta, nunca adivinha):

1. projeto que **não está em `sas_lineage_nodes`** → 404 com a mesma mensagem do vínculo
   ("rode o pipeline antes"); declarar quem não existe cria um extra fantasma;
2. projeto **na linha de base congelada** → 409. Hoje `_egps_novos()` o descarta em
   silêncio na leitura (de propósito, para nunca duplicar), mas quem clicou merece saber
   que o clique não fez nada;
3. projeto que **já é sucessor ou casca** → 409: o vínculo vence a declaração
   (`motivo_extra` já decide assim), então declarar seria um no-op enganoso.

**UI:** lista + campo com `datalist` sobre o corpus (mesmo componente do
`VinculoSucessorPanel`) + botão Remover. Ao lado de cada item, o motivo pelo qual ele é
extra hoje, para a gestão ver quando a declaração virou redundante (o EGP ganhou vínculo).

## Dívida a limpar junto

A linha que eu semeei em 29/09 foi um `INSERT INTO {T_CFG} (chave, valor)` — a tabela tem
4 colunas, então `updated_by` e `updated_at` ficaram **NULL**. O primeiro save pela UI
corrige; até lá, não dá para saber quem declarou o ROI (fui eu, por script).

## Verifica

- declarar um EGP fora da linha de base faz o contador "(+N extra)" subir 1 e o funil de
  extras ganhar 1 no denominador, **sem mexer no total de 193**;
- remover a declaração devolve tudo ao estado anterior (é derivado, nada materializado);
- as três recusas acima retornam o código certo e não gravam nada.

## Entregue (01/10/2026)

**Backend** (`main.py`, junto de `_egps_novos` para leitura e escrita da mesma config
ficarem adjacentes):

- `_egps_novos_raw()` — a lista CRUA, sem o filtro da linha de base. `_egps_novos` filtra
  na leitura; se a escrita usasse a lista filtrada, remover um item escondido por esse
  filtro seria um clique sem efeito;
- `_grava_egps_novos()` — MERGE em `sas_app_config` + auditoria em `sas_pipeline_audit`
  (`'(config)'`, campo `egps_novos`) + `_bump_gen()`. Sem o bump o contador `(+N extra)`
  seguiria servindo a geração anterior;
- `GET /api/egps-novos` — lista + `motivo_sem_declaracao` (o que sobraria sem a
  declaração) e `redundante`;
- `PATCH /api/egps-novos` — `declarar` / `remover`, com as três recusas do ticket.

**Frontend:** seção **EGPs novos** na aba Gestão, acima de Responsáveis BV. Campo com
`datalist` sobre o corpus (mesma queryKey `nodes-all` do `VinculoSucessorPanel`, que é a
mesma lista que a guarda 404 do servidor consulta), tabela com o motivo ao lado e botão
Remover. Linha redundante fica esmaecida com o motivo explícito.

### Verificado

13 testes novos (`test_egps_novos_endpoint.py`), 499 na suíte. As três recusas provam
também que **não gravam nada** (nenhum MERGE/INSERT emitido) — declarar quem não existe
criaria um extra fantasma irrastreável.

Round-trip ao vivo no clone `monitoramento_sas_atualizados_dev`:

| | total_egps | extras |
|---|---|---|
| antes | 193 | 24 |
| declarado `Atacado__ARQPAUTA_vAut` | **193** | **25** |
| removido | 193 | 24 |

Total congelado intacto, extra +1, volta exata ao estado anterior.

**Dívida do seed limpa** no clone: `updated_by = lucas.muller@indicium.ai` e `updated_at`
preenchidos, 2 eventos na auditoria. **Em prod a linha segue com os dois NULL** — como o
ticket previu, o primeiro save pela UI corrige.
