import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "./api";

// Tag textual do mês do plano de priorização. null/undefined (fora do recorte fixo) => "—".
export const mesTag = (mes: number | null | undefined) => (mes == null ? "—" : `M${mes}`);

// Hook compartilhado: mapa projeto -> mês do plano dinâmico. Usa a MESMA queryKey do WavesView
// (["priorizacao"]) => cache único; quando um pin é gravado (PATCH invalida ["priorizacao"]),
// todas as abas que usam este hook re-renderizam com o mês atualizado.
export function useMesPlan() {
  const q = useQuery({ queryKey: ["priorizacao"], queryFn: () => api.priorizacao(), staleTime: 60_000 });
  // Plano + EXTRAS. O extra não está em `meses[].egps` (não ocupa vaga no plano), mas tem
  // mês — o do Antecessor, decisão da gestão de 30/09/2026. Sem esta união ele saía com
  // "—" em toda tela e era derrubado por qualquer filtro de mês, levando junto os inputs
  // que só extra lê. `meses` (as opções do filtro) continua vindo só do plano: o mês do
  // extra é sempre o mês de um EGP do plano, então nenhuma opção nova aparece.
  //
  // `mesOfPlano` é o mesmo mapa SEM os extras, para as visões da linha de base que herdam
  // mês de EGP (input lido por vários EGPs). Ali o mês tem de vir só do plano: um input que
  // a linha de base e um extra leem pertence à linha de base, e a conta dela não muda
  // porque um extra chegou — é a mesma régua do funil de ingestão por mês do Resumo.
  const mesOfPlano = useMemo(() => {
    const m = new Map<string, number>();
    (q.data?.meses ?? []).forEach((mm) => mm.egps.forEach((e) => m.set(e.projeto, mm.mes)));
    return m;
  }, [q.data]);
  const mesOf = useMemo(() => {
    const m = new Map(mesOfPlano);
    (q.data?.extras ?? []).forEach((e) => m.set(e.projeto, e.mes));
    return m;
  }, [q.data, mesOfPlano]);
  const meses = useMemo(() => (q.data?.meses ?? []).map((mm) => mm.mes), [q.data]);
  return { mesOf, mesOfPlano, meses, isFetching: q.isFetching };
}
