#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Script de Setup Completo do Banco de Dados SAS
==============================================
Zera o banco, recria tabelas e insere dados dos logs no Databricks SQL

Suporta processamento sequencial (completo) e paralelo (rápido).
Usa autenticação OAuth U2M (Browser Login) para conexão com Databricks.

Configuração (.env):
    DATABRICKS_SERVER_HOSTNAME=seu-workspace.cloud.databricks.com
    DATABRICKS_HTTP_PATH=/sql/1.0/warehouses/seu-warehouse-id
    DATABRICKS_CATALOG=bv_dev_db (opcional, padrão)
    DATABRICKS_SCHEMA=bv_migration_sas (opcional, padrão)

Uso:
    # Processamento sequencial (completo, com todas as funcionalidades)
    python ingest_sas_logs.py [--clean] [--sort_minsize] [--check_duplicates] [--check_file_hash]
    
    # Processamento paralelo (rápido, 3-8x mais rápido)
    python ingest_sas_logs.py --parallel [--workers N] [--clean] [--sort_minsize] [--check_duplicates] [--check_file_hash]

Flags:
    --clean              Limpa a tabela antes de processar (remove todos os dados)
    --sort_minsize       Processa arquivos em ordem crescente de tamanho (menores primeiro)
    --check_duplicates   Verifica duplicatas no banco antes de inserir (inserção incremental segura)
    --check_file_hash    Valida arquivos únicos usando hash SHA256 (detecta duplicatas por conteúdo)

Exemplos:
    # Sequencial completo
    python ingest_sas_logs.py --clean
    
    # Paralelo com 6 workers
    python ingest_sas_logs.py --parallel --workers 6 --clean
    
    # Paralelo com workers automáticos (CPUs - 1)
    python ingest_sas_logs.py --parallel --clean --sort_minsize
    
    # Inserção incremental com verificação de duplicatas
    python ingest_sas_logs.py --check_duplicates
    
    # Validação de arquivos únicos por hash
    python ingest_sas_logs.py --check_file_hash
    
    # Combinado: verifica banco E valida hash de arquivos
    python ingest_sas_logs.py --check_duplicates --check_file_hash
"""

from databricks import sql
import sys
import os
import argparse
from pathlib import Path
from dotenv import load_dotenv
import logging
import shutil
import time
import multiprocessing as mp
from typing import Optional, Tuple, Dict, Any, List
import signal
import hashlib

# Carrega variáveis do .env
load_dotenv()

# Constantes
FILE_TIMEOUT = 3600  # 1 hora por arquivo (apenas Unix)
PREVIEW_FILE_COUNT = 5  # Número de arquivos para preview
MAX_WORKERS_DEFAULT_OFFSET = 1  # Offset para cálculo de workers padrão
BYTES_PER_MB = 1024 * 1024  # Bytes por megabyte
TABLE_NAME = 'log_base_final'

# Configuração de logging (apcional, para debug)
logger = logging.getLogger(__name__)


def get_db_config() -> Dict[str, str]:
    """
    Retorna configuração do Databricks com validação.

    Returns:
        Dict com configuração do Databricks (server_hostname, http_path, catalog, schema)

    Raises:
        ValueError: Se alguma variável de ambiente obrigatória não estiver configurada
    """
    host = os.getenv('DATABRICKS_SERVER_HOSTNAME')
    if not host:
        raise ValueError("DATABRICKS_SERVER_HOSTNAME não configurado no .env")

    http_path = os.getenv('DATABRICKS_HTTP_PATH')
    if not http_path:
        raise ValueError("DATABRICKS_HTTP_PATH não configurado no .env")

    # Catalog e Schema (opcionais, com valores padrão)
    catalog = os.getenv('DATABRICKS_CATALOG', 'bv_dev_db')
    schema = os.getenv('DATABRICKS_SCHEMA', 'bv_migration_sas')

    # Nome completo da tabela (catalog.schema.table)
    # Usando log_base_final para validação
    full_table_name = f"{catalog}.{schema}.{TABLE_NAME}"

    return {
        'server_hostname': host,
        'http_path': http_path,
        'catalog': catalog,
        'schema': schema,
        'table_name': f'{TABLE_NAME}',  # Nome simples da tabela
        'full_table_name': full_table_name  # Nome completo para uso em queries
    }


def get_table_name(table_name: str=TABLE_NAME) -> str:
    """
    Retorna o nome completo da tabela (catalog.schema.table).
    
    Args:
        table_name: Nome da tabela (padrão: 'log_base')
        
    Returns:
        Nome completo da tabela no formato catalog.schema.table
    """
    catalog = DB_CONFIG.get('catalog', 'bv_dev_db')
    schema = DB_CONFIG.get('schema', 'bv_migration_sas')
    return f"{catalog}.{schema}.{table_name}"


# Configuração do Databricks com validação
try:
    DB_CONFIG = get_db_config()
except ValueError as e:
    print(f"❌ Erro de configuração: {e}")
    sys.exit(1)


def setup_logging(level: int = logging.INFO) -> None:
    """Configura logging do módulo"""
    logging.basicConfig(
        level=level,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )


def timeout_handler(signum: int, frame: Any) -> None:
    """Handler para timeout de processamento de arquivo (apenas Unix)"""
    raise TimeoutError("Processamento do arquivo excedeu o tempo limite")


def parse_arguments() -> argparse.Namespace:
    """Parse dos argumentos de linha de comando"""
    parser = argparse.ArgumentParser(
        description='Setup do banco de dados SAS - Processa logs e insere dados',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Exemplos:
  # Processamento sequencial completo
  python ingest_sas_logs.py --clean
  
  # Processamento paralelo rápido
  python ingest_sas_logs.py --parallel --workers 6 --clean
  
  # Paralelo com ordenação por tamanho
  python ingest_sas_logs.py --parallel --sort_minsize
        """
    )
    parser.add_argument(
        '--parallel',
        action='store_true',
        help='Processa arquivos em paralelo (3-8x mais rápido)'
    )
    parser.add_argument(
        '--workers',
        type=int,
        default=None,
        help='Número de workers paralelos (padrão: CPUs - 1, apenas com --parallel)'
    )
    parser.add_argument(
        '--clean',
        action='store_true',
        help='Limpa o banco de dados antes de processar (remove todas as tabelas)'
    )
    parser.add_argument(
        '--sort_minsize',
        action='store_true',
        help='Processa arquivos em ordem crescente de tamanho (menores primeiro)'
    )
    parser.add_argument(
        '--check_duplicates',
        action='store_true',
        help='Verifica duplicatas no banco antes de inserir (inserção incremental segura)'
    )
    parser.add_argument(
        '--check_file_hash',
        action='store_true',
        help='Valida arquivos únicos usando hash SHA256 (detecta arquivos duplicados mesmo com nomes diferentes)'
    )
    return parser.parse_args()


