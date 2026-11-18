@echo off
setlocal
cd /d "%~dp0"
echo This build script must run on Windows 10/11 x64 with Python 3.11+ and Inno Setup 6 installed.
where py >nul 2>nul || (echo Python launcher not found. Install Python 3.11+ and retry.& pause& exit /b 1)
if not exist .build-venv py -3 -m venv .build-venv
call .build-venv\Scripts\activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt pyinstaller
pyinstaller --noconfirm --clean --windowed --name Hamkaraneh --collect-all fastapi --collect-all starlette --collect-all uvicorn --collect-all multipart --collect-all itsdangerous launcher.py
if errorlevel 1 (echo PyInstaller failed.& pause& exit /b 1)
set ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe
if not exist "%ISCC%" set ISCC=%ProgramFiles%\Inno Setup 6\ISCC.exe
if not exist "%ISCC%" (echo Inno Setup 6 compiler not found. Install it then retry.& pause& exit /b 1)
"%ISCC%" Hamkaraneh.iss
if errorlevel 1 (echo Installer compilation failed.& pause& exit /b 1)
echo Done. Installer is in the output folder.
pause
