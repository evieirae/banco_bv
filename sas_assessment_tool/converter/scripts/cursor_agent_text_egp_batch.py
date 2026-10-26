from __future__ import annotations

import argparse
import os
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from shutil import which


def _is_gui_cursor_help_blob(blob: str) -> bool:
    """Evita confundir o help do Electron com o CLI `agent`."""
    return "Usage: cursor.exe" in blob and "[options]" in blob


def _probe_agent_cli(exe: Path) -> bool:
    try:
        r = subprocess.run(
            [str(exe), "--version"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    blob = (r.stdout or "") + (r.stderr or "")
    if r.returncode != 0:
        return False
    return not _is_gui_cursor_help_blob(blob)


def _cursor_agent_install_candidates() -> list[Path]:
    """Windows: instalador oficial coloca wrappers em %LOCALAPPDATA%\\cursor-agent\\."""
    local = os.environ.get("LOCALAPPDATA")
    if not local:
        return []
    base = Path(local) / "cursor-agent"
    return [base / "agent.cmd", base / "cursor-agent.cmd"]


def _agent_executable_candidates(cli_override: Path | None) -> list[Path]:
    out: list[Path] = []
    if cli_override is not None:
        out.append(cli_override)
    env_p = os.environ.get("CURSOR_BATCH_AGENT")
    if env_p:
        out.append(Path(env_p))
    out.extend(_cursor_agent_install_candidates())
    for w in (which("agent"), which("cursor-agent"), which("agent.cmd")):
        if w:
            out.append(Path(w))
    home = Path.home()
    out.extend([home / ".local" / "bin" / "agent", home / ".local" / "bin" / "agent.exe"])
    seen: set[str] = set()
    uniq: list[Path] = []
    for p in out:
        key = str(p.resolve()) if p.exists() else str(p)
        if key in seen:
            continue
        seen.add(key)
        uniq.append(p)
    return uniq


def resolve_agent_executable(cli_agent: Path | None) -> Path | None:
    for cand in _agent_executable_candidates(cli_agent):
        if cand.is_file() and _probe_agent_cli(cand):
            return cand
    return None


def run_agent(agent_exe: Path, workspace: Path, prompt: str) -> subprocess.CompletedProcess[str]:
    """O prompt vai por stdin (sem argumento posicional), para nao estourar o limite de linha de comando no Windows.

    Usa ``--output-format text`` para o stdout ser **só a resposta final** (Markdown/texto), nao NDJSON
    de ``stream-json`` (logs de thinking/assistant).

    Nao usar ``-`` como ultimo argv: o wrapper ``agent.cmd`` -> ``cursor-agent.ps1`` pode falhar com
    PSArgumentException (argumento ``name`` invalido) ao repassar ``-`` pelo ``cmd``/PowerShell.
    """
    cmd = [
        str(agent_exe),
        "--trust",
        "--yolo",
        "--workspace",
        str(workspace.resolve()),
        "-p",
        "--output-format",
        "text",
    ]
    return subprocess.run(
        cmd,
        input=prompt,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description=(
            "Lote: template + ficheiros .txt em --input-dir -> respostas em --output-dir "
            "(REPROCES__*), usando o Cursor Agent CLI em modo texto (resposta final, sem NDJSON)."
        )
    )
    p.add_argument(
        "--input-dir",
        type=Path,
        default=Path("text_egps"),
        help="Pasta com .txt (default: text_egps).",
    )
    p.add_argument(
        "--template",
        type=Path,
        default=Path("prompt-egp-excel-csv.txt"),
        help="Ficheiro de instruções (default: prompt-egp-excel-csv.txt).",
    )
    p.add_argument(
        "--output-dir",
        type=Path,
        default=Path("respostas_text_egp"),
        help="Pasta de saída (default: respostas_text_egp).",
    )
    p.add_argument(
        "--workspace",
        type=Path,
        default=Path.cwd(),
        help="Valor de --workspace do Agent CLI (default: diretório atual).",
    )
    p.add_argument(
        "--agent",
        type=Path,
        default=None,
        help="Caminho explícito para agent/agent.cmd (opcional).",
    )
    p.add_argument(
        "--no-skip",
        action="store_true",
        help="Reprocessar mesmo se REPROCES__*.txt já existir.",
    )
    p.add_argument(
        "--jobs",
        type=int,
        default=1,
        metavar="N",
        help="Número de ficheiros .txt a processar em paralelo (default: 1, sequencial).",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    input_dir: Path = args.input_dir
    template_path: Path = args.template
    output_dir: Path = args.output_dir
    workspace: Path = args.workspace
    cli_agent: Path | None = args.agent

    if not template_path.is_file():
        print(f"Template não encontrado: {template_path}", file=sys.stderr)
        return 2
    if not input_dir.is_dir():
        print(f"Pasta de entrada não encontrada: {input_dir}", file=sys.stderr)
        return 2
    if not workspace.is_dir():
        print(f"Workspace não é um diretório: {workspace}", file=sys.stderr)
        return 2

    agent_exe = resolve_agent_executable(cli_agent)
    if agent_exe is None:
        print(
            "Cursor Agent CLI nao encontrado.\n"
            "- Instale: PowerShell: irm 'https://cursor.com/install?win32=true' | iex\n"
            "- Ou passe --agent com o caminho para agent.cmd (tipico: "
            "%LOCALAPPDATA%\\cursor-agent\\agent.cmd).\n"
            "- Variavel de ambiente CURSOR_BATCH_AGENT tambem e aceite.",
            file=sys.stderr,
        )
        return 127

    output_dir.mkdir(parents=True, exist_ok=True)
    template_texto = template_path.read_text(encoding="utf-8")

    arquivos = sorted(f for f in input_dir.iterdir() if f.is_file() and f.suffix == ".txt")

    jobs = max(1, int(args.jobs))
    print_lock = threading.Lock()

    def process_one(path_in: Path) -> None:
        nome_arquivo = path_in.name
        nome_saida = f"REPROCES__{nome_arquivo}"
        caminho_saida = output_dir / nome_saida

        if caminho_saida.exists() and not args.no_skip:
            with print_lock:
                print(f"[SKIP] Pulando: {nome_arquivo}")
            return

        conteudo_ego = path_in.read_text(encoding="utf-8")
        prompt_final = f"{template_texto}\n\n--- CONTEÚDO ---\n{conteudo_ego}"

        with print_lock:
            print(f"[RUN] Processando [{agent_exe}]: {nome_arquivo}...", end=" ", flush=True)

        try:
            processo = run_agent(agent_exe, workspace, prompt_final)
        except OSError as e:
            with print_lock:
                print(f"[FAIL] Falha: {e}")
            return

        resposta = processo.stdout or ""
        if processo.returncode == 0:
            caminho_saida.write_text(resposta, encoding="utf-8")
            with print_lock:
                if "⚠️" in resposta or "Pendente" in resposta or "não mapeada" in resposta.lower():
                    print("[WARN] Sucesso, mas o Agente detectou divergencias!")
                else:
                    print("[OK] Sucesso!")
        else:
            err_tail = (resposta or "(sem saída)")[-4000:]
            with print_lock:
                print(f"[ERR] Erro (exit {processo.returncode}): {err_tail}")
                if "Authentication required" in resposta or "CURSOR_API_KEY" in resposta:
                    login_hint = f'"{agent_exe}" login'
                    print(
                        "[HINT] Autentique o CLI (o Git Bash pode nao ter `agent` no PATH). "
                        f"Ex.: {login_hint}\n"
                        "[HINT] Ou defina a variavel de ambiente CURSOR_API_KEY.",
                        file=sys.stderr,
                    )
                if (
                    "Linha de comando muito longa" in resposta
                    or "command line is too long" in resposta.lower()
                ):
                    print(
                        "[HINT] Prompt demasiado longo para argv: este script ja usa stdin; "
                        "atualize scripts/respostas_text_egp.py ou abra um issue.",
                        file=sys.stderr,
                    )

    if jobs == 1:
        for path_in in arquivos:
            process_one(path_in)
    else:
        with ThreadPoolExecutor(max_workers=jobs) as ex:
            futures = [ex.submit(process_one, p) for p in arquivos]
            for fu in as_completed(futures):
                fu.result()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
