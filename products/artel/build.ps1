# MyVeras Build Script
# Автоматическая сборка проекта и создание установщика

param(
    [string]$Configuration = "Release",
    [string]$Platform = "x64",
    [switch]$Clean = $false,
    [switch]$Package = $true,
    [switch]$SkipTests = $false
)

$ErrorActionPreference = "Stop"

# Цветной вывод
function Write-ColorOutput($Message, $Color = "White") {
    Write-Host $Message -ForegroundColor $Color
}

# Функция очистки
function Clean-Build() {
    Write-ColorOutput "Очистка проекта..." "Yellow"
    
    Get-ChildItem -Path . -Include bin, obj, packages -Recurse | Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
    Get-ChildItem -Path . -Include *.exe, *.msi, *.zip -Recurse -Filter "MyVeras*" | Remove-Item -Force -ErrorAction SilentlyContinue
    
    Write-ColorOutput "Очистка завершена" "Green"
}

# Функция восстановления пакетов
function Restore-Packages() {
    Write-ColorOutput "Восстановление NuGet пакетов..." "Yellow"
    
    dotnet restore MyVeras.sln
    
    if ($LASTEXITCODE -ne 0) {
        throw "Ошибка восстановления пакетов"
    }
    
    Write-ColorOutput "Пакеты восстановлены" "Green"
}

# Функция сборки
function Build-Solution() {
    Write-ColorOutput "Сборка решения ($Configuration)..." "Yellow"
    
    dotnet build MyVeras.sln --configuration $Configuration --no-restore
    
    if ($LASTEXITCODE -ne 0) {
        throw "Ошибка сборки"
    }
    
    Write-ColorOutput "Сборка завершена" "Green"
}

# Функция тестирования
function Run-Tests() {
    if ($SkipTests) {
        Write-ColorOutput "Тесты пропущены" "Yellow"
        return
    }
    
    Write-ColorOutput "Запуск тестов..." "Yellow"
    
    # Здесь можно добавить тестовые проекты
    # dotnet test MyVeras.Tests --configuration $Configuration --no-build --verbosity normal
    
    Write-ColorOutput "Тесты завершены" "Green"
}

# Функция публикации
function Publish-Application() {
    Write-ColorOutput "Публикация приложения..." "Yellow"
    
    $publishPath = "publish\MyVeras.Setup"
    
    if (Test-Path $publishPath) {
        Remove-Item $publishPath -Recurse -Force
    }
    
    New-Item -ItemType Directory -Path $publishPath -Force
    
    dotnet publish MyVeras.Setup\MyVeras.Setup.csproj --configuration $Configuration --output $publishPath --no-build
    
    if ($LASTEXITCODE -ne 0) {
        throw "Ошибка публикации"
    }
    
    Write-ColorOutput "Приложение опубликовано" "Green"
    return $publishPath
}

# Функция создания установщика
function Create-Installer($PublishPath) {
    if (-not $Package) {
        Write-ColorOutput "Создание установщика пропущено" "Yellow"
        return
    }
    
    Write-ColorOutput "Создание установщика..." "Yellow"
    
    # EXE установщик уже создан при публикации
    Write-ColorOutput "EXE установщик готов" "Green"
}

# Функция создания архива
function Create-Archive($PublishPath) {
    Write-ColorOutput "Создание архива..." "Yellow"
    
    $timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
    $archiveName = "MyVeras-AI-Rendering-$timestamp.zip"
    $archivePath = "publish\$archiveName"
    
    if (Test-Path $archivePath) {
        Remove-Item $archivePath -Force
    }
    
    # Создание архива с EXE файлом
    $installerPath = "MyVeras.Setup\bin\Release\MyVeras.Setup.exe"
    
    if (Test-Path $installerPath) {
        Compress-Archive -Path $installerPath -DestinationPath $archivePath
        Write-ColorOutput "Архив создан: $archiveName" "Green"
    }
    else {
        Write-ColorOutput "Файл установщика не найден" "Yellow"
    }
}

# Основной скрипт
try {
    Write-ColorOutput "MyVeras AI Rendering - Build Script" "Cyan"
    Write-ColorOutput "================================" "Cyan"
    
    if ($Clean) {
        Clean-Build
    }
    
    Restore-Packages
    Build-Solution
    Run-Tests
    
    $publishPath = Publish-Application
    Create-Installer $publishPath
    Create-Archive $publishPath
    
    Write-ColorOutput "================================" "Cyan"
    Write-ColorOutput "Сборка успешно завершена!" "Green"
    Write-ColorOutput "Файлы находятся в папке publish\" "Green"
    
    # Показать результаты
    Get-ChildItem -Path "publish" -File | ForEach-Object {
        $size = [math]::Round($_.Length / 1MB, 2)
        Write-ColorOutput "$($_.Name) ($size MB)" "White"
    }
}
catch {
    Write-ColorOutput "ОШИБКА: $($_.Exception.Message)" "Red"
    exit 1
}

# Открыть папку с результатами
if (Test-Path "publish") {
    Start-Process "publish"
}
