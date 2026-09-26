@echo off
chcp 65001 >nul
cd /d "%~dp0"

rem Busca Python: primero el lanzador "py" (lo instala python.org), luego "python"
py -3 --version >nul 2>nul
if not errorlevel 1 (
    py -3 app.py
    goto fin
)
python --version >nul 2>nul
if not errorlevel 1 (
    python app.py
    goto fin
)

echo.
echo  No encuentro Python en este ordenador.
echo.
echo  1. Descargalo de https://www.python.org/downloads/  (se abre ahora en el navegador)
echo  2. Al instalar, marca la casilla "Add python.exe to PATH"
echo  3. Vuelve a abrir este archivo (iniciar.bat)
echo.
start "" https://www.python.org/downloads/

:fin
pause
