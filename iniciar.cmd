@echo off
setlocal
title Steam Families
where python >nul 2>nul
if errorlevel 1 (
  echo.
  echo No encuentro Python. Instala Python desde https://www.python.org/downloads/
  echo y vuelve a hacer doble clic en este fichero.
  echo.
  pause
  exit /b 1
)
python "%~dp0steam_families.py" --datos "%~dp0."
if errorlevel 1 pause
