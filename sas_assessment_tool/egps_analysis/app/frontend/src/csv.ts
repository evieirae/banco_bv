// Exportador de CSV client-side, Excel pt-BR: separador ';' + BOM UTF-8 (abre com
// acento e colunas certas). Compartilhado por Monitor/EGPs/Escopo/Escopo de migração.

import { hojeSP } from "./diasUteis";

export interface CsvColumn<T> {
  header: string;
  get: (row: T) => string | number | boolean | null | undefined;
}

// aspas em torno da célula só quando há caractere que quebra o CSV; aspas internas dobradas.
export const csvEscape = (v: string | number | boolean | null | undefined): string => {
  const s = v === null || v === undefined ? "" : String(v);
  return /[";\n\r]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
};

// booleano -> "sim"/"não" (aceita também os "true"/"false" string que a API às vezes devolve).
export const csvBool = (v: boolean | string | null | undefined): string =>
  v === true || v === "true" ? "sim" : v === false || v === "false" ? "não" : "";

// data AAAA-MM-DD de HOJE em America/Sao_Paulo para compor o nome do arquivo.
// (era toISOString() = UTC: export feito das 21h em diante saía com a data de amanhã.)
export const csvDate = (): string => hojeSP();

// nome do EGP sem o prefixo `area__` (igual ao shortName exibido nas tabelas).
export const egpShort = (id: string): string =>
  id.includes("__") ? id.split("__").slice(1).join("__") : id;

// monta as linhas (header + dados) a partir de colunas declarativas.
export function csvFromColumns<T>(rows: T[], cols: CsvColumn<T>[]): string[] {
  const lines = [cols.map((c) => csvEscape(c.header)).join(";")];
  for (const r of rows) lines.push(cols.map((c) => csvEscape(c.get(r))).join(";"));
  return lines;
}

// dispara o download de um CSV a partir de linhas já formatadas (BOM + CRLF).
export function csvDownload(filename: string, lines: string[]): void {
  const blob = new Blob(["﻿" + lines.join("\r\n")], { type: "text/csv;charset=utf-8;" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}
