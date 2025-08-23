:: This batch file sets up the development environment for the G-Assist Marvel Rivals plugin
@echo off
setlocal

:: Determine if we have 'python' or 'python3' in the path
where /q python
if ERRORLEVEL 1 goto python3
set PYTHON=python
goto setup

:python3
where /q python3
if ERRORLEVEL 1 goto nopython
set PYTHON=python3

:setup
set VENV=.venv

:: Create virtual environment if it doesn't exist
if not exist %VENV% (
    echo Creating virtual environment...
    %PYTHON% -m venv %VENV%
)

:: Activate virtual environment
call %VENV%\Scripts\activate.bat

:: Install dependencies
echo Installing dependencies...
pip install -r requirements.txt

echo.
echo ===================================
echo Setup completed successfully!
echo.
echo Virtual environment created at: %VENV%
echo.
echo To build the plugin, run: build.bat
echo ===================================

call %VENV%\Scripts\deactivate.bat
exit /b 0

:nopython
echo Python needs to be installed and in your path
exit /b 1 