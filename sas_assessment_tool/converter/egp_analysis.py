import os
import zipfile
import re

# --- CONFIGURAÇÃO ---
DIRETORIO_ORIGEM = './egps'  # Onde estão os arquivos .egp
DIRETORIO_DESTINO = './saida_tasks' # Onde os .txt serão salvos

# Configuração de Estimativa de Horas (Sua solicitação)
HORAS_POR_TAMANHO = {
    'P': 6,
    'M': 8,
    'G': 12,
    'GG': 16
}

# Palavras-chave para pontuar complexidade
KEYWORDS = {
    'PROC SQL': {'peso': 2, 'desc': 'Queries SQL'},
    'MERGE': {'peso': 3, 'desc': 'Joins/Merges'},
    'DATA': {'peso': 1, 'desc': 'Data Steps'},
    '%MACRO': {'peso': 5, 'desc': 'Macros (Complexidade Alta)'},
    'DO ': {'peso': 3, 'desc': 'Loops/Iterações'},
    'RETAIN': {'peso': 2, 'desc': 'Lógica de Retenção'},
    'TRANSPOSE': {'peso': 2, 'desc': 'Pivotagem de dados'}
}

def analisar_conteudo_arquivo(conteudo_texto):
    """
    Analisa uma string de texto (código SAS) e retorna métricas.
    """
    stats = {
        'linhas_codigo': 0,
        'ocorrencias': {k: 0 for k in KEYWORDS.keys()},
        'score_complexidade': 0
    }
    
    # 1. Contar linhas (ignorando vazias)
    linhas = [L for L in conteudo_texto.split('\n') if L.strip() != '']
    stats['linhas_codigo'] = len(linhas)
    
    # 2. Buscar palavras-chave (Case insensitive)
    conteudo_upper = conteudo_texto.upper()
    for key, info in KEYWORDS.items():
        count = len(re.findall(re.escape(key), conteudo_upper))
        stats['ocorrencias'][key] += count
        stats['score_complexidade'] += (count * info['peso'])
        
    return stats

def processar_egp(caminho_arquivo):
    """
    Abre o EGP como ZIP e varre os arquivos internos.
    """
    resumo_geral = {
        'nome_arquivo': os.path.basename(caminho_arquivo),
        'total_linhas': 0,
        'qtd_tasks_programas': 0,
        'score_total': 0,
        'detalhes_keywords': {k: 0 for k in KEYWORDS.keys()}
    }
    
    try:
        if not zipfile.is_zipfile(caminho_arquivo):
            return "ERRO: O arquivo não é um formato ZIP válido."

        with zipfile.ZipFile(caminho_arquivo, 'r') as z:
            for file_info in z.infolist():
                if file_info.filename.endswith(('.sas', '.xml', '.txt', '.log')):
                    with z.open(file_info) as f:
                        try:
                            conteudo = f.read().decode('utf-8', errors='ignore')
                            if 'PROC ' in conteudo.upper() or 'DATA ' in conteudo.upper():
                                stats_arquivo = analisar_conteudo_arquivo(conteudo)
                                if stats_arquivo['linhas_codigo'] > 5:
                                    resumo_geral['qtd_tasks_programas'] += 1
                                    resumo_geral['total_linhas'] += stats_arquivo['linhas_codigo']
                                    resumo_geral['score_total'] += stats_arquivo['score_complexidade']
                                    for k, v in stats_arquivo['ocorrencias'].items():
                                        resumo_geral['detalhes_keywords'][k] += v
                        except Exception:
                            continue
        return resumo_geral
    except Exception as e:
        return f"ERRO CRÍTICO: {str(e)}"

def gerar_relatorio_txt(dados, dir_destino):
    nome_txt = os.path.splitext(dados['nome_arquivo'])[0] + "_resumo.txt"
    caminho_txt = os.path.join(dir_destino, nome_txt)
    
    # --- Lógica de Classificação e Horas ---
    tamanho = "P"
    if dados['score_total'] > 50: tamanho = "M"
    if dados['score_total'] > 150: tamanho = "G"
    if dados['score_total'] > 300: tamanho = "GG"
    
    horas_estimadas = HORAS_POR_TAMANHO[tamanho]
    # ---------------------------------------

    linhas_relatorio = [
        f"=== RESUMO AUTOMÁTICO DE MIGRAÇÃO ===",
        f"Arquivo: {dados['nome_arquivo']}",
        f"-------------------------------------",
        f"Classificação:      {tamanho}",
        f"Estimativa Horas:   {horas_estimadas}h",
        f"Score Complexidade: {dados['score_total']}",
        f"",
        f"--- Volumetria ---",
        f"Tasks/Programas Detectados: {dados['qtd_tasks_programas']}",
        f"Linhas de Código (Aprox):   {dados['total_linhas']}",
        f"",
        f"--- Detalhes Técnicos ---",
    ]
    
    for k, v in dados['detalhes_keywords'].items():
        if v > 0:
            linhas_relatorio.append(f"{KEYWORDS[k]['desc']} ({k}): {v}")
            
    if dados['detalhes_keywords']['%MACRO'] > 0:
        linhas_relatorio.append("\n[!] ALERTA: Macros detectadas. Considere adicionar buffer de risco.")

    with open(caminho_txt, 'w', encoding='utf-8') as f:
        f.write('\n'.join(linhas_relatorio))

def main():
    if not os.path.exists(DIRETORIO_ORIGEM):
        os.makedirs(DIRETORIO_ORIGEM)
        print(f"Diretório '{DIRETORIO_ORIGEM}' criado.")
        return

    if not os.path.exists(DIRETORIO_DESTINO):
        os.makedirs(DIRETORIO_DESTINO)

    arquivos = [f for f in os.listdir(DIRETORIO_ORIGEM) if f.lower().endswith('.egp')]
    print(f"Encontrados {len(arquivos)} arquivos EGP. Iniciando...\n")
    
    for arq in arquivos:
        print(f"Processando: {arq}...")
        resultado = processar_egp(os.path.join(DIRETORIO_ORIGEM, arq))
        
        if isinstance(resultado, str):
            with open(os.path.join(DIRETORIO_DESTINO, arq + "_ERRO.txt"), 'w') as f:
                f.write(resultado)
        else:
            gerar_relatorio_txt(resultado, DIRETORIO_DESTINO)

    print(f"\nConcluído! Verifique a pasta '{DIRETORIO_DESTINO}'.")

if __name__ == "__main__":
    main()