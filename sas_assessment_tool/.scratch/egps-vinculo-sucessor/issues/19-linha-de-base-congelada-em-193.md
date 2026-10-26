# 19: A linha de base é congelada em 193

**Decisão da gestão, 29/09/2026.** O total de EGPs deixa de ser calculado a cada leitura e passa a ser uma **lista congelada**. Tudo que entrar depois é `extra` — **inclusive o que o grafo classificaria como dependência**.

**Congelado nos DOIS lados:** quem sai do escopo continua no denominador. Justificativa do usuário: `Despriorizado e Contabilizado` já conta por desenho, e remoção/dedup não vão mais acontecer. O progresso passa a ser medido contra um número que nunca muda.

**Marco:** 29/09/2026. A foto está em `egps_analysis/src/linha_base_congelada_2026-09-29.csv` — **193 projetos**, com a classe de cada um: 168 `base` + 11 `dependencia` + 14 `ex_dependencia`. Capturada de prod, somente leitura.

**Consequência imediata:** as 27 versões que entraram hoje, os 5 que o grafo puxou como dependência e as 5 cascas são todos `extra`.

**Resolve os tickets 16 e 18**, que existiam por causa do mesmo sintoma — o total subindo sozinho:
- **16** (concluir uma ex-dependência sobe o total): não sobe mais, o denominador é fixo
- **18** (a janela entre corpus e vínculo infla o total): não infla mais, o que entra é extra por definição

**Blocked by:** None

**Status:** ENTREGUE (29/09/2026, commits 0c4dc28c + 02213c24)

- [ ] `total_egps` é **sempre 193**, em toda superfície, venha o que vier no corpus
- [ ] Todo projeto do recorte fora da lista congelada é `extra`, mesmo sendo dependência pelo grafo
- [ ] Despriorizado continua dentro dos 193 (não sai do denominador)
- [ ] A decomposição exibida (base/dependências/ex) vem da **classe gravada no CSV**, não do cálculo vivo
- [ ] O contador de extras mostra quantos e quais
- [ ] Medido nos dois schemas: prod dá 193, e o ambiente com os 27 também dá 193
- [ ] A lista congelada é versionada e a data está no nome — trocar a linha de base é ato deliberado, não efeito colateral