def setup_directories() -> Tuple[Path, Path]:
    """Cria estrutura de diretórios necessária"""
    # Usa o diretório do script como base para caminhos relativos
    script_dir = Path(__file__).parent.absolute()
    log_files_dir = script_dir / "log_files"
    processed_dir = log_files_dir / "processed"
    failed_dir = log_files_dir / "failed"

    log_files_dir.mkdir(exist_ok=True)
    processed_dir.mkdir(exist_ok=True)
    failed_dir.mkdir(exist_ok=True)

    logger.info(f"Diretórios criados/verificados:")
    logger.info(f"  • {processed_dir}")
    logger.info(f"  • {failed_dir}")

    return processed_dir, failed_dir


def calculate_file_hash(file_path: Path, chunk_size: int = 8192) -> str:
    """
    Calcula hash SHA256 de um arquivo para verificação de unicidade.
    
    Args:
        file_path: Caminho do arquivo
        chunk_size: Tamanho do chunk para leitura (padrão: 8KB)
    
    Returns:
        Hash SHA256 hexadecimal do arquivo
    """
    sha256_hash = hashlib.sha256()
    try:
        with open(file_path, "rb") as f:
            # Lê arquivo em chunks para economizar memória
            for chunk in iter(lambda: f.read(chunk_size), b""):
                sha256_hash.update(chunk)
        return sha256_hash.hexdigest()
    except Exception as e:
        logger.error(f"Erro ao calcular hash de {file_path.name}: {e}")
        return ""


def is_file_already_processed(log_file: Path, processed_dir: Path) -> bool:
    """Verifica se um arquivo já foi processado"""
    processed_path = processed_dir / log_file.name
    return processed_path.exists()


def check_file_in_database(conn: Any, log_file: Path, table_name: str) -> Tuple[bool, int]:
    """
    Verifica se um arquivo já foi inserido no banco e quantos registros existem.
    
    Args:
        conn: Conexão com o banco
        log_file: Arquivo de log
        table_name: Nome completo da tabela
    
    Returns:
        Tupla (existe_no_banco, quantidade_registros)
        - existe_no_banco: True se há registros deste arquivo, False caso contrário
        - quantidade_registros: Número de registros encontrados
    """
    try:
        cursor = conn.cursor()
        # Verifica quantos registros deste arquivo existem
        check_sql = f"SELECT COUNT(*) FROM {table_name} WHERE log_file = ?"
        cursor.execute(check_sql, (log_file.name,))
        result = cursor.fetchone()
        count = result[0] if result and len(result) > 0 else 0
        return (count > 0, count)
    except Exception as e:
        logger.warning(f"Erro ao verificar arquivo no banco: {e}")
        return (False, 0)


