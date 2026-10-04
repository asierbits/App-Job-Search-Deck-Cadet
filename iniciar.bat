@echo off
rem knok: arranca el motor con Docker y abre el banco de pruebas en el navegador.
chcp 65001 >nul
cd /d "%~dp0"

where docker >nul 2>nul
if errorlevel 1 (
  echo No encuentro Docker. Usa iniciar-sin-docker.bat (no necesita Docker) o instala Docker Desktop.
  pause
  exit /b 1
)
docker info >nul 2>nul
if errorlevel 1 (
  echo Docker no esta funcionando. Si Docker Desktop dice que falta la virtualizacion,
  echo usa iniciar-sin-docker.bat: funciona igual sin Docker.
  pause
  exit /b 1
)

if not exist .env (
  > .env echo KNOK_SECRET_KEY=local-%RANDOM%%RANDOM%%RANDOM%%RANDOM%
  echo Creado .env
)
rem Las versiones anteriores creaban .env "sin red" (solo datos de ejemplo): se quita esa linea
findstr /b /c:"KNOK_OFFLINE_SOURCES=" .env >nul && (
  findstr /v /b /c:"KNOK_OFFLINE_SOURCES=" .env > .env.tmp
  move /y .env.tmp .env >nul
)
findstr /b /c:"KNOK_LOCAL_SINGLE_USER=" .env >nul || >> .env echo KNOK_LOCAL_SINGLE_USER=true

echo Arrancando knok (la primera vez tarda unos minutos)...
docker compose up -d --build
if errorlevel 1 (
  echo No se pudo arrancar. Revisa los mensajes de arriba.
  pause
  exit /b 1
)

echo Esperando a que la API responda...
set /a intentos=0
:esperar
set /a intentos+=1
if %intentos% gtr 60 (
  echo La API no responde. Mira los registros con: docker compose logs api
  pause
  exit /b 1
)
timeout /t 2 >nul
powershell -NoProfile -Command "try { $r = Invoke-WebRequest -UseBasicParsing http://localhost:8000/health; exit 0 } catch { exit 1 }" >nul 2>nul
if errorlevel 1 goto esperar

echo Listo. Abriendo http://localhost:8000/
start "" http://localhost:8000/
echo Para pararlo, ejecuta detener.bat
