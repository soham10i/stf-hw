@echo off
REM STF Digital Twin - Windows Startup Script
REM Run this script from the project root directory

echo ================================================
echo STF Digital Twin - Starting All Services
echo ================================================

REM Check if virtual environment exists
if not exist "venv\Scripts\activate.bat" (
    echo ERROR: Virtual environment not found!
    echo Please run: python -m venv venv
    echo Then: venv\Scripts\activate
    echo Then: pip install -r requirements.txt
    pause
    exit /b 1
)

REM Start FastAPI Server
echo Starting FastAPI Server...
start "STF-API" cmd /k "cd /d %~dp0 && venv\Scripts\activate && python -m uvicorn api.main:app --host 0.0.0.0 --port 8000"
timeout /t 3 /nobreak > nul

REM Start Mock Hardware
echo Starting Mock Hardware Simulation...
start "STF-Hardware" cmd /k "cd /d %~dp0 && venv\Scripts\activate && python -m hardware.mock_factory"
timeout /t 1 /nobreak > nul

REM Start Main Controller
echo Starting Main Controller...
start "STF-Controller" cmd /k "cd /d %~dp0 && venv\Scripts\activate && python -m controller.main_controller"
timeout /t 1 /nobreak > nul

REM Start Streamlit Dashboard
echo Starting Streamlit Dashboard...
start "STF-Dashboard" cmd /k "cd /d %~dp0 && venv\Scripts\activate && streamlit run dashboard/app.py"

echo.
echo ================================================
echo All services started!
echo ================================================
echo.
echo Access Points:
echo   Dashboard:  http://localhost:8501
echo   Analytics:  http://localhost:8501/analytics
echo   API Docs:   http://localhost:8000/docs
echo.
echo Close this window to keep services running.
echo Close individual service windows to stop them.
echo ================================================
pause
