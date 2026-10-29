@echo off
title AOE 1 Multiplayer Helper
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" aoe_gui.py
) else (
    python aoe_gui.py
)
pause
