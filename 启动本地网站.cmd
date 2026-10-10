@echo off
setlocal
cd /d "%~dp0"
set "CENTER_NODE=node"
where node.exe >nul 2>nul
if not errorlevel 1 goto pythoncheck
set "CENTER_NODE=%USERPROFILE%\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin\node.exe"
if exist "%CENTER_NODE%" goto pythoncheck
echo Node.js 20+ is required. Install Node.js, then try again.
pause
exit /b 1
:pythoncheck
set "CENTER_PYTHON=%LOCAL_CENTER_PYTHON%"
if defined CENTER_PYTHON goto verify
set "CENTER_PYTHON=%USERPROFILE%\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
if exist "%CENTER_PYTHON%" goto verify
set "CENTER_PYTHON=python"
:verify
"%CENTER_PYTHON%" -c "import sys; assert sys.version_info >= (3,10)" >nul 2>nul
if not errorlevel 1 goto ready
echo Python 3.10+ is required. Install Python or set LOCAL_CENTER_PYTHON.
pause
exit /b 1
:ready
set "LOCAL_CENTER_PYTHON=%CENTER_PYTHON%"
set "CENTER_PORT=8777"
if defined PORT set "CENTER_PORT=%PORT%"
echo Admin: http://127.0.0.1:%CENTER_PORT%/admin
echo Members: create a user in Admin and copy their personal portal link.
echo Keep this window open. Press Ctrl+C to stop the software.
start "" "http://127.0.0.1:%CENTER_PORT%/admin"
"%CENTER_NODE%" server.js
if errorlevel 1 pause
endlocal
