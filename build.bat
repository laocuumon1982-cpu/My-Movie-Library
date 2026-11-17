@echo off
chcp 65001 >nul
cd /d "%~dp0"
python -m pip install --upgrade pyinstaller pywebview
python -m PyInstaller --noconfirm --clean --onefile --noconsole --name "My Movie Library" --icon icon.ico --add-data "icon.ico;." --add-data "web;web" --hidden-import webapp --hidden-import app --collect-all webview --collect-all pythonnet --collect-all clr_loader mml.py
if not exist portable\Data mkdir portable\Data
copy /y "dist\My Movie Library.exe" portable\ >nul
copy /y Data\HUONG_DAN.txt portable\Data\ >nul
copy /y README_PORTABLE.txt portable\README.txt >nul
echo.
echo Xong: dist\My Movie Library.exe  va thu muc portable\
pause