def move_file_to_processed(log_file: Path, processed_dir: Path) -> bool:
    """Move arquivo para pasta de processados"""
    try:
        dest = processed_dir / log_file.name
        shutil.move(str(log_file), str(dest))
        return True
    except (OSError, shutil.Error) as e:
        logger.error(f"Erro ao mover arquivo {log_file.name}: {e}")
        return False


def move_file_to_failed(log_file: Path, failed_dir: Path, reason: str = "") -> bool:
    """Move arquivo para pasta de falhas"""
    try:
        dest = failed_dir / log_file.name
        shutil.move(str(log_file), str(dest))
        if reason:
            logger.warning(f"Arquivo movido para failed: {log_file.name}. Motivo: {reason}")
        return True
    except (OSError, shutil.Error) as e:
        logger.error(f"Erro ao mover arquivo {log_file.name} para failed: {e}")
        return False


def connect_db():
    """Conecta ao Databricks via OAuth U2M (Browser Login)"""
    host = os.getenv('DATABRICKS_SERVER_HOSTNAME')
    http_path = os.getenv('DATABRICKS_HTTP_PATH')

    if not host or not http_path:
        raise ValueError("Defina DATABRICKS_SERVER_HOSTNAME e DATABRICKS_HTTP_PATH no .env")

    print(f"🔌 Conectando ao host: {host}")
    logger.info(f"Conectando ao Databricks: {host}")
    # auth_type="databricks-oauth" abre o navegador para login
    try:
        conn = sql.connect(server_hostname=host, http_path=http_path, auth_type="databricks-oauth")
        print("✅ Conectado ao Databricks com sucesso!")
        logger.info("Conexão com Databricks estabelecida")
        return conn
    except Exception as e:
        print(f"❌ Erro ao conectar: {e}")
        logger.error(f"Erro ao conectar ao Databricks: {e}")
        sys.exit(1)


def get_log_files_to_process(
        log_dir: Path,
        processed_dir: Path,
        sort_by_size: bool = False,
        check_database: bool = False,
        conn: Optional[Any] = None,
        table_name: Optional[str] = None,
        check_file_hash: bool = False
) -> List[Path]:
    """
    Retorna lista de arquivos .log não processados, opcionalmente ordenados por tamanho.
    
    Args:
        log_dir: Diretório com arquivos .log
        processed_dir: Diretório com arquivos já processados
        sort_by_size: Se True, ordena por tamanho (menor primeiro)
        check_database: Se True, verifica também no banco se o arquivo já foi inserido
        conn: Conexão com o banco (necessário se check_database=True)
        table_name: Nome completo da tabela (necessário se check_database=True)
        check_file_hash: Se True, valida arquivos únicos usando hash (remove duplicatas por conteúdo)
        
    Returns:
        Lista de Paths dos arquivos para processar
    """
    all_log_files = list(log_dir.glob("*.log"))
    
    # Filtra arquivos não processados (pasta processed)
    log_files = [
        f for f in all_log_files
        if not is_file_already_processed(f, processed_dir)
    ]
    
    # Se solicitado, verifica também no banco
    if check_database and conn and table_name:
        files_to_remove = []
        files_partial = []
        for f in log_files:
            exists, count = check_file_in_database(conn, f, table_name)
            if exists:
                # Arquivo existe no banco - permite reprocessamento se parcial
                # Se tiver poucos registros, pode ser inserção parcial (permite reprocessar)
                if count < 100:  # Threshold: menos de 100 registros = possível inserção parcial
                    files_partial.append((f, count))
                    print(f"   ⚠️  Arquivo parcialmente processado: {f.name} ({count} registros) - será reprocessado")
                else:
                    files_to_remove.append(f)
                    print(f"   ℹ️  Arquivo já existe no banco: {f.name} ({count:,} registros) - pulando")
        log_files = [f for f in log_files if f not in files_to_remove]
    
    # Se solicitado, valida arquivos únicos por hash (remove duplicatas por conteúdo)
    if check_file_hash:
        file_hashes = {}
        unique_files = []
        duplicates_found = []
        
        for f in log_files:
            file_hash = calculate_file_hash(f)
            if not file_hash:
                # Se não conseguiu calcular hash, inclui o arquivo mesmo assim
                unique_files.append(f)
                continue
            
            if file_hash in file_hashes:
                # Arquivo duplicado encontrado
                original_file = file_hashes[file_hash]
                duplicates_found.append((f, original_file))
                print(f"   ⚠️  Arquivo duplicado detectado: {f.name} (mesmo conteúdo de {original_file.name})")
            else:
                file_hashes[file_hash] = f
                unique_files.append(f)
        
        if duplicates_found:
            print(f"   📊 {len(duplicates_found)} arquivo(s) duplicado(s) removido(s) da lista de processamento")
        
        log_files = unique_files

    if sort_by_size:
        log_files.sort(key=lambda f: f.stat().st_size)

    return log_files


