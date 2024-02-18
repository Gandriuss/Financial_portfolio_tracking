rem Running PortfolioTracking/Code/main.py
@echo off

rem Affect only local variables:
setlocal

rem Path to the file that stores the last run date:
set LAST_RUN_FILE=C:/Users/andrius.resetnikovas/Documents/PortfolioTracking/Code/scheduler/last_run_date.txt

rem Get today's date in YYYY-MM-DD format, i.e. Retrieve local DateTime and parse it within a loop then truncate for date:
for /f "tokens=2 delims==" %%I in ('wmic os get localdatetime /value') do set datetime=%%I
set TODAY=%datetime:~0,4%-%datetime:~4,2%-%datetime:~6,2%

rem Check if the last run file exists and read the date:
if exist "%LAST_RUN_FILE%" (
    set /p LAST_RUN=<"%LAST_RUN_FILE%"
) else (
    set LAST_RUN=
)

rem Check if the script ran today:
if "%TODAY%"=="%LAST_RUN%" (
    rem Exit if the script ran today
    goto end
)

rem Run portfolio tracking script:
python C:/Users/andrius.resetnikovas/Documents/PortfolioTracking/Code/main.py

rem Update the last run file with today's date:
echo %TODAY% > "%LAST_RUN_FILE%"

:end
endlocal