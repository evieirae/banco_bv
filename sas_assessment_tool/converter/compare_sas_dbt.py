#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Compara resultado exportado do SAS com o exportado do dbt usando datacompy.

Formato de cada arquivo é definido pela extensão: .csv, .xls ou .xlsx (Excel usa sempre a
primeira planilha). Qualquer combinação é aceita (ex.: um XLSX e um CSV).

Suporta mapeamento de colunas (nomes diferentes entre SAS e dbt), chave de join
configurável, delimitador/encoding por arquivo CSV e gera relatório em arquivo.

Nomes de colunas são normalizados para minúsculas (cabeçalhos e argumentos da CLI aceitam
qualquer caso). Antes da comparação: vírgula decimal -> ponto; valores inteiros vindos como
float do Excel (ex.: 6.0) são alinhados com inteiros (ex.: 6).

Como executar:
  python compare_sas_dbt.py sas_export.csv dbt_export.csv
  python compare_sas_dbt.py sas.xlsx dbt.csv --join-cols "id,data"
  python compare_sas_dbt.py sas.csv dbt.csv \\
    --sas-cols "Data_Processamento,Id,Valor" --dbt-cols "data_processamento,id,valor" \\
    --join-cols "Data_Processamento,Id" --date-cols "data_processamento" \\
    --sas-delim ";" --sas-encoding "latin-1" --report output/comparison_report.txt
"""

from __future__ import annotations

import argparse
import re
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any

import pandas as pd

try:
    from datacompy.core import Compare as DataCompyCompare
except ImportError:
    print("Erro: pacote 'datacompy' não instalado. Execute: pip install datacompy", file=sys.stderr)
    sys.exit(2)

DEFAULT_REPORT = "comparison_report.txt"
ENCODING_FALLBACK = ("utf-8", "latin-1", "cp1252")
SUPPORTED_EXTENSIONS = (".csv", ".xls", ".xlsx")

# OOXML escapes reserved XML characters in shared strings / names (_x0020_ = space).
_EXCEL_OOXML_CHAR_ESC = re.compile(r"_x([0-9a-fA-F]{4})_")


def _decode_excel_xml_escapes(text: str) -> str:
    return _EXCEL_OOXML_CHAR_ESC.sub(lambda m: chr(int(m.group(1), 16)), text)


def _decode_excel_cell_value(val: Any) -> Any:
    if pd.isna(val):
        return val
    if isinstance(val, str):
        return _decode_excel_xml_escapes(val)
    return val


def _decode_excel_read_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    """Undo Excel OOXML _xHHHH_ escapes in column names and string cells."""
    out = df.copy()
    out.columns = pd.Index(_decode_excel_xml_escapes(str(c)) for c in out.columns)
    for col in out.columns:
        out[col] = out[col].map(_decode_excel_cell_value)
    return out


def _parse_cols(s: str) -> list[str]:
    """Converte string 'a,b,c' em lista ['a','b','c'] com strip."""
    return [c.strip() for c in s.split(",") if c.strip()]


def read_csv_with_fallback(
    path: Path,
    sep: str = ",",
    encoding: str | None = None,
) -> pd.DataFrame:
    """Lê CSV com encoding opcional e fallback se falhar."""
    encodings = [encoding] if encoding else list(ENCODING_FALLBACK)
    last_error = None
    for enc in encodings:
        try:
            return pd.read_csv(path, sep=sep, encoding=enc)
        except (UnicodeDecodeError, pd.errors.ParserError) as e:
            last_error = e
            continue
    raise ValueError(f"Não foi possível ler {path} com encodings {encodings}") from last_error


def read_file_to_dataframe(
    path: Path,
    sep: str = ",",
    encoding: str | None = None,
    sheet_name: int | str = 0,
) -> pd.DataFrame:
    """
    Lê CSV, XLS ou XLSX para DataFrame. Formato definido pela extensão do arquivo.
    Para CSV usa sep e encoding; para Excel usa sheet_name (ignora sep/encoding).
    """
    suffix = Path(path).suffix.lower()
    if suffix not in SUPPORTED_EXTENSIONS:
        raise ValueError(
            f"Extensão não suportada: {suffix}. Use uma de: {', '.join(SUPPORTED_EXTENSIONS)}"
        )
    if suffix == ".csv":
        return read_csv_with_fallback(path, sep=sep, encoding=encoding)
    try:
        df = pd.read_excel(path, sheet_name=sheet_name)
    except ImportError as e:
        hint = "pip install openpyxl" if suffix == ".xlsx" else "pip install xlrd"
        raise ValueError(
            f"Não foi possível ler {path} (Excel). Instale a dependência: {hint}"
        ) from e
    return _decode_excel_read_dataframe(df)


def align_dataframes(
    df_sas: pd.DataFrame,
    df_dbt: pd.DataFrame,
    sas_cols: list[str] | None,
    dbt_cols: list[str] | None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Alinha os dois DataFrames por mapeamento de colunas.
    Retorna (df_sas_aligned, df_dbt_aligned) com as mesmas colunas na mesma ordem (nomes canônicos = dbt).
    """
    if sas_cols is not None and dbt_cols is not None:
        if len(sas_cols) != len(dbt_cols):
            raise ValueError(
                f"--sas-cols e --dbt-cols devem ter a mesma quantidade de colunas: "
                f"{len(sas_cols)} vs {len(dbt_cols)}"
            )
        missing_sas = set(sas_cols) - set(df_sas.columns)
        if missing_sas:
            raise ValueError(f"Colunas ausentes no arquivo SAS: {missing_sas}")
        missing_dbt = set(dbt_cols) - set(df_dbt.columns)
        if missing_dbt:
            raise ValueError(f"Colunas ausentes no arquivo dbt: {missing_dbt}")
        # SAS: selecionar na ordem sas_cols e renomear para dbt_cols (canônico)
        df_sas_aligned = df_sas[sas_cols].rename(columns=dict(zip(sas_cols, dbt_cols)))
        # dbt: selecionar na ordem dbt_cols
        df_dbt_aligned = df_dbt[dbt_cols].copy()
        return df_sas_aligned, df_dbt_aligned

    # Sem mapeamento: exige mesmas colunas nos dois
    common = set(df_sas.columns) & set(df_dbt.columns)
    if common != set(df_sas.columns) or common != set(df_dbt.columns):
        only_sas = set(df_sas.columns) - set(df_dbt.columns)
        only_dbt = set(df_dbt.columns) - set(df_sas.columns)
        raise ValueError(
            "Sem --sas-cols/--dbt-cols os dois arquivos devem ter as mesmas colunas. "
            f"Só no SAS: {only_sas}. Só no dbt: {only_dbt}."
        )
    order = list(df_dbt.columns)
    return df_sas[order].copy(), df_dbt[order].copy()


