@echo off
setlocal
set "PYTHONUTF8=1"
cd /d "%~dp0"
set "DEMO_PYTHON=python"
if exist "D:\ProgramData\anaconda3\python.exe" set "DEMO_PYTHON=D:\ProgramData\anaconda3\python.exe"
if defined DONG_LANPEC_PYTHON set "DEMO_PYTHON=%DONG_LANPEC_PYTHON%"
"%DEMO_PYTHON%" "%~dp0main.py" %*
set "DEMO_EXIT=%ERRORLEVEL%"
if not "%DEMO_EXIT%"=="0" (
  echo.
  echo [ERROR] The design assistant could not start. See the error above.
  echo Python: "%DEMO_PYTHON%"
  pause
)
exit /b %DEMO_EXIT%
