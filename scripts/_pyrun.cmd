@echo off
REM Cross-platform Python launcher for AI log hooks (Windows cmd.exe).
REM Tries python -> python3 -> py -3 in order, runs the given script with all args.
REM Exits 0 silently if no Python is found - hooks must never block the AI tool.

where python >nul 2>nul
if not errorlevel 1 (
  python %*
  exit /b 0
)

where python3 >nul 2>nul
if not errorlevel 1 (
  python3 %*
  exit /b 0
)

if exist "%LocalAppData%\Programs\Python\Python310\python.exe" (
  "%LocalAppData%\Programs\Python\Python310\python.exe" %*
  exit /b 0
)

where py >nul 2>nul
if not errorlevel 1 (
  py -3 %*
  exit /b 0
)

exit /b 0
