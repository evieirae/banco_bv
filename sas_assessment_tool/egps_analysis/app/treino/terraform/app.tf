resource "aws_ecr_repository" "app" {
  name         = local.nome
  force_delete = true
}

resource "aws_iam_role" "execucao" {
  name = "${local.nome}-exec"
  assume_role_policy = jsonencode({
    Version   = "2012-10-17"
    Statement = [{ Effect = "Allow", Principal = { Service = "ecs-tasks.amazonaws.com" }, Action = "sts:AssumeRole" }]
  })
}

resource "aws_iam_role_policy_attachment" "execucao_base" {
  role       = aws_iam_role.execucao.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

resource "aws_iam_role_policy" "execucao_segredo" {
  name = "ler-segredo-do-banco"
  role = aws_iam_role.execucao.id
  policy = jsonencode({
    Version   = "2012-10-17"
    Statement = [{ Effect = "Allow", Action = ["secretsmanager:GetSecretValue"], Resource = [aws_secretsmanager_secret.banco.arn] }]
  })
}

resource "aws_ecs_cluster" "treino" {
  name = local.nome
}

resource "aws_cloudwatch_log_group" "app" {
  name              = "/ecs/${local.nome}"
  retention_in_days = 1
}

resource "aws_security_group" "alb" {
  name        = "${local.nome}-alb"
  description = "ALB do ensaio: HTTP so dos IPs permitidos (sem login, sem dado real)"
  vpc_id      = aws_vpc.treino.id
  ingress {
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = var.ips_permitidos
  }
  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "aws_security_group" "app" {
  name        = "${local.nome}-app"
  description = "Tarefas do app: entrada so do ALB do ensaio"
  vpc_id      = aws_vpc.treino.id
  ingress {
    from_port       = 8000
    to_port         = 8000
    protocol        = "tcp"
    security_groups = [aws_security_group.alb.id]
  }
  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "aws_lb" "treino" {
  name               = local.nome
  load_balancer_type = "application"
  subnets            = local.subnets
  security_groups    = [aws_security_group.alb.id]
}

resource "aws_lb_target_group" "app" {
  name        = local.nome
  port        = 8000
  protocol    = "HTTP"
  target_type = "ip"
  vpc_id      = aws_vpc.treino.id
  health_check {
    path    = "/api/health"
    matcher = "200"
  }
}

resource "aws_lb_listener" "http" {
  load_balancer_arn = aws_lb.treino.arn
  port              = 80
  protocol          = "HTTP"
  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.app.arn
  }
}

# Mesma imagem e mesmas variáveis de produção, exceto a identidade: aqui não há login do
# Google (sem domínio), então IDENTIDADE=dev — o login é validado pela PR do passo 0.
resource "aws_ecs_task_definition" "app" {
  family                   = local.nome
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = 512
  memory                   = 2048
  execution_role_arn       = aws_iam_role.execucao.arn
  container_definitions = jsonencode([{
    name         = "app"
    image        = "${aws_ecr_repository.app.repository_url}:treino"
    essential    = true
    portMappings = [{ containerPort = 8000, protocol = "tcp" }]
    environment = [
      { name = "DB_BACKEND", value = "postgres" },
      { name = "PUBLISH_SCHEMA", value = "compat" },
      { name = "IDENTIDADE", value = "dev" },
      { name = "DEV_USUARIO", value = var.dev_usuario },
      { name = "SOMENTE_LEITURA", value = "1" },
      { name = "FAMILIAS_SAFRA", value = "1" },
      { name = "APP_PORT", value = "8000" },
      { name = "PGHOST", value = aws_db_instance.banco.address },
      { name = "PGPORT", value = "5432" },
      { name = "PGDATABASE", value = "monitoramento" },
      { name = "PGUSER", value = "mestre" },
      { name = "PG_PAPEL", value = "app_leitura" },
      { name = "PGSSLMODE", value = "require" },
    ]
    secrets = [
      { name = "PGPASSWORD", valueFrom = "${aws_secretsmanager_secret.banco.arn}:db_password::" },
    ]
    logConfiguration = {
      logDriver = "awslogs"
      options = {
        "awslogs-group"         = aws_cloudwatch_log_group.app.name
        "awslogs-region"        = "us-east-1"
        "awslogs-stream-prefix" = "app"
      }
    }
  }])
}

resource "aws_ecs_service" "app" {
  name            = local.nome
  cluster         = aws_ecs_cluster.treino.id
  task_definition = aws_ecs_task_definition.app.arn
  desired_count   = 1
  launch_type     = "FARGATE"

  network_configuration {
    subnets          = local.subnets
    security_groups  = [aws_security_group.app.id]
    assign_public_ip = true
  }

  load_balancer {
    target_group_arn = aws_lb_target_group.app.arn
    container_name   = "app"
    container_port   = 8000
  }

  depends_on = [aws_lb_listener.http]
}
