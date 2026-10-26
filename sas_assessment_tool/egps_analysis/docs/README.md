# Artefatos de organização da migração — manifestos & docs

> Última atualização: **2026-06-10**.
> Este arquivo explica os **manifestos** (`egps_analysis/_manifests/`) e as **pastas de `docs/`** criadas durante a preparação dos insumos da migração SAS→dbt. Para o status e os próximos passos da migração em si, ver [`STATUS_MIGRACAO_SAS.md`](../../STATUS_MIGRACAO_SAS.md) na raiz.

## Contexto (por que esses artefatos existem)

A migração começou com **~960 `.egp` + `.zip` e centenas de scripts `.sas`** espalhados em dezenas de pastas no root do repositório (entregas por área/time, uploads de usuários do SharePoint, etc.). Esse material foi **consolidado, descompactado, deduplicado e triado** dentro de `egps_analysis/received_egps/` (organizado por área), separando o que é **código a migrar** do que é **referência** ou **descarte**.

Como boa parte dessas operações foi **destrutiva (MOVE / DELETE, não cópia)**, dois princípios guiaram tudo:

1. **Reversibilidade** — toda operação destrutiva gerou um **manifesto** (`origem → destino`, com hash quando relevante) para poder desfazer.
2. **Separação clara por finalidade** — migração (`received_egps/`) · insumos de pipeline (`src/`) · referência de negócio (`docs/referencias_negocio/`) · arquivo não-migrável (`docs/_arquivo_*`) · saídas de análise (`docs/analises/`).

Nada que é lido pelos scripts da pipeline (`egps_extractor.py`, `orchestrator_inventory.py`) foi movido — eles não dependem de nenhum destes arquivos.

---

## 1. `egps_analysis/_manifests/` — logs de reversão

Cada `.tsv` registra uma operação de reorganização. Para **desfazer**: mover cada `destino → origem` (linhas com `DELETED`/ação de remoção indicam que o arquivo idêntico permanece no destino canônico citado, normalmente em `SAS_UC4/`).

| Manifesto | Operação registrada | Colunas | Registros |
|---|---|---|---|
| `egp_move_manifest.tsv` | Consolidação inicial: `.egp`/`.zip` das pastas do root → `received_egps/<área>/` (inclui merges Cobrança→Cobranças, Operações e CX→Operações) | `action, src, dest_or_kept` | 1080 |
| `egp_unzip_manifest.tsv` | Descompactação dos `.zip` (EGPs comprimidos) para eliminar duplicados | `action, zip, inner, dest` | 488 |
| `egp_unzip2_manifest.tsv` | 2ª passada de descompactação (casos recursivos / conjuntos curados) | `action, source, dest` | 80 |
| `sas_ingest_manifest.tsv` | Ingestão dos scripts SAS de produção: `SAS_UC4` (232 jobs) + `campanha_SuperaBV` (20) | `action, src, dest` | 253 |
| `sas_user_ingest_manifest.tsv` | Ingestão dos `.sas` de usuários (SharePoint): 12 pessoais → `sas_files/<usuário>/` + 8 jobs Rodas → `Rodas/sas_files/Programas 2026/` | `source, dest, sha256` | 20 |
| `leftovers_move_manifest.tsv` | Esvaziamento das pastas do root: referências → `docs/referencias_negocio/`, scratch → `docs/_arquivo_scratch_usuarios/` | `source, dest, kind` | 12 |
| `rodas_dedup_manifest.tsv` | Dedup Rodas vs `SAS_UC4` (lar canônico = `SAS_UC4`): 11 cópias idênticas deletadas + 3 conflitos arquivados | `source, dest_or_action, reason, sha256` | 14 |

---

## 2. `egps_analysis/docs/` — documentação e arquivos não-migráveis

### Pastas criadas na organização

