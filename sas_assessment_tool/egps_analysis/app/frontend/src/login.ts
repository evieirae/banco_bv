// Login na AWS (ADR 0005): sem sessão, o backend manda toda navegação para /login, e a API
// responde 401 com {entrar: "/login"}. Este é o caso da sessão que expira com o app aberto:
// leva à página de login guardando onde a pessoa estava. Sem o campo `entrar` (401 do
// Databricks, 403 de quem não tem cadastro) nada muda.
export function destinoDoLogin(status: number, corpo: string, pathname: string, search: string): string | null {
  if (status !== 401) return null;
  let entrar: unknown;
  try {
    entrar = (JSON.parse(corpo) as { entrar?: unknown }).entrar;
  } catch {
    return null;
  }
  return typeof entrar === "string" ? `${entrar}?volta=${encodeURIComponent(pathname + search)}` : null;
}
