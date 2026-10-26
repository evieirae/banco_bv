#!/usr/bin/env python3
"""
Script para converter CSV de migração SAS em scripts Cypher para Neo4j
Time BV - Migração SAS

Versão Refatorada: 100% Data-Driven
- Usa diretamente os valores do CSV (labels e tipos de relacionamento)
- Sem lógica hardcoded de mapeamento
- Propriedades simples: name e type
- Gera arquivos separados por tipo (compatível com docker-compose.yml)
"""

import csv
from collections import defaultdict
from pathlib import Path

# Configurações
CSV_FILE = "modelagem_bv.csv"  # gerado por project_sas/egps_analysis/docs/analises/build_neo4j_modelagem.py
OUTPUT_DIR = Path(".")
NODES_DIR = OUTPUT_DIR / "nodes"
RELATIONSHIPS_DIR = OUTPUT_DIR / "relationships"

# Criar diretórios se não existirem
NODES_DIR.mkdir(exist_ok=True)
RELATIONSHIPS_DIR.mkdir(exist_ok=True)


def sanitize_name(name):
    """Sanitiza nomes para uso em Cypher (remove valores inválidos)"""
    if not name or name == "_null_" or name.strip() == "":
        return None
    return name.strip()


def escape_cypher_string(value):
    """Escapa strings para uso seguro em Cypher"""
    if value is None:
        return "null"
    value = str(value).replace("\\", "\\\\").replace("'", "\\'").replace('"', '\\"')
    return f"'{value}'"


def normalize_filename(node_type):
    """Normaliza tipo de nó para nome de arquivo"""
    return node_type.lower().replace(" ", "_").replace("-", "_")


