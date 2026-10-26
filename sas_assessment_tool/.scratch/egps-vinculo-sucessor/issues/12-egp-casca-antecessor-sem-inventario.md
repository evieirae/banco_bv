# 12: EGP casca — antecessor sem inventário próprio entra no funil

**What to build:** Um antecessor absorvido por um unificador que **nunca terá inventário próprio** ganha linha no funil, pode chegar a `Migrado` e conta no denominador — para que a migração dele feche junto com a do unificador. Sem isso ele não existe como projeto do corpus e o vínculo (que mora na linha do antecessor) não teria onde ser gravado.

Mecanismo **absorvido do PR #136** e registrado na spec em 28/09/2026 (§3.6, regras 22–27). O código existe na develop (`src/egps_casca.csv` + ~75 linhas em `publish_to_databricks.py`) e precisa ser reimplementado sobre esta árvore — não copiado às cegas, porque a régua de contagem aqui é outra.

**Blocked by:** None (independe do vínculo; o cadastro hoje tem 5 cascas, todas de Cobranças)

**Status:** ENTREGUE (29/09/2026, commits be9b00d2)

- [ ] Casca declarada em `src/egps_casca.csv` (`pasta,nome,area,unificado_em,motivo`) aparece como projeto após o publish; arquivo ausente = lista vazia, não erro
- [ ] `projeto = "<pasta>__<nome>"` — `pasta` é o rótulo cru da extração e NÃO é colapsado na `area` canônica ("Cobranças" vs "Cobrança")
- [ ] A casca sobrevive a um segundo publish (nasce dentro do publish, não por insert do app — `sas_lineage_nodes` é full-replace)
- [ ] `escopo_indi` continua `true` depois de rodar `recompute_escopo()` (requer atualizar `sas_escopo` à parte — sem isso a flag se apaga sozinha)
- [ ] A casca aparece na aba EGPs, via o input sintético `casco::<projeto>` (um EGP com zero inputs some do `GROUP BY` de `sas_egp_inputs`)
- [ ] O input sintético NÃO entra na fila de ingestão e NÃO é sanitizado pelas regras §3.4.15/§3.4.18
- [ ] A casca recebe vínculo `Unificado`, exibe `Desatualizado`, espelha a etapa do sucessor e **conta** no denominador