def resolve_join_columns(
    join_cols_sas: list[str] | None,
    sas_cols: list[str] | None,
    dbt_cols: list[str] | None,
    canonical_columns: list[str],
) -> list[str]:
    """
    Resolve join_columns para o datacompy (sempre em nomes canônicos = colunas do dbt).
    Se há mapeamento, join_cols_sas são nomes no lado SAS; converte para canônico.
    """
    if not join_cols_sas:
        return []
    if sas_cols is not None and dbt_cols is not None:
        sas_to_dbt = dict(zip(sas_cols, dbt_cols))
        missing_join = [c for c in join_cols_sas if c not in sas_to_dbt]
        if missing_join:
            raise ValueError(
                f"Colunas de join devem estar em --sas-cols: ausentes {missing_join}"
            )
        join_canonical = [sas_to_dbt[c] for c in join_cols_sas]
    else:
        join_canonical = list(join_cols_sas)
    missing = set(join_canonical) - set(canonical_columns)
    if missing:
        raise ValueError(f"Colunas de join não existem no conjunto alinhado: {missing}")
    return join_canonical


def normalize_date_columns(
    df: pd.DataFrame,
    date_cols: list[str],
    source: str,
) -> pd.DataFrame:
    """
    Normaliza colunas de data para string YYYY-MM-DD para comparação.
    - source='sas': DDMonYYYY (texto SAS); datas vindas de Excel (datetime/Timestamp)
      ou strings ISO com hora (ex.: 2024-05-09 00:00:00) também viram YYYY-MM-DD.
    - source='bq': formato BQ/dbt YYYY-MM-DD ou datetime.
    Valores que falharem no parse permanecem inalterados (string).
    """
    if not date_cols:
        return df
    df = df.copy()
    date_set = [c for c in date_cols if c in df.columns]
    for col in date_set:
        if source == "sas":
            def _parse_sas(val):
                if pd.isna(val) or str(val).strip() == "":
                    return ""
                if isinstance(val, date):
                    return val.strftime("%Y-%m-%d")
                try:
                    s = str(val).strip()
                    dt = datetime.strptime(s, "%d%b%Y")
                    return dt.strftime("%Y-%m-%d")
                except (ValueError, TypeError):
                    try:
                        dt = pd.to_datetime(s, format="%Y-%m-%d", errors="coerce")
                        if pd.isna(dt):
                            dt = pd.to_datetime(s, errors="coerce")
                        return dt.strftime("%Y-%m-%d") if pd.notna(dt) else s
                    except (ValueError, TypeError):
                        return s
            df[col] = df[col].apply(_parse_sas)
        else:
            def _parse_bq(val):
                if pd.isna(val) or str(val).strip() == "":
                    return ""
                if isinstance(val, (pd.Timestamp, datetime)):
                    return val.strftime("%Y-%m-%d")
                try:
                    s = str(val).strip()
                    dt = pd.to_datetime(s, format="%Y-%m-%d", errors="coerce")
                    if pd.isna(dt):
                        dt = pd.to_datetime(s, errors="coerce")
                    return dt.strftime("%Y-%m-%d") if pd.notna(dt) else s
                except (ValueError, TypeError):
                    return s
            df[col] = df[col].apply(_parse_bq)
    return df


