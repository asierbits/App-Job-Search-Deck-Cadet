@echo off
rem knok sin Docker: Python + base de datos en un archivo (SQLite). Para tu PC, sin instalar nada mas.
chcp 65001 >nul
cd /d "%~dp0"
title knok

rem --- 1. Buscar Python (primero el lanzador "py" de python.org, luego "python")
set "PY="
py -3 --version >nul 2>nul
if not errorlevel 1 set "PY=py -3"
if not defined PY (
  python --version >nul 2>nul
  if not errorlevel 1 set "PY=python"
)
if not defined PY goto sin_python
%PY% -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)"
if errorlevel 1 (
  echo Tu Python es antiguo: knok necesita Python 3.11 o mas reciente.
  goto sin_python
)

rem --- 2. Entorno propio de knok (solo la primera vez o si cambian las dependencias)
if not exist ".venv\Scripts\python.exe" (
  echo Preparando knok por primera vez. Tarda unos minutos...
  %PY% -m venv .venv
  if errorlevel 1 goto error
)
set "VPY=.venv\Scripts\python.exe"
fc /b pyproject.toml ".venv\pyproject.instalado" >nul 2>nul
if errorlevel 1 (
  echo Instalando dependencias...
  "%VPY%" -m pip install --disable-pip-version-check -q --upgrade pip
  "%VPY%" -m pip install --disable-pip-version-check -q -e .
  if errorlevel 1 goto error
  copy /y pyproject.toml ".venv\pyproject.instalado" >nul
)

rem --- 3. Configuracion local (modo de prueba sin red la primera vez)
if not exist .env (
  > .env echo KNOK_OFFLINE_SOURCES=true
  >> .env echo KNOK_SECRET_KEY=local-%RANDOM%%RANDOM%%RANDOM%%RANDOM%
  echo Creado .env en modo de prueba sin red.
)
findstr /b /c:"KNOK_DATABASE_URL=" .env >nul || >> .env echo KNOK_DATABASE_URL=sqlite:///./knok.db
findstr /b /c:"KNOK_EMBEDDED_WORKER=" .env >nul || >> .env echo KNOK_EMBEDDED_WORKER=true

rem --- 4. Base de datos al dia y arranque
"%VPY%" -m alembic upgrade head
if errorlevel 1 goto error

echo.
echo  knok en marcha en http://localhost:8000/playground
echo  Para pararlo, cierra esta ventana (o pulsa Ctrl+C).
echo.
start "" cmd /c "timeout /t 5 >nul & start "" http://localhost:8000/playground"
"%VPY%" -m uvicorn knok.api.main:app --host 127.0.0.1 --port 8000
goto fin

:sin_python
echo.
echo  Necesitas Python 3.11 o mas reciente.
echo  1. Descargalo de https://www.python.org/downloads/  (se abre ahora)
echo  2. Al instalar, marca la casilla "Add python.exe to PATH"
echo  3. Vuelve a abrir este archivo
start "" https://www.python.org/downloads/
pause
exit /b 1

:error
echo.
echo  Algo ha fallado. Copia los mensajes de arriba y envialos para revisarlo.
pause
exit /b 1

:fin
pause
