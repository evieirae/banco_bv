# A training não tem VPC que sobreviva à noite: o ensaio cria a sua.
resource "aws_vpc" "treino" {
  cidr_block           = "10.42.0.0/16"
  enable_dns_hostnames = true
  tags                 = { Name = local.nome }
}

resource "aws_internet_gateway" "treino" {
  vpc_id = aws_vpc.treino.id
  tags   = { Name = local.nome }
}

resource "aws_subnet" "publica" {
  for_each                = { a = "10.42.1.0/24", b = "10.42.2.0/24" }
  vpc_id                  = aws_vpc.treino.id
  cidr_block              = each.value
  availability_zone       = "us-east-1${each.key}"
  map_public_ip_on_launch = true
  tags                    = { Name = "${local.nome}-${each.key}" }
}

resource "aws_route_table" "publica" {
  vpc_id = aws_vpc.treino.id
  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.treino.id
  }
  tags = { Name = local.nome }
}

resource "aws_route_table_association" "publica" {
  for_each       = aws_subnet.publica
  subnet_id      = each.value.id
  route_table_id = aws_route_table.publica.id
}

locals {
  subnets = [for s in aws_subnet.publica : s.id]
}
