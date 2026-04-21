@echo off
title EBD Digital

echo ============================================
echo          EBD Digital — Iniciando...
echo ============================================
echo.

REM Verificar Python
python --version >nul 2>&1
if errorlevel 1 (
    echo ERRO: Python nao encontrado. Instale o Python 3.10+ em python.org
    pause
    exit /b 1
)

REM Criar .env se nao existir
if not exist ".env" (
    echo Criando arquivo .env com valores padrao...
    copy ".env.example" ".env"
)

REM Criar ambiente virtual se nao existir
if not exist "venv" (
    echo Criando ambiente virtual...
    python -m venv venv
)

REM Ativar ambiente virtual
call venv\Scripts\activate.bat

REM Instalar dependencias
echo Instalando dependencias...
pip install -r requirements.txt -q

echo.
echo ============================================
echo  Sistema iniciado em: http://localhost:5000
echo.
echo  Painel Admin:  http://localhost:5000/admin/login
echo  Area Aluno:    http://localhost:5000/aluno/login
echo.
echo  Login admin padrao: admin / admin123
echo ============================================
echo.

python app.py

pause
