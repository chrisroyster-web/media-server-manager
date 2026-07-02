@echo off
setlocal enabledelayedexpansion

echo ============================================================
echo  All Clear Server Services — Release Build
echo ============================================================
echo.

:: ── Locate iscc.exe ─────────────────────────────────────────
set ISCC=
if exist "C:\Program Files (x86)\Inno Setup 6\iscc.exe" (
    set "ISCC=C:\Program Files (x86)\Inno Setup 6\iscc.exe"
) else if exist "C:\Program Files\Inno Setup 6\iscc.exe" (
    set "ISCC=C:\Program Files\Inno Setup 6\iscc.exe"
)

if "%ISCC%"=="" (
    echo ERROR: Inno Setup 6 not found.
    echo        Install from https://jrsoftware.org/isdl.php
    goto :fail
)

:: ── Step 1: PyInstaller ─────────────────────────────────────
echo [1/2] Running PyInstaller...
echo.
pyinstaller main.spec --noconfirm
if errorlevel 1 (
    echo.
    echo ERROR: PyInstaller failed.
    goto :fail
)

echo.
echo [2/2] Running Inno Setup...
echo.
"%ISCC%" AllClearServerServices_Setup.iss
if errorlevel 1 (
    echo.
    echo ERROR: Inno Setup compile failed.
    goto :fail
)

echo.
echo ============================================================
echo  BUILD COMPLETE
echo  Output: installer_output\
dir /b installer_output\*.exe 2>nul
echo ============================================================
goto :end

:fail
echo.
echo ============================================================
echo  BUILD FAILED — see errors above
echo ============================================================
exit /b 1

:end
endlocal