def _normalize_cell_for_datacompy(val: Any) -> Any:
    """
    Canonicaliza valor para comparação: vírgula -> ponto; inteiros como 6.0 viram '6'
    (igual a int 6 / string '6'), reduzindo divergência Excel vs CSV no datacompy.
    """
    if pd.isna(val):
        return val
    if isinstance(val, str) and val.strip() == "":
        return ""
    s = str(val).strip().replace(",", ".")
    try:
        x = float(s)
        if x == int(x):
            return str(int(x))
        return str(round(x, 12)).rstrip("0").rstrip(".")
    except (ValueError, TypeError):
        return str(val).strip()


def normalize_decimal_in_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    """
    Normaliza células para o datacompy: vírgula decimal -> ponto; números inteiros sem sufixo .0.
    """
    df = df.copy()
    for col in df.columns:
        df[col] = df[col].map(_normalize_cell_for_datacompy)
    return df


def run(
    path_sas: Path,
    path_dbt: Path,
    sas_cols: list[str] | None = None,
    dbt_cols: list[str] | None = None,
    join_cols: list[str] | None = None,
    date_cols: list[str] | None = None,
    sas_delim: str = ",",
    sas_encoding: str | None = None,
    dbt_delim: str = ",",
    dbt_encoding: str | None = None,
    report_path: Path | None = None,
    abs_tol: float = 0.0,
    rel_tol: float = 0.0,
) -> bool:
    """
    Executa a comparação. Retorna True se os dados batem, False caso contrário.
    """
    df_sas = read_file_to_dataframe(path_sas, sep=sas_delim, encoding=sas_encoding, sheet_name=0)
    df_sas.columns = df_sas.columns.str.lower()
    df_dbt = read_file_to_dataframe(path_dbt, sep=dbt_delim, encoding=dbt_encoding, sheet_name=0)
    df_dbt.columns = df_dbt.columns.str.lower()

    df_sas_aligned, df_dbt_aligned = align_dataframes(df_sas, df_dbt, sas_cols, dbt_cols)
    if date_cols:
        df_sas_aligned = normalize_date_columns(df_sas_aligned, date_cols, source="sas")
        df_dbt_aligned = normalize_date_columns(df_dbt_aligned, date_cols, source="bq")
    df_sas_aligned = normalize_decimal_in_dataframe(df_sas_aligned)
    df_dbt_aligned = normalize_decimal_in_dataframe(df_dbt_aligned)
    canonical_columns = list(df_dbt_aligned.columns)

    join_columns = resolve_join_columns(join_cols, sas_cols, dbt_cols, canonical_columns)
    if not join_columns:
        # datacompy sem join_columns: usa on_index=True (linha i com linha i)
        compare = DataCompyCompare(
            df_sas_aligned,
            df_dbt_aligned,
            on_index=True,
            abs_tol=abs_tol,
            rel_tol=rel_tol,
            df1_name="SAS",
            df2_name="dbt",
            cast_column_names_lower=False,
        )
    else:
        compare = DataCompyCompare(
            df_sas_aligned,
            df_dbt_aligned,
            join_columns=join_columns,
            abs_tol=abs_tol,
            rel_tol=rel_tol,
            df1_name="SAS",
            df2_name="dbt",
            cast_column_names_lower=False,
        )

    report_text = compare.report()

    if report_path is not None:
        report_path = Path(report_path)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(report_text, encoding="utf-8")
        print(f"Relatório salvo em: {report_path}")

    # Resumo no terminal
    print("\n--- Resumo ---")
    print(f"Match: {compare.matches()}")
    print(f"Linhas só no SAS: {len(compare.df1_unq_rows)}")
    print(f"Linhas só no dbt: {len(compare.df2_unq_rows)}")
    if hasattr(compare, "all_mismatch") and callable(compare.all_mismatch):
        try:
            mm = compare.all_mismatch()
            print(f"Linhas com diferença de valor: {len(mm)}")
        except Exception:
            pass
    print("--------------\n")

    return bool(compare.matches())


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Compara exportações SAS vs dbt usando datacompy. "
        "Formato (.csv, .xls, .xlsx) é detectado pela extensão de cada arquivo.",
    )
    parser.add_argument(
        "sas_csv",
        type=Path,
        help="Primeiro arquivo (SAS). Extensão define: .csv, .xls ou .xlsx",
    )
    parser.add_argument(
        "dbt_csv",
        type=Path,
        help="Segundo arquivo (dbt). Extensão define: .csv, .xls ou .xlsx",
    )
    parser.add_argument(
        "--sas-cols",
        type=str,
        default=None,
        help="Colunas do SAS na ordem desejada, separadas por vírgula (par com --dbt-cols)",
    )
    parser.add_argument(
        "--dbt-cols",
        type=str,
        default=None,
        help="Colunas do dbt na mesma ordem que --sas-cols (mapeamento 1:1)",
    )
    parser.add_argument(
        "--join-cols",
        type=str,
        default=None,
        help="Colunas de join (chave), em nomes do lado SAS, separadas por vírgula",
    )
    parser.add_argument(
        "--date-cols",
        type=str,
        default=None,
        help="Colunas de data (nomes canônicos após mapeamento). SAS DDMonYYYY -> BQ YYYY-MM-DD para comparação",
    )
    parser.add_argument(
        "--sas-delim",
        type=str,
        default=",",
        help="Delimitador quando o arquivo SAS for CSV (default: ,)",
    )
    parser.add_argument(
        "--sas-encoding",
        type=str,
        default=None,
        help="Encoding quando o arquivo SAS for CSV (default: tenta utf-8, latin-1, cp1252)",
    )
    parser.add_argument(
        "--dbt-delim",
        type=str,
        default=",",
        help="Delimitador quando o arquivo dbt for CSV (default: ,)",
    )
    parser.add_argument(
        "--dbt-encoding",
        type=str,
        default=None,
        help="Encoding quando o arquivo dbt for CSV (default: tenta utf-8, latin-1, cp1252)",
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=None,
        metavar="PATH",
        help=f"Caminho do arquivo de relatório (default: {DEFAULT_REPORT} no diretório atual)",
    )
    parser.add_argument(
        "--abs-tol",
        type=float,
        default=0.0,
        help="Tolerância absoluta para comparação numérica (default: 0)",
    )
    parser.add_argument(
        "--rel-tol",
        type=float,
        default=0.0,
        help="Tolerância relativa para comparação numérica (default: 0)",
    )
    args = parser.parse_args()

    sas_cols = _parse_cols(args.sas_cols) if args.sas_cols else None
    dbt_cols = _parse_cols(args.dbt_cols) if args.dbt_cols else None
    join_cols = _parse_cols(args.join_cols) if args.join_cols else None
    date_cols = _parse_cols(args.date_cols) if args.date_cols else None
    if sas_cols:
        sas_cols = [c.lower() for c in sas_cols]
    if dbt_cols:
        dbt_cols = [c.lower() for c in dbt_cols]
    if join_cols:
        join_cols = [c.lower() for c in join_cols]
    if date_cols:
        date_cols = [c.lower() for c in date_cols]

    if (sas_cols is None) != (dbt_cols is None):
        parser.error("Forneça ambos --sas-cols e --dbt-cols para mapeamento de colunas.")

    report_path = args.report
    if report_path is None:
        report_path = Path.cwd() / DEFAULT_REPORT

    if not args.sas_csv.is_file():
        print(f"Arquivo não encontrado: {args.sas_csv}", file=sys.stderr)
        sys.exit(1)
    if not args.dbt_csv.is_file():
        print(f"Arquivo não encontrado: {args.dbt_csv}", file=sys.stderr)
        sys.exit(1)
    if Path(args.sas_csv).suffix.lower() not in SUPPORTED_EXTENSIONS:
        print(
            f"Extensão não suportada: {Path(args.sas_csv).suffix}. "
            f"Use uma de: {', '.join(SUPPORTED_EXTENSIONS)}",
            file=sys.stderr,
        )
        sys.exit(1)
    if Path(args.dbt_csv).suffix.lower() not in SUPPORTED_EXTENSIONS:
        print(
            f"Extensão não suportada: {Path(args.dbt_csv).suffix}. "
            f"Use uma de: {', '.join(SUPPORTED_EXTENSIONS)}",
            file=sys.stderr,
        )
        sys.exit(1)

    try:
        ok = run(
            path_sas=args.sas_csv,
            path_dbt=args.dbt_csv,
            sas_cols=sas_cols,
            dbt_cols=dbt_cols,
            join_cols=join_cols,
            date_cols=date_cols,
            sas_delim=args.sas_delim,
            sas_encoding=args.sas_encoding,
            dbt_delim=args.dbt_delim,
            dbt_encoding=args.dbt_encoding,
            report_path=report_path,
            abs_tol=args.abs_tol,
            rel_tol=args.rel_tol,
        )
        sys.exit(0 if ok else 1)
    except (ValueError, FileNotFoundError) as e:
        print(f"Erro: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
