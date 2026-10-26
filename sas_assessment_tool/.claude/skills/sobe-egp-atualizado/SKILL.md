---
name: sobe-egp-atualizado
description: Use when new .egp files must ENTER the corpus — a folder the BV sent, a Downloads folder with updated versions, "sobe esses EGPs", "adiciona no app". Covers the whole path from the binary to the published corpus: name collision, area inference, extraction, orchestrator, publish, and the verification that proves nothing was lost. Does NOT create the vínculo — that is `vincula-egp-atualizado`, and skipping it silently reclassifies the EGP as a dependency.
---

# Subir EGP atualizado para o corpus

Leva um `.egp` do disco até o corpus publicado. São 6 passos e cada um tem uma armadilha
que já mordeu — todas medidas, nenhuma hipotética.

## Antes de tudo: isto não termina aqui

Um EGP que entra no corpus **sem vínculo** não fica só invisível. Ele produz tabelas que a
linha de base consome, o grafo o puxa como **dependência**, e os inputs dele vão para o
card de dependências da gestão. Medido em 30/09/2026: 3 EGPs assim moveram 26 inputs e o
card marcava 88 contra os 61 de produção.

Depois desta skill, rode `vincula-egp-atualizado`. Sempre.

## Passo 1 — Colisão de nome (ANTES de copiar)

```bash
find received_egps/ -name "<arquivo>.egp"
```

Nome igual ao de um EGP do corpus **sobrescreve o antecessor**. O caso real: o BV mandou
`Import_Excecoes.egp`, que tem exatamente o nome do `Import_Excecoes` já publicado —
copiar por cima trocaria o antecessor em vez de adicionar o sucessor, e o diff antigo ×
novo deixaria de existir.

## Passo 2 — Normalizar o nome

| situação | o que fazer |
|---|---|
| sufixo ` 1`, ` 2`, `(1)` | **remover** — é duplicata de download do Windows, e já criou EGP fantasma neste corpus |
| colide com projeto existente | acrescentar `__ATU<AAAAMMDD>` (régua §2 etapa 2 da spec) |
| cadastrado em `src/egps_casca.csv` como `unificado_em` | usar **exatamente** a grafia de lá |

A última não é estética: as cascas são declaradas pela coluna `unificado_em`, e se o
unificador entrar com outra grafia o vínculo não casa e as cascas ficam órfãs.

A chave do projeto no corpus é `<pasta>__<nome do arquivo>`. A pasta é o rótulo CRU da
área ("Cobranças"), que **não** é igual à área canônica ("Cobrança") — não unifique as duas.

## Passo 3 — Extrair com a área certa

```python
import egps_extractor as ex
ex.extract_code_from_egp("received_egps/Cobranças/<arq>.egp",
                         ex.DEFAULT_OUTPUT_FOLDER, business_area="Cobranças")
```

**Não** chame `python egps_extractor.py <arquivo>`. Passando arquivo avulso o extrator não
infere a área — só a varredura de pasta faz isso — e o EGP entra como área **"Raiz"**, com
o `.txt` sem o prefixo. Aconteceu em 30/09: os 4 saíram errados e só não viraram corpus
porque o `[OK]` da saída mostra a área.

**Verifique a linha `[OK]`**: tem de dizer `Área: <sua área>` e o arquivo tem de nascer
`text_egps/<Área>__<nome>.txt`.

## Passo 4 — Orquestrador (~5,5 min)

```bash
venv/bin/python orchestrator_inventory.py
```

Regenera `01_*.csv` … `08_*.csv` a partir de `text_egps/`. **Eles são versionados** — rodar
aqui é certo quando o objetivo é subir EGP, e é proibido quando o objetivo é só analisar
(aí vai em worktree descartável; ver `analise-egp-atualizado`).

Confira que os novos entraram: `grep -l "<nome>" 0*.csv`.

## Passo 5 — Publish

```bash
DATABRICKS_CONFIG_PROFILE=bv venv/bin/python publish_to_databricks.py \
  --apply --schema <schema> --profile bv --warehouse-id <id>
```

Sem `--apply` é dry-run. Contra o schema de PROD exige `--prod-confirm`.

**Se o publish morrer depois de "lineage recriadas":** o corpus subiu e a reaplicação de
identidade ficou pela metade — os colapsos de alias estão desfeitos. Aconteceu em 30/09 por
falha de DNS. Rode, nesta ordem, antes de olhar qualquer número:

```bash
venv/bin/python identidade_reaplica.py --schema <schema> --profile bv --warehouse-id <id> --aplica
```

É idempotente: reconhece o que já foi aplicado. Depois rode a guarda
(`identidade_guard.checa_no_banco` e `flags_defasadas`); as duas têm de voltar
`ok: True` e `0`.

## Passo 6 — Verificar

Três perguntas, nesta ordem:

1. **Entraram?** `sas_lineage_nodes` subiu pelo número de EGPs novos.
2. **Onde caíram?** Leia `_egp_readiness_uncached("indi_deps")`. Sem vínculo, o normal é
   cair em `dependencia` (se produz algo que a base lê) ou ficar **invisível**. As duas
   coisas são defeito a resolver no passo seguinte, não resultado final.
3. **Perdeu alguém?** Compare os projetos do `05_prontidao_egp.csv` com os nós do schema.
   Casca não conta: ela não sai do orquestrador, o publish a recria de `src/egps_casca.csv`.

## O que esta skill NÃO faz

- **Não cria vínculo.** Use `vincula-egp-atualizado`.
- **Não escreve em prod** sem autorização explícita daquela execução.
- **Não decide se vale a pena subir.** Isso é `analise-egp-atualizado`, que mede impacto
  downstream, veto e quadrante. Rode ela ANTES quando a pergunta ainda for "vale?".

## Efeito fora da árvore

`received_egps/` costuma ser compartilhado entre o repo principal e os worktrees (symlink).
Copiar `.egp` ali torna o arquivo parte do corpus para **qualquer** sessão, e um publish em
prod feito de outro lugar passaria a incluí-lo. É aditivo e não toca antecessor, mas diga
isso ao usuário em vez de deixar implícito.
