import subprocess
import sys
import os

def run_command(command, cwd=None):
    """Executa um comando no terminal e retorna o código de saída e o output."""
    process = subprocess.Popen(
        command,
        shell=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=cwd,
    )
    stdout, stderr = process.communicate()
    return (
        process.returncode,
        stdout.decode('utf-8', errors='replace'),
        stderr.decode('utf-8', errors='replace'),
    )

def audit_and_fix(target_path):
    py = sys.executable
    abs_target = os.path.abspath(target_path)
    sqlfluff_cwd = None
    sqlfluff_path_arg = abs_target
    if os.path.basename(abs_target) == "models":
        parent_dir = os.path.dirname(abs_target)
        if os.path.isfile(os.path.join(parent_dir, ".sqlfluff")):
            sqlfluff_cwd = parent_dir
            sqlfluff_path_arg = "models"
    print(f"\n[1/3] Iniciando Auditoria (Lint) em: {target_path}")
    
    # 1. Primeiro Lint
    lint_code, lint_out, _ = run_command(
        f'"{py}" -m sqlfluff lint "{sqlfluff_path_arg}" --dialect bigquery',
        cwd=sqlfluff_cwd,
    )
    
    if lint_code == 0:
        print("[OK] Codigo perfeito! Nenhuma correcao necessaria.")
        return True

    print("[AVISO] Problemas encontrados. Iniciando Auto-Fix...")
    
    # 2. Executa o Fix (Força a correção sem pedir confirmação com --force)
    fix_code, _, fix_err = run_command(
        f'"{py}" -m sqlfluff fix "{sqlfluff_path_arg}" --dialect bigquery',
        cwd=sqlfluff_cwd,
    )
    
    if fix_code != 0:
        print(f"[ERRO] Falha ao corrigir automaticamente:\n{fix_err}")
        return False
    
    print("[OK] Correcoes aplicadas.")

    # 3. Lint de Verificação Final
    print("[3/3] Verificando novamente...")
    final_lint_code, final_out, _ = run_command(
        f'"{py}" -m sqlfluff lint "{sqlfluff_path_arg}" --dialect bigquery',
        cwd=sqlfluff_cwd,
    )
    
    if final_lint_code == 0:
        print("[OK] Sucesso! O codigo agora esta limpo e padronizado.")
        return True
    else:
        print("[AVISO] Ainda restam alguns avisos manuais:")
        print(final_out)
        return False

if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(errors="replace")
    # Pega o caminho passado como argumento ou usa o diretório 'models' como padrão
    target_dir = sys.argv[1] if len(sys.argv) > 1 else "models"
    
    if not os.path.exists(target_dir):
        print(f"Diretório {target_dir} não encontrado. Nada a fazer.")
        sys.exit(0)
        
    audit_and_fix(target_dir)