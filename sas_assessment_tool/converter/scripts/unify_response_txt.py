import os
import csv
import re
import unicodedata

# --- CONFIGURAÇÕES ---
PASTA_RESPOSTAS = './respostas_text_egp'
ARQUIVO_CSV_SAIDA = 'mapeamento_projetos.csv'


def normalizar_para_comparacao(texto):
    texto_sem_acentos = unicodedata.normalize('NFKD', texto)
    texto_sem_acentos = ''.join(c for c in texto_sem_acentos if not unicodedata.combining(c))
    return texto_sem_acentos.lower().strip()


def limpar_titulo_saida(linha):
    titulo = re.sub(r'^\s*#{2,6}\s*', '', linha).strip()

    match_negrito = re.match(r'^\*\*(.*?)\*\*(?:\s*\(.*\))?\s*$', titulo)
    if match_negrito:
        titulo = match_negrito.group(1)

    return titulo.strip().strip('`')


def deve_ignorar_titulo(titulo):
    titulo_normalizado = normalizar_para_comparacao(titulo)

    if not titulo_normalizado or titulo_normalizado == '**':
        return True

    prefixos_ignorados = (
        'area:',
        'projeto (arquivo .egp):',
        'observacao',
        'observacoes',
        'nota',
        'esclarecimento',
        '---',
    )

    if any(titulo_normalizado.startswith(prefixo) for prefixo in prefixos_ignorados):
        return True

    return (
        titulo_normalizado == 'resumo'
        or titulo_normalizado.startswith('resumo para ')
        or titulo_normalizado.startswith('resumo de ')
    )


def linha_eh_titulo_saida(linha):
    linha_limpa = linha.strip()

    if re.match(r'^#{2,6}\s+\S+', linha_limpa):
        return True

    return bool(re.match(r'^\*\*.+\*\*\s*$', linha_limpa))


def extrair_blocos_documentacao(trecho_documentacao):
    blocos = []
    titulo_atual = None
    texto_atual = []
    capturando_texto = False

    def fechar_bloco():
        nonlocal titulo_atual, texto_atual, capturando_texto

        if titulo_atual and texto_atual and not deve_ignorar_titulo(titulo_atual):
            blocos.append((titulo_atual, ' '.join(texto_atual).strip()))

        texto_atual = []
        capturando_texto = False

    for linha in trecho_documentacao.split('\n'):
        linha_limpa = linha.strip()

        if linha_limpa == '---':
            fechar_bloco()
            titulo_atual = None
            continue

        texto_match = re.match(r'^\*\*Texto para Excel:\*\*\s*(.*)', linha_limpa)
        if texto_match and titulo_atual:
            capturando_texto = True
            texto_atual.append(texto_match.group(1).strip())
            continue

        if linha_eh_titulo_saida(linha_limpa):
            fechar_bloco()
            titulo = limpar_titulo_saida(linha_limpa)
            titulo_atual = None if deve_ignorar_titulo(titulo) else titulo
            continue

        if capturando_texto and linha_limpa:
            texto_atual.append(linha_limpa)

    fechar_bloco()
    return blocos

def extrair_dados_para_csv():
    dados_finais = []
    
    # Lista arquivos e ordena
    arquivos = sorted([f for f in os.listdir(PASTA_RESPOSTAS) if f.endswith('.txt')])
    
    if not arquivos:
        print("Nenhum arquivo encontrado na pasta de respostas.")
        return

    print(f"Lendo {len(arquivos)} arquivos para extração...")

    for nome_arquivo in arquivos:
        caminho = os.path.join(PASTA_RESPOSTAS, nome_arquivo)
        with open(caminho, 'r', encoding='utf-8-sig') as f:
            conteudo = f.read()
        
        # Normaliza quebras de linha
        conteudo = conteudo.replace('\r\n', '\n')

        # 1. Isolar apenas a seção de DOCUMENTAÇÃO EXCEL
        # Isso evita que o "Relatório de Integridade" suje a extração
        partes = conteudo.split('--- DOCUMENTAÇÃO EXCEL ---')
        if len(partes) < 2:
            print(f"Aviso: Seção de documentação não encontrada em {nome_arquivo}. Pulando...")
            continue
        
        trecho_documentacao = partes[1]

        # 2. Extrair Área e Projeto (buscamos no documento todo para garantir)
        area_match = re.search(r'\*\*Área:\*\*\s*(.*)', conteudo)
        area_projeto = area_match.group(1).strip() if area_match else "Não Identificado"

        projeto_match = re.search(r'\*\*Projeto \(Arquivo \.EGP\):\*\*\s*(.*)', conteudo)
        nome_projeto = projeto_match.group(1).strip() if projeto_match else "Não Identificado"

        # 3. Extrair os blocos de tabelas dentro do trecho isolado
        padrao_bloco = extrair_blocos_documentacao(trecho_documentacao)

        for tabela, texto in padrao_bloco:
            # Limpeza de ruído e espaços
            tabela_limpa = tabela.strip().replace('\n', ' ')
            texto_limpo = texto.strip().replace('\n', ' ')
            
            # Evita capturar "Área" ou "Projeto" como nome de tabela caso o regex escape
            if tabela_limpa.lower() in ['área:', 'projeto (arquivo .egp):']:
                continue

            dados_finais.append({
                'Texto para Excel': texto_limpo,
                'Tabela': tabela_limpa,
                'Projeto': nome_projeto,
                'Área': area_projeto,
            })

    # 4. Salvar em CSV
    if dados_finais:
        with open(ARQUIVO_CSV_SAIDA, 'w', newline='', encoding='utf-8-sig') as f_csv:
            colunas = ['Texto para Excel', 'Tabela', 'Projeto', 'Área']
            # Delimitador ';' para facilitar abertura direta no Excel BR
            writer = csv.DictWriter(f_csv, fieldnames=colunas, delimiter=';')
            
            writer.writeheader()
            writer.writerows(dados_finais)

        print(f"Sucesso! {len(dados_finais)} linhas geradas no arquivo: {ARQUIVO_CSV_SAIDA}")
    else:
        print("Nenhuma linha de dados foi extraída.")

if __name__ == "__main__":
    extrair_dados_para_csv()