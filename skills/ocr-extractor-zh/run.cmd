@echo off
REM ocr-extractor-zh launcher (Windows).
REM
REM Purpose: find a usable Python 3.9+ and forward all arguments to the main script.
REM Why: GUI-launched processes often do not inherit the shell PATH, so hardcoding
REM      "python3" fails on many user machines.
REM
REM NOTE: This file is deliberately ASCII-only. cmd.exe reads a .bat/.cmd file using
REM       the console OEM code page (e.g. cp936 on Chinese Windows), so non-ASCII
REM       characters here would be displayed as mojibake. UTF-8 continuation bytes can
REM       never be ASCII, so such a file still *parses* correctly, but every message
REM       the user sees would be unreadable -- which is exactly when they need it most.
REM       User-facing Chinese messages are produced by the Python scripts instead.

setlocal EnableExtensions
set "HERE=%~dp0"
set "MAIN=%HERE%scripts\ocr_cli.py"

if not exist "%MAIN%" (
  echo [ERROR] Main script not found: %MAIN% 1>&2
  exit /b 4
)

REM Keep Python console output on UTF-8 so Chinese results are readable
set "PYTHONIOENCODING=utf-8"
set "PYTHONUTF8=1"

set "PY="

if defined PYTHON (
  "%PYTHON%" -c "import sys; sys.exit(0 if sys.version_info>=(3,9) else 1)" >nul 2>&1 && set "PY=%PYTHON%"
)
if not defined PY (
  py -3 -c "import sys; sys.exit(0 if sys.version_info>=(3,9) else 1)" >nul 2>&1 && set "PY=py -3"
)
if not defined PY (
  python -c "import sys; sys.exit(0 if sys.version_info>=(3,9) else 1)" >nul 2>&1 && set "PY=python"
)
if not defined PY (
  python3 -c "import sys; sys.exit(0 if sys.version_info>=(3,9) else 1)" >nul 2>&1 && set "PY=python3"
)
if not defined PY (
  for /f "delims=" %%D in ('dir /b /o-n "%LOCALAPPDATA%\Programs\Python\Python3*" 2^>nul') do (
    if exist "%LOCALAPPDATA%\Programs\Python\%%D\python.exe" set "PY=%LOCALAPPDATA%\Programs\Python\%%D\python.exe"
  )
)

if not defined PY (
  echo [ERROR] Python 3.9 or newer was not found. 1>&2
  echo. 1>&2
  echo How to install: 1>&2
  echo   1^) Microsoft Store: search for "Python 3.12" and install. 1>&2
  echo   2^) https://www.python.org/downloads/windows/ -- during setup, 1>&2
  echo      make sure "Add python.exe to PATH" is checked. 1>&2
  echo. 1>&2
  echo You can also point at an existing interpreter explicitly: 1>&2
  echo   set PYTHON=C:\path\to\python.exe ^&^& run.cmd ... 1>&2
  exit /b 3
)

if "%DOC_MEDIA_SKILLS_DEBUG%"=="1" echo [debug] interpreter: %PY% 1>&2

%PY% "%MAIN%" %*
exit /b %ERRORLEVEL%
