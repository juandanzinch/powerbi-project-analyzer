@echo off
REM Windows batch script to run Power BI analyzer
REM Supports multiple .pbip files and batch processing

if "%1"=="" (
    echo.
    echo Power BI Analyzer - Usage
    echo ========================
    echo.
    echo Analyze a specific .pbip file:
    echo   run.bat ..\RecursosFuente\MyProject.pbip
    echo.
    echo Analyze all .pbip files in a folder:
    echo   run.bat ..\RecursosFuente\
    echo.
    echo Analyze from current folder:
    echo   run.bat .
    echo.
    goto end
)

python main.py %1

:end
