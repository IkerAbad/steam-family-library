@echo off
setlocal
title Steam Families
set "PY=python"
where python >nul 2>nul
if errorlevel 1 (
  where py >nul 2>nul
  if errorlevel 1 (
    echo.
    echo No encuentro Python. Instala Python desde https://www.python.org/downloads/
    echo y vuelve a hacer doble clic en este fichero.
    echo.
    pause
    exit /b 1
  )
  set "PY=py -3"
)
%PY% "%~dp0steam_families.py" --datos "%~dp0datos"
if errorlevel 1 pause
