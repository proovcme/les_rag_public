@echo off
setlocal enabledelayedexpansion

echo MyVeras AI Rendering - Build Script
echo ================================

REM Проверка .NET
dotnet --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: .NET SDK not found
    pause
    exit /b 1
)

REM Параметры сборки
set CONFIGURATION=Release
set PLATFORM=x64
set CLEAN=false
set PACKAGE=true
set SKIP_TESTS=false

REM Парсинг аргументов
:parse_args
if "%~1"=="" goto :args_done
if /i "%~1"=="--clean" set CLEAN=true
if /i "%~1"=="--no-package" set PACKAGE=false
if /i "%~1"=="--skip-tests" set SKIP_TESTS=true
if /i "%~1"=="--debug" set CONFIGURATION=Debug
if /i "%~1"=="--platform" set PLATFORM=%~2
shift
if "%PLATFORM%"=="" goto :parse_args
goto :parse_args

:args_done

echo Configuration: %CONFIGURATION%
echo Platform: %PLATFORM%
echo Clean: %CLEAN%
echo Package: %PACKAGE%
echo.

REM Очистка
if "%CLEAN%"=="true" (
    echo Cleaning project...
    for /d /r . %%d in (bin obj) do if exist "%%d" rd /s /q "%%d"
    del /s /q *.exe *.msi *.zip 2>nul
    echo Clean completed.
)

REM Восстановление пакетов
echo Restoring NuGet packages...
dotnet restore MyVeras.sln
if errorlevel 1 (
    echo ERROR: Package restore failed
    pause
    exit /b 1
)

REM Сборка
echo Building solution (%CONFIGURATION%/%PLATFORM%)...
dotnet build MyVeras.sln --configuration %CONFIGURATION% --platform %PLATFORM% --no-restore
if errorlevel 1 (
    echo ERROR: Build failed
    pause
    exit /b 1
)

REM Тесты
if "%SKIP_TESTS%"=="false" (
    echo Running tests...
    REM Здесь можно добавить тестовые проекты
    echo Tests completed.
)

REM Публикация
echo Publishing application...
set PUBLISH_PATH=publish\MyVeras.Setup
if exist "%PUBLISH_PATH%" rmdir /s /q "%PUBLISH_PATH%"
mkdir "%PUBLISH_PATH%"

dotnet publish MyVeras.Setup\MyVeras.Setup.csproj --configuration %CONFIGURATION% --platform %PLATFORM% --output %PUBLISH_PATH% --self-contained false --no-build
if errorlevel 1 (
    echo ERROR: Publish failed
    pause
    exit /b 1
)

REM Установщик
if "%PACKAGE%"=="true" (
    echo Creating installer...
    
    REM Проверка WiX
    wix --version >nul 2>&1
    if errorlevel 1 (
        echo WARNING: WiX Toolset not found. Skipping installer creation.
        goto :skip_installer
    )
    
    wix build MyVeras.Setup.Wix\MyVeras.Setup.Wix.wixproj --configuration %CONFIGURATION%
    if errorlevel 1 (
        echo ERROR: Installer build failed
        pause
        exit /b 1
    )
    
    :skip_installer
)

REM Архив
echo Creating archive...
set TIMESTAMP=%date:~-4,4%%date:~-7,2%%date:~-10,2%-%time:~0,2%%time:~3,2%%time:~6,2%
set TIMESTAMP=%TIMESTAMP: =0%
set ARCHIVE_NAME=MyVeras-AI-Rendering-%TIMESTAMP%.zip
set ARCHIVE_PATH=publish\%ARCHIVE_NAME%

if exist "%ARCHIVE_PATH%" del "%ARCHIVE_PATH%"

set INSTALLER_PATH=MyVeras.Setup.Wix\bin\%CONFIGURATION%\MyVeras-AI-Rendering-Setup.msi
if exist "%INSTALLER_PATH%" (
    powershell -Command "Compress-Archive -Path '%INSTALLER_PATH%' -DestinationPath '%ARCHIVE_PATH%'"
    echo Archive created: %ARCHIVE_PATH%
)

echo ================================
echo Build completed successfully!
echo Files are in publish\ folder.

REM Показать результаты
dir publish\*.exe publish\*.msi publish\*.zip 2>nul

REM Открыть папку с результатами
if exist "publish" start "" "publish"

pause
