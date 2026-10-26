import { useMemo, useState } from "react";

export type SortDir = "asc" | "desc";
export interface SortState<K extends string> {
  key: K;
  dir: SortDir;
}

type Cell = string | number | null | undefined;
const isEmpty = (v: Cell) => v === null || v === undefined || v === "";

/**
 * Ordenação client-side reutilizável. `accessor` deve ser estável (definido fora do
 * componente) para evitar reordenar a cada render. Vazios/nulos sempre por último,
 * independente da direção. Texto compara case-insensitive (pt-BR, numérico natural).
 */
export function useTableSort<T, K extends string>(
  rows: T[],
  accessor: (row: T, key: K) => Cell,
  initial: SortState<K>,
) {
  const [sort, setSort] = useState<SortState<K>>(initial);

  const sorted = useMemo(() => {
    const dir = sort.dir === "asc" ? 1 : -1;
    return [...rows].sort((a, b) => {
      const x = accessor(a, sort.key);
      const y = accessor(b, sort.key);
      const ex = isEmpty(x);
      const ey = isEmpty(y);
      if (ex && ey) return 0;
      if (ex) return 1;
      if (ey) return -1;
      if (typeof x === "number" && typeof y === "number") return (x - y) * dir;
      return String(x).localeCompare(String(y), "pt-BR", { numeric: true }) * dir;
    });
  }, [rows, sort, accessor]);

  const onSort = (key: K) =>
    setSort((s) => (s.key === key ? { key, dir: s.dir === "asc" ? "desc" : "asc" } : { key, dir: "asc" }));

  const indicator = (key: K) => (sort.key === key ? (sort.dir === "asc" ? " ▲" : " ▼") : "");

  return { sorted, sort, onSort, indicator };
}
