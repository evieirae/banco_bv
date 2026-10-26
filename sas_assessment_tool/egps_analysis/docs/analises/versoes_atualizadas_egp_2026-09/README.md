# Estudo: versões atualizadas de EGP — set/2026

Tudo que este estudo produziu está nesta pasta. Entrada: pasta "EGP Atualizado" do
SharePoint do BV (Cobrança / Projetos Cobrança Atualizados), 30 `.egp`, todos de
Cobranças. Rodada de 01–02/09/2026.

## Por onde começar

| Documento | Público | Para quê |
|---|---|---|
| [Memorando para a gestão](BV_Migracao_SAS_Gestao_EGPs_Atualizados_2026-09-02.md) | gestão | o que muda na migração e as 6 decisões pendentes. **Comece aqui se você decide.** |
| [Validação Nível 2](BV_Migracao_SAS_Validacao_Nivel2_2026-09-02.md) | técnico | impacto medido no inventário reprocessado; corrige duas conclusões do Nível 1 |
| [Delta da fila (CSV)](BV_Migracao_SAS_Nivel2_Fila_Delta_2026-09-02.csv) | técnico | os 91 artefatos que entram e os 59 que saem da fila, com tipo |
| [Análise consolidada](BV_Migracao_SAS_Analise_Consolidada_Versoes_EGP_2026-09-02.md) | técnico | o impacto com os agregados e o que mudou no nosso entendimento. **Comece aqui se você executa.** |
| [Plano da rodada](BV_Migracao_SAS_Plano_Troca_EGP_2026-09-01.md) | técnico | registro de impacto por EGP, ordem de trabalho, calibrações |
| [Anexo: detalhe dos bloqueados](BV_Migracao_SAS_Anexo_Detalhe_Bloqueados_2026-09-01.md) | técnico | os 8 blocos por EGP num só documento, do impacto maior para o menor |
| [CSV consolidado](BV_Migracao_SAS_Troca_EGP_2026-09-01.csv) | técnico | 30 linhas × 39 colunas, o dado bruto |
| os 8 markdowns `Troca_<egp>_*` | técnico | a fonte de cada bloco do anexo, um arquivo por EGP |

## A conclusão em três linhas

A fila de ingestão **cresce 32 artefatos** (6.843 → 6.875; 91 entram, 59 saem), medido no
inventário reprocessado. O ganho é de **15 arquivos de rede** a menos, não os 40 que a
soma por EGP sugeria. E o veto acertou **6 de 6**: todos os outputs removidos com
consumidor externo entraram de fato na fila.

E o contexto que muda o uso de tudo isto: a adoção da versão nova **já estava decidida
pelo cliente** desde 21/08/2026. Este estudo não decide se troca; ele registra o impacto
downstream, que é o que o direcionamento do BV exige.

## Os 8 markdowns de detalhe

Sete bloqueados por veto e um par não resolvido:

- `PERFORMANCE_CL_202608_GCP` — remove `PERF_CL.CL_TABLEAU` (7 consumidores)
- `Performance_Saldo_COLORE_..._Lite_V5` — remove `PAGOSCBR.PAGOS_CYBER_202603` (3)
- `PROJECT_ATIVA_TABLEAU_NEW_RPA` — remove `ATIVA.BASE_ATIVA_202510` (2)
- `Oportunidade Protesto_20260703` — remove `KEVIN.PUBLICO_PROTESTO_20260210` (2)
- `Campanha_Entrega_amigavel_v4_mensal_gcp` — remove `ENTREGA.BASE_ELEG_110226` (2)
- `processo_carga_score_solar_jul_26_REAPONTADO_PJeOFENS` — remove `GRIMALDI.SOLAR_FLEX_MASSIFICADOS_20250211` (2)
- `Project_Compensacao_Encargos_v1` — antecessor já convertido e entregue em 31/08
- `Project_Atualiza_Bases_Auxiliares_GCP_Inc_Cadu_HUB` — antecessor desconhecido (31% de overlap)

## O que NÃO está aqui

As **ferramentas** ficam fora desta pasta de propósito, porque são código e seguem a
convenção do subprojeto (script solto na raiz de `egps_analysis/`, rodado de lá):

- `egps_analysis/compare_egp_versions.py` — gera tudo que está nesta pasta
- `egps_analysis/pipeline_status_snapshot.py` — snapshot de `sas_egp_pipeline`, alimenta
  o veto por etapa/status
- `egps_analysis/src/pipeline_status_snapshot.csv` — o snapshot em si; **não versionado**, 
  porque vale 7 dias e o script recusa snapshot velho. Regere antes de usar.
- `.claude/skills/analise-egp-atualizado/` — o procedimento reutilizável

## Como regenerar

```bash
cd egps_analysis
venv/bin/python pipeline_status_snapshot.py           # snapshot vale 7 dias
venv/bin/python compare_egp_versions.py --novo "/caminho/EGP Atualizado"
```

Os defaults do script já escrevem nesta pasta. Cada rodada nova deve ir para uma pasta
própria com a sua data (`--out` e `--md-dir`), não sobrescrever esta — os cortes de
quadrante são fixos justamente para as rodadas serem comparáveis entre si.

## Nota sobre completude

Foram descartados 8 markdowns de rodadas intermediárias deste mesmo dia, gerados antes
de dois bugs serem corrigidos (veto que contava o próprio EGP como consumidor, e
detector de consolidação que dava 14 antecessores falsos). Traziam veredito errado — por
exemplo `Atualiza_UF_Cartoes` como "Valor 64.7 · Não trocar (veto)" quando ele é
byte-idêntico ao corpus. São regeneráveis rodando o script.

O **Nível 2** rodou em 02/09 (worktree descartável, inventário reprocessado) e está no
documento de validação. Ele corrigiu duas conclusões do Nível 1, então prefira os números
dele quando houver divergência.
