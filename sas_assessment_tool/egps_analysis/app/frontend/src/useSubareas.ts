import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "./api";
import { mapaSubarea, ordenarSubareas, type MapaSubarea } from "./subareas";

// Acesso ao cadastro Responsável BV -> sub-área. Uma queryKey só (["responsaveis-bv"])
// compartilhada por TODAS as abas: o cadastro tem ~11 linhas e muda raramente, então a
// primeira aba que abrir paga a busca e as outras leem do cache do React Query.
// Separado de subareas.ts de propósito: lá ficam helpers puros, testáveis sob node.
export function useSubareas(): {
  mapa: MapaSubarea;
  nomes: string[];          // grafias cadastradas (datalist do campo Responsável BV)
  subareas: string[];       // sub-áreas distintas cadastradas (datalist da Gestão)
  pronto: boolean;          // cadastro já chegou — antes disso TUDO resolve "Sem sub-área"
} {
  const q = useQuery({ queryKey: ["responsaveis-bv"], queryFn: () => api.responsaveisBv() });
  const rows = useMemo(() => q.data?.rows ?? [], [q.data]);
  // `pronto` existe porque o mapa vazio é indistinguível de "ninguém tem sub-área": sem
  // esse sinal, chips e tabela piscam 100% em "Sem sub-área" antes do cadastro chegar.
  const pronto = !q.isPending;
  return useMemo(() => ({
    mapa: mapaSubarea(rows),
    nomes: rows.map((r) => r.nome).sort((a, b) => a.localeCompare(b, "pt-BR")),
    subareas: ordenarSubareas(rows.map((r) => (r.subarea ?? "").trim()).filter(Boolean)),
    pronto,
  }), [rows, pronto]);
}
