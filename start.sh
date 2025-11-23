#!/bin/bash

# Colores para output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

echo -e "${GREEN}=== Iniciando Bot de Trading ===${NC}"

# 1. Verificar Python
if ! command -v python3 &> /dev/null; then
    echo -e "${RED}Error: Python3 no está instalado.${NC}"
    exit 1
fi

# 2. Instalar dependencias si no existen
echo -e "${YELLOW}Verificando dependencias...${NC}"
python3 -m pip install -r requirements.txt > /dev/null 2>&1
if [ $? -eq 0 ]; then
    echo -e "${GREEN}Dependencias instaladas correctamente.${NC}"
else
    echo -e "${RED}Error instalando dependencias. Revisa tu conexión a internet.${NC}"
    exit 1
fi

# 3. Verificar archivo .env
if [ ! -f .env ]; then
    echo -e "${RED}Error: No se encontró el archivo .env${NC}"
    echo -e "${YELLOW}Creando archivo .env de ejemplo...${NC}"
    cp .env.example .env
    echo -e "${YELLOW}POR FAVOR: Abre el archivo .env y coloca tus API KEYS de Binance antes de continuar.${NC}"
    exit 1
fi

# 4. Ejecutar el bot
echo -e "${GREEN}Ejecutando el bot... (Presiona Ctrl+C para detener)${NC}"
python3 main.py