- **`analises/`** — **saídas** das análises (relatórios, não insumos de pipeline):
  - `duplicados_areas.csv` — os 35 EGPs cujo nome aparece em ≥2 áreas, classificados em idêntico / quase-igual / diferente (com `sha256` de cada cópia).
  - `duplicados_egp.txt` — lista bruta de duplicados por nome nas pastas **originais** (pré-consolidação).
  - `cobranca_projetos_x_egps.csv` — cruzamento do registro de projetos da Cobrança × `received_egps` (match exato / variante / sem `.egp`).

- **`referencias_negocio/`** — arquivos que **não são código a converter**, mas têm valor de referência (preservam o caminho de origem por área/usuário):
  - `…/20260302_Projetos.xlsx` — registro de projetos da Cobrança (dono/status/área); é a **fonte** do `src/cobranca_projetos.csv`.
  - `…/doc3040_v2_RM.map.txt` — mapa XML do SAS (`SXLEMAP`) para ler o **Doc3040 (Bacen 3040 / SCR)**; dependência técnica de quem migrar processos de 3040.
  - `…/Acessos Bancos de Dados NCC 1.docx` — documentação de acessos a bancos de dados.
  - `…/SAS V3/Leia-me.txt` — nota com **correspondência de nomes** de EGP (ex.: `Provisão_4_966_202601_MFS.egp` ↔ `Proviso_4_966_202509_GVCS_v2.egp`).
  - `…/Bruno Lage` e `…/joao.neves2` `Stored Process/*.docx` — documentação (mapeamento) de stored processes. ⚠️ **`joao.neves2` subiu só a doc — o código real dos stored processes não está no repo.**

- **`_arquivo_scratch_usuarios/`** — código de usuário **não ingerido** na migração. Critério acordado: só entra quem cria **tabela permanente** usável por outro EGP a jusante. Estes criam só `WORK`/modelos do EM Miner:
  - `henrique.campos` ×3 (`Query Tb*.txt` — queries `PROC SQL` que geram tabelas `WORK`).
  - `chang.fang` ×3 (`Score_*.txt` — *score code* gerado pelo SAS Enterprise Miner).

- **`_arquivo_rodas_conflitos/`** — as variantes de `Rodas/Programas 2026` dos 3 conflitos em que o **`SAS_UC4` venceu** (preservadas para rastro): `tbpotencialrodascomercial`, `tbrelatorioapnp`, `tbvisaopdvs`. (A cópia corrompida/antiga; a boa está no `SAS_UC4`.)

### Docs deste trabalho

- `CODE_REVIEW.md` — review técnico do módulo `egps_analysis` (achados P0/P1/P2).
- `README.md` — este arquivo.

### Docs pré-existentes do módulo (índice, não criados nesta organização)

- `PIPELINE_INVENTARIO_MIGRACAO_SAS.md` — roteiro/ordem da pipeline de inventário.
- `EGPS_EXTRACTOR.md` · `EGPS_EXTRACTOR_V9.md` — documentação do extrator.
- `DATA_SRC_CHAMELEON.md` · `DATA_SRC_REPMAP.md` · `DATA_SRC_INVENTARIO_TRANSACIONAL.md` — docs dos insumos em `src/`.
- `PASSO_A_PASSO_TABELAS_MODERNIZAVEIS_EGP.md` · `RELATORIOS_06_E_MIGRATION_HINTS.md`.
- [`CLASSIFICACAO_INPUTS_SAS.md`](CLASSIFICACAO_INPUTS_SAS.md) — **o que conta como input** de um EGP/`.sas`: as 3 categorias (`table_in`, `file_in`, `script_in`; `libname_in` é só contexto), regras de filtragem (librefs voláteis, macros não resolvidos, SAME-SCRIPT re-reads, modo `executable` vs `full`) e como cada `table_in` vira (ou não) aresta no grafo de dependências.

---

## 3. Insumo derivado em `src/`

- `egps_analysis/src/cobranca_projetos.csv` — registro **limpo** (1.508 projetos) extraído do `Projetos.xlsx`. Fica em `src/` (e não em `analises/`) por ser **insumo** reaproveitável (dono/status/área por projeto), não um relatório pontual.