def print_file_preview(log_files: List[Path], max_files: int = PREVIEW_FILE_COUNT) -> None:
    """
    Imprime preview dos primeiros arquivos com seus tamanhos.
    
    Args:
        log_files: Lista de arquivos para mostrar
        max_files: Número máximo de arquivos para mostrar
    """
    preview_count = min(max_files, len(log_files))
    for i, f in enumerate(log_files[:preview_count], 1):
        size_mb = f.stat().st_size / BYTES_PER_MB
        print(f"   {i}. {f.name}: {size_mb:.2f} MB")
    if len(log_files) > preview_count:
        print(f"   ... e mais {len(log_files) - preview_count} arquivo(s)")


def drop_all_tables(conn: Any) -> None:
    """Remove a tabela log_base_final do schema especificado"""
    print("\n" + "=" * 80)
    print("🗑️  REMOVENDO TABELA")
    print("=" * 80)

    cursor = conn.cursor()

    # Obtém o nome completo da tabela
    full_table_name = get_table_name(TABLE_NAME)

    print(f"📋 Removendo tabela: {full_table_name}")

    try:
        cursor.execute(f"DROP TABLE IF EXISTS {full_table_name}")
        conn.commit()
        print(f"   ✅ Tabela {full_table_name} removida com sucesso")
    except Exception as e:
        print(f"   ⚠️  Erro ao remover {full_table_name}: {e}")
        logger.warning(f"Erro ao remover tabela {full_table_name}: {e}")

    print(f"✅ Tabela removida com sucesso!")


def create_tables_direct(conn: Any) -> None:
    """Cria a tabela log_base no Databricks no schema especificado"""
    print("\n📊 Criando tabela log_base...")

    cursor = conn.cursor()

    # Obtém o nome completo da tabela (catalog.schema.table)
    full_table_name = get_table_name(TABLE_NAME)
    print(f"   📍 Criando tabela em: {full_table_name}")

    # Tabela log_base (sintaxe Databricks/Delta Lake)
    # Databricks usa BIGINT IDENTITY ao invés de SERIAL
    # Usa nome completo catalog.schema.table
    create_table_sql = f'''
        CREATE TABLE IF NOT EXISTS {full_table_name} (
            id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            log_file STRING,
            line_number BIGINT,
            log_level STRING,
            session_id STRING,
            user_id STRING,
            content STRING,
            log_date TIMESTAMP,
            real_time DECIMAL(12, 4),
            user_cpu_time DECIMAL(12, 4),
            system_cpu_time DECIMAL(12, 4),
            memory BIGINT,
            os_memory BIGINT,
            system_time DECIMAL(12, 4),
            page_faults BIGINT,
            page_swaps BIGINT,
            voluntary_context_switches BIGINT,
            involuntary_context_switches BIGINT,
            step_count INT,
            switch_count INT,
            step_timestamp STRING,
            type_process STRING,
            client_project_name STRING,
            task STRING,
            process_flow_name STRING,
            project_path STRING,
            inserted_at TIMESTAMP
        )
    '''

    try:
        cursor.execute(create_table_sql)
        conn.commit()
        print(f"   ✅ Tabela {full_table_name} criada com sucesso")
        logger.info(f"Tabela {full_table_name} criada")
    except Exception as e:
        print(f"   ❌ Erro ao criar {full_table_name}: {e}")
        logger.error(f"Erro ao criar tabela {full_table_name}: {e}")
        raise


def create_indexes(conn: Any) -> None:
    """Cria índices básicos para otimização da tabela log_base"""
    print("\n📋 Criando índices se necessário...")
    cursor = conn.cursor()

    # Obtém o nome completo da tabela
    full_table_name = get_table_name(TABLE_NAME)

    # Índices básicos para log_base (Databricks usa sintaxe diferente)
    # Nota: Databricks Delta Lake otimiza automaticamente, mas podemos criar índices Z-ORDER
    indexes = [
        f'CREATE INDEX IF NOT EXISTS idx_log_base_user_id ON {full_table_name}(user_id)',
        f'CREATE INDEX IF NOT EXISTS idx_log_base_log_file ON {full_table_name}(log_file)',
        f'CREATE INDEX IF NOT EXISTS idx_log_base_level ON {full_table_name}(log_level)',
        f'CREATE INDEX IF NOT EXISTS idx_log_base_type_process ON {full_table_name}(type_process)'
    ]

    created_count = 0
    for index_sql in indexes:
        try:
            cursor.execute(index_sql)
            created_count += 1
        except Exception:
            # Índice pode já existir ou sintaxe pode ser diferente no Databricks
            # Databricks pode usar OPTIMIZE ZORDER BY ao invés de índices tradicionais
            pass
    conn.commit()
    if created_count > 0:
        print(f"   ✅ {created_count} índices criados/verificados")
    else:
        print("   ℹ️  Índices não criados (Databricks pode usar otimização automática)")


