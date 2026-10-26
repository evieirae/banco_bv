# -*- coding: utf-8 -*-
"""Identidade vinda do login do load balancer (ADR 0005).

O ALB faz o login do Google e repassa ao app o cabeçalho `x-amzn-oidc-data`: um JWT ES256
assinado pelo PRÓPRIO ALB. Qualquer coisa que alcance o container consegue forjar esse
cabeçalho — por isso a assinatura é conferida com a chave pública regional da AWS e o
`signer` tem de ser o ARN do nosso load balancer. Sem essas duas checagens o e-mail é só
um texto que o cliente mandou.
Doc: https://docs.aws.amazon.com/elasticloadbalancing/latest/application/listener-authenticate-users.html
"""
import base64
import functools
import json
import urllib.request

import jwt  # PyJWT

URL_CHAVE = "https://public-keys.auth.elb.{regiao}.amazonaws.com/{kid}"


class IdentidadeInvalida(Exception):
    pass


def _b64url(s):
    s = s.rstrip("=")
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


@functools.lru_cache(maxsize=32)
def _chave_publica(regiao, kid):
    with urllib.request.urlopen(URL_CHAVE.format(regiao=regiao, kid=kid), timeout=5) as r:
        return r.read().decode("ascii")


def email_do_cabecalho(token, signer_esperado, regiao="us-east-1", busca_chave=None):
    """E-mail (minúsculo) do usuário logado. Qualquer falha levanta IdentidadeInvalida."""
    if not token:
        raise IdentidadeInvalida("cabeçalho x-amzn-oidc-data ausente")
    partes = token.split(".")
    if len(partes) != 3:
        raise IdentidadeInvalida("JWT malformado")
    try:
        cab = json.loads(_b64url(partes[0]))
    except ValueError as e:
        raise IdentidadeInvalida(f"cabeçalho do JWT ilegível: {e}") from e
    if not signer_esperado or cab.get("signer") != signer_esperado:
        raise IdentidadeInvalida(f"signer inesperado: {cab.get('signer')!r}")
    kid = cab.get("kid")
    if not kid:
        raise IdentidadeInvalida("JWT sem kid")
    pem = (busca_chave or _chave_publica)(regiao, kid)
    # O token vai COMO VEIO: o ALB emite base64url com '=' e assina o texto já com esse
    # padding. Tirar o '=' antes de conferir muda o que foi assinado e reprova todo login real
    # (pego na bancada da training, 14/10/2026).
    try:
        dados = jwt.decode(token, pem, algorithms=["ES256"], options={"verify_aud": False})
    except jwt.PyJWTError as e:
        raise IdentidadeInvalida(f"assinatura/validade do JWT: {e}") from e
    email = (dados.get("email") or "").strip().lower()
    if not email:
        raise IdentidadeInvalida("JWT sem e-mail (o login precisa do escopo 'email')")
    # Só com email_verified o provedor garante que a pessoa é dona do e-mail; sem isso o
    # cadastro casaria com um endereço que ninguém confirmou. O Google manda booleano; o
    # userinfo do Cognito (plano B do login), o texto "true".
    if dados.get("email_verified") not in (True, "true"):
        raise IdentidadeInvalida(f"e-mail não verificado pelo provedor: {email}")
    return email
