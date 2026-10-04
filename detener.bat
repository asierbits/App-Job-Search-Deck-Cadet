@echo off
rem knok: para el motor (los datos se conservan).
cd /d "%~dp0"
docker compose down
echo knok parado. Tus datos se conservan; vuelve a abrir iniciar.bat cuando quieras.
pause
