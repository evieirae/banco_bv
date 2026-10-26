// Aba "Perguntas" — Genie space embutido em iframe (restrita a bv_users, ver App.tsx).
// O iframe roda com a sessão Databricks do PRÓPRIO usuário: quem responde pelo acesso é a
// permissão do space ("Can run" para bv_users), não este componente. O embed é preview do
// Databricks e depende de cookie de terceiro (app em databricksapps.com, Genie em
// databricks.com) — por isso o link para abrir o space fora do app fica sempre visível.
// Fontes do space (instruções + SQLs de exemplo): egps_analysis/app/genie/.

export function GenieView({ url }: { url: string }) {
  const urlDireta = url.replace("/embed/genie/", "/genie/");
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
      <div className="card" style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 12 }}>
        <span>
          Pergunte sobre status de EGPs e inputs, por que uma tela mostra um número e outra
          mostra outro, recortes, histórico e comentários. As respostas usam a mesma régua das
          telas, a partir do retrato que o app grava (pode ter alguns minutos de atraso — a
          resposta diz a hora). Os dados são sempre os de PRODUÇÃO, também no app dev.
        </span>
        <a href={urlDireta} target="_blank" rel="noopener noreferrer"
          style={{ whiteSpace: "nowrap", color: "var(--accent-line)", fontWeight: 600 }}>
          Abrir em nova aba ↗
        </a>
      </div>
      <div className="genie-frame-wrap">
        <iframe
          className="genie-frame"
          title="Genie — Consulta do app"
          src={url}
          allow="clipboard-write"
        />
      </div>
    </div>
  );
}
