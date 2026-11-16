@echo off
setlocal
cd /d "%~dp0"
rem Use a Python runtime already included with Codex when no Python launcher is installed.
where py >nul 2>&1
if errorlevel 1 goto codex_runtime
if not exist ".venv\Scripts\python.exe" (
    py -3 -m venv .venv
    if errorlevel 1 (
        echo Python 3.10 or newer is required. Install Python with its Windows launcher.
        pause
        exit /b 1
    )
)
".venv\Scripts\python.exe" -c "from PIL import Image; from pillow_heif import register_heif_opener" >nul 2>&1
if errorlevel 1 (
    ".venv\Scripts\python.exe" -m pip install -r requirements.txt
    if errorlevel 1 (
        echo Setup needs an internet connection to install the image decoders.
        pause
        exit /b 1
    )
)
".venv\Scripts\python.exe" app.py %*
pause
exit /b

:codex_runtime
set "CNS_PYTHON="
for /d %%R in ("%ProgramFiles%\WindowsApps\OpenAI.CodexPrimaryRuntime*") do if exist "%%R\dependencies\python\python.exe" set "CNS_PYTHON=%%R\dependencies\python\python.exe"
if not defined CNS_PYTHON (
    echo Python 3.10 or newer is required. See README.md for setup instructions.
    pause
    exit /b 1
)
"%CNS_PYTHON%" -c "from PIL import Image" >nul 2>&1
if errorlevel 1 (
    echo Pillow is missing. See README.md for manual setup instructions.
    pause
    exit /b 1
)
"%CNS_PYTHON%" -c "import pillow_heif" >nul 2>&1
if errorlevel 1 echo HEIC support needs the manual setup in README.md. Other supported images remain available.
"%CNS_PYTHON%" app.py %*
pause
