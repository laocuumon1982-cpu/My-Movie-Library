@echo off
chcp 65001 >nul
cd /d "%~dp0"
python -c "import webview" 2>nul || python -m pip install --user pywebview
python mml.py || pause
