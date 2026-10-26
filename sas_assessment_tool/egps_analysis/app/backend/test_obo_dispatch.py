"""Verificação offline (sem servidor/rede) do on-behalf-of-user:
dispatch de _client() pelo contextvar e o middleware ASGI extraindo o header."""
import asyncio
import main


def test_client_dispatch_by_contextvar():
    main._sp_client = lambda: "SP"          # noqa: monkeypatch
    main._user_client = lambda tok: f"USER:{tok}"  # noqa: monkeypatch
    assert main._client() == "SP", "sem token deve usar o service principal"
    reset = main._user_token.set("xyz")
    try:
        assert main._client() == "USER:xyz", "com token deve usar o cliente do usuário"
    finally:
        main._user_token.reset(reset)
    assert main._client() == "SP", "após reset volta ao SP"


def test_middleware_sets_and_resets_token():
    seen = {}

    async def fake_app(scope, receive, send):
        seen["tok"] = main._user_token.get()

    mw = main._OBOAuthMiddleware(fake_app)
    scope = {"type": "http", "headers": [(b"x-forwarded-access-token", b"tok123")]}
    asyncio.run(mw(scope, None, None))
    assert seen["tok"] == "tok123", "middleware deve expor o token via contextvar"
    assert main._user_token.get() is None, "contextvar deve ser resetado após o request"


def test_middleware_no_header_is_none():
    seen = {}

    async def fake_app(scope, receive, send):
        seen["tok"] = main._user_token.get()

    mw = main._OBOAuthMiddleware(fake_app)
    asyncio.run(mw({"type": "http", "headers": []}, None, None))
    assert seen["tok"] is None, "sem header → token None → fallback SP"


def test_non_http_scope_passthrough():
    called = {"n": 0}

    async def fake_app(scope, receive, send):
        called["n"] += 1

    mw = main._OBOAuthMiddleware(fake_app)
    asyncio.run(mw({"type": "lifespan"}, None, None))
    assert called["n"] == 1, "scopes não-http passam direto"


def test_require_obo_rejects_missing_token():
    from fastapi import HTTPException
    main._sp_client = lambda: "SP"          # noqa
    main._user_client = lambda tok: f"USER:{tok}"  # noqa
    orig = main.REQUIRE_OBO
    main.REQUIRE_OBO = True
    try:
        reset = main._user_token.set("xyz")
        try:
            assert main._client() == "USER:xyz", "com token, REQUIRE_OBO não bloqueia"
        finally:
            main._user_token.reset(reset)
        raised_status = None
        try:
            main._client()
        except HTTPException as e:
            raised_status = e.status_code
        assert raised_status == 401, "sem token + REQUIRE_OBO deve levantar 401 (não cair no SP)"
    finally:
        main.REQUIRE_OBO = orig


def test_middleware_whitespace_token_is_none():
    seen = {}

    async def fake_app(scope, receive, send):
        seen["tok"] = main._user_token.get()

    mw = main._OBOAuthMiddleware(fake_app)
    asyncio.run(mw({"type": "http", "headers": [(b"x-forwarded-access-token", b"   ")]}, None, None))
    assert seen["tok"] is None, "token só com espaços → None (cai no fallback, não erro espúrio)"


def test_sql_error_mapping():
    from fastapi import HTTPException
    for msg, code in [
        ("PERMISSION_DENIED: user does not have SELECT", 403),
        ("RESOURCE: PermissionDenied on table", 403),
        ("Invalid access token", 401),
        ("token expired", 401),
        ("Warehouse is starting / timeout", 502),
    ]:
        e = main._sql_http_error(msg)
        assert isinstance(e, HTTPException) and e.status_code == code, f"{msg!r} -> {e.status_code} (esperado {code})"


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    fail = 0
    for t in tests:
        try:
            t()
            print(f"PASS  {t.__name__}")
        except AssertionError as e:
            fail += 1
            print(f"FAIL  {t.__name__}: {e}")
    print(f"\n{len(tests) - fail}/{len(tests)} passaram")
    raise SystemExit(1 if fail else 0)
