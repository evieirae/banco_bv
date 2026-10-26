---
name: vincula-egp-atualizado
description: Use when an updated EGP is already in the corpus and its vínculo must be created, corrected or repointed — "cria o vínculo", "qual o antecessor disso", "esse EGP não aparece no app", "muda o vínculo para a versão nova", or when the counter "no corpus, sem vínculo" / the orphan-vínculo warning fires. Confirms the antecessor from measured evidence (never by name similarity), picks the papel (Atualizado / Substituído / Unificado), writes through the endpoint, and proves with before/after that inputs changed bucket without changing the total.
---

# Vincular EGP atualizado: confirmar antecessor e papel

O vínculo é o que faz o app saber que um EGP é versão nova de outro. Sem ele o EGP é
invisível ou vira dependência, e os inputs dele distorcem o card da gestão.

## 1. Quem precisa de vínculo

```python
m.egps_sem_vinculo()   # GET /api/egps-sem-vinculo
```

Devolve duas listas, e elas são problemas DIFERENTES:

- **`sem_vinculo`** — está no corpus, fora da linha de base, fora do recorte e sem vínculo
  em nenhuma direção. Invisível.
- **`orfaos`** — o vínculo existe e **não faz nada**, porque o ANTECESSOR está fora do
  recorte: ele não exibe `Desatualizado`, não espelha etapa e não puxa o sucessor. A regra
  olha o antecessor de propósito — o sucessor pode estar no recorte por outro antecessor, e
  aí o vínculo inerte continua inerte, só que escondido.

Uma terceira forma de desencontro, que o contador ainda não cobre: **linha de pipeline sem
nó de corpus** (visto em `Cadu_HUB__ATU20260901`, com etapa e mês, sem nó). Se achar, não
apague — pode ser estado humano que volta a fazer sentido num republish.

## 2. Confirmar o antecessor — NUNCA por semelhança de nome

Em ordem de confiança:

| fonte | o que é |
|---|---|
| `sas_egp_atualizados.egp_original` | pareamento medido por **hash de tasks**; vários antecessores vêm separados por `" + "` |
| `src/egps_casca.csv`, coluna `unificado_em` | cadastro versionado de quem foi absorvido por qual unificador |
| `compare_egp_versions.py` | `overlap_tasks` + `confianca_par` (ver `analise-egp-atualizado`) |
| email / Slack do BV | decisão de negócio; registre a fonte no commit |

**A armadilha do `egp_key`:** em `sas_egp_atualizados` ele é a chave de **chegada**, não o
projeto do corpus. `Elegibilidade menor que 90_GCP_v4` (chegada) × `…__ATU20260901`
(corpus). Vincular pelo `egp_key` aponta o EGP **para ele mesmo**.

Overlap abaixo de 40% o script recusa. Recusa não é erro — é pergunta para o humano. Só
force `--antigo` quando houver evidência externa (o `egps_casca.csv`, um email). Diga ao
usuário que forçou e com base em quê.

## 3. Escolher o papel

| tipo | quando | efeito |
|---|---|---|
| `Atualizado` | versão nova do mesmo EGP | antecessor fica `Desatualizado` e **espelha a etapa** do sucessor |
| `Unificado` | N antecessores viram 1 | idem; antecessor sem inventário próprio vira casca |
| `Substituído` | outro EGP entra no lugar | **não** espelha: o antecessor fecha e o sucessor segue independente |

Dois antecessores para o mesmo sucessor = `Unificado`, não dois `Atualizado`.

O tipo **não é derivável** do arquivo: `tipos_acordo` tem nome idêntico ao antecessor e
overlap 0,0, e quatro renomeações têm overlap ≥ 0,8. Quem decide é a gestão.

## 4. Escrever — pelo endpoint, nunca por SQL

```python
with patch.object(m, "_require_gestao", lambda *a, **k: None):
    m.egp_pipeline(m.EgpPipe(projeto=ANTECESSOR, funil="migracao",
                             egp_vinculo_tipo=TIPO, egp_sucessor=SUCESSOR))
```

Confira os dois nomes contra `sas_lineage_nodes` **antes**; o endpoint recusa com 404, mas o
erro no meio de um lote é pior que a checagem.

O endpoint aplica as guardas e a cópia §3.3.11 (etapa, mês, JIRA, responsável do antecessor
para o sucessor, uma vez só). SQL direto pula tudo isso.

**Recusa esperada:** *"EGP com status Migrado não recebe sucessor"*. A guarda está certa —
reabrir o status é decisão da gestão, não force.

## 5. Provar que deu certo

Foto antes e depois de `landing()`:

```
ANTES:  escopo=1237 deps=71 extras=54 TOTAL=1362
DEPOIS: escopo=1237 deps=61 extras=64 TOTAL=1362
```

**O TOTAL é o teste.** Vínculo *reclassifica* input, não cria nem destrói. Total diferente
= algo está errado, pare e investigue.

## 6. Repontar para uma versão mais nova

Quando chega a v3 de uma cadeia v1 → v2 → v3, repontar v1 direto para v3 **achata a cadeia
e tem custo**: o v2 deixa de ser sucessor de alguém. Se o v2 não estiver na linha de base
congelada, ele deixa de ser `extra` (que é enumeração: sucessor ∪ casca ∪ novo) e cai como
**dependência comum**, levando os inputs exclusivos dele para o card da gestão. Medido em
01/10 no `Cadu_HUB`: 9 inputs voltaram para dependências.

Antes de repontar, confira se o intermediário tem etapa/status/mês gravado. Repontar casca
(sem nada gravado) é barato; repontar EGP com trabalho registrado é decisão da gestão.

E **não é necessário para o espelho**: `fim_do_espelho` percorre a cadeia inteira, então a
etapa já chega ao fim sem achatar. O ganho real do repontamento é a lista "Substitui" ficar
completa no sucessor.

## Armadilhas de recorte que parecem bug e não são

- **Sucessor de casca não entrava no recorte.** A cadeia partia da base, e casca e novo são
  removidos dela (regra 27) — corrigido em 30/09, a cadeia agora parte de
  `level ∪ casca ∪ novo`. Se um unificador de cascas sumir da tela, é isto.
- **Casca espelha a etapa do unificador.** Unificador recém-chegado não tem etapa, então as
  cascas continuam sem etapa. Não é o vínculo que falhou.
- **Antecessor fora do recorte** gera vínculo órfão (ver §1). Criar o vínculo não basta; o
  antecessor precisa estar no recorte para ele valer.
