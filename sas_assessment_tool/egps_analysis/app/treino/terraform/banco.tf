# Banco do ensaio: mesma engine e classe de produção, mas descartável (o nuke leva à noite) e
# acessível do seu IP — as migrações e a massa sintética rodam da sua máquina. Só dado sintético.
resource "aws_security_group" "banco" {
  name        = "${local.nome}-rds"
  description = "Postgres do ensaio: tarefas do app e os IPs permitidos"
  vpc_id      = aws_vpc.treino.id

  ingress {
    from_port       = 5432
    to_port         = 5432
    protocol        = "tcp"
    security_groups = [aws_security_group.app.id]
    description     = "App"
  }

  ingress {
    from_port   = 5432
    to_port     = 5432
    protocol    = "tcp"
    cidr_blocks = var.ips_permitidos
    description = "Migracoes e massa sintetica, da maquina de quem ensaia"
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "aws_db_subnet_group" "banco" {
  name       = local.nome
  subnet_ids = local.subnets
}

resource "random_password" "mestre" {
  length  = 32
  special = false # vai num DSN montado pelo script; sem caractere que precise de escape
}

resource "aws_db_instance" "banco" {
  identifier     = local.nome
  engine         = "postgres"
  engine_version = "17"
  instance_class = "db.t3.micro"
  port           = 5432

  # Sem db_name: o banco do app nasce pelo `python -m db.migra --cria-banco`, com collation
  # C (ordem de bytes, como o Spark). O db_name o criaria com a collation de idioma da
  # instância, e as listas do app sairiam em outra ordem.
  username = "mestre"
  password = random_password.mestre.result

  allocated_storage = 20
  storage_type      = "gp3"
  storage_encrypted = true

  db_subnet_group_name   = aws_db_subnet_group.banco.name
  vpc_security_group_ids = [aws_security_group.banco.id]
  publicly_accessible    = true

  backup_retention_period = 0
  deletion_protection     = false
  skip_final_snapshot     = true
  apply_immediately       = true
}

# Para a tarefa do app ler a senha como em produção (secrets do ECS). Sem janela de
# recuperação: o nome do dia seguinte é outro, mas um segredo "em exclusão" não atrapalha.
resource "aws_secretsmanager_secret" "banco" {
  name                    = "${local.nome}/db"
  recovery_window_in_days = 0
}

resource "aws_secretsmanager_secret_version" "banco" {
  secret_id     = aws_secretsmanager_secret.banco.id
  secret_string = jsonencode({ db_password = random_password.mestre.result })
}
