variable "perfil_aws" {
  description = "Profile SSO local da conta training (aws sso login --profile <este>)."
  type        = string
  default     = "indicium-training"
}

variable "sufixo" {
  description = "MMDD do ensaio: entra em todo nome, para não colidir com sobra do dia anterior."
  type        = string
  validation {
    condition     = can(regex("^[0-9]{4}$", var.sufixo))
    error_message = "sufixo = MMDD (4 dígitos)."
  }
}

variable "ips_permitidos" {
  description = "CIDRs que alcançam o app e o banco do ensaio (seu IP, VPN). Não há login aqui."
  type        = list(string)
  validation {
    condition     = length(var.ips_permitidos) > 0 && !contains(var.ips_permitidos, "0.0.0.0/0")
    error_message = "Informe ao menos um CIDR e nunca 0.0.0.0/0: o ensaio não tem login."
  }
}

variable "dev_usuario" {
  description = "E-mail que o app usa como identidade (IDENTIDADE=dev) e que entra como gestão."
  type        = string
}

locals {
  nome = "monsas-treino-${var.sufixo}"
}
