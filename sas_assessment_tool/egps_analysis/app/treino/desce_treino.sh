#!/bin/bash
# Derruba o ensaio de um dia na conta TRAINING (plano 1a, Parte T). O aws-nuke NÃO limpa a
# conta toda noite: em 15/10/2026 o ensaio 1014 seguia de pé, ocupando uma das 5 VPCs da
# região. Quem sobe um ensaio derruba.
#
# Duas rodadas, para nada ser destruído sem o plan revisado (a partir de egps_analysis/app,
# depois de `aws sso login --profile indicium-training`):
#   SUFIXO=1014 bash treino/desce_treino.sh            # gera e mostra o plan de destruição
#   SUFIXO=1014 APLICA=1 bash treino/desce_treino.sh   # aplica exatamente aquele plan
# PERFIL_AWS e PYTHON como no sobe_treino.sh.
set -euo pipefail
cd "$(dirname "$0")/.."

: "${SUFIXO:?defina SUFIXO (MMDD do ensaio a derrubar, ex.: SUFIXO=1014)}"
PERFIL="${PERFIL_AWS:-indicium-training}"
PY="${PYTHON:-.venv/bin/python}"
TF=treino/terraform
PLANO="desce-$SUFIXO.tfplan"
CONTA_TREINO=196029031078

conta=$(aws sts get-caller-identity --profile "$PERFIL" --query Account --output text)
if [ "$conta" != "$CONTA_TREINO" ]; then
  echo "ERRO: o profile '$PERFIL' aponta para a conta $conta, não para a training ($CONTA_TREINO). Abortado." >&2
  exit 1
fi

terraform -chdir="$TF" init -reconfigure -input=false \
  -backend-config="profile=$PERFIL" \
  -backend-config="key=deploy/terraform/training-acc/monitoramento_sas_treino/$SUFIXO.tfstate"

if [ "${APLICA:-}" = "1" ]; then
  if [ ! -f "$TF/$PLANO" ]; then
    echo "ERRO: sem $TF/$PLANO. Rode antes sem APLICA=1 e revise o plan." >&2
    exit 1
  fi
  terraform -chdir="$TF" apply -input=false "$PLANO"
  rm -f "$TF/$PLANO"
  echo "[treino] ensaio $SUFIXO derrubado"
  exit 0
fi

# Na derrubada os valores das variáveis não mudam o resultado (tudo sai); só precisam passar
# nas validações. O sufixo, sim, é o do ensaio: ele vem do estado escolhido no init.
terraform -chdir="$TF" plan -destroy -input=false -out="$PLANO" -var "perfil_aws=$PERFIL" \
  -var "sufixo=$SUFIXO" -var 'ips_permitidos=["127.0.0.1/32"]' -var "dev_usuario=derrubada@indicium.ai"
terraform -chdir="$TF" show -json "$PLANO" | "$PY" -m treino.confere_plano --derruba
echo "[treino] revise o plan acima; para aplicar: SUFIXO=$SUFIXO APLICA=1 bash treino/desce_treino.sh"
