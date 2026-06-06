using System;
using System.IO;
using System.Threading.Tasks;
using Microsoft.Extensions.Logging;
using MyVeras.Setup.Models;

namespace MyVeras.Setup.Services
{
    /// <summary>
    /// Реализация сервиса установки
    /// </summary>
    public class InstallationService : IInstallationService
    {
        private readonly ILogger<InstallationService> _logger;
        private readonly IRevitService _revitService;
        private readonly IFileService _fileService;

        public InstallationService(
            ILogger<InstallationService> logger,
            IRevitService revitService,
            IFileService fileService)
        {
            _logger = logger;
            _revitService = revitService;
            _fileService = fileService;
        }

        public async Task<InstallationResult> InstallAsync()
        {
            try
            {
                _logger.LogInformation("Starting MyVeras installation...");

                var revitInfo = await _revitService.GetRevitInfoAsync();
                if (!revitInfo.IsInstalled)
                {
                    return new InstallationResult
                    {
                        Success = false,
                        ErrorMessage = "Revit 2025 не найден в системе"
                    };
                }

                var copyResult = await CopyPluginFilesAsync();
                if (!copyResult.Success)
                {
                    return copyResult;
                }

                var registerResult = await RegisterPluginAsync();
                if (!registerResult.Success)
                {
                    return registerResult;
                }

                _logger.LogInformation("MyVeras installation completed successfully");
                return new InstallationResult { Success = true };
            }
            catch (Exception ex)
            {
                _logger.LogError(ex, "Installation failed");
                return new InstallationResult
                {
                    Success = false,
                    ErrorMessage = ex.Message
                };
            }
        }

        public async Task<InstallationResult> CopyPluginFilesAsync()
        {
            try
            {
                _logger.LogInformation("Copying plugin files...");

                var revitInfo = await _revitService.GetRevitInfoAsync();
                
                // Жестко прописываем правильный путь Autodesk
                var addinsPath = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.CommonApplicationData), 
                    "Autodesk", "Revit", "Addins", "2025");
                var pluginPath = Path.Combine(addinsPath, "MyVeras");

                _logger.LogInformation($"Addins path: {addinsPath}");
                _logger.LogInformation($"Plugin path: {pluginPath}");
                _logger.LogInformation($"Install path: {revitInfo.InstallPath}");

                // Проверяем что путь именно ProgramData, а не Program Files
                if (!addinsPath.Contains("ProgramData"))
                {
                    _logger.LogError($"Wrong addins path: {addinsPath}. Expected ProgramData path!");
                    return new InstallationResult
                    {
                        Success = false,
                        ErrorMessage = $"Неправильный путь для Addins: {addinsPath}. Ожидался путь с ProgramData"
                    };
                }

                Directory.CreateDirectory(addinsPath);
                Directory.CreateDirectory(pluginPath);

                var currentPath = Path.GetDirectoryName(typeof(InstallationService).Assembly.Location);
                _logger.LogInformation($"Current path: {currentPath}");
                
                // Копируем все DLL файлы из текущей папки
                var dllFiles = Directory.GetFiles(currentPath, "*.dll");
                _logger.LogInformation($"Found {dllFiles.Length} DLL files to copy");
                
                foreach (var sourcePath in dllFiles)
                {
                    var fileName = Path.GetFileName(sourcePath);
                    var targetPath = Path.Combine(pluginPath, fileName);
                    
                    try
                    {
                        File.Copy(sourcePath, targetPath, true);
                        _logger.LogInformation($"Copied: {fileName} -> {targetPath}");
                    }
                    catch (Exception ex)
                    {
                        _logger.LogError(ex, $"Failed to copy {fileName} to {targetPath}");
                        return new InstallationResult
                        {
                            Success = false,
                            ErrorMessage = $"Failed to copy {fileName}: {ex.Message}"
                        };
                    }
                }

                _logger.LogInformation($"Copied {dllFiles.Length} DLL files to plugin folder");

                // Проверяем основные зависимости
                var requiredDlls = new[]
                {
                    "MyVeras.RevitAPI.dll",
                    "MyVeras.Core.dll",
                    "MyVeras.Models.dll",
                    "Newtonsoft.Json.dll"
                };

                foreach (var dll in requiredDlls)
                {
                    var dllPath = Path.Combine(pluginPath, dll);
                    if (!File.Exists(dllPath))
                    {
                        _logger.LogError($"Required dependency missing: {dll}");
                        return new InstallationResult
                        {
                            Success = false,
                            ErrorMessage = $"Отсутствует обязательная зависимость: {dll}"
                        };
                    }
                }

                _logger.LogInformation("All required dependencies verified");

