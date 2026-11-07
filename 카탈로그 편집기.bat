@echo off
chcp 65001 >nul
cd /d "%~dp0"
python --version >nul 2>nul
if not errorlevel 1 (
  python editor_server.py --open
  goto done
)
py -3 --version >nul 2>nul
if not errorlevel 1 (
  py -3 editor_server.py --open
  goto done
)
echo.
powershell -NoProfile -Command "Write-Host ([regex]::Unescape('\uD30C\uC774\uC36C(Python)\uC774 \uC774 \uCEF4\uD4E8\uD130\uC5D0 \uC124\uCE58\uB418\uC5B4 \uC788\uC9C0 \uC54A\uC2B5\uB2C8\uB2E4.\nhttps://www.python.org/downloads/ \uC5D0\uC11C Python 3 \uB97C \uC124\uCE58\uD55C \uB4A4 \uC774 \uC544\uC774\uCF58\uC744 \uB2E4\uC2DC \uB450 \uBC88 \uB20C\uB7EC \uC8FC\uC138\uC694.\n(\uC124\uCE58 \uCCAB \uD654\uBA74\uC5D0\uC11C Add python.exe to PATH \uCE78\uC744 \uAF2D \uCCB4\uD06C\uD558\uC138\uC694)'))"
echo (Python is not installed: https://www.python.org/downloads/)
:done
echo.
pause
