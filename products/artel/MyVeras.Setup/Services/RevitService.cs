using System;
using System.IO;
using System.Threading.Tasks;
using Microsoft.Win32;
using Microsoft.Extensions.Logging;
using MyVeras.Setup.Models;
using System.Diagnostics;

namespace MyVeras.Setup.Services
{
    /// <summary>
    /// Реализация сервиса работы с Revit
    /// </summary>
    public class RevitService : IRevitService
    {
        private readonly ILogger<RevitService> _logger;
        private const string Revit2025Version = "2025";
        private const string Revit2025RegistryKey = @"SOFTWARE\Autodesk\Revit\2025";

        public RevitService(ILogger<RevitService> logger)
        {
            _logger = logger;
        }

        /// <summary>
        /// Получение информации об установленных версиях Revit
        /// </summary>
        public async Task<RevitInfo> GetRevitInfoAsync()
        {
            return await Task.Run(() =>
            {
                var revitInfo = new RevitInfo();
                
                // Ищем Revit 2025 в реестре
                var revitPath = FindRevit2025InRegistry();
                
                if (!string.IsNullOrEmpty(revitPath))
                {
                    revitInfo.IsInstalled = true;
                    revitInfo.InstallPath = revitPath;
                    revitInfo.Version = "2025";
                    
                    // Правильный путь для Addins по рекомендации Autodesk
                    revitInfo.AddinsPath = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.CommonApplicationData), 
                        "Autodesk", "Revit", "Addins", "2025");
                    
                    _logger.LogInformation($"Found Revit 2025 at: {revitPath}");
                    _logger.LogInformation($"Addins path: {revitInfo.AddinsPath}");
                }
                else
                {
                    revitInfo.IsInstalled = false;
                    _logger.LogWarning("Revit 2025 not found in registry");
                }
                
                return revitInfo;
            });
        }

        private string FindRevit2025InRegistry()
        {
            try
            {
                using (var key = Registry.LocalMachine.OpenSubKey(Revit2025RegistryKey))
                {
                    if (key != null)
                    {
                        var installPath = key.GetValue("InstallationPath") as string;
                        if (!string.IsNullOrEmpty(installPath) && Directory.Exists(installPath))
                        {
                            _logger.LogInformation($"Found Revit 2025 at: {installPath}");
                            return installPath;
                        }
                    }
                }

                var commonPaths = new[]
                {
                    @"C:\Program Files\Autodesk\Revit 2025",
                    @"C:\Program Files (x86)\Autodesk\Revit 2025",
                    Environment.GetFolderPath(Environment.SpecialFolder.ProgramFiles) + @"\Autodesk\Revit 2025",
                    Environment.GetFolderPath(Environment.SpecialFolder.ProgramFilesX86) + @"\Autodesk\Revit 2025"
                };

                foreach (var path in commonPaths)
                {
                    if (Directory.Exists(path))
                    {
                        var revitExe = Path.Combine(path, "Revit.exe");
                        if (File.Exists(revitExe))
                        {
                            _logger.LogInformation($"Found Revit 2025 at: {path}");
                            return path;
                        }
                    }
                }

                _logger.LogWarning("Revit 2025 not found");
                return null;
            }
            catch (Exception ex)
            {
                _logger.LogError(ex, "Failed to get Revit install path");
                return null;
            }
        }

        public async Task<bool> IsRevitInstalledAsync()
        {
            try
            {
                var installPath = await GetRevitInstallPathAsync();
                return !string.IsNullOrEmpty(installPath) && Directory.Exists(installPath);
            }
            catch (Exception ex)
            {
                _logger.LogError(ex, "Failed to check Revit installation");
                return false;
            }
        }

        public async Task<string> GetRevitInstallPathAsync()
        {
            return await Task.Run(() =>
            {
                try
                {
                    using (var key = Registry.LocalMachine.OpenSubKey(Revit2025RegistryKey))
                    {
                        if (key != null)
                        {
                            var installPath = key.GetValue("InstallationPath") as string;
                            if (!string.IsNullOrEmpty(installPath) && Directory.Exists(installPath))
                            {
                                _logger.LogInformation($"Found Revit 2025 at: {installPath}");
                                return installPath;
                            }
                        }
                    }

                    var commonPaths = new[]
                    {
                        @"C:\Program Files\Autodesk\Revit 2025",
                        @"C:\Program Files (x86)\Autodesk\Revit 2025",
                        Environment.GetFolderPath(Environment.SpecialFolder.ProgramFiles) + @"\Autodesk\Revit 2025",
                        Environment.GetFolderPath(Environment.SpecialFolder.ProgramFilesX86) + @"\Autodesk\Revit 2025"
                    };

                    foreach (var path in commonPaths)
                    {
                        if (Directory.Exists(path))
                        {
                            var revitExe = Path.Combine(path, "Revit.exe");
                            if (File.Exists(revitExe))
                            {
                                _logger.LogInformation($"Found Revit 2025 at: {path}");
                                return path;
                            }
                        }
                    }

                    _logger.LogWarning("Revit 2025 not found");
                    return null;
                }
                catch (Exception ex)
                {
                    _logger.LogError(ex, "Failed to get Revit install path");
                    return null;
                }
            });
        }

        public async Task<string> GetRevitVersionAsync()
        {
            return await Task.Run(() =>
            {
                try
                {
                    var installPath = GetRevitInstallPathAsync().GetAwaiter().GetResult();
                    if (string.IsNullOrEmpty(installPath))
                        return null;

                    var revitExe = Path.Combine(installPath, "Revit.exe");
                    if (File.Exists(revitExe))
                    {
                        var versionInfo = FileVersionInfo.GetVersionInfo(revitExe);
                        var version = versionInfo.FileVersion;
                        _logger.LogInformation($"Revit version: {version}");
                        return version;
                    }

                    return Revit2025Version;
                }
                catch (Exception ex)
                {
                    _logger.LogError(ex, "Failed to get Revit version");
                    return Revit2025Version;
                }
            });
        }
    }
}
