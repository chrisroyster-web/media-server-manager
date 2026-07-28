@echo off
setlocal enabledelayedexpansion

rem -- Locate iscc.exe --
set ISCC=
if exist "C:\Program Files (x86)\Inno Setup 6\iscc.exe" (
    set "ISCC=C:\Program Files (x86)\Inno Setup 6\iscc.exe"
) else if exist "C:\Program Files\Inno Setup 6\iscc.exe" (
    set "ISCC=C:\Program Files\Inno Setup 6\iscc.exe"
) else if exist "%LOCALAPPDATA%\Programs\Inno Setup 6\iscc.exe" (
    set "ISCC=%LOCALAPPDATA%\Programs\Inno Setup 6\iscc.exe"
)

if "%ISCC%"=="" (
    echo ERROR: Inno Setup 6 not found.
    echo        Install from https://jrsoftware.org/isdl.php
    exit /b 1
)

echo [1/2] Running PyInstaller...
pyinstaller MediaServerManager.spec --noconfirm
if errorlevel 1 (
    echo ERROR: PyInstaller failed.
    exit /b 1
)

echo.
echo [2/2] Running Inno Setup...
"%ISCC%" AllClearServerServices_Setup.iss
if errorlevel 1 (
    echo ERROR: Inno Setup compile failed.
    exit /b 1
)

echo.
echo BUILD COMPLETE -- installer_output\
dir /b installer_output\*.exe 2>nul

endlocal
