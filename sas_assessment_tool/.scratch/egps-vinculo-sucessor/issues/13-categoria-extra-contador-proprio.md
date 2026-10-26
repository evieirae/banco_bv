# 13: Categoria `extra` com contador próprio

**What to build:** Todo EGP que entra no corpus depois da linha de base — sucessores e cascas — vira `Tipo = extra`: listado no recorte, **fora do total base**, com **contador próprio ao lado**. A linha de base (193 em 28/09: recorte + ex-dependências contabilizadas) não se mexe porque um extra chegou.

Decisão da gestão em 28/09/2026. **Revisa duas regras já implementadas:** o `Substituído` deixa de entrar no denominador, e a casca deixa de contar nele (§3.1.2 e §3.6 regra 27 da spec, ambas reescritas).

**Blocked by:** 05 e 12 (a maquinaria e as cascas já existem; isto reclassifica)

**Status:** ENTREGUE (29/09/2026, commits be9b00d2)

- [ ] Filtro Tipo tem 4 valores: base · dependência · ex-dependência · **extra** — o valor `sucessor` não existe mais
- [ ] Sucessor (de qualquer tipo de vínculo, inclusive `Substituído`) e casca aparecem como `extra`
- [ ] O total base NÃO muda quando um extra entra; o contador de extras sobe
- [ ] O funil por área NÃO se mexe por causa de casca (hoje a Cobrança subiria +5)
- [ ] Espelhamento de etapa/status continua decidido pelo TIPO DE VÍNCULO, não pela categoria extra — são eixos independentes
- [ ] A distinção sucessor × casca continua visível no detalhe do EGP
