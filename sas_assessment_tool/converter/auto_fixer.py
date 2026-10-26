import subprocess
import sys
import os

def run_command(command):
    """Executa um comando no terminal e retorna o código de saída e o output."""
    process = subprocess.Popen(
        command, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE
    )
    stdout, stderr = process.communicate()
    return process.returncode, stdout.decode('utf-8'), stderr.decode('utf-8')

def audit_and_fix(target_path):
    print(f"\n🔍 [1/3] Iniciando Auditoria (Lint) em: {target_path}")
    
    # 1. Primeiro Lint
    lint_code, lint_out, _ = run_command(f"sqlfluff lint {target_path} --dialect bigquery")
    
    if lint_code == 0:
        print("✅ Código perfeito! Nenhuma correção necessária.")
        return True

    print(f"⚠️  Problemas encontrados. Iniciando Auto-Fix...")
    
    # 2. Executa o Fix (Força a correção sem pedir confirmação com --force)
    fix_code, _, fix_err = run_command(f"sqlfluff fix {target_path} --dialect bigquery --force")
    
    if fix_code != 0:
        print(f"❌ Erro crítico ao tentar corrigir automaticamente:\n{fix_err}")
        return False
    
    print("🛠️  Correções aplicadas.")

    # 3. Lint de Verificação Final
    print(f"🔍 [3/3] Verificando novamente...")
    final_lint_code, final_out, _ = run_command(f"sqlfluff lint {target_path} --dialect bigquery")
    
    if final_lint_code == 0:
        print("✅ Sucesso! O código agora está limpo e padronizado.")
        return True
    else:
        print("⚠️  Ainda restam alguns avisos manuais:")
        print(final_out)
        return False

if __name__ == "__main__":
    # Pega o caminho passado como argumento ou usa o diretório 'models' como padrão
    target_dir = sys.argv[1] if len(sys.argv) > 1 else "models"
    
    if not os.path.exists(target_dir):
        print(f"Diretório {target_dir} não encontrado. Nada a fazer.")
        sys.exit(0)
        
    audit_and_fix(target_dir)