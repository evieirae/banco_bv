output "url" {
  value = "http://${aws_lb.treino.dns_name}"
}

output "ecr_url" {
  value = aws_ecr_repository.app.repository_url
}

output "rds_host" {
  value = aws_db_instance.banco.address
}

output "rds_senha" {
  value     = random_password.mestre.result
  sensitive = true
}

output "nome" {
  value = local.nome
}
