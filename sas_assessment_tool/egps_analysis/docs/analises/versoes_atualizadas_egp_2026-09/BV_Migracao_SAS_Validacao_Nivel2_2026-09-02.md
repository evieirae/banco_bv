# Validação Nível 2 — impacto medido no corpus recomposto

Rodada de 02/09/2026. Esta é a medição que faltava: o inventário inteiro reprocessado
com as 30 versões novas adotadas, em vez da soma dos deltas EGP a EGP.

**Ela corrige duas conclusões do Nível 1.** Leia esta antes do memorando de gestão e da
análise consolidada, que foram escritos com os números do Nível 1 e já estão anotados.

## Como foi feito

Worktree git descartável a partir do commit `1c2d1098`, com os 1.741 `.txt` e o `src/`
do HEAD. A árvore principal não foi tocada em nenhum momento.

1. **Baseline:** orquestrador rodado no worktree sem alteração nenhuma. Isso importa —
   comparar contra os `01`–`06` da árvore principal misturaria versões de código.
2. **Adoção:** 27 `.egp` novos extraídos (os 3 de código idêntico ficaram fora) e os
   **32 `.txt` dos antecessores removidos**. O `Project_Atualiza_Bases_Auxiliares` só
   entrou, sem remover nada, porque o antecessor não está confirmado.
3. **Segundo passe:** orquestrador rodado de novo e os dois conjuntos comparados.

Corpus: 1.741 → 1.736 `.txt`. EGPs no inventário: 1.244 → 1.239.

---

## Correção 1: a fila de ingestão cresce, não fica neutra

| | Baseline | Depois | Delta |
|---|---|---|---|
| Artefatos que exigem ingestão externa | 6.843 | 6.875 | **+32** |
| ... entram | | | 91 |
| ... saem | | | 59 |

O Nível 1 dizia "neutro, 509 para 507". Os dois números estão certos e medem coisas
diferentes. O Nível 1 somava a contagem própria de cada EGP; um input que sai do EGP A
mas continua sendo lido pelo EGP B desaparece dessa soma e **permanece na fila**. No
corpus, só 59 inputs saíram de verdade, enquanto 91 entraram.

Composição dos 91 que entram: **todos são tabela, nenhum arquivo**. 82 são `lib.membro`
SAS/Local e 9 são BigQuery nativo. Dos 59 que saem, 57 são tabela e 2 são caminho de
arquivo.

Lista completa em `BV_Migracao_SAS_Nivel2_Fila_Delta_2026-09-02.csv`.

## Correção 2: o ganho em planilhas de rede é de 15 arquivos, não de 40

O `-40 file_in` do Nível 1 era redução de **referências**, não de arquivos a ingerir.

| Categoria | Referências (EGP × artefato) | Artefatos distintos |
|---|---|---|
| `file_in` | 5.674 → 5.635 (**−39**) | 2.833 → 2.818 (**−15**) |
| `table_in` | 20.451 → 20.408 (**−43**) | 8.314 → 8.329 (**+15**) |
| `script_in` | 1.548 → 1.548 (0) | 375 → 375 (0) |

São duas coisas reais e distintas. Trinta e nove referências a menos significa menos EGPs
acoplados a planilha de rede, o que é ganho de arquitetura. Mas para quem executa a
ingestão o ganho é de **15 arquivos**, porque os outros continuam sendo lidos por outros
EGPs. E em troca entram 15 tabelas distintas.

---

## O veto acertou 6 de 6

Os seis outputs que o Nível 1 vetou por terem 2 ou mais consumidores externos **entraram
todos na fila de ingestão** do corpus recomposto. Ou seja: o EGP novo deixa de produzir a
tabela, o consumidor continua lendo, e ela passa a exigir ingestão externa.

| Output vetado | Entrou na fila |
|---|---|
| `PERF_CL.CL_TABLEAU` | sim |
| `PAGOSCBR.PAGOS_CYBER_202603` | sim |
| `ATIVA.BASE_ATIVA_202510` | sim |
| `KEVIN.PUBLICO_PROTESTO_20260210` | sim |
| `ENTREGA.BASE_ELEG_110226` | sim |
| `GRIMALDI.SOLAR_FLEX_MASSIFICADOS_20250211` | sim |

É a validação mais forte da rodada. O mecanismo de veto não estava sendo conservador
demais; ele apontava consequência real, e agora está quantificada.

Vale notar que o `ATIVA.BASE_ATIVA_202510` só apareceu porque o pareamento passou a ser
N:1. Com o modelo 1:1 esse output pertencia ao segundo antecessor e ficava invisível.

---

## Demais efeitos medidos

| Métrica | Baseline | Depois | Delta |
|---|---|---|---|
| EGPs no inventário | 1.244 | 1.239 | −5 |
| Arestas EGP → EGP | 1.870 | 1.861 | −9 (74 novas, 83 somem) |
| Projetos que dependem de alguém | 574 | 565 | −9 |
| Tabelas geradas (referências) | 43.047 | 42.892 | −155 |
| Tabelas consumidas (referências) | 19.591 | 19.536 | −55 |
| Arquivos exportados | 1.234 | 1.257 | **+23** |
| Libnames | 8.381 | 8.322 | −59 |
| Inputs `Nativa BigQuery` | 2.540 | 2.523 | −17 |
| Inputs `[Modernizada]` (usada por) | 2.812 | 2.804 | −8 |

Os EGPs no inventário caem 5, e não 27, porque 12 das versões novas têm o mesmo nome de
projeto do antecessor: substituem no lugar, sem mexer na contagem. Entram 15 chaves de
projeto novas e saem 20.

Dois sinais que reforçam a suspeita já registrada de **corte de escopo** em vez de
modernização: os inputs já modernizados caem (`Nativa BigQuery` −17, `[Modernizada]` −8),
e os arquivos exportados sobem (+23), o que é o oposto de simplificação.

---

## O que isto muda nas recomendações

A ordem de trabalho do plano **não muda**, mas a justificativa de duas delas muda.

- Os 6 EGPs vetados continuam bloqueados, e agora com evidência quantificada: cada um
  adiciona um item concreto à fila de ingestão.
- Os 4 EGPs de "adotar primeiro" perdem parte do argumento. O ganho de `file_in` deles é
  real em acoplamento, mas menor do que parecia em fila de ingestão.
- O planejamento de ingestão precisa reservar capacidade para **+32 artefatos**, não para
  fila estável. Os +37 apontados no Nível 1 continuam valendo como demanda concentrada
  nos três EGPs; o +32 é o efeito líquido no corpus depois de descontar o que saiu.

## Limites desta validação

Ela mede a adoção dos **27** com conteúdo novo, incluindo os 6 vetados e o par não
resolvido. Não é o cenário de execução recomendado, é o cenário do direcionamento do BV:
adotar tudo. Se os 6 vetados ficarem de fora, a fila cresce menos, e quanto menos exige
uma nova rodada para medir.

As 3 consolidações não confirmadas foram tratadas como reais, então os 32 antecessores
removidos incluem 5 remoções que dependem de resposta da área. Se alguma consolidação for
falsa, aquele antecessor volta ao corpus e o delta muda.

O worktree foi descartado depois da medição. Para reproduzir, o procedimento está na
skill `analise-egp-atualizado`, seção Nível 2.