                await Task.Delay(1000);

                return new InstallationResult { Success = true };
            }
            catch (Exception ex)
            {
                _logger.LogError(ex, "Failed to copy plugin files");
                return new InstallationResult
                {
                    Success = false,
                    ErrorMessage = $"Ошибка копирования файлов: {ex.Message}"
                };
            }
        }

        public async Task<InstallationResult> RegisterPluginAsync()
        {
            try
            {
                _logger.LogInformation("Registering plugin...");

                var revitInfo = await _revitService.GetRevitInfoAsync();
                var addinsPath = revitInfo.AddinsPath; // Используем правильный путь Autodesk
                
                // Создаем папку для плагина
                var pluginFolder = Path.Combine(addinsPath, "MyVeras");
                if (!Directory.Exists(pluginFolder))
                {
                    Directory.CreateDirectory(pluginFolder);
                    _logger.LogInformation($"Created plugin folder: {pluginFolder}");
                }

                // Копируем .addin файл в папку Addins
                var sourceAddinPath = Path.Combine(AppDomain.CurrentDomain.BaseDirectory, "MyVeras.addin");
                var targetAddinPath = Path.Combine(addinsPath, "MyVeras.addin");
                
                if (!File.Exists(sourceAddinPath))
                {
                    return new InstallationResult
                    {
                        Success = false,
                        ErrorMessage = "Исходный файл MyVeras.addin не найден"
                    };
                }

                File.Copy(sourceAddinPath, targetAddinPath, true);
                _logger.LogInformation($"Copied addin file to: {targetAddinPath}");

                // Обновляем путь к сборке в .addin файле
                var addinContent = await Task.Run(() => File.ReadAllText(targetAddinPath));
                var assemblyPath = Path.Combine(pluginFolder, "MyVeras.RevitAPI.dll");
                
                if (!File.Exists(assemblyPath))
                {
                    return new InstallationResult
                    {
                        Success = false,
                        ErrorMessage = "Сборка MyVeras.RevitAPI.dll не найдена в папке плагина"
                    };
                }

                // Обновляем оба AddIn элементов с абсолютным путем
                addinContent = addinContent.Replace("<Assembly>MyVeras.RevitAPI.dll</Assembly>", $"<Assembly>{assemblyPath}</Assembly>");
                await Task.Run(() => File.WriteAllText(targetAddinPath, addinContent));

                await Task.Delay(500);

                _logger.LogInformation("Plugin registered successfully");
                
                // Создаем файл журнала установки
                var logPath = Path.Combine(pluginFolder, "installation.log");
                var logContent = $@"MyVeras Installation Log
Installation Date: {DateTime.Now}
Revit Version: 2025
Installation Path: {revitInfo.InstallPath}
Plugin Path: {pluginFolder}
Addin Path: {targetAddinPath}
Assembly Path: {assemblyPath}

Installation Status: SUCCESS
";

                await Task.Run(() => File.WriteAllText(logPath, logContent));
                _logger.LogInformation($"Installation log created: {logPath}");

                return new InstallationResult { Success = true };
            }
            catch (Exception ex)
            {
                _logger.LogError(ex, "Failed to register plugin");
                return new InstallationResult
                {
                    Success = false,
                    ErrorMessage = $"Ошибка регистрации плагина: {ex.Message}"
                };
            }
        }

        public async Task<InstallationResult> UninstallAsync()
        {
            try
            {
                _logger.LogInformation("Starting MyVeras uninstallation...");

                var revitInfo = await _revitService.GetRevitInfoAsync();
                if (!revitInfo.IsInstalled)
                {
                    return new InstallationResult
                    {
                        Success = false,
                        ErrorMessage = "Revit 2025 не найден"
                    };
                }

                var addinsPath = Path.Combine(revitInfo.InstallPath, "Addins");
                var pluginPath = Path.Combine(addinsPath, "MyVeras");
                var addinPath = Path.Combine(addinsPath, "MyVeras.addin");

                if (Directory.Exists(pluginPath))
                {
                    Directory.Delete(pluginPath, true);
                    _logger.LogInformation($"Removed plugin directory: {pluginPath}");
                }

                if (File.Exists(addinPath))
                {
                    File.Delete(addinPath);
                    _logger.LogInformation($"Removed addin file: {addinPath}");
                }

                await Task.Delay(1000);

                _logger.LogInformation("MyVeras uninstallation completed successfully");
                return new InstallationResult { Success = true };
            }
            catch (Exception ex)
            {
                _logger.LogError(ex, "Uninstallation failed");
                return new InstallationResult
                {
                    Success = false,
                    ErrorMessage = ex.Message
                };
            }
        }
    }
}
