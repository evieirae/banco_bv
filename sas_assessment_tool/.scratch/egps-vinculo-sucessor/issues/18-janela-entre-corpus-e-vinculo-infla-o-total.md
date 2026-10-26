# 18: Entre a entrada no corpus e o vínculo, o sucessor conta como dependência comum

**O que é:** A spec §2 ordena **etapa 2 (entrada no corpus) → etapa 3 (vínculo)**, mas não diz o que vale **no meio**. E no meio o sucessor é um projeto comum do corpus: se qualquer EGP do escopo consome uma saída dele, o grafo o puxa como **dependência** — e dependência **conta** no total.

Só aparece quando o fluxo roda de verdade. Não é bug do código: a régua funciona exatamente como desenhada assim que o vínculo existe.

**Medido em 29/09/2026**, na entrada real das 27 versões (ambiente `monitoramento_sas_atualizados_dev`):

- total foi de **193 → 198**; as dependências, de **11 → 16**
- os 5 responsáveis são sucessores sem vínculo:
  - `Cobranças__Elegibilidade menor que 90_GCP_v4__ATU20260901`
  - `Cobranças__Elegibilidade_Gradativo_20251103_reap_v26__ATU20260901`
  - `Cobranças__NuContratoContabil_Atualizado__ATU20260901`
  - `Cobranças__PERFORMANCE_CL_202608_GCP__ATU20260901`
  - `Cobranças__Project_Atualiza_Bases_Auxiliares_GCP_Inc_Cadu_HUB__ATU20260901`
- os outros 22 não aparecem: nada do escopo lê a saída deles
- **simulação dos 5 vínculos devolve o total a 193** (`contáveis = 189 − 10 extras = 179`, mais 14 ex-dependências) — provado injetando na fonte única e medindo no mesmo processo

**Por que importa:** a janela deveria durar o tempo de uma classificação, mas o ticket 10 existe justamente porque "deveria durar pouco" não é garantia — sem ninguém agir, dura dias. Enquanto durar, a liderança vê o total subir sem que EGP algum tenha entrado no escopo, que é a surpresa que a decisão da categoria `extra` foi criada para evitar.

**Blocked by:** None — mas é régua, e a decisão é da gestão.

**Status:** RESOLVIDO pelo ticket 19 (29/09/2026)

Caminhos possíveis, nenhum escolhido:
- [ ] **Aceitar e anunciar** — a janela é curta se a classificação vier junto; basta o aviso ("o total subiu N porque há N sucessores sem vínculo")
- [ ] **Sufixo `__ATU` como marcador** — o sucessor entra como `extra` desde a entrada no corpus, sem esperar o vínculo. Barato, mas põe uma convenção de NOME dentro de uma régua de contagem, e a spec diz que o mecanismo é o vínculo
- [ ] **Vínculo obrigatório na entrada** — funde as etapas 2 e 3, e some com a janela. Mas o vínculo é decisão de gestão e a entrada no corpus é operação técnica; casá-las trava o pipeline numa reunião

---

## Resolvido sem escolher nenhum dos 3 caminhos

Mesma causa do ticket 16, mesma cura: com a linha de base congelada, o que entra no corpus depois da foto e `extra` **por definicao**. A janela entre a etapa 2 e a 3 deixou de inflar o total — medido com 41 versoes no corpus e o total parado em 193.

O caminho do sufixo `__ATU` como marcador, registrado aqui, **nao** foi tomado — e bom que nao: poria convencao de nome de arquivo dentro de regua de contagem.
