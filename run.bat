@echo off
REM Launch without a console window when pythonw is available.
where pythonw >nul 2>nul
if %ERRORLEVEL%==0 (
    start "" pythonw "%~dp0main.py" %*
) else (
    python "%~dp0main.py" %*
)
