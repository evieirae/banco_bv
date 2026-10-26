import { useRef } from "react";
import { useVirtualizer } from "@tanstack/react-virtual";
import type { OutputRow } from "../types";

export type OutputSortKey =
  | "artifact" | "categoria" | "areas" | "qtd_produtores" | "qtd_consumidores" | "terminal";

const isTruthy = (v: boolean | string | null | undefined) => v === true || v === "true";

interface Props {
  rows: OutputRow[];
  onSort: (k: OutputSortKey) => void;
  indicator: (k: OutputSortKey) => string;
  onSelect: (r: OutputRow) => void;
}

const ROW_H = 40;

export function OutputsTable({ rows, onSort, indicator, onSelect }: Props) {
  const parentRef = useRef<HTMLDivElement>(null);
  const virt = useVirtualizer({
    count: rows.length,
    getScrollElement: () => parentRef.current,
    estimateSize: () => ROW_H,
    overscan: 12,
  });

  const H = (k: OutputSortKey, label: string, cls: string) => (
    <div className={`${cls} sort-th`} onClick={() => onSort(k)} title="ordenar">
      {label}{indicator(k)}
    </div>
  );

  return (
    <div className="table-wrap">
      <div className="thead outputs-table">
        <div className="c-idx">#</div>
        {H("artifact", "Artefato", "c-art")}
        {H("categoria", "Categoria", "c-cat")}
        {H("areas", "Área(s)", "c-area")}
        {H("qtd_produtores", "Produtores", "c-num")}
        {H("qtd_consumidores", "Consumidores", "c-num")}
        {H("terminal", "Tipo", "c-out-type")}
      </div>

      <div className="tbody" ref={parentRef}>
        <div style={{ height: virt.getTotalSize(), position: "relative" }}>
          {virt.getVirtualItems().map((vi) => {
            const r = rows[vi.index];
            const terminal = isTruthy(r.terminal);
            return (
              <div
                key={r.chave_canonica}
                className="trow outputs-table"
                style={{ transform: `translateY(${vi.start}px)`, height: ROW_H }}
              >
                <div className="c-idx">{vi.index + 1}</div>
                <div
                  className="c-art clickable"
                  title={`${r.artifact} — clique p/ detalhes`}
                  onClick={() => onSelect(r)}
                >
                  {r.artifact}
                </div>
                <div className="c-cat">{r.categoria}</div>
                <div className="c-area" title={r.areas}>{r.areas}</div>
                <div
                  className="c-num"
                  title={r.produtor_escolhido
                    ? `produtor definido: ${r.produtor_escolhido}`
                    : (r.qtd_criadores != null && Number(r.qtd_criadores) === 0 && Number(r.qtd_produtores) > 0
                      ? "acumulador — ninguém cria (só INSERT/UPDATE)"
                      : ((r.qtd_criadores != null ? Number(r.qtd_criadores) : Number(r.qtd_produtores)) > 1
                        ? "ambíguo — produtor a definir" : undefined))}
                >
                  {r.qtd_criadores != null ? r.qtd_criadores : r.qtd_produtores}
                  {r.qtd_criadores != null && Number(r.qtd_criadores) !== Number(r.qtd_produtores)
                    ? <span className="muted" style={{ fontSize: 11 }}> ({r.qtd_produtores} escrevem)</span>
                    : null}
                  {r.produtor_escolhido
                    ? <span style={{ color: "#16a34a", fontWeight: 700 }}> ✓</span>
                    : (Number(r.qtd_produtores) > 1
                      ? <span style={{ color: "#d97706", fontWeight: 700 }}> ●</span>
                      : null)}
                </div>
                <div className="c-num">{r.qtd_consumidores}</div>
                <div className="c-out-type">
                  <span className={`pill ${terminal ? "ok" : "todo"}`}>
                    {terminal ? "Terminal" : "Intermediário"}
                  </span>
                </div>
              </div>
            );
          })}
        </div>
        {rows.length === 0 && <div className="empty">Nenhuma linha para os filtros atuais.</div>}
      </div>
    </div>
  );
}