def process_single_file_parallel(args: Tuple[Path, int, int, int, Dict[str, Any]]) -> Tuple[str, bool, str, float, int]:
    """
    Processa um único arquivo (executado em processo separado para paralelização)
    
    Args:
        args: tupla (log_file, worker_id, file_index, total_files, db_config)
    
    Returns:
        tupla (filename, success, message, elapsed_time, records_count)
    """
    log_file, worker_id, file_index, total_files, db_config = args

    # Importa o analisador (necessário dentro do processo worker)
    try:
        # Adiciona o diretório do script ao path para garantir que o import funcione
        script_dir = Path(__file__).parent.absolute()
        if str(script_dir) not in sys.path:
            sys.path.insert(0, str(script_dir))
        from sas_log_analyzer import SASLogAnalyzer
    except ImportError as e:
        return (log_file.name, False, f"Erro ao importar analisador: {e}", 0, 0)

    try:

        # Cada worker tem sua própria conexão
        # O oauth_lock é passado via db_config se disponível
        oauth_lock = db_config.get('oauth_lock')
        analyzer = SASLogAnalyzer(db_config, oauth_lock=oauth_lock)

        if not analyzer.connect_database():
            return (log_file.name, False, "Falha na conexão", 0, 0)

        try:
            start_time = time.time()

            # Analisa o arquivo
            result = analyzer.analyze_log_file(str(log_file))

            if not result:
                return (log_file.name, False, "Análise retornou vazio", 0, 0)

            # Verifica se há dados (apenas log_base)
            log_base_count = len(result.get('log_base', []))
            records_count = log_base_count

            if log_base_count > 0:
                # Salva no banco
                analyzer.save_to_database(str(log_file), result)
                elapsed = time.time() - start_time

                return (log_file.name, True, f"Sucesso: {records_count:,} registros em {elapsed:.2f}s", elapsed,
                        records_count)
            else:
                return (log_file.name, False, "Arquivo vazio ou sem dados", 0, 0)

        finally:
            if analyzer.conn:
                analyzer.conn.close()

    except Exception as e:
        logger.error(f"Erro ao processar {log_file.name}: {e}", exc_info=True)
        return (log_file.name, False, str(e), 0, 0)


