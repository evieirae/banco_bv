#!/usr/bin/env python3
"""
======================================
Conversor em lote .sas7bdat -> CSV
======================================

Le datasets SAS (.sas7bdat) sem precisar de SAS instalado e converte para CSV.
Suporta arquivos gravados com compressao SAS (COMPRESS=CHAR/RLE e
COMPRESS=BINARY/RDC): tanto o pyreadstat (ReadStat, engine primaria) quanto o
leitor embutido do pandas (fallback) descompactam nativamente.

Cascata de tentativas por arquivo (a primeira que funcionar vence):
  1. pyreadstat com encoding automatico (detectado do header do arquivo)
  2. pyreadstat com encoding forcado (--encoding, default latin-1 — WLATIN1 e
     o encoding tipico de instalacoes SAS Windows pt-BR)
  3. pandas.read_sas com encoding inferido
  4. pandas.read_sas com encoding forcado

A leitura e feita em chunks (--chunksize) e o CSV e escrito incrementalmente,
entao tabelas maiores que a RAM funcionam. Cada arquivo vira um .tmp que so e
renomeado para .csv no sucesso — re-rodar o lote retoma de onde parou (arquivos
com .csv ja existente sao pulados, a menos que --overwrite).

Ao final, grava _conversion_report.csv no diretorio de saida com o resultado
por arquivo (status, linhas, colunas, engine/encoding usados, compressao
detectada, duracao, erro). Exit code: 0 = tudo ok, 1 = houve falhas.

Usage:
  venv/bin/python sas7bdat_to_csv.py --input /pasta/com/sas7bdat --output ./saida_csv
  venv/bin/python sas7bdat_to_csv.py --input dados/tabela.sas7bdat --output ./saida_csv
  venv/bin/python sas7bdat_to_csv.py --input /dados --output ./saida --recursive --overwrite
  venv/bin/python sas7bdat_to_csv.py --input /dados --output ./saida --encoding cp1252 --sep ";"
"""

import argparse
import csv
import sys
import time
from pathlib import Path
from typing import Iterator, List, Optional, Tuple

try:
    import pandas as pd
except ImportError:
    print(
        "Missing dependency: pandas. Install with: pip install -r requirements.txt",
        file=sys.stderr,
    )
    raise SystemExit(1)

try:
    import pyreadstat
except ImportError:
    pyreadstat = None  # fallback pandas ainda funciona; avisamos no main()


REPORT_NAME = "_conversion_report.csv"
REPORT_COLUMNS = [
    "arquivo",
    "saida",
    "status",
    "linhas",
    "colunas",
    "engine",
    "encoding",
    "compressao",
    "duracao_s",
    "erro",
]


def find_inputs(input_path: Path, recursive: bool) -> List[Path]:
    if input_path.is_file():
        return [input_path]
    pattern = "**/*.sas7bdat" if recursive else "*.sas7bdat"
    files = sorted(p for p in input_path.glob(pattern) if p.is_file())
    # case-insensitive: cobre .SAS7BDAT vindo de servidores Windows
    upper = "**/*.SAS7BDAT" if recursive else "*.SAS7BDAT"
    for p in sorted(input_path.glob(upper)):
        if p.is_file() and p not in files:
            files.append(p)
    return files


COMPRESSION_LABELS = {
    b"SASYZCRL": "RLE (COMPRESS=CHAR)",
    b"SASYZCR2": "RDC (COMPRESS=BINARY)",
    b"": "nenhuma",
}


def detect_metadata(path: Path) -> Tuple[str, str]:
    """(compressao, file_encoding) lidos do header sas7bdat; '' se indisponivel.

    O metadado do pyreadstat nao expoe compressao; o leitor do pandas expoe a
    assinatura (SASYZCRL/SASYZCR2) direto do header, sem ler os dados.
    """
    try:
        from pandas.io.sas.sas7bdat import SAS7BDATReader

        reader = SAS7BDATReader(str(path))
        try:
            comp = reader.compression or b""
            enc = reader.inferred_encoding or ""
        finally:
            reader.close()
        return COMPRESSION_LABELS.get(comp, comp.decode("ascii", "replace")), str(enc)
    except Exception:
        return "", ""


