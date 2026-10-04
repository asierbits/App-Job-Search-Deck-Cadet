@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo.
echo  Actualizando Busca Practicas...
echo.

where git >nul 2>nul
if errorlevel 1 goto sin_git
if not exist ".git" goto sin_git

rem Tu configuracion, tu cuenta y tus datos no se tocan: no estan en GitHub (.gitignore)
git pull
if errorlevel 1 (
    echo.
    echo  No se pudo actualizar. Si has cambiado algun fichero del programa a mano,
    echo  avisa a quien te lo paso.
    goto fin
)
echo.
echo  Listo. Si el panel estaba abierto, cierralo (ventana negra) y vuelve a abrir iniciar.bat
goto fin

:sin_git
echo  Esta carpeta no se descargo con git, asi que no se puede actualizar sola.
echo.
echo  Para actualizar:
echo   1. Descarga el ZIP nuevo (GitHub: boton verde "Code" y luego "Download ZIP",
echo      o el que te pasen).
echo   2. Descomprimelo ENCIMA de esta carpeta y acepta reemplazar los ficheros.
echo      Tu configuracion, tu cuenta de Gmail y tus datos no se pierden.

:fin
echo.
pause
