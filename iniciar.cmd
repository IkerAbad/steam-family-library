@echo off
title Steam Families
where python >nul 2>nul
if errorlevel 1 (
  echo.
  echo No encuentro Python. Instalalo desde https://www.python.org/downloads/
  echo y vuelve a hacer doble clic en este fichero.
  echo.
  pause
  exit /b 1
)
python "%~dp0app.py" --datos "%~dp0"
if errorlevel 1 pause
