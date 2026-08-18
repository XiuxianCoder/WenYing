@echo off
setlocal
cd /d "%~dp0"

set "WENYING_PYTHON="
if exist ".venv\Scripts\pythonw.exe" set "WENYING_PYTHON=%CD%\.venv\Scripts\pythonw.exe"
if not defined WENYING_PYTHON if exist ".venv\Scripts\python.exe" set "WENYING_PYTHON=%CD%\.venv\Scripts\python.exe"
if not defined WENYING_PYTHON for /f "delims=" %%P in ('where pythonw.exe 2^>nul') do if not defined WENYING_PYTHON set "WENYING_PYTHON=%%P"
if not defined WENYING_PYTHON for /f "delims=" %%P in ('where python.exe 2^>nul') do if not defined WENYING_PYTHON set "WENYING_PYTHON=%%P"

if not defined WENYING_PYTHON (
  echo Python 3.10 or newer was not found.
  pause
  exit /b 1
)

for %%I in ("%WENYING_PYTHON%") do set "WENYING_PYTHON_HOME=%%~dpI"
if exist "%WENYING_PYTHON_HOME%Library\lib\tcl8.6" set "TCL_LIBRARY=%WENYING_PYTHON_HOME%Library\lib\tcl8.6"
if exist "%WENYING_PYTHON_HOME%Library\lib\tk8.6" set "TK_LIBRARY=%WENYING_PYTHON_HOME%Library\lib\tk8.6"
if exist "%WENYING_PYTHON_HOME%tcl\tcl8.6" set "TCL_LIBRARY=%WENYING_PYTHON_HOME%tcl\tcl8.6"
if exist "%WENYING_PYTHON_HOME%tcl\tk8.6" set "TK_LIBRARY=%WENYING_PYTHON_HOME%tcl\tk8.6"

start "" "%WENYING_PYTHON%" app.py
endlocal
