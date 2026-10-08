@echo off
rem Rebuild everything from the CSV files in data\ (Windows).
cd /d "%~dp0"
python src\build_db.py || goto :error
python src\run_queries.py > nul || goto :error
python src\analysis.py > nul || goto :error
python src\charts.py || goto :error
python src\build_dashboard.py || goto :error
python src\checks.py || goto :error
echo.
echo Done. Open dashboard\index.html in a browser.
exit /b 0

:error
echo.
echo A step failed. Read the message above.
exit /b 1