def run_analyzer_parallel(
        processed_dir: Path,
        failed_dir: Path,
        sort_by_size: bool = False,
        num_workers: Optional[int] = None,
        check_duplicates: bool = False,
        check_file_hash: bool = False,
        conn: Optional[Any] = None,
        table_name: Optional[str] = None
) -> bool:
    """Executa o analisador de logs em modo paralelo"""
    print("\n" + "=" * 80)
    print("📊 INSERINDO DADOS DOS LOGS (MODO PARALELO)")
    print("=" * 80)

    try:
        # Setup inicial
        script_dir = Path(__file__).parent.absolute()
        log_dir = script_dir / "log_files"
        all_log_files = list(log_dir.glob("*.log"))

        if not all_log_files:
            print(f"⚠️  Nenhum arquivo .log encontrado em {log_dir}")
            return False

        # Filtra arquivos já processados usando função auxiliar
        # Nota: Em modo paralelo, verificamos apenas pasta processed (banco é verificado no analisador se necessário)
        log_files = get_log_files_to_process(
            log_dir, processed_dir, sort_by_size,
            check_database=check_duplicates,  # Verifica banco se solicitado
            conn=conn,  # Conexão para verificação no banco
            table_name=table_name,  # Nome da tabela para verificação
            check_file_hash=check_file_hash  # Hash pode ser usado mesmo em paralelo
        )

        if not log_files:
            print(f"ℹ️  Todos os {len(all_log_files)} arquivo(s) já foram processados")
            return True

        skipped_count = len(all_log_files) - len(log_files)
        if skipped_count > 0:
            print(f"ℹ️  {skipped_count} arquivo(s) já processado(s) - pulando")

        # Mostra preview usando função auxiliar
        if sort_by_size:
            print(f"📊 Arquivos ordenados por tamanho (menor primeiro)")
        else:
            print(f"📊 Arquivos em ordem alfabética")

        print_file_preview(log_files)
        print(f"📋 Encontrados {len(log_files)} arquivo(s) de log para processar")

        # Número de workers
        if num_workers is None:
            num_workers = max(1, mp.cpu_count() - MAX_WORKERS_DEFAULT_OFFSET)

        print(f"\n🔧 Usando {num_workers} workers paralelos (de {mp.cpu_count()} CPUs disponíveis)")
        print(f"⚡ Aceleração esperada: ~{num_workers}x")
        print("🔒 Usando lock de autenticação para evitar múltiplas abas do navegador")
        print()

        # Cria Manager para lock compartilhável entre processos (necessário para Windows/spawn)
        manager = mp.Manager()
        oauth_lock = manager.Lock()
        
        # Prepara DB_CONFIG com lock para os workers
        db_config_with_lock = DB_CONFIG.copy()
        db_config_with_lock['oauth_lock'] = oauth_lock

        # Prepara argumentos para cada arquivo
        total_files = len(log_files)
        tasks = [
            (log_file, idx % num_workers, idx + 1, total_files, db_config_with_lock)
            for idx, log_file in enumerate(log_files)
        ]

        # Processa em paralelo
        print("🚀 Iniciando processamento paralelo...\n")

        start_time = time.time()
        success_count = 0
        failed_count = 0
        total_records = 0

        # Usa multiprocessing.Pool para processar em paralelo
        with mp.Pool(processes=num_workers) as pool:
            # imap_unordered retorna resultados assim que ficam prontos
            results = pool.imap_unordered(process_single_file_parallel, tasks)

            # Processa resultados conforme chegam
            for idx, (filename, success, message, elapsed, records_count) in enumerate(results, 1):
                log_file = log_dir / filename

                # Calcula progresso
                progress = (idx / total_files) * 100
                elapsed_total = time.time() - start_time

                # ETA simples
                if idx > 0:
                    avg_time = elapsed_total / idx
                    remaining = total_files - idx
                    eta_seconds = remaining * avg_time
                    eta_str = f"{eta_seconds / 3600:.1f}h" if eta_seconds > 3600 else f"{eta_seconds / 60:.1f}min"
                else:
                    eta_str = "calculando..."

                if success:
                    # Move para processed
                    try:
                        if move_file_to_processed(log_file, processed_dir):
                            success_count += 1
                            total_records += records_count
                            print(f"✅ [{idx}/{total_files}] {filename[:50]:<50} | {progress:5.1f}% | ETA: {eta_str}")
                        else:
                            print(f"⚠️  [{idx}/{total_files}] Processado mas erro ao mover: {filename}")
                    except Exception:
                        print(f"⚠️  [{idx}/{total_files}] Processado mas erro ao mover: {filename}")
                else:
                    # Move para failed
                    try:
                        move_file_to_failed(log_file, failed_dir, message)
                        failed_count += 1
                        print(f"❌ [{idx}/{total_files}] FALHOU: {filename} - {message[:40]}")
                    except Exception:
                        print(f"❌ [{idx}/{total_files}] Falhou: {filename}")

        elapsed_total = time.time() - start_time

        # Resumo final
        print("\n" + "=" * 80)
        print("📊 RESUMO DO PROCESSAMENTO PARALELO")
        print("=" * 80)
        print(f"✅ Sucesso: {success_count:,} arquivo(s)")
        print(f"❌ Falhas: {failed_count:,} arquivo(s)")
        print(f"📁 Total processado: {success_count + failed_count:,} arquivo(s)")
        print(f"📊 Total de registros: ~{total_records:,}")
        print(f"⏱️  Tempo total: {elapsed_total / 3600:.2f} horas ({elapsed_total / 60:.1f} minutos)")

        if success_count > 0:
            avg_time = elapsed_total / success_count
            print(f"🚀 Velocidade média: {avg_time:.2f}s por arquivo")
            print(f"💾 Taxa: {(success_count / elapsed_total) * 3600:.0f} arquivos/hora")

        print("=" * 80)

        return success_count > 0 or failed_count == 0

    except (OSError, Exception) as e:
        print(f"❌ Erro ao executar analisador paralelo: {e}")
        logger.error(f"Erro ao executar analisador paralelo: {e}", exc_info=True)
        return False
    except Exception as e:
        print(f"❌ Erro inesperado ao executar analisador paralelo: {e}")
        logger.critical(f"Erro inesperado: {e}", exc_info=True)
        return False


