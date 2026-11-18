@echo off
setlocal
title Steam Families
set "AQUI=%~dp0."
set "PROGRAMA=%~dp0app.py"
if not exist "%PROGRAMA%" (
  echo No encuentro app.py junto a este fichero.
  pause
  exit /b 1
)
where python >nul 2>nul
if errorlevel 1 (
  echo.
  echo No encuentro Python. Instalalo desde https://www.python.org/downloads/
  echo y vuelve a hacer doble clic en este fichero.
  echo.
  pause
  exit /b 1
)
python "%PROGRAMA%" --datos "%AQUI%"
if errorlevel 1 pause
