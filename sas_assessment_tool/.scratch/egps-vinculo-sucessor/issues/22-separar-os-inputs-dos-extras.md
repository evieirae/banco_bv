# 22 — Separar os inputs dos extras (Visão geral + filtro na aba Inputs)

**Status:** ENTREGUE (29/09/2026) · revisa a §3.4.13 da spec

## O problema

A §3.4.13 decidiu que os inputs do sucessor "entram junto com o recorte, sem bloco
separado a somar". Isso resolvia o denominador e criou um ponto cego: **não havia como
saber quanto do inventário chegou junto com as versões novas.**

O sintoma concreto medido em 29/09 no schema dos atualizados: das 1.256 unidades do card
"Inputs no escopo", **5 eram os inputs sintéticos `casco::`** das cascas — placeholder de
EGP sem inventário, contado como inventário do escopo Indicium.

## A decisão (gestão, 29/09/2026)

**O Total de Inputs não muda.** Input de versão nova é trabalho real e continua dentro.
A separação é de LEITURA: os três grupos da Visão geral passam a **particionar** o total.

```
Escopo Indicium         1.251
Dependências               91
Extras                     28   ← grupo novo
─────────────────────────────
Total de Inputs         1.370   (era 1.256 + 114)
```

**Duas contagens, porque são duas perguntas.** Isto é o que erra em silêncio se alguém
"simplificar" para uma:

| campo | pergunta | 29/09 | onde aparece |
|---|---|---|---|
| `so_de_extra` | nenhum EGP contável lê | 28 | o grupo da Visão geral |
| `de_extra` | algum extra lê | 190 | o filtro da aba Inputs |

As 162 de diferença são compartilhadas com a linha de base. No **grupo** elas pertencem à
linha de base (contá-las nos dois lados quebraria a partição); no **filtro** elas aparecem,
porque lá a pergunta é "o que a versão nova consome".

## O que foi feito

- `_chaves_por_extra()` — `(lidas_por_extra, lidas_por_contavel)` em chave de safra,
  cacheado por geração. Devolve os dois conjuntos CRUS de propósito: o rollup de família
  precisa dos dois (a safra que o contável lê pode não ser a que o extra lê).
- `_marca_extra(rows)` — anota `de_extra`/`so_de_extra`. Roda **depois** da agregação por
  família: basta uma safra lida por EGP contável para a família inteira sair do grupo.
- `landing()` — itens 8/9 (`inputs_extras`, `inputs_extras_a_ingerir`); os itens 3/4 e 6/7
  passam a excluir o `so_de_extra`; `total_inputs = item3 + item6 + item8`.
- Front: grupo "Extras (fora da linha de base)" no Resumo (3 cards, espelho do de
  dependências), chip "só inputs de extras" na FilterBar, 2 colunas no export CSV.
- `test_inputs_de_extra.py` — 9 testes; os dois que importam são
  `test_familia_e_a_uniao_das_safras` e `test_separar_nao_mexeu_no_denominador`.

## O que NÃO foi feito

As tabelas "Inputs por origem (DOR1)" do Resumo seguem inteiras (escopo | +deps), sem
terceira coluna de extras. Elas já somam o mesmo total; quebrar por origem o grupo dos
extras não foi pedido.

**Divergência conhecida e aceita:** no escopo `indi` da aba Inputs, o card conta 1.256 e o
card "Inputs no escopo" do Resumo conta 1.251. A diferença são exatamente os 5 `casco::`,
que a aba mostra (são linhas do recorte) e o Resumo joga no grupo dos extras. Está no
tooltip do card.
