provider "aws" {
  profile = var.perfil_aws
  region  = "us-east-1"

  default_tags {
    tags = {
      Company   = "IndiciumTech"
      Ensaio    = "monitoramento-sas"
      ManagedBy = "Terraform"
    }
  }
}

terraform {
  # profile e key vêm no init (-backend-config): o profile é o seu SSO da training, e a key é
  # uma por DIA — cada ensaio começa com estado vazio e é derrubado pelo próprio estado
  # (treino/desce_treino.sh); o aws-nuke não limpa a conta toda noite. O bucket é protegido do nuke.
  backend "s3" {
    region       = "us-east-1"
    bucket       = "indicium-training-tfstate"
    encrypt      = true
    use_lockfile = true
  }

  # >= 1.10 pelo use_lockfile (trava nativa do S3).
  required_version = ">= 1.10.0, < 2.0.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.0"
    }
  }
}
