# Genie space — agente de consulta do app (Migração SAS)

Fontes do Genie space que a aba **Perguntas** do app embute em iframe. O agente responde
status de EGPs/inputs, **por que uma tela mostra X e outra Y** (apontando os itens),
recortes, histórico e comentários. Decisões: `docs/adr/0004-app-grava-classificacao-para-consulta.md`
(raiz do repo) e o glossário `CONTEXT.md`.

| Space | id | Lê | Estado |
|---|---|---|---|
| Oficial — "Consulta do app — Migração SAS" | `01f1c0f81649139385ba0856ebefbfad` | schema de PROD | versão consulta desde 08/10/2026 (23/23 e 22/23 nos benchmarks com dados de prod) |

Para testar uma mudança antes do oficial, crie um space temporário com `--schema
monitoramento_sas_dev` (as tabelas `sas_consulta_*` do dev precisam estar gravadas) e
apague-o depois — foi assim na migração (space de prévia, já apagado).

- Acesso: "Can run" para o grupo `bv_users`. É ESSA permissão que controla quem usa — a aba
  do app só esconde o iframe de quem não é `bv_users`.
- Embed: liberado no workspace só para os domínios do app; `GENIE_EMBED_URL` no `app.yaml` e
  no `app.dev.yaml` aponta para o space oficial.

| Arquivo | Conteúdo |
|---|---|
| `instrucoes.md` | Instruções gerais. Na montagem, o catálogo `../docs/divergencias-entre-telas.md` é anexado — ele é a fonte das explicações de "por que X ≠ Y". |
| `exemplos.sql` | SQLs de exemplo, blocos `-- <ID> <pergunta>`; `R*` = reconciliação entre telas; `P*` usam parâmetros declarados em `conhecimento.py`. |
| `conhecimento.py` | Knowledge store: colunas (descrição, sinônimos, entity matching, exclusão), joins, filtros/campos/medidas nomeados, parâmetros. |
| `benchmarks.sql` | Perguntas de avaliação com SQL-gabarito (`-- <ID> \| escalar\|conjunto \| <pergunta>`). Estado de EGP/input tem gabarito nas tabelas de consulta (a régua do app). Não repita aqui perguntas que já são exemplo. |
| `valida_conhecimento.py` | Roda tudo acima contra o schema-alvo (só leitura): coluna inexistente, expressão que não compila, join sem casamento, exemplo/gabarito quebrado. |
| `monta_space.py` | Gera `serialized_space.json` + `update_body.json` (formato `version: 2`). |
| `avalia.py` | Pergunta os benchmarks ao Genie (conversa nova cada) e compara com o gabarito. |

Os SQLs são escritos com o schema de PROD (`bv_dev_db.monitoramento_sas.`); `--schema` /
`GENIE_SCHEMA` trocam o prefixo para o alvo.

## Atualizar um space

```bash
cd egps_analysis/app/genie
PY=../../venv/bin/python                                 # precisa do databricks-sdk e do profile `bv`
$PY valida_conhecimento.py [--schema monitoramento_sas_dev]   # 0 falhas antes de subir
python3 monta_space.py [--schema monitoramento_sas_dev]       # -> serialized_space.json, update_body.json
databricks genie update-space <space_id> -p bv --json @update_body.json
GENIE_SPACE_ID=<space_id> GENIE_SCHEMA=<schema> $PY avalia.py <rotulo>   # 2 rodadas antes de concluir
```

- `update-space` SUBSTITUI o space inteiro — edições feitas pela tela do Genie que não
  estiverem aqui se perdem. Mudou pela tela? Traga para estes arquivos antes.
- Mudou o que uma tela do app conta? Atualize o catálogo e a coluna `conta_*` correspondente
  (ver `frontend/ONBOARDING.md`) e rode o `avalia.py`.
- Formato do `serialized_space` (confirmado em 06/10/2026): `version: 2` (é ela que aceita
  `enable_entity_matching`/`enable_format_assistance`), textos como lista de linhas,
  `join_specs`/`sql_snippets` dentro de `instructions`, coleções com `id` ordenadas por id,
  `column_configs` ordenados por nome.
- Arquivos gerados (`serialized_space.json`, `update_body.json`, `create_*`, `avaliacao_*.json`)
  não são versionados.