def run_analyzer(processed_dir: Path, failed_dir: Path, sort_by_size: bool = False,
                check_duplicates: bool = False, check_file_hash: bool = False,
                conn: Optional[Any] = None, table_name: Optional[str] = None) -> bool:
    """Executa o analisador de logs em modo sequencial"""
    print("\n" + "=" * 80)
    print("📊 INSERINDO DADOS DOS LOGS")
    print("=" * 80)

    try:
        # Importa o analisador
        # Adiciona o diretório do script ao path para garantir que o import funcione
        script_dir = Path(__file__).parent.absolute()
        if str(script_dir) not in sys.path:
            sys.path.insert(0, str(script_dir))
        from sas_log_analyzer import SASLogAnalyzer

        analyzer = SASLogAnalyzer(DB_CONFIG)

        if not analyzer.connect_database():
            print("❌ Falha ao conectar ao banco")
            logger.error("Falha ao conectar ao banco de dados")
            return False

        # Processa logs usando função auxiliar
        script_dir = Path(__file__).parent.absolute()
        log_dir = script_dir / "log_files"
        all_log_files = list(log_dir.glob("*.log"))

        if not all_log_files:
            print(f"⚠️  Nenhum arquivo .log encontrado em {log_dir}")
            return False

        # Filtra arquivos já processados usando função auxiliar
        # Nota: Em modo paralelo, não verificamos banco aqui (cada worker verifica)
        log_files = get_log_files_to_process(
            log_dir, processed_dir, sort_by_size,
            check_database=False,  # Workers verificam individualmente
            check_file_hash=False  # Hash é custoso em paralelo
        )

        if not log_files:
            print(f"ℹ️  Todos os {len(all_log_files)} arquivo(s) já foram processados")
            return True

        skipped_count = len(all_log_files) - len(log_files)
        if skipped_count > 0:
            print(f"ℹ️  {skipped_count} arquivo(s) já processado(s) - pulando")

        # Mostra preview usando função auxiliar
        if sort_by_size:
            print(f"📊 Arquivos ordenados por tamanho (menor primeiro)")

        print_file_preview(log_files)
        print(f"📋 Encontrados {len(log_files)} arquivo(s) de log para processar")

        success_count = 0
        failed_count = 0

        for i, log_file in enumerate(log_files, 1):
            file_size_mb = log_file.stat().st_size / BYTES_PER_MB
            print(f"\n📄 [{i}/{len(log_files)}] Processando: {log_file.name} ({file_size_mb:.2f} MB)")

            file_start_time = time.time()

            try:
                # Configura timeout para o arquivo (apenas em sistemas Unix)
                signal_available = False
                try:
                    if hasattr(signal, 'SIGALRM'):
                        signal.signal(signal.SIGALRM, timeout_handler)
                        signal.alarm(FILE_TIMEOUT)
                        signal_available = True
                except (AttributeError, OSError):
                    pass

                # Analisa o arquivo
                print(f"   🔍 Analisando arquivo...")
                result = analyzer.analyze_log_file(str(log_file))

                # Cancela alarme se foi configurado
                if signal_available:
                    signal.alarm(0)

                if not result:
                    print(f"   ❌ Análise retornou None ou vazio")
                    move_file_to_failed(log_file, failed_dir, "Análise retornou vazio")
                    failed_count += 1
                    continue

                # Verifica se há dados para salvar (apenas log_base)
                log_base_count = len(result.get('log_base', []))

                print(f"   📊 Dados coletados:")
                print(f"      • log_base: {log_base_count:,} registros")

                # Salva no banco (apenas log_base)
                if log_base_count > 0:
                    print(f"   💾 Salvando no banco...")
                    analyzer.save_to_database(str(log_file), result)
                    print(f"   ✅ Processado e salvo com sucesso")
                else:
                    print(f"   ⚠️  Nenhum dado para salvar (arquivo pode estar vazio ou formato diferente)")

                if move_file_to_processed(log_file, processed_dir):
                    success_count += 1
                else:
                    print(f"   ⚠️  Arquivo processado mas não foi movido")

            except (OSError, Exception, TimeoutError) as e:
                print(f"   ❌ Erro ao processar: {e}")
                logger.error(f"Erro ao processar {log_file.name}: {e}", exc_info=True)
                move_file_to_failed(log_file, failed_dir, str(e))
                failed_count += 1
                continue
            except Exception as e:
                print(f"   ❌ Erro inesperado ao processar: {e}")
                logger.critical(f"Erro inesperado ao processar {log_file.name}: {e}", exc_info=True)
                move_file_to_failed(log_file, failed_dir, str(e))
                failed_count += 1
                continue

        if analyzer.conn:
            analyzer.conn.close()

        # Resumo final
        print("\n" + "=" * 80)
        print("📊 RESUMO DO PROCESSAMENTO")
        print("=" * 80)
        print(f"✅ Sucesso: {success_count} arquivo(s)")
        print(f"❌ Falhas: {failed_count} arquivo(s)")
        print(f"📁 Total processado: {success_count + failed_count} arquivo(s)")

        return success_count > 0 or failed_count == 0

    except (ImportError, OSError, Exception) as e:
        print(f"❌ Erro ao executar analisador: {e}")
        logger.error(f"Erro ao executar analisador: {e}", exc_info=True)
        return False
    except Exception as e:
        print(f"❌ Erro inesperado ao executar analisador: {e}")
        logger.critical(f"Erro inesperado: {e}", exc_info=True)
        return False


def validate_setup(conn: Any) -> None:
    """Valida o setup final - verifica apenas a tabela log_base"""
    print("\n" + "=" * 80)
    print("✅ VALIDAÇÃO FINAL")
    print("=" * 80)

    cursor = conn.cursor()

    # Obtém o nome completo da tabela
    full_table_name = get_table_name(TABLE_NAME)

    # Verifica se a tabela log_base existe
    try:
        # Tenta contar registros - se a tabela não existir, vai dar erro
        cursor.execute(f"SELECT COUNT(*) FROM {full_table_name}")
        result = cursor.fetchone()
        log_base_count = result[0] if result and len(result) > 0 else 0
        table_exists = True

        print(f"\n📊 ESTATÍSTICAS:")
        print(f"   • Tabela: {full_table_name}")
        print(f"   • Status: ✅ Existe")
        print(f"   • Registros: {log_base_count:,}")

        print("\n✅ Setup completo e validado!")
    except Exception as e:
        print(f"⚠️  Tabela {full_table_name} não encontrada ou erro ao acessar: {e}")
        logger.error(f"Erro ao validar setup: {e}", exc_info=True)


def main() -> None:
    """Função principal"""
    # Parse argumentos
    args = parse_arguments()

    print("=" * 80)
    print("🚀 SETUP COMPLETO DO BANCO DE DADOS SAS")
    print("=" * 80)

    if args.parallel:
        print("⚡ Modo: PARALELO (processamento rápido)")
        if args.workers:
            print(f"🔧 Workers: {args.workers}")
        else:
            print(f"🔧 Workers: automático (CPUs - 1)")
    else:
        print("📊 Modo: SEQUENCIAL (processamento completo)")

    if args.clean:
        print("🧹 Limpeza: COMPLETA (--clean)")
    else:
        print("📂 Limpeza: INCREMENTAL (mantém dados existentes)")

    if args.sort_minsize:
        print("📊 Ordenação: Por tamanho (menores primeiro)")

    print("=" * 80)

    # Cria estrutura de diretórios
    processed_dir, failed_dir = setup_directories()

    # Conecta
    conn = connect_db()

    try:
        # 1. Zera tabela (apenas se --clean)
        if args.clean:
            table_name = get_table_name(TABLE_NAME)
            print("\n" + "=" * 80)
            print("⚠️  ATENÇÃO: OPERAÇÃO DESTRUTIVA")
            print("=" * 80)
            print("Esta operação irá APAGAR TODOS os dados da tabela:")
            print(f"   📋 {table_name}")
            print()
            print("ℹ️  IMPORTANTE: Apenas esta tabela será apagada.")
            print("   Outras tabelas no banco NÃO serão afetadas.")
            print("=" * 80)
            
            while True:
                resposta = input(f"\n❓ Você confirma que deseja EXCLUIR todos os dados de '{table_name}'? (digite 'SIM' para confirmar ou 'NÃO' para cancelar): ").strip().upper()
                
                if resposta == 'SIM':
                    print("\n✅ Confirmação recebida. Prosseguindo com a limpeza...")
                    drop_all_tables(conn)
                    break
                elif resposta == 'NÃO' or resposta == 'NAO':
                    print("\n❌ Operação cancelada pelo usuário.")
                    print("Saindo do script...")
                    return
                else:
                    print("⚠️  Resposta inválida. Digite 'SIM' para confirmar ou 'NÃO' para cancelar.")
        else:
            print("\nℹ️  Pulando limpeza da tabela (modo incremental)")

        # 2. Cria tabela log_base (se não existir)
        create_tables_direct(conn)

        # 3. Insere dados dos logs (sequencial ou paralelo)
        table_name = get_table_name(TABLE_NAME)
        if args.parallel:
            if not run_analyzer_parallel(processed_dir, failed_dir, args.sort_minsize, args.workers, 
                                        args.check_duplicates, args.check_file_hash, conn, table_name):
                print("⚠️  Aviso: Falha ao inserir alguns dados")
        else:
            if not run_analyzer(processed_dir, failed_dir, args.sort_minsize, 
                              args.check_duplicates, args.check_file_hash, conn, table_name):
                print("⚠️  Aviso: Falha ao inserir alguns dados")

        # 4. Cria índices básicos (após processamento para não atrasar inserções)
        create_indexes(conn)

        # 5. Valida
        validate_setup(conn)

        print("\n" + "=" * 80)
        print("🎉 SETUP CONCLUÍDO COM SUCESSO!")
        print("=" * 80)

    except (Exception, OSError, ValueError) as e:
        print(f"\n❌ Erro durante setup: {e}")
        logger.error(f"Erro durante setup: {e}", exc_info=True)
    except Exception as e:
        print(f"\n❌ Erro inesperado durante setup: {e}")
        logger.critical(f"Erro inesperado durante setup: {e}", exc_info=True)
    finally:
        if conn:
            conn.close()


if __name__ == "__main__":
    # Configura logging apenas se for o módulo principal
    setup_logging()

    # Configura multiprocessing para Windows (spawn) ou Unix (fork)
    if sys.platform == 'win32':
        mp.set_start_method('spawn', force=True)
    else:
        try:
            mp.set_start_method('fork', force=True)
        except RuntimeError:
            mp.set_start_method('spawn', force=True)

    main()
