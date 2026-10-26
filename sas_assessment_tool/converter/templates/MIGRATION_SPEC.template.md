# MIGRATION_SPEC — `<egp_key>`

Contrato de contexto para tradutor (Agente 1) e governança (Agente 2).

**Gerar preenchido automaticamente:** a partir de `converter/`, execute:

`python generate_migration_spec.py "<egp_key>"`

Isto cria `draft_models/<egp_key>/MIGRATION_SPEC.md` com dados do `egp_catalog.yaml`, `area_cd_governanca.yaml` e cabeçalho de `text_egps/<egp_key>.txt`. Complete as secções **TODO** manualmente se necessário.

---

## Estrutura (referência)

1. Identificação (egp_key, PROJECT, EGP_SLUG, produto_compacto)
2. Arquitetura alvo (TARGET_ARCH efetivo, override, resumo extrator)
3. Catálogo e governança (area, cd_governanca, componente_dbt, staging_mode, staging_ref_map)
4. Paths dbt (clone root, DBT_CLONE_DEST, sandbox)
4.1 Nomenclatura e anti-colisão (contrato)
5. Fontes e saídas (TODO analítico) — incluir em **saídas (marts)** cada `PROC EXPORT` e cada persistência em **libref de biblioteca permanente** (não `WORK`) / entrada de **`PERMANENT OUTPUTS (Target Marts)`** no cabeçalho do `.txt` (ver `01_sas_to_dbt.mdc` §2.1–2.2).
6. Macros e parâmetros críticos
7. Ordem lógica / dependências
8. Filtros (ligação a FILTERS_ORIGINAIS)
9. Manifest canónico do draft (`draft_manifest`, editável)

Ver também `docs/AGENT_CONVERSAO_MELHORIAS.md` (secções 1 e 3).

---

## Contrato “machine-readable” (obrigatório)

O `generate_migration_spec.py` inclui no topo do `MIGRATION_SPEC.md` um bloco:

- `## 0. CONTRATO (machine-readable)`
- um bloco ` ```yaml ... ``` `

Esse YAML é a **fonte de verdade** para checagens mecânicas (ex.: `draft_gate.py`) e evita depender de parsing frágil de tabelas Markdown.

Regras:

- **Não edite manualmente** o YAML do **§0 CONTRATO** (gerado pelo script).
- Para mudar valores do contrato, altere o `registry/egp_catalog.yaml` (ou re-extraia o `.txt`) e **regenere** o spec.

---

## 9. Manifest canónico do draft (editável)

Lista fechada dos modelos que **devem existir** em `draft_models/<egp_key>/models/{staging|intermediate|marts}/` antes do `draft_gate` (quando preenchida, o gate valida ficheiro a ficheiro).

**Isto é independente** do bloco `## 0. CONTRATO` — pode e deve ser editado pelo analista ou pelo Agente 1 após criar/renomear `.sql`/`.py`.

Exemplo (copiar, ajustar `stem` aos nomes reais; `layer` obrigatório: `staging`, `intermediate` ou `marts`):

```yaml
draft_manifest:
  schema_version: 1
  models:
    - layer: staging
      stem: stg_meu_fluxo_fonte
    - layer: intermediate
      stem: int_produto_compacto_passo
    - layer: marts
      stem: produto_compacto_saida_fato
```

- Com `models: []` ou sem este bloco: o `draft_gate` **não** falha por manifesto (cobertura fica a cargo da revisão / checklist semântica).
- Com `models` **não vazio**: cada par (`layer`, `stem`) tem de corresponder a `models/<layer>/<stem>.sql` ou `.py` no draft; caso contrário o gate **erro**.
- Alinhe entradas a **`PERMANENT OUTPUTS (Target Marts)`**, a **escritas em libref permanente** (ex.: `data ADAMOR....`) visíveis no SAS, e a cada **`PROC EXPORT`** → 1 mart (ver `01_sas_to_dbt.mdc` §2.1–2.2). **Sem** export nem libref permanente a mapear, os marts de fallback devem seguir **§2.3** (tabela(s) **`WORK` terminal(is)** — não a regra “1 mart por `int_*`”). Documente no §5 qualquer fusão de duas saídas num único mart.
