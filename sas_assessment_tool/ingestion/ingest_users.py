#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Script de Ingestão de Usuários
===============================
Carrega dados de usuários do arquivo CSV para a tabela users_final no Databricks.

Configuração (.env):
    DATABRICKS_SERVER_HOSTNAME=seu-workspace.cloud.databricks.com
    DATABRICKS_HTTP_PATH=/sql/1.0/warehouses/seu-warehouse-id
    DATABRICKS_CATALOG=bv_dev_db (opcional, padrão)
    DATABRICKS_SCHEMA=bv_migration_sas (opcional, padrão)

Arquivo de entrada:
    src/users.csv (formato CSV com separador ';')

Tabela de destino:
    {catalog}.{schema}.users_final

Uso:
    python ingest_users.py

Características:
    - Criação automática da tabela com base nas colunas do CSV
    - Normalização automática de nomes de colunas para SQL
    - Inserção em lote com tratamento de erros
    - Suporte a múltiplos formatos de data/hora
"""
import pandas as pd
from databricks import sql
from pathlib import Path
from datetime import datetime
import sys
import os
from dotenv import load_dotenv

# Carrega variáveis do .env
load_dotenv()
PATH_FILE_USERS = "src/users.csv"
TABLE_NAME_USERS = 'users_final'


def get_db_config():
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
    full_table_name = f"{catalog}.{schema}.{TABLE_NAME_USERS}"

    return {
        'server_hostname': host,
        'http_path': http_path,
        'catalog': catalog,
        'schema': schema,
        'table_name': f'{TABLE_NAME_USERS}',
        'full_table_name': full_table_name
    }


def connect_db():
    """Conecta ao Databricks via OAuth U2M (Browser Login)"""
    host = os.getenv('DATABRICKS_SERVER_HOSTNAME')
    http_path = os.getenv('DATABRICKS_HTTP_PATH')

    if not host or not http_path:
        raise ValueError("Defina DATABRICKS_SERVER_HOSTNAME e DATABRICKS_HTTP_PATH no .env")

    print(f"🔌 Conectando ao host: {host}")
    # auth_type="databricks-oauth" abre o navegador para login
    try:
        conn = sql.connect(server_hostname=host, http_path=http_path, auth_type="databricks-oauth")
        print("✅ Conectado ao Databricks com sucesso!")
        return conn
    except Exception as e:
        print(f"❌ Erro ao conectar: {e}")
        sys.exit(1)


def normalize_column_name(col_name: str) -> str:
    """
    Normaliza nome de coluna para formato SQL válido.
    
    Args:
        col_name: Nome da coluna original
        
    Returns:
        Nome normalizado
    """
    # Normaliza nome da coluna (remove espaços, caracteres especiais)
    sql_col_name = col_name.strip().lower().replace(' ', '_').replace('-', '_').replace('/', '_')
    sql_col_name = ''.join(c if c.isalnum() or c == '_' else '_' for c in sql_col_name)

    # Remove underscores duplicados
    while '__' in sql_col_name:
        sql_col_name = sql_col_name.replace('__', '_')

    # Remove underscore inicial se houver
    if sql_col_name.startswith('_'):
        sql_col_name = sql_col_name[1:]

    return sql_col_name


def load_users_from_csv(conn, csv_path: str = PATH_FILE_USERS):
    """
    Carrega dados de usuários do arquivo CSV para a tabela users_final no Databricks.
    
    Args:
        conn: Conexão com Databricks
        csv_path: Caminho para o arquivo CSV
        
    Returns:
        True se sucesso, False caso contrário
    """
    print("\n" + "=" * 80)
    print("👥 CARREGANDO DADOS DE USUÁRIOS DO CSV")
    print("=" * 80)

    # Usa o diretório do script como base para caminhos relativos
    script_dir = Path(__file__).parent.absolute()
    csv_file = script_dir / csv_path if not Path(csv_path).is_absolute() else Path(csv_path)
    
    if not csv_file.exists():
        print(f"⚠️  Arquivo não encontrado: {csv_file}")
        print("   Pulando carregamento de usuários...")
        return False

    try:
        # Lê o arquivo CSV (separador é ; e pode ter quebras de linha dentro de aspas)
        print(f"📄 Lendo arquivo: {csv_file.name}")
        try:
            # Usa csv.DictReader para lidar corretamente com quebras de linha dentro de aspas
            import csv
            rows = []
            with open(csv_file, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f, delimiter=';', quotechar='"')
                for row in reader:
                    # Limpa valores (remove espaços extras, quebras de linha)
                    cleaned_row = {}
                    for key, value in row.items():
                        if value:
                            # Remove quebras de linha múltiplas e espaços extras
                            cleaned_value = ' '.join(value.split())
                            cleaned_row[key] = cleaned_value
                        else:
                            cleaned_row[key] = None
                    rows.append(cleaned_row)
            df = pd.DataFrame(rows)
        except Exception as e:
            print(f"   ⚠️  Erro ao ler CSV: {e}")
            print("   🔄 Tentando com pandas...")
            # Fallback: tenta com pandas
            df = pd.read_csv(
                csv_file,
                sep=';',
                encoding='utf-8',
                quotechar='"',
                on_bad_lines='skip',
                engine='python'
            )

        if df.empty:
            print("⚠️  Arquivo CSV está vazio!")
            return False

        print(f"   ✅ {len(df)} linha(s) encontrada(s)")
        print(f"   ✅ {len(df.columns)} coluna(s): {', '.join(df.columns)}")

        # Obtém configuração do banco
        db_config = get_db_config()
        table_name = db_config['full_table_name']
        cursor = conn.cursor()

        # 1. Cria tabela users_final
        print(f"\n📋 Criando/atualizando tabela {table_name}...")

        # Remove tabela se existir (para recriar com novas colunas se necessário)
        try:
            cursor.execute(f"DROP TABLE IF EXISTS {table_name}")
            conn.commit()
        except Exception as e:
            print(f"   ⚠️  Aviso ao remover tabela: {e}")

        # Constrói CREATE TABLE dinamicamente (sintaxe Databricks)
        columns_sql = ["id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY"]

        # Mapeia tipos do pandas para tipos SQL Databricks
        type_mapping = {
            'int64': 'BIGINT',
            'float64': 'DECIMAL(15,2)',
            'object': 'STRING',
            'datetime64[ns]': 'TIMESTAMP',
            'bool': 'BOOLEAN'
        }

        for col in df.columns:
            sql_col_name = normalize_column_name(col)

            # Determina tipo SQL
            dtype = str(df[col].dtype)
            if dtype in type_mapping:
                sql_type = type_mapping[dtype]
            elif 'int' in dtype:
                sql_type = 'BIGINT'
            elif 'float' in dtype:
                sql_type = 'DECIMAL(15,2)'
            elif 'date' in dtype.lower() or 'time' in dtype.lower():
                sql_type = 'TIMESTAMP'
            else:
                sql_type = 'STRING'

            columns_sql.append(f"{sql_col_name} {sql_type}")
            print(f"   • {col} → {sql_col_name} ({sql_type})")

        # Adiciona inserted_at
        columns_sql.append("inserted_at TIMESTAMP")

        create_table_sql = f"""
            CREATE TABLE {table_name} (
                {', '.join(columns_sql)}
            )
        """

        cursor.execute(create_table_sql)
        conn.commit()
        print(f"   ✅ Tabela {table_name} criada com sucesso!")

        # 2. Insere dados em lote
        print(f"\n💾 Inserindo {len(df)} registro(s)...")
        inserted_at = datetime.now()
        inserted_count = 0

        # Prepara dados em lote
        data_batch = []
        column_names = [normalize_column_name(col) for col in df.columns]

        for idx, row in df.iterrows():
            try:
                values = []

                for col in df.columns:
                    value = row[col]
                    if pd.isna(value):
                        values.append(None)
                    elif isinstance(value, pd.Timestamp):
                        values.append(value.to_pydatetime())
                    elif isinstance(value, (int, float)):
                        values.append(float(value) if isinstance(value, float) else int(value))
                    else:
                        # Converte para string e limpa quebras de linha
                        str_value = str(value).strip()
                        values.append(str_value if str_value else None)

                # Adiciona inserted_at
                values.append(inserted_at)

                data_batch.append(tuple(values))

            except Exception as e:
                print(f"   ⚠️  Erro ao preparar linha {idx + 1}: {e}")
                continue

        # Insere em lote usando executemany
        if data_batch:
            # Prepara SQL de inserção
            placeholders = ', '.join(['?' for _ in range(len(column_names) + 1)])  # +1 para inserted_at
            column_names_with_inserted = column_names + ['inserted_at']

            insert_sql = f"""
                INSERT INTO {table_name} ({', '.join(column_names_with_inserted)})
                VALUES ({placeholders})
            """

            # Insere em lotes de 500
            batch_size = 500
            total_batches = (len(data_batch) + batch_size - 1) // batch_size

            for i in range(0, len(data_batch), batch_size):
                batch = data_batch[i:i + batch_size]
                current_batch = (i // batch_size) + 1

                try:
                    if total_batches > 1:
                        print(f"   📦 Inserindo lote {current_batch}/{total_batches} ({len(batch)} registros)...",
                              end='', flush=True)

                    cursor.executemany(insert_sql, batch)
                    conn.commit()
                    inserted_count += len(batch)

                    if total_batches > 1:
                        print(f" ✅")
                    else:
                        print(f"   ✅ {inserted_count} registro(s) inserido(s)")

                except Exception as e:
                    print(f"\n   ⚠️  Erro ao inserir lote {current_batch}: {e}")
                    # Tenta inserir um por um
                    print(f"   🔄 Tentando inserir individualmente...")
                    for row in batch:
                        try:
                            cursor.execute(insert_sql, row)
                            conn.commit()
                            inserted_count += 1
                        except Exception as row_error:
                            # Ignora duplicatas
                            if "duplicate" in str(row_error).lower() or "already exists" in str(row_error).lower():
                                pass
                            else:
                                print(f"      ⚠️  Erro ao inserir linha: {row_error}")
                            continue

        print(f"\n   ✅ {inserted_count} registro(s) inserido(s) com sucesso!")

        # 3. Valida inserção
        cursor.execute(f"SELECT COUNT(*) FROM {table_name}")
        result = cursor.fetchone()
        count = result[0] if result and len(result) > 0 else 0
        print(f"\n✅ Total de {count} usuário(s) na tabela {table_name}")

        return True

    except ImportError:
        print("❌ Erro: pandas não está instalado!")
        print("   Execute: pip install pandas")
        return False
    except Exception as e:
        print(f"❌ Erro ao carregar usuários: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    # Teste standalone
    conn = connect_db()
    try:
        load_users_from_csv(conn)
    finally:
        if conn:
            conn.close()
