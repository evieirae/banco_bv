#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Configuração do pytest para o pacote ingestion
==============================================

Este arquivo configura o ambiente de testes para garantir que os imports
funcionem corretamente, independentemente de onde o pytest é executado.
"""

import sys
from pathlib import Path

# Adiciona o diretório raiz do projeto ao PYTHONPATH
project_root = Path(__file__).parent.parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

# Adiciona o diretório ingestion ao PYTHONPATH
ingestion_dir = Path(__file__).parent.parent
if str(ingestion_dir) not in sys.path:
    sys.path.insert(0, str(ingestion_dir))
