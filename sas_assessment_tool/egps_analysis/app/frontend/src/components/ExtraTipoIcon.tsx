// Ícone do TIPO do extra. SVG inline, 5 formas DISTINTAS entre si — não só cores: a
// tabela já usa cor para etapa/status, e mais uma escala de cor ali vira ruído (e some
// para quem não distingue as duas). Herda `currentColor`, então acompanha o badge no
// tema claro e no escuro sem uma regra de CSS por tipo.
import { PAPEL_AJUDA, PAPEL_FAMILIA, papeisDoVinculo } from "../vinculo";

const P: Record<string, JSX.Element> = {
  // seta circular: a mesma coisa, de novo
  Atualizado: <path d="M9.5 3.4A4.2 4.2 0 1 0 11 6.8M9.5 1.6v2.2H7.3" />,
  // duas setas opostas: saiu um, entrou outro
  "Substituído": <path d="M2 4h7.2L7.4 2.2M10 8H2.8l1.8 1.8" />,
  // dois traços convergindo num só: N viraram 1
  Unificado: <path d="M1.8 2.4 5.4 6H10M1.8 9.6 5.4 6" />,
  // círculo vazado: ficou a casca, o inventário foi embora
  casca: <circle cx="6" cy="6" r="3.6" strokeDasharray="2.2 1.6" />,
  // cruz: chegou um a mais
  novo: <path d="M6 2.2v7.6M2.2 6h7.6" />,
};

export function ExtraTipoIcon({ tipo }: { tipo: string }) {
  const d = P[tipo];
  if (!d) return null;
  return (
    <svg className="xt-ico" viewBox="0 0 12 12" width="11" height="11" aria-hidden="true"
      fill="none" stroke="currentColor" strokeWidth="1.3"
      strokeLinecap="round" strokeLinejoin="round">{d}</svg>
  );
}

/** O PAPEL desta linha no vínculo, nos dois lados: Desatualizado/Atualizado,
 * Unificado/Unificador, Substituído/Substituto.
 *
 * Reusa a forma da FAMÍLIA (as três de cima) em vez de inventar seis: o que muda entre as
 * duas pontas é de que lado o EGP está, não que tipo de vínculo é — e quem diz o lado é a
 * palavra, que é justamente o que se quer ler. Seis formas parecidas seriam ruído. */
export function VinculoPapeis({ linha }: {
  linha: { vinculo_tipo?: string | null; sucessor?: string | null;
           antecessores?: { tipo: string | null }[] };
}) {
  const papeis = papeisDoVinculo(linha);
  if (!papeis.length) return null;
  return (
    <span className="xt-tipos">
      {papeis.map((p) => (
        <span key={p} className="xt-tipo vinc-papel" title={`${p}: ${PAPEL_AJUDA[p] ?? ""}`}>
          <ExtraTipoIcon tipo={PAPEL_FAMILIA[p]} />{p}
        </span>
      ))}
    </span>
  );
}
