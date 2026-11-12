@echo off
rem ---------------------------------------------------------------
rem  Springtrap - lanzador con interfaz GUI para Windows
rem  Uso:  Springtrap.bat              (conversacion con interfaz grafica)
rem ---------------------------------------------------------------

chcp 65001 >nul
setlocal

set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"

cd /d "%~dp0"

rem --- Mandibula (servo en ESP32) ---
rem  Guia: docs\MANDIBULA.md
set "SPRINGTRAP_JAW=1"
set "SPRINGTRAP_JAW_PORT=COM6"
set "SPRINGTRAP_JAW_MIN=10"
set "SPRINGTRAP_JAW_MAX=36"
set "SPRINGTRAP_JAW_FLOOR=-38"
set "SPRINGTRAP_JAW_CEIL=-18"
set "SPRINGTRAP_JAW_GAMMA=0.55"
set "SPRINGTRAP_JAW_ATTACK=0.9"
set "SPRINGTRAP_JAW_RELEASE=0.35"
set "SPRINGTRAP_JAW_SLEW=1200"
set "SPRINGTRAP_JAW_DEADBAND=1"

rem --- Verificar entorno virtual ---
set "PY=%~dp0.venv\Scripts\python.exe"
if not exist "%PY%" (
    echo  [ERROR] No encuentro el entorno virtual en: %PY%
    echo  Crealo una sola vez desde esta carpeta:
    echo      py -3.14 -m venv .venv
    echo      .venv\Scripts\python.exe -m pip install -r requirements.txt
    echo.
    pause
    exit /b 1
)

rem --- Ejecutar interfaz GUI ---
"%PY%" gui.py
set "CODIGO=%ERRORLEVEL%"

if not "%CODIGO%"=="0" (
    echo.
    echo  Springtrap termino con codigo %CODIGO%.
    pause
)

endlocal & exit /b %CODIGO%
