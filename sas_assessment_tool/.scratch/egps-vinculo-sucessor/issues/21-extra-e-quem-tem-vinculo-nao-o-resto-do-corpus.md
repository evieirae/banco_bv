# 21: `extra` é quem tem vínculo, não todo o resto do corpus

**Encontrado em uso real, 29/09/2026.** O usuário viu `ACORDO_AMIGAVEL_v1` marcado como **`extra · novo`** no app. Ele é um EGP do corpus desde o snapshot de junho — não chegou depois de nada.

**A causa:** o ticket 19 trocou `extras` de **enumeração** (`sucessores ∪ cascas`) para **definição** (`recorte − linha_base`). Ficou mais simples e varreu junto uma terceira categoria que ninguém pretendia: **ex-dependência que não entra na contagem**. Só 14 das 34 ex-dependências entraram nos 193 (as com etapa real, critério "189"); as outras 20 ficaram fora da lista e a régua as pegou.

Medido: a tela marca **37** como extra, dos quais **19 são ex-dependências** — 18 com motivo `novo`, que afirma "chegou depois do congelamento". Nenhuma chegou. 17 das 19 estão com `etapa=''`, que é exatamente o que as manteve fora da contagem.

**E o contador discorda da tela:** `_extras(frontier)` dá **18** porque ex-dependência **não está no frontier** (0 de 34 — por definição, ela deixou de ser dependência). Mas a aba EGPs lista as ex-dependências com badge, e o `anexa_vinculo` marca `e_extra` em toda linha fora dos 193. Dois conjuntos diferentes, duas contas diferentes.

**Blocked by:** None

**Status:** ENTREGUE (verificado em 01/10/2026 — ver §Verificação)

## Decisões da gestão (29/09/2026)

- [x] **`extra` volta a ser ENUMERAÇÃO**: é EGP com **vínculo de atualização** com outro — sucessor apontado por um vínculo, e casca (que tem `unificado_em`). **Não** é "todo o resto do corpus"
- [x] **Ex-dependência NUNCA é extra.** O badge de ex-dependência já basta; ela não recebe segundo rótulo
- [x] O filtro **"Indicium + dependências" mostra exatamente os 193**
- [x] Filtro novo: **só os extras**
- [x] Filtro novo: **Indicium + dependências + extras**
- [x] O total segue **congelado em 193** (ticket 19 continua valendo no denominador — o que muda é só quem se chama `extra`)
- [x] A tela e o contador passam a concordar sobre quem é extra

## Verificação (01/10/2026, clone `monitoramento_sas_atualizados_dev`)

O trabalho já estava na branch desde 29/09; faltava medir e marcar. Medido ao vivo:

- **enumeração**: 24 extras, motivos `sucessor` 18 · `casca` 5 · `novo` 1 — soma fechada,
  nenhum por exclusão. Tipos: Atualizado 14, Unificado 4, Substituído 2, casca 5, novo 1;
- **ex-dependência nunca é extra**: 36 ex-deps no recorte, **0** marcadas extra;
- **tela == contador**: 24 = 24, e `/api/egps-extras` devolve o mesmo conjunto
  (era o defeito original, 37 × 18);
- **total congelado**: `total_egps = 193`, inalterado;
- **filtros novos**: `indi_deps_extras` ("Indicium + dependências + extras") e `extras`
  ("só os extras") em `vinculo.ts:RECORTES`. São vistas CLIENT-SIDE do payload de
  `indi_deps` (`recorteApi`), de propósito — pedir o mesmo recorte ao servidor duas vezes
  é justamente como a tabela e o contador voltariam a discordar.

70 testes verdes (`test_extra_enumeracao.py` + `test_vinculos.py`).
