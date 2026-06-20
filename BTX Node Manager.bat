@echo off
title BTX Node Manager
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
  echo Creating virtual environment...
  python -m venv .venv
  if errorlevel 1 (
    echo Python not found. Install Python 3.10+ from https://www.python.org/downloads/
    pause
    exit /b 1
  )
  call .venv\Scripts\pip install -r requirements.txt
)

start "" ".venv\Scripts\pythonw.exe" -m btx_node_gui