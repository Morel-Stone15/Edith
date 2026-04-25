@echo off
echo ==========================================
echo    EDITH CORE STARTUP (Python Flask)
echo ==========================================
echo.
echo Activation de l'environnement virtuel...
if not exist .venv (
    echo [ERROR] Environnement virtuel .venv introuvable.
    pause
    exit /b 1
)

:: Chemin vers le python de l'environnement virtuel
set VENV_PYTHON=.venv\Scripts\python.exe

echo Verification des dependances...
%VENV_PYTHON% -m pip install -r requirements.txt | findstr /V "already satisfied"

echo.
echo Démarrage du serveur EDITH...
echo Accès local  : http://127.0.0.1:3000
echo Accès Mobile : http://192.168.1.77:3000 (Vérifiez votre IP avec ipconfig)
echo.

%VENV_PYTHON% app.py

echo.
echo [INFO] Serveur arrêté.
pause
