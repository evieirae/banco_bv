# -*- coding: utf-8 -*-
"""Identidade do ALB: só e-mail com assinatura do NOSSO load balancer passa."""
import base64
import json
import os
import sys
import time

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from jwt.algorithms import ECAlgorithm

sys.path.insert(0, os.path.dirname(__file__))
import auth_alb  # noqa: E402

SIGNER = "arn:aws:elasticloadbalancing:us-east-1:835825599161:loadbalancer/app/tf-load-balancer/abc"


def _par():
    priv = ec.generate_private_key(ec.SECP256R1())
    pem_pub = priv.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo).decode()
    return priv, pem_pub


def _token(priv, email="Fulano@BV.com.br", signer=SIGNER, exp=None, padding=False, verificado=True):
    dados = {"email": email, "exp": exp or int(time.time()) + 60}
    if verificado is not None:
        dados["email_verified"] = verificado
    if not padding:
        return jwt.encode(dados, priv, algorithm="ES256", headers={"signer": signer, "kid": "k1"})
    # Como o ALB faz: base64url COM '=' em cada parte, e a assinatura cobre o texto JÁ com o
    # padding (pego na bancada da training: tirar o '=' antes de conferir quebrava a assinatura
    # de todo login real). Antes este teste punha o '=' depois de assinar — token que não existe.
    def b64(b):
        return base64.urlsafe_b64encode(b).decode()
    cab = b64(json.dumps({"alg": "ES256", "kid": "k1", "signer": signer, "typ": "JWT"}).encode())
    corpo = b64(json.dumps(dados).encode())
    assinatura = ECAlgorithm(ECAlgorithm.SHA256).sign(f"{cab}.{corpo}".encode(), priv)
    return f"{cab}.{corpo}.{b64(assinatura)}"


def test_email_valido_sai_minusculo():
    priv, pub = _par()
    assert auth_alb.email_do_cabecalho(_token(priv), SIGNER, busca_chave=lambda r, k: pub) == "fulano@bv.com.br"


def test_aceita_padding_do_alb():
    priv, pub = _par()
    t = _token(priv, padding=True)
    assert auth_alb.email_do_cabecalho(t, SIGNER, busca_chave=lambda r, k: pub) == "fulano@bv.com.br"


def test_recusa_outro_signer():
    priv, pub = _par()
    with pytest.raises(auth_alb.IdentidadeInvalida, match="signer"):
        auth_alb.email_do_cabecalho(_token(priv, signer="arn:outro"), SIGNER, busca_chave=lambda r, k: pub)


def test_recusa_assinatura_de_outra_chave():
    priv, _ = _par()
    _, pub_outra = _par()
    with pytest.raises(auth_alb.IdentidadeInvalida, match="assinatura"):
        auth_alb.email_do_cabecalho(_token(priv), SIGNER, busca_chave=lambda r, k: pub_outra)


def test_recusa_token_vencido():
    priv, pub = _par()
    with pytest.raises(auth_alb.IdentidadeInvalida):
        auth_alb.email_do_cabecalho(_token(priv, exp=int(time.time()) - 10), SIGNER,
                                    busca_chave=lambda r, k: pub)


def test_recusa_sem_email():
    priv, pub = _par()
    with pytest.raises(auth_alb.IdentidadeInvalida, match="e-mail"):
        auth_alb.email_do_cabecalho(_token(priv, email=""), SIGNER, busca_chave=lambda r, k: pub)


def test_recusa_email_que_o_provedor_nao_verificou():
    # o Google só garante que a pessoa é dona do e-mail com email_verified verdadeiro
    priv, pub = _par()
    with pytest.raises(auth_alb.IdentidadeInvalida, match="verificado"):
        auth_alb.email_do_cabecalho(_token(priv, verificado=False), SIGNER, busca_chave=lambda r, k: pub)


def test_recusa_token_sem_email_verified():
    priv, pub = _par()
    with pytest.raises(auth_alb.IdentidadeInvalida, match="verificado"):
        auth_alb.email_do_cabecalho(_token(priv, verificado=None), SIGNER, busca_chave=lambda r, k: pub)


def test_aceita_email_verified_em_texto():
    # o userinfo do Cognito (plano B do login) manda "true" como texto; o do Google, booleano
    priv, pub = _par()
    t = _token(priv, verificado="true")
    assert auth_alb.email_do_cabecalho(t, SIGNER, busca_chave=lambda r, k: pub) == "fulano@bv.com.br"


def test_recusa_cabecalho_ausente_e_signer_nao_configurado():
    with pytest.raises(auth_alb.IdentidadeInvalida):
        auth_alb.email_do_cabecalho("", SIGNER)
    priv, pub = _par()
    with pytest.raises(auth_alb.IdentidadeInvalida, match="signer"):
        auth_alb.email_do_cabecalho(_token(priv), "", busca_chave=lambda r, k: pub)
