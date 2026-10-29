@echo off
title Dong Goi AoE1 Launcher thanh file EXE
cd /d "%~dp0"
echo ========================================================
echo   DANG DONG GOI AOE 1 LAUNCHER THANH FILE EXE DUY NHAT
echo ========================================================
echo.
echo Dang chay PyInstaller trong .venv...
".venv\Scripts\pyinstaller.exe" --noconsole --onefile --clean --name "AoE1_Launcher" aoe_gui.py

echo.
if exist "dist\AoE1_Launcher.exe" (
    echo [OK] DA DONG GOI THANH CONG!
    echo File EXE nam tai: dist\AoE1_Launcher.exe
    echo.
    echo Ban co the copy file AoE1_Launcher.exe de gui cho ban be choi cung.
) else (
    echo [LOI] Co van de xay ra trong qua trinh dong goi.
)
echo.
pause
