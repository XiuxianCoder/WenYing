@echo off
setlocal
cd /d "%~dp0"

if exist "release\win-unpacked\文映 WenYing.exe" (
  start "" "release\win-unpacked\文映 WenYing.exe"
  exit /b 0
)

set "WENYING_NPM="
for /f "delims=" %%P in ('where npm.cmd 2^>nul') do if not defined WENYING_NPM set "WENYING_NPM=%%P"
if not defined WENYING_NPM if exist "C:\nvm4w\nodejs\npm.cmd" set "WENYING_NPM=C:\nvm4w\nodejs\npm.cmd"
if not defined WENYING_NPM (
  echo npm was not found. Install Node.js 22.12 or newer.
  pause
  exit /b 1
)

if not exist "node_modules\electron\dist\electron.exe" (
  echo Electron dependencies are not installed.
  echo Run: npm install
  pause
  exit /b 1
)

if not exist "dist\index.html" (
  call "%WENYING_NPM%" run build:web
  if errorlevel 1 exit /b 1
)

start "" /min cmd.exe /c call "%WENYING_NPM%" run start
endlocal
