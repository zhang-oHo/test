@echo off
setlocal enabledelayedexpansion

set "PROJECT_ROOT=%~dp0.."
pushd "%PROJECT_ROOT%"
set "PROJECT_ROOT=%CD%"
popd

set "ENV_FILE=%PROJECT_ROOT%\.env"

if exist "%ENV_FILE%" (
    for /f "usebackq tokens=1* delims== eol=#" %%K in ("%ENV_FILE%") do (
        set "_k=%%K"
        set "_v=%%~L"
        rem %%~L strips surrounding double-quotes; handle single-quotes manually
        if "!_v:~0,1!"=="'" if "!_v:~-1!"=="'" set "_v=!_v:~1,-1!"
        set "!_k!=!_v!"
    )
) else (
    echo WARNING: .env not found at %ENV_FILE% -- starting with system environment variables only. 1>&2
)

if not defined APP_PORT set "APP_PORT=8000"
if "%APP_PORT%"=="" set "APP_PORT=8000"

set "UVICORN=%PROJECT_ROOT%\.venv\Scripts\uvicorn.exe"
if not exist "%UVICORN%" (
    echo ERROR: Cannot find %UVICORN%. Create the virtual environment and install dependencies first. 1>&2
    exit /b 1
)

cd /d "%PROJECT_ROOT%"
"%UVICORN%" app.main:app --host 0.0.0.0 --port %APP_PORT% --reload
exit /b %ERRORLEVEL%
