---
name: github
description: Interage com o repositório GitHub: cria pull requests, lê e escreve comentários, consulta status de PRs, lista branches e verifica o status do pipeline de CI.
---

# Skill: GitHub Interaction

## Pré-requisitos

As seguintes variáveis de ambiente devem estar definidas:

| Variável | Descrição |
|----------|-----------|
| `GITHUB_TOKEN` | Personal Access Token com escopos `repo` e `read:org` |
| `GITHUB_REPO_OWNER` | Organização ou usuário GitHub (ex.: `indiciumtech`) |
| `GITHUB_REPO_NAME` | Nome do repositório (ex.: `sas_assessment_tool`) |

## Operações disponíveis

### Criar PR
```bash
python tools/github_tools.py create-pr \
  --title "feat: migração EGP [NOME]" \
  --source <branch> \
  --target main \
  [--description "Texto da descrição"] \
  [--draft]
```

### Ver status de um PR
```bash
python tools/github_tools.py get-pr --id <número>
# Retorna: id, title, status (draft/open/merged/closed), url, source_branch, target_branch
```

### Listar PRs
```bash
python tools/github_tools.py list-prs [--state open|closed|all]
```

### Ler comentários de um PR
```bash
python tools/github_tools.py list-comments --pr-id <número>
```

### Adicionar comentário a um PR
```bash
python tools/github_tools.py add-comment --pr-id <número> --body "Texto do comentário"
```

### Responder a um comentário de review (thread na linha/arquivo)
Usa a API de *pull request review comments* (`in_reply_to`), não o comentário geral da *issue*.

```bash
python tools/github_tools.py reply-review --pr-id <número> --in-reply-to <id_do_comentário> --body "Texto"
# ou corpo longo / UTF-8:
python tools/github_tools.py reply-review --pr-id <número> --in-reply-to <id> --body-file caminho.md
```

O `id` do comentário de review aparece na API `GET /repos/{owner}/{repo}/pulls/{pr}/comments` ou na URL da discussão no GitHub.

### Listar branches
```bash
python tools/github_tools.py list-branches
```

### Ver status do pipeline de CI
```bash
python tools/github_tools.py pipeline-status --pr-id <número>
# ou por commit SHA:
python tools/github_tools.py pipeline-status --commit <sha>
# Retorna: name, state (success/failed/running/pending), url
```

## Integração com o pipeline de migração

Após o skill `/orchestrator` concluir com sucesso (PASSO 6):

1. Execute `list-branches` para confirmar que o branch do projeto existe.
2. Execute `create-pr` apontando para `main`, com o título `feat: migração EGP [NOME_DO_PROJETO]`.
3. Use o conteúdo do `AUDITORIA_[NOME].md` como `--description` do PR.
4. Execute `pipeline-status --pr-id <id>` para confirmar que os checks de CI passaram.

**Não abra o PR antes do PASSO 6 ter sido concluído com sucesso.**
