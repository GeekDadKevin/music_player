@echo off
:: Build music_player.exe — single self-contained executable.
::
:: Prerequisites (run once):
::   uv add --dev pyinstaller
::
:: After building, copy your .env into dist\ before running:
::   copy .env dist\.env

setlocal

set ROOT=%~dp0..
cd /d "%ROOT%"

echo [build] Cleaning previous output...
if exist dist\music_player.exe del /f /q dist\music_player.exe
if exist dist\music_player     rmdir /s /q dist\music_player
if exist build                 rmdir /s /q build

echo [build] Running PyInstaller (onefile)...
uv run pyinstaller music_player.spec
if errorlevel 1 (
    echo [build] FAILED.
    exit /b 1
)

echo.
echo [build] Done.  Output: dist\music_player.exe
echo [build] Remember to copy your .env file:
echo         copy .env dist\.env
echo.

endlocal
