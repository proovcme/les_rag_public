# Сборка MyVeras AI Rendering

## Требования

### Программное обеспечение
- **Visual Studio 2022** или **.NET SDK 8.0**
- **WiX Toolset v4.0+** (для создания MSI установщика)
- **Autodesk Revit 2025** (для тестирования)
- **Windows 10/11** x64

### .NET Packages
```bash
dotnet --version  # 8.0.0+
wix --version    # 4.0.0+
```

## Быстрая сборка

### PowerShell (рекомендуется)
```powershell
# Полная сборка с установщиком
.\build.ps1

# Только сборка без установщика
.\build.ps1 --no-package

# Очистка и пересборка
.\build.ps1 --clean

# Debug конфигурация
.\build.ps1 --debug
```

### Batch файл
```batch
# Полная сборка
build.bat

# С параметрами
build.bat --clean --no-package
```

## Ручная сборка

### 1. Восстановление пакетов
```bash
dotnet restore MyVeras.sln
```

### 2. Сборка решения
```bash
dotnet build MyVeras.sln --configuration Release --platform x64
```

### 3. Публикация установщика
```bash
dotnet publish MyVeras.Setup\MyVeras.Setup.csproj --configuration Release --platform x64
```

### 4. Создание MSI установщика
```bash
wix build MyVeras.Setup.Wix\MyVeras.Setup.Wix.wixproj --configuration Release
```

## Структура сборки

```
MyVeras/
├── build.ps1                 # PowerShell скрипт сборки
├── build.bat                 # Batch скрипт сборки
├── publish/                  # Результаты сборки
│   ├── MyVeras.Setup/        # Публикация приложения
│   └── MyVeras-*.zip         # Архив с установщиком
├── MyVeras.Setup.Wix/
│   └── bin/Release/          # MSI установщик
└── MyVeras.Setup/
    └── bin/x64/Release/      # EXE установщик
```

## Процесс сборки

### Этап 1: Подготовка
- Очистка временных файлов (опционально)
- Восстановление NuGet пакетов
- Проверка зависимостей

### Этап 2: Компиляция
- Сборка всех проектов (.NET Framework 4.8)
- Компиляция WPF интерфейса
- Проверка Revit API совместимости

### Этап 3: Публикация
- Создание самодостаточного EXE файла
- Копирование зависимостей
- Включение ресурсов и конфигураций

### Этап 4: Упаковка
- Создание WiX установщика (MSI)
- Генерация лицензионного соглашения
- Создание ярлыков и записей реестра

### Этап 5: Архивация
- Упаковка в ZIP архив
- Добавление временной метки
- Автоматическое открытие папки с результатами

## Результаты сборки

### Файлы в папке publish/
- **MyVeras.Setup.exe** - Основной установщик
- **MyVeras-AI-Rendering-Setup.msi** - Windows Installer пакет
- **MyVeras-AI-Rendering-YYYYMMDD-HHMMSS.zip** - Архив дистрибутива

### Размеры файлов (приблизительные)
- EXE установщик: ~15 MB
- MSI пакет: ~12 MB  
- ZIP архив: ~8 MB

## Установка

### Автоматическая установка
```bash
# Тихая установка
MyVeras.Setup.exe --silent

# Интерактивная установка
MyVeras.Setup.exe
```

### MSI установка
```bash
# Тихая установка
msiexec /i MyVeras-AI-Rendering-Setup.msi /quiet

# С логом
msiexec /i MyVeras-AI-Rendering-Setup.msi /l*v install.log
```

## Отладка сборки

### Общие проблемы
1. **WiX Toolset не найден** - Установите WiX Toolset v4.0+
2. **Revit API отсутствует** - Установите Revit 2025 или измените пути в .csproj
3. **.NET Framework отсутствует** - Установите .NET Framework 4.8 Developer Pack

### Логирование
```powershell
# Включить детальное логирование
.\build.ps1 -Verbose

# Проверить переменные окружения
$env:PATH
```

### Тестирование
```bash
# Запуск тестов (если есть)
dotnet test MyVeras.Tests --configuration Release

# Проверка установки
.\publish\MyVeras.Setup.exe --dry-run
```

## Разработка

### Добавление новых проектов
1. Создать проект в Visual Studio
2. Добавить в MyVeras.sln
3. Обновить скрипты сборки при необходимости

### Изменение зависимостей
```bash
# Обновить все пакеты
dotnet nuget update MyVeras.sln

# Добавить новый пакет
dotnet add MyVeras.Core package SomePackage
```

### Кастомизация установщика
Изменить файлы в `MyVeras.Setup.Wix/`:
- `MyVeras.Setup.Wix.wixproj` - настройки сборки
- `Product.wxs` - структура установщика
- `License.rtf` - лицензионное соглашение

## CI/CD Интеграция

### GitHub Actions
```yaml
- name: Build MyVeras
  run: ./build.ps1 --clean --no-package
```

### Azure DevOps
```yaml
- task: DotNetCoreCLI@2
  inputs:
    command: 'build'
    projects: 'MyVeras.sln'
```

## Поддержка

При проблемах со сборкой:
1. Проверьте системные требования
2. Очистите и пересоберите проект
3. Проверьте логи сборки
4. Обратитесь к документации Revit API
