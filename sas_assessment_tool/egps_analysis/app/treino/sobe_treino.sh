#!/bin/bash
# Ensaio diário do app na conta TRAINING (ADR 0005; plano 1a, Parte T).
# Este script sobe TUDO do zero — infra, imagem, migrações e massa sintética — e termina no
# teste de fumaça. Nunca com dado do BV. O aws-nuke NÃO limpa a training toda noite (o 1014
# amanheceu de pé em 15/10/2026): derrube com treino/desce_treino.sh ao terminar.
#
# Uso (a partir de egps_analysis/app), depois de `aws sso login --profile indicium-training`:
#   IPS='["203.0.113.7/32"]' DEV_USUARIO=fulano@indicium.ai bash treino/sobe_treino.sh
# PERFIL_AWS troca o profile (padrão indicium-training). O script confere a conta antes.
# PYTHON troca o interpretador (padrão .venv/bin/python, com o requirements.txt instalado).
set -euo pipefail
cd "$(dirname "$0")/.."

: "${IPS:?defina IPS, ex.: IPS='[\"203.0.113.7/32\"]' (seu IP e/ou a VPN)}"
: "${DEV_USUARIO:?defina DEV_USUARIO (o e-mail que entra como gestão no ensaio)}"
PERFIL="${PERFIL_AWS:-indicium-training}"
# Python com as dependências do app (requirements.txt); padrão: o .venv do app.
PY="${PYTHON:-.venv/bin/python}"
if ! command -v "$PY" > /dev/null; then
  echo "ERRO: sem $PY. Crie: python3 -m venv .venv && .venv/bin/pip install -r requirements.txt (ou passe PYTHON=...)" >&2
  exit 1
fi
TF=treino/terraform
SUFIXO="$(date +%m%d)"
CONTA_TREINO=196029031078

conta=$(aws sts get-caller-identity --profile "$PERFIL" --query Account --output text)
if [ "$conta" != "$CONTA_TREINO" ]; then
  echo "ERRO: o profile '$PERFIL' aponta para a conta $conta, não para a training ($CONTA_TREINO). Abortado." >&2
  exit 1
fi

echo "[treino] infra do dia $SUFIXO"
terraform -chdir="$TF" init -reconfigure -input=false \
  -backend-config="profile=$PERFIL" \
  -backend-config="key=deploy/terraform/training-acc/monitoramento_sas_treino/$SUFIXO.tfstate"
# Nada de apply às cegas: o plan vai para arquivo, a guarda recusa se ele destruir ou
# substituir algo (o ensaio só cria, ou não muda nada na 2ª rodada do dia), e só ENTÃO se
# aplica exatamente aquele plan.
terraform -chdir="$TF" plan -input=false -out=treino.tfplan -var "perfil_aws=$PERFIL" \
  -var "sufixo=$SUFIXO" -var "ips_permitidos=$IPS" -var "dev_usuario=$DEV_USUARIO"
terraform -chdir="$TF" show -json treino.tfplan | "$PY" -m treino.confere_plano
terraform -chdir="$TF" apply -input=false treino.tfplan
rm -f "$TF/treino.tfplan"

ECR=$(terraform -chdir="$TF" output -raw ecr_url)
URL=$(terraform -chdir="$TF" output -raw url)
NOME=$(terraform -chdir="$TF" output -raw nome)
RDS=$(terraform -chdir="$TF" output -raw rds_host)
# senha só em variável de ambiente (nunca na linha de comando nem no log)
PGPASSWORD=$(terraform -chdir="$TF" output -raw rds_senha)
export PGPASSWORD
export PG_DSN="host=$RDS dbname=monitoramento user=mestre sslmode=require"

echo "[treino] imagem"
aws ecr get-login-password --profile "$PERFIL" --region us-east-1 \
  | docker login --username AWS --password-stdin "${ECR%%/*}"
docker build -t "$ECR:treino" .
docker push "$ECR:treino"

echo "[treino] banco, migrações e massa sintética"
# --cria-banco: o RDS nasce sem o banco do app (collation C só se escolhe ao criar)
"$PY" -m db.migra --cria-banco
"$PY" -m sync.sintetico --gestao "$DEV_USUARIO"

echo "[treino] serviço"
aws ecs update-service --profile "$PERFIL" --region us-east-1 --cluster "$NOME" \
  --service "$NOME" --force-new-deployment > /dev/null
aws ecs wait services-stable --profile "$PERFIL" --region us-east-1 --cluster "$NOME" --services "$NOME"

echo "[treino] fumaça em $URL"
"$PY" -m treino.fumaca "$URL" --usuario "$DEV_USUARIO"
echo "[treino] ensaio $SUFIXO OK — $URL (ao terminar: SUFIXO=$SUFIXO bash treino/desce_treino.sh)"
