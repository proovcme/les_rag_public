@echo off
echo ========================================
echo MyVeras AI Rendering - Build Script
echo ========================================

REM Set paths
set SOLUTION_DIR=%~dp0
set OUTPUT_DIR=C:\ProgramData\Autodesk\Revit\Addins\2025\MyVeras

echo Solution Directory: %SOLUTION_DIR%
echo Output Directory: %OUTPUT_DIR%

REM Create output directory
if not exist "%OUTPUT_DIR%" (
    echo Creating output directory...
    mkdir "%OUTPUT_DIR%"
)

REM Clean output directory
echo Cleaning output directory...
del /Q "%OUTPUT_DIR%\*.*"

echo.
echo ========================================
echo Building projects...
echo ========================================

REM Build all projects in solution
cd /d "%SOLUTION_DIR%"
dotnet build MyVeras.sln --configuration Release --verbosity minimal

if %ERRORLEVEL% neq 0 (
    echo ERROR: Build failed
    goto :error
)

echo.
echo ========================================
echo Copying DLL files...
echo ========================================

REM Copy main DLL
echo Copying MyVeras.RevitAPI.dll...
copy "%SOLUTION_DIR%MyVeras.RevitAPI\bin\Release\net48\MyVeras.RevitAPI.dll" "%OUTPUT_DIR%\"

REM Copy dependency DLLs
echo Copying MyVeras.Models.dll...
copy "%SOLUTION_DIR%MyVeras.Models\bin\Release\net48\MyVeras.Models.dll" "%OUTPUT_DIR%\"

echo Copying MyVeras.Settings.dll...
copy "%SOLUTION_DIR%MyVeras.Settings\bin\Release\net48\MyVeras.Settings.dll" "%OUTPUT_DIR%\"

echo Copying MyVeras.Core.dll...
copy "%SOLUTION_DIR%MyVeras.Core\bin\Release\net48\MyVeras.Core.dll" "%OUTPUT_DIR%\"

echo Copying MyVeras.Engines.dll...
copy "%SOLUTION_DIR%MyVeras.Engines\bin\Release\net48\MyVeras.Engines.dll" "%OUTPUT_DIR%\"

echo Copying MyVeras.UI.dll...
copy "%SOLUTION_DIR%MyVeras.UI\bin\Release\net48\MyVeras.UI.dll" "%OUTPUT_DIR%\"

REM Copy Newtonsoft.Json.dll
echo Copying Newtonsoft.Json.dll...
copy "%SOLUTION_DIR%MyVeras.Settings\bin\Release\net48\Newtonsoft.Json.dll" "%OUTPUT_DIR%\"

REM Copy .addin file
echo Copying MyVeras.addin...
copy "%SOLUTION_DIR%MyVeras.addin" "C:\ProgramData\Autodesk\Revit\Addins\2025\MyVeras.addin"

echo.
echo ========================================
echo Build completed successfully!
echo ========================================
echo Output directory: %OUTPUT_DIR%
echo.
echo To test:
echo 1. Close Revit if running
echo 2. Start Revit 2025
echo 3. Look for "MyVeras AI" button
echo.

goto :end

:error
echo.
echo ========================================
echo BUILD FAILED!
echo ========================================
exit /b 1

:end
cd /d "%SOLUTION_DIR%"
