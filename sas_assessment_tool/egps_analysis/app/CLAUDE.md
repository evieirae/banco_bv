# CLAUDE.md — app `monitoramento-sas`

Antes de mexer neste app, leia **[`frontend/ONBOARDING.md`](frontend/ONBOARDING.md)** (regras duras + gotchas) e **[`README.md`](README.md) → Decisões de design** (o porquê das escolhas). Não reinvente o que já está documentado. Perguntas sobre abas/permissões/fluxos de usuário: **[`GUIA_DO_APP.md`](GUIA_DO_APP.md)**.

Atalhos críticos (detalhe no ONBOARDING):

- **Deploy e escrita em produção → só com consentimento humano explícito.** Nunca `git commit`/`push` sem o usuário pedir (e **sem** `Co-Authored-By`).
- **Não use `curl`** — é bloqueado por política da organização (será negado). Para checar o app localmente, use `./local_app.sh` (que pode chamar `curl` internamente).
- **Tabelas de prod:** `bv_dev_db.monitoramento_sas` (profile `bv`, warehouse `5922c26f81f1bbdd`). Não é `client_journey`.
- **OBO:** cada query roda como o usuário logado; `REQUIRE_OBO=true` recusa request sem token.
- **`frontend/src/pipeline.ts` espelha `backend/main.py`** (status/funil) — sincronize os dois.
- **Não remova `<base href="/">` do `frontend/index.html`** — sustenta os deep-links de rota aninhada (`/egps/<id>`).
- **`backend/main.py` pode estar bloqueado para Read** (context-guard) — edite via subagente/replace direcionado e revise com `git diff`.