def extract_nodes_and_relationships(csv_file):
    """
    Extrai nós e relacionamentos do CSV de forma dinâmica.
    Retorna:
        - nodes: {(name, type): {name, type}} - nós únicos
        - relationships: [(nome_pai, tipo_pai, tipo_rel, nome_filho, tipo_filho)]
    """
    nodes = {}
    relationships = []
    
    print(f"Processando arquivo: {csv_file}")
    
    with open(csv_file, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        total_rows = 0
        skipped_rows = 0
        
        for row in reader:
            total_rows += 1
            if total_rows % 10000 == 0:
                print(f"  Processadas {total_rows} linhas...")
            
            # Extrair dados da linha
            nome_pai = sanitize_name(row.get('nome_pai', ''))
            tipo_pai = sanitize_name(row.get('tipo_pai', ''))
            tipo_rel = sanitize_name(row.get('tipo_relacionamento', ''))
            nome_filho = sanitize_name(row.get('nome_filho', ''))
            tipo_filho = sanitize_name(row.get('tipo_filho', ''))
            
            # Validar dados obrigatórios
            if not nome_pai or not tipo_pai or not tipo_rel or not nome_filho or not tipo_filho:
                skipped_rows += 1
                continue
            
            # Registrar nó pai (usando tipo_pai como label)
            if (nome_pai, tipo_pai) not in nodes:
                nodes[(nome_pai, tipo_pai)] = {
                    'name': nome_pai,
                    'type': tipo_pai
                }
            
            # Registrar nó filho (usando tipo_filho como label)
            if (nome_filho, tipo_filho) not in nodes:
                nodes[(nome_filho, tipo_filho)] = {
                    'name': nome_filho,
                    'type': tipo_filho
                }
            
            # Registrar relacionamento (usando tipo_relacionamento diretamente)
            relationships.append((nome_pai, tipo_pai, tipo_rel, nome_filho, tipo_filho))
    
    print(f"\nTotal de linhas processadas: {total_rows}")
    print(f"Linhas ignoradas (dados inválidos): {skipped_rows}")
    print(f"\nResumo:")
    print(f"  Nós únicos: {len(nodes)}")
    print(f"  Relacionamentos: {len(relationships)}")
    
    # Estatísticas por tipo de nó
    nodes_by_type = defaultdict(int)
    for (name, node_type) in nodes.keys():
        nodes_by_type[node_type] += 1
    
    print(f"\nNós por tipo:")
    for node_type, count in sorted(nodes_by_type.items()):
        print(f"  {node_type}: {count}")
    
    # Estatísticas por tipo de relacionamento
    rels_by_type = defaultdict(int)
    for (pai, tipo_pai, tipo_rel, filho, tipo_filho) in relationships:
        rels_by_type[tipo_rel] += 1
    
    print(f"\nRelacionamentos por tipo:")
    for rel_type, count in sorted(rels_by_type.items()):
        print(f"  {rel_type}: {count}")
    
    return nodes, relationships


def generate_clear_data_script(output_dir):
    """Gera script para limpar todos os dados do Neo4j"""
    output_file = output_dir / "clear_all_data.cypher"
    
    with open(output_file, 'w', encoding='utf-8') as f:
        f.write("// Cypher script to clear all data from Neo4j\n")
        f.write("// Generated from CSV migration data - Time BV\n")
        f.write("// Version: Data-Driven (100% dynamic)\n\n")
        f.write("// Delete all relationships\n")
        f.write("MATCH ()-[r]-() DELETE r;\n\n")
        f.write("// Delete all nodes\n")
        f.write("MATCH (n) DELETE n;\n\n")
        f.write("// Drop all constraints (optional - comment out if you want to keep constraints)\n")
        f.write("// CALL apoc.schema.assert({}, {});\n")
    
    print(f"✓ Gerado: {output_file}")


def generate_node_creation_cypher(nodes, output_dir):
    """
    Gera scripts Cypher para criar nós, um arquivo por tipo de nó.
    """
    # Agrupar nós por tipo (label)
    nodes_by_type = defaultdict(list)
    for (name, node_type), props in nodes.items():
        nodes_by_type[node_type].append(props)
    
    # Criar um arquivo por tipo de nó
    for node_type in sorted(nodes_by_type.keys()):
        node_list = nodes_by_type[node_type]
        filename = normalize_filename(node_type)
        output_file = output_dir / f"create_{filename}_nodes.cypher"
        
        with open(output_file, 'w', encoding='utf-8') as f:
            f.write(f"// Cypher script to create {node_type} nodes in Neo4j\n")
            f.write("// Generated from CSV migration data - Time BV\n")
            f.write("// Version: Data-Driven (100% dynamic)\n")
            f.write(f"// Total nodes: {len(node_list)}\n\n")
            
            # Criar constraint
            constraint_name = filename
            f.write("// Create unique constraint\n")
            f.write(f"CREATE CONSTRAINT {constraint_name}_name_unique IF NOT EXISTS ")
            f.write(f"FOR (n:{node_type}) REQUIRE n.name IS UNIQUE;\n\n")
            
            # Criar nós
            f.write(f"// Create {len(node_list)} nodes\n")
            for node in sorted(node_list, key=lambda x: x['name']):
                name_escaped = escape_cypher_string(node['name'])
                type_escaped = escape_cypher_string(node['type'])
                f.write(f"CREATE (n:{node_type} {{name: {name_escaped}, type: {type_escaped}}});\n")
        
        print(f"✓ Gerado: {output_file} ({len(node_list)} nós)")


def generate_relationship_creation_cypher(relationships, output_dir):
    """
    Gera scripts Cypher para criar relacionamentos, um arquivo por tipo de relacionamento.
    """
    # Agrupar relacionamentos por tipo
    rels_by_type = defaultdict(list)
    for pai, tipo_pai, tipo_rel, filho, tipo_filho in relationships:
        rels_by_type[tipo_rel].append((pai, tipo_pai, filho, tipo_filho))
    
    # Criar um arquivo por tipo de relacionamento
    for rel_type in sorted(rels_by_type.keys()):
        rel_list = rels_by_type[rel_type]
        filename = normalize_filename(rel_type)
        output_file = output_dir / f"create_{filename}_relationships.cypher"
        
        with open(output_file, 'w', encoding='utf-8') as f:
            f.write(f"// Cypher script to create {rel_type} relationships in Neo4j\n")
            f.write("// Generated from CSV migration data - Time BV\n")
            f.write("// Version: Data-Driven (100% dynamic)\n")
            f.write(f"// Total relationships: {len(rel_list)}\n\n")
            
            # Criar relacionamentos
            for pai, tipo_pai, filho, tipo_filho in rel_list:
                pai_escaped = escape_cypher_string(pai)
                filho_escaped = escape_cypher_string(filho)
                
                # Usar labels diretamente do CSV
                f.write(f"MATCH (pai:{tipo_pai} {{name: {pai_escaped}}}), ")
                f.write(f"(filho:{tipo_filho} {{name: {filho_escaped}}}) ")
                f.write(f"CREATE (pai)-[:{rel_type}]->(filho);\n")
        
        print(f"✓ Gerado: {output_file} ({len(rel_list)} relacionamentos)")


def main():
    """Função principal"""
    print("=" * 60)
    print("Conversor CSV para Cypher - Migração SAS (Time BV)")
    print("Versão: Data-Driven (100% dinâmico)")
    print("=" * 60)
    print()
    
    # Verificar se arquivo CSV existe
    if not Path(CSV_FILE).exists():
        print(f"❌ Erro: Arquivo '{CSV_FILE}' não encontrado!")
        print(f"   Certifique-se de que o arquivo está no diretório atual.")
        return
    
    # Extrair nós e relacionamentos do CSV
    nodes, relationships = extract_nodes_and_relationships(CSV_FILE)
    
    if not nodes:
        print("\n❌ Erro: Nenhum nó válido encontrado no CSV!")
        return
    
    if not relationships:
        print("\n⚠️  Aviso: Nenhum relacionamento encontrado no CSV!")
    
    print("\n" + "=" * 60)
    print("Gerando scripts Cypher...")
    print("=" * 60)
    print()
    
    # Gerar script de limpeza
    generate_clear_data_script(NODES_DIR)
    
    # Gerar scripts de nós (um arquivo por tipo)
    generate_node_creation_cypher(nodes, NODES_DIR)
    
    # Gerar scripts de relacionamentos (um arquivo por tipo)
    generate_relationship_creation_cypher(relationships, RELATIONSHIPS_DIR)
    
    print("\n" + "=" * 60)
    print("✓ Conversão concluída!")
    print("=" * 60)
    print(f"\nScripts gerados em:")
    print(f"  - {NODES_DIR}/ ({len(set(n[1] for n in nodes.keys()))} tipos de nós)")
    print(f"  - {RELATIONSHIPS_DIR}/ ({len(set(r[2] for r in relationships))} tipos de relacionamentos)")
    print("\nPróximo passo:")
    print("  docker-compose up -d")
    print("\nO docker-compose irá carregar automaticamente todos os scripts Cypher gerados!")


if __name__ == "__main__":
    main()
