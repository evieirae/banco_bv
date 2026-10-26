# Monitoramento de Outputs — Design Spec

- **Data:** 2026-07-04
- **App:** `monitoramento-sas` (`egps_analysis/app/`)
- **Status:** design aprovado pelo usuário ("do it")
- **Autor:** Lucas Müller (+ Claude Code)

## 1. Objetivo

Nova aba **Monitoramento Outputs**, análoga à de inputs mas para as tabelas/artefatos **produzidos** pelos EGPs. **Read-only** (sem status/responsável — os outputs não serão migrados), focada em **informação**: quem produz, quem consome, se é terminal ou intermediário, e se já existe no lake.

## 2. Achado que motiva o trabalho

Os outputs **não estão em nenhuma tabela Delta consultável** hoje. Eles existem no report 06 (`table_out` 45.665, `file_out` 2.148, `libname_out` 1.650 linhas) mas o `publish_to_databricks.py` **filtra e descarta** outputs ao montar `sas_inputs_monitor` (só `table_in/file_in/script_in` entram; ver `publish_to_databricks.py:337-365`). O que sobra em Delta é só o contador agregado `sas_lineage_nodes.n_outputs`. Portanto a feature exige **pipeline (publish) + backend + frontend**, não é só-frontend.

## 3. Decisões (com o usuário)

- **Incluir todos os tipos de output:** `table_out`, `file_out`, `libname_out` (usuário escolheu "tudo"). `libname_out` é binding de libname, não tabela de dado — fica **filtrável por categoria** (não removido).
- **Infos por output:** nome, categoria, área(s), produtor(es), nº consumidores, **terminal × intermediário**, **disponível no lake**, e **listas de EGPs** (produtores/consumidores) via drawer.
- **"Também é input" fundido em "terminal/intermediário":** são o mesmo sinal (um output é intermediário exatamente quando ≥1 EGP o consome). Sem coluna redundante.
- **Read-only:** sem `status_humano`/`responsavel`/`observacao`. As tabelas de output são **full-replace** a cada publish (sem MERGE de colunas humanas).

## 4. Dados (pipeline + Delta)

Duas tabelas novas, criadas no `publish` (full-replace, como edges/nodes/egp_inputs):

- **`sas_egp_outputs`** (grão EGP×output; espelha `sas_egp_inputs`): `projeto, area, onda, escopo_indi, chave_canonica, artifact, categoria`.
- **`sas_outputs_monitor`** (grão output distinto): `chave_canonica, artifact, categoria, areas, qtd_produtores, qtd_consumidores, terminal BOOLEAN, modernizada_auto, escopo_indi`.

Construção no `publish` (reusa estruturas já computadas): a partir das linhas de output do report 06 e dos dicts existentes `proj_out` (outputs por EGP) e `proj_in` (inputs por EGP):
- **produtores(o)** = EGPs com `o` em `proj_out`.
- **consumidores(o)** = EGPs com `o` em `proj_in` (mesmo `canon()`), i.e. quem lê aquele nome como input.
- **terminal** = `qtd_consumidores == 0`.
- **modernizada_auto** ("disponível no lake") = reusa a detecção de modernização (chameleon + `inputs_modernizados.csv`) aplicada ao nome do output.
- **areas** = união das áreas dos produtores.
- **escopo_indi** = ≥1 produtor no escopo (`sas_escopo`).
- **canonicalização** = mesma `canon()`/`is_noise_table` já usada p/ inputs (consistência de identidade).

**`recompute_escopo` (backend)** passa a re-derivar `escopo_indi` também nas 2 tabelas de output — **com guarda**: se as tabelas ainda não existem (antes do 1º publish com outputs), os UPDATEs de output são **pulados** (não podem quebrar a edição de escopo, que é frequente). Roda via `exec_fn` (OBO nas edições; SP no job de ingestão).

## 5. Backend (3 endpoints read-only)

- `GET /api/outputs?scope&area&categoria&q&terminal` → lista filtrada de `sas_outputs_monitor` (`OutputRow[]`). `scope` ∈ {indi, base} (default indi). `terminal=true` → só terminais.
- `GET /api/output?chave=` → detalhe p/ o drawer: **produtores** (de `sas_egp_outputs`) + **consumidores** (de `sas_egp_inputs`), cada um com projeto/área.
- `GET /api/outputs-egps?scope&area` → pares `chave_canonica`→`projeto` (produtor) p/ o export explodido.

Sem escrita. Gating: aberto (como `/api/inputs`; não é restrito a bv_users).

## 6. Frontend — aba "Monitoramento Outputs" (slug `/monitoramento-outputs`)

- Registrada em `routes.ts`/`App.tsx` (visível a todos, como Monitoramento Inputs).
- **Colunas:** Artefato · Categoria · Área(s) · Produtores (nº) · Consumidores (nº) · Terminal/Intermediário · Disponível no lake.
- **Filtros** (espelham inputs, adaptados): **escopo** (só Indicium / base), **área** (multi), **categoria** (multi: table_out/file_out/libname_out), toggle **"só terminais"**, **busca**. **Sem** status/responsável.
- **Drawer** ao clicar na linha: listas de EGPs **produtores** e **consumidores** (via `/api/output`).
- **Exportar CSV** reusando `csv.ts` — **nome do EGP sem prefixo de área** (`egpShort`). Colunas do CSV = as da tabela; explode por EGP produtor via `/api/outputs-egps` (espelha o export de inputs).
- **Default escopo Indicium** (base completa pode ter ~20k+ outputs distintos; Indicium reduz o payload). Virtualização client-side (react-virtual, já usada nos inputs) se necessário.

## 7. Popular os dados

As 2 tabelas são criadas/preenchidas pelo `publish`. Após deployar publish+backend+front, rodar **um Processar & publicar** (aba Ingestão) ou um publish local. Até lá, `/api/outputs` retorna vazio e a aba mostra "nada" graciosamente.

## 8. Fora de escopo (YAGNI)

- Status/responsável/observação em outputs (não serão migrados).
- Editar/priorizar outputs.
- Paths físicos por output (não pedido; a identidade física é dos inputs).
- Lineage output→output multi-nível (o drawer mostra 1 salto: produtores + consumidores diretos).

## 9. Critérios de aceitação

- Aba lista os outputs do escopo Indicium com nome/categoria/área/produtores/consumidores/terminal/disponível.
- Filtros (área, categoria, só-terminais, busca, escopo) e busca funcionam client/server como na de inputs.
- Drawer mostra os EGPs produtores e consumidores corretos de um output.
- Export CSV sai com nome do EGP sem área.
- Editar o escopo (aba Escopo) re-deriva `escopo_indi` dos outputs **quando as tabelas existem**; nunca quebra a edição de escopo quando ainda não existem.
- `publish` cria/preenche `sas_egp_outputs` e `sas_outputs_monitor` sem afetar as tabelas de input nem as colunas humanas.
