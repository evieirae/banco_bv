import { useQuery } from "@tanstack/react-query";
import { api } from "../api";
import { montarOrganograma, iniciais, fotoKey } from "../organograma";

// Fotos (opcionais): arquivos em src/assets/organograma/<email-sanitizado>.png. import.meta.glob
// monta o mapa no bundle; sem arquivo → iniciais. Adicionar foto = soltar o arquivo (zero código).
const FOTOS = import.meta.glob("../assets/organograma/*.png", {
  eager: true, query: "?url", import: "default",
}) as Record<string, string>;
const fotoPorArquivo = new Map<string, string>(
  Object.entries(FOTOS).map(([path, url]) => [path.split("/").pop()!, url]),
);
function urlFoto(email: string): string | undefined {
  const k = fotoKey(email);
  return k ? fotoPorArquivo.get(k) : undefined;
}

export function OrganogramaSection() {
  // Mesma queryKey dos dropdowns de responsável → cache compartilhado. Os grupos saem de
  // organograma=true + papel (grupo derivado do papel em montarOrganograma).
  const q = useQuery({ queryKey: ["analistas"], queryFn: () => api.analistas() });
  const grupos = montarOrganograma(q.data?.rows ?? []);
  if (grupos.length === 0) return null;  // ninguém marcado ainda / carregando

  return (
    <section className="org">
      <h2 className="org-title">Time Indicium</h2>
      <div className="org-groups">
        {grupos.map((g) => (
          <div className="org-col" key={g.titulo}>
            <h3 className="org-col-title">{g.titulo}</h3>
            <div className="org-people">
              {g.pessoas.map((p) => {
                const foto = urlFoto(p.email);
                return (
                  <div className="org-card" key={p.email || p.nome}>
                    <div className="org-avatar">
                      {foto
                        ? <img src={foto} alt={p.nome} />
                        : <span className="org-initials">{iniciais(p.nome)}</span>}
                    </div>
                    <div className="org-info">
                      <div className="org-nome">{p.nome}</div>
                      <div className="org-papel">{p.papel}</div>
                    </div>
                  </div>
                );
              })}
            </div>
            {g.pessoas.some((p) => p.papel === "DE" || p.papel === "AE") && (
              <div className="org-legend">DE = Data Engineer · AE = Analytics Engineer</div>
            )}
          </div>
        ))}
      </div>
    </section>
  );
}
