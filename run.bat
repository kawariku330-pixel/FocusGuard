@echo off
cd /d "%~dp0"

set "PYTHONW_CMD="
if exist "%LOCALAPPDATA%\Python\pythoncore-3.14-64\pythonw.exe" (
    set "PYTHONW_CMD=%LOCALAPPDATA%\Python\pythoncore-3.14-64\pythonw.exe"
) else (
    where pythonw >nul 2>&1
    if %errorlevel% equ 0 (
        set "PYTHONW_CMD=pythonw"
    ) else if exist "%LOCALAPPDATA%\Programs\Python\Python314\pythonw.exe" (
        set "PYTHONW_CMD=%LOCALAPPDATA%\Programs\Python\Python314\pythonw.exe"
    ) else (
        where pyw >nul 2>&1
        if %errorlevel% equ 0 (
            set "PYTHONW_CMD=pyw"
        ) else (
            where python >nul 2>&1
            if %errorlevel% equ 0 (
                set "PYTHONW_CMD=python"
            )
        )
    )
)

if "%PYTHONW_CMD%"=="" (
    echo [ERROR] Python not found. Please install Python.
    pause
    exit /b 1
)

start "" "%PYTHONW_CMD%" "%~dp0focus_guard.pyw"
