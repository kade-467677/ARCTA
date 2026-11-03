@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"

set PORT=8737
set URL=http://127.0.0.1:%PORT%

where py >nul 2>nul
if %errorlevel%==0 (
    set PYCMD=py -3
) else (
    set PYCMD=python
)

if not exist ".venv\Scripts\python.exe" (
    echo Premiere utilisation : creation de l'environnement et installation des dependances...
    %PYCMD% -m venv .venv
    if errorlevel 1 (
        echo.
        echo Python 3.12 ou plus recent est requis. Installez-le depuis https://www.python.org/downloads/ puis relancez ce fichier.
        pause
        exit /b 1
    )
    ".venv\Scripts\python.exe" -m pip install --upgrade pip
    ".venv\Scripts\python.exe" -m pip install -r requirements.txt
)

echo Demarrage d'ARCTA sur %URL% ...
start "" "%URL%"
".venv\Scripts\python.exe" -m uvicorn apps.arcta_web.main:app --host 127.0.0.1 --port %PORT%

echo.
echo ARCTA est arrete.
pause
