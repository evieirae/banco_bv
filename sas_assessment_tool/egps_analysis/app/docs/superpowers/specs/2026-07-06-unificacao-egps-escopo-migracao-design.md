# Unificação: aba EGPs absorve Escopo de migração

**Data:** 2026-07-06 · **Decisões do usuário:** EGPs absorve · só frontier transitivo (1-nível morre) · cards de inputs distintos sempre visíveis · linhas de dependência editáveis.

## Backend
- `GET /api/egp-readiness?scope=indi|indi_deps|base` (novo valor `indi_deps` = mesmo `_frontier_egps` da Priorização/Resumo). `GET /api/migration-scope` **removido**.
- Cada row (ReadinessRow) ganha: `tipo` ("escopo"|"dependencia"), `dep_nivel` (0=base), `n_sem_fonte` (inputs SAS/Local externo não modernizados), `dep_ausente` (n_sem_fonte>0). Deps têm `responsavel` (vem de graça: linhas hidratadas pelo mesmo caminho).
- Payload ganha cabeçalho SEMPRE (qualquer scope): `base_count`, `dep_count`, `total`, `inputs_distintos`, `inputs_distintos_disp`, `inputs_distintos_faltam`, `inputs_distintos_base`, `inputs_sem_fonte` — calculados sobre o recorte do SELETOR (não sobre filtros client-side; legenda avisa).
- scope=indi/base: `tipo="escopo"`, `dep_nivel=0`, `dep_count=0`.

## Frontend (ReadinessView unificada)
- Seletor 3 opções: só Indicium / **Indicium + dependências** / todos. queryKey `["egp-readiness", scope]`.
- Cards no topo (sempre): EGPs (base+deps quando indi_deps), Inputs distintos, A ingerir, Sem fonte (com %). Chips de prontidão/quick-win/bloqueado inalterados (aplicam também às deps — bucket é por %).
- Coluna **Tipo** (badge escopo | dependência·N) só no modo indi_deps; **⚠** (sem fonte, tooltip n_sem_fonte) como badge no nome do EGP ao lado do 🔒.
- Deps editáveis: mesmos dropdowns etapa/status/responsável (PATCH já aceita qualquer projeto).
- CSV: + Tipo, Nível dep, Sem fonte.
- Remoções: aba/rota migration-scope, `MigrationScopeView.tsx`, `api.migrationScope`, tipos `MigrationScope*`; botão "abrir na aba EGPs ↗" do detalhe. **Alias**: slug `escopo-migracao` → readiness em `parsePath` (links salvos não quebram); deep-links `/egps/<id>` intactos.

## Verificação
pytest backend (25) + preview read-only dos números em prod + build TS + verificação visual pós-deploy. Deploy e push só com OK explícito.
