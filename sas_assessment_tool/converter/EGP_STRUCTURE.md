# Estrutura Interna de Arquivos .EGP (SAS Enterprise Guide)

Este documento detalha a anatomia de um arquivo `.egp` quando descompactado. O objetivo é fornecer um guia para desenvolvedores que precisam extrair código e metadados programaticamente sem utilizar o software SAS.

> **Nota Técnica:** Desde a versão 4.2 do SAS Enterprise Guide, o arquivo `.egp` é um arquivo compactado (ZIP) contendo uma estrutura de diretórios baseada em XML e arquivos de texto.

---

## 1. Visão Geral da Árvore de Diretórios

Ao extrair um arquivo `.egp`, você encontrará a seguinte estrutura hierárquica:

```text
NOME_DO_PROJETO/
│
├── project.xml                <-- 🧠 ARQUIVO MESTRE (Comece por aqui)
├── project.properties         <-- Metadados gerais (Versão do EG, datas)
│
├── Git/                       <-- (Opcional) Se houver integração com Git
│
└── element/                   <-- 📦 O CONTEÚDO (Onde o código vive)
    │
    ├── {UUID-DA-TAREFA-1}/    <-- Pasta de um "Nó" do fluxo (Programas, Queries, etc.)
    │   ├── element.xml        <-- Definição do Tipo da tarefa
    │   ├── code.sas           <-- 💎 Código SAS (se for um Program Node)
    │   ├── log.txt (ou .xml)  <-- Log da última execução
    │   ├── props.xml          <-- Propriedades da tarefa visual
    │   └── ...
    │
    ├── {UUID-DA-TAREFA-2}/    <-- Pasta de outro "Nó"
    │   ├── query.sql          <-- 💎 Código SQL (se for Query Builder)
    │   └── element.xml
    │
    └── ... (Dezenas de outras pastas com UUIDs)

2. Arquivos da Raiz
project.xml

Este é o mapa do projeto. Ele contém a árvore visual que você vê no SAS Enterprise Guide.

Função: Relacionar os nomes amigáveis das tarefas com os UUIDs das pastas.

O que extrair: Tags <Element>.

Atributo ID: O nome da pasta dentro de element/.

Tag <Label>: O nome visível do programa (ex: "01_Carga_Dados").

Tag <Type>: O tipo do objeto (ex: SAS.EG.ProjectElements.CodeTask).

Exemplo de XML:

XML
<Element ID="{550E8400-E29B-41D4-A716-446655440000}" Type="SAS.EG.ProjectElements.CodeTask">
    <Label>01_Importacao_Vendas</Label>
    <Container>...</Container>
</Element>

3. O Diretório element/

Este diretório contém subpastas nomeadas com GUIDs (Identificadores Globais Únicos). Cada pasta representa um ícone no fluxo do processo (um Programa, uma Query, um Dataset, um Log, uma Nota).

Arquivos Críticos dentro das Pastas {UUID}

Para fins de migração (SAS -> Python/SQL), você deve buscar os seguintes arquivos, nesta ordem de prioridade:

A. code.sas (Prioridade 1)

O que é: O script SAS puro.

Onde aparece: Em nós do tipo "Programa SAS" (ícone do bonequinho correndo).

Uso: Copiar o conteúdo para migração direta.

B. query.sql (Prioridade 2)

O que é: O código SQL ANSI gerado pelo "Query Builder" (Construtor de Consultas Visual).

Onde aparece: Em nós de Query.

Uso: Pode ser migrado quase diretamente para SparkSQL ou banco de dados, com pequenos ajustes de dialeto.

C. log.txt ou log.xml (Prioridade 3)

O que é: O registro da última execução.

Por que é importante: Se o nó for uma tarefa visual (ex: Filtro, Gráfico) e não tiver code.sas, o Log geralmente contém o código gerado (MPRINT) que foi executado. É a "cópia de segurança" da lógica.

D. element.xml

O que é: Metadados da pasta.

O que buscar:

Se não houver código, procure por tags <Path> ou <Filename>. Isso indica que o código é um Link Externo (%INCLUDE) e reside na rede, não no EGP.

E. props.xml

O que é: XML complexo com as configurações das janelas visuais (checkboxes, dropdowns selecionados).

Uso: Último recurso. Difícil de parsear. Contém a lógica de tarefas visuais (ex: "FilterCondition", "SortOrder") que não geraram código salvo.

4. Algoritmo de Extração (Lógica para Script)

Para automatizar a leitura, o script deve seguir este fluxo lógico:

Ler Raiz: Abrir project.xml e criar um Dicionário (Hash Map):

Key: {UUID} (ex: {550E...})

Value: "Nome da Tarefa" (ex: "Carga Vendas")

Iterar: Percorrer todas as pastas em element/.

Identificar Conteúdo: Para cada pasta, verificar a existência de arquivos na seguinte ordem:

IF exists code.sas -> É um Programa SAS Manual. (Extrair)

ELSE IF exists query.sql -> É uma Query SQL. (Extrair)

ELSE IF exists element.xml com <Path> -> É uma referência externa. (Logar Caminho)

ELSE -> É uma tarefa visual ou artefato sem código explícito. Verificar log.txt ou ignorar.

Enriquecer: Associar o código extraído ao "Nome da Tarefa" usando o dicionário do passo 1.

5. Tipos de Dependência (Para Mapeamento)

Ao ler os arquivos de código (.sas ou .sql), utilize Regex para identificar a linhagem de dados:

Inputs (Leitura):

SET Lib.Tabela;

MERGE Lib.Tabela;

FROM Lib.Tabela

Outputs (Escrita):

DATA Lib.Tabela;

CREATE TABLE Lib.Tabela

INSERT INTO Lib.Tabela