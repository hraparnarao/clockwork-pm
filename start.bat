@echo off
cd /d "%~dp0"
echo Starting ClockWork PM...
echo.
echo Open your browser at: http://localhost:8765
echo.
python -m uvicorn main:app --port 8765
pause