def chunks_pyreadstat(path: Path, chunksize: int, encoding: Optional[str]) -> Iterator[pd.DataFrame]:
    for df, _meta in pyreadstat.read_file_in_chunks(
        pyreadstat.read_sas7bdat,
        str(path),
        chunksize=chunksize,
        encoding=encoding,
        dates_as_pandas_datetime=True,
    ):
        yield df


def chunks_pandas(path: Path, chunksize: int, encoding: Optional[str]) -> Iterator[pd.DataFrame]:
    reader = pd.read_sas(
        str(path),
        format="sas7bdat",
        chunksize=chunksize,
        encoding=encoding or "infer",
    )
    with reader:
        for df in reader:
            yield df


def header_columns(path: Path, engine: str, encoding: Optional[str]) -> List[str]:
    """Nomes de colunas para tabela com 0 linhas (nenhum chunk emitido)."""
    if engine.startswith("pyreadstat") and pyreadstat is not None:
        _, meta = pyreadstat.read_sas7bdat(str(path), metadataonly=True)
        return list(meta.column_names)
    df = pd.read_sas(str(path), format="sas7bdat", encoding=encoding or "infer")
    return list(df.columns)


def write_csv(
    path: Path,
    out_tmp: Path,
    engine: str,
    chunksize: int,
    encoding: Optional[str],
    sep: str,
    csv_encoding: str,
) -> Tuple[int, int]:
    """Converte um arquivo com uma engine especifica. Retorna (linhas, colunas)."""
    if engine.startswith("pyreadstat"):
        chunk_iter = chunks_pyreadstat(path, chunksize, encoding)
    else:
        chunk_iter = chunks_pandas(path, chunksize, encoding)

    rows = 0
    cols = 0
    wrote_header = False
    for df in chunk_iter:
        df.to_csv(
            out_tmp,
            mode="a" if wrote_header else "w",
            header=not wrote_header,
            index=False,
            sep=sep,
            encoding=csv_encoding,
        )
        wrote_header = True
        rows += len(df)
        cols = len(df.columns)

    if not wrote_header:  # tabela com 0 linhas: grava so o header
        columns = header_columns(path, engine, encoding)
        pd.DataFrame(columns=columns).to_csv(
            out_tmp, index=False, sep=sep, encoding=csv_encoding
        )
        cols = len(columns)
    return rows, cols


def convert_one(
    path: Path,
    out_csv: Path,
    chunksize: int,
    retry_encoding: str,
    sep: str,
    csv_encoding: str,
) -> dict:
    start = time.monotonic()
    compression, file_encoding = detect_metadata(path)
    attempts: List[Tuple[str, Optional[str]]] = []
    if pyreadstat is not None:
        attempts.append(("pyreadstat", None))
        attempts.append((f"pyreadstat[{retry_encoding}]", retry_encoding))
    attempts.append(("pandas", None))
    attempts.append((f"pandas[{retry_encoding}]", retry_encoding))

    out_csv.parent.mkdir(parents=True, exist_ok=True)
    out_tmp = out_csv.with_suffix(out_csv.suffix + ".tmp")
    errors: List[str] = []
    for engine, encoding in attempts:
        try:
            rows, cols = write_csv(
                path, out_tmp, engine, chunksize, encoding, sep, csv_encoding
            )
            out_tmp.replace(out_csv)
            return {
                "status": "ok",
                "linhas": rows,
                "colunas": cols,
                "engine": engine,
                "encoding": encoding or (file_encoding or "auto"),
                "compressao": compression,
                "duracao_s": round(time.monotonic() - start, 2),
                "erro": "",
            }
        except Exception as exc:  # noqa: BLE001 — cascata de engines, erro vai pro relatorio
            errors.append(f"{engine}: {type(exc).__name__}: {exc}")
            out_tmp.unlink(missing_ok=True)

    return {
        "status": "erro",
        "linhas": "",
        "colunas": "",
        "engine": "",
        "encoding": "",
        "compressao": compression,
        "duracao_s": round(time.monotonic() - start, 2),
        "erro": " | ".join(errors),
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Converte .sas7bdat (inclusive com compressao SAS) para CSV, em lote."
    )
    parser.add_argument("--input", "-i", required=True, help="Arquivo .sas7bdat ou diretorio com eles")
    parser.add_argument("--output", "-o", required=True, help="Diretorio de saida dos CSVs")
    parser.add_argument(
        "--encoding",
        default="latin-1",
        help="Encoding forcado nas tentativas de retry (default: latin-1 / WLATIN1)",
    )
    parser.add_argument("--chunksize", type=int, default=100_000, help="Linhas por chunk (default: 100000)")
    parser.add_argument("--sep", default=",", help="Separador do CSV de saida (default: ,)")
    parser.add_argument(
        "--csv-encoding",
        default="utf-8-sig",
        help="Encoding do CSV de saida (default: utf-8-sig, abre certo no Excel)",
    )
    parser.add_argument("--overwrite", action="store_true", help="Reconverte mesmo se o CSV ja existir")
    parser.add_argument("--recursive", action="store_true", help="Desce subdiretorios do --input")
    args = parser.parse_args()

    input_path = Path(args.input)
    output_dir = Path(args.output)
    if not input_path.exists():
        parser.error(f"--input nao existe: {input_path}")
    if pyreadstat is None:
        print(
            "AVISO: pyreadstat nao instalado — usando apenas o leitor do pandas "
            "(mais lento). Instale com: pip install pyreadstat",
            file=sys.stderr,
        )

    files = find_inputs(input_path, args.recursive)
    if not files:
        print(f"Nenhum .sas7bdat encontrado em {input_path}", file=sys.stderr)
        return 1

    root = input_path if input_path.is_dir() else input_path.parent
    output_dir.mkdir(parents=True, exist_ok=True)
    report_rows: List[dict] = []
    failures = 0
    skipped = 0
    for n, path in enumerate(files, 1):
        rel = path.relative_to(root).with_suffix(".csv")
        out_csv = output_dir / rel
        if out_csv.exists() and not args.overwrite:
            skipped += 1
            print(f"[{n}/{len(files)}] pulado (ja existe): {rel}")
            report_rows.append(
                {"arquivo": str(path), "saida": str(out_csv), "status": "pulado",
                 "linhas": "", "colunas": "", "engine": "", "encoding": "",
                 "compressao": "", "duracao_s": "", "erro": ""}
            )
            continue
        print(f"[{n}/{len(files)}] convertendo {path.name} ...", flush=True)
        result = convert_one(
            path, out_csv, args.chunksize, args.encoding, args.sep, args.csv_encoding
        )
        result = {"arquivo": str(path), "saida": str(out_csv), **result}
        report_rows.append(result)
        if result["status"] == "erro":
            failures += 1
            print(f"    ERRO: {result['erro']}", file=sys.stderr)
        else:
            print(
                f"    ok: {result['linhas']} linhas x {result['colunas']} colunas "
                f"({result['engine']}, {result['duracao_s']}s)"
            )

    report_path = output_dir / REPORT_NAME
    with report_path.open("w", newline="", encoding="utf-8-sig") as fh:
        writer = csv.DictWriter(fh, fieldnames=REPORT_COLUMNS)
        writer.writeheader()
        writer.writerows(report_rows)

    ok = len(files) - failures - skipped
    print(
        f"\nConcluido: {ok} convertidos, {skipped} pulados, {failures} com erro. "
        f"Relatorio: {report_path}"
    )
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
