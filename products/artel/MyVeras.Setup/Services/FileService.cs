using System;
using System.IO;
using System.Threading.Tasks;
using Microsoft.Extensions.Logging;

namespace MyVeras.Setup.Services
{
    /// <summary>
    /// Реализация файлового сервиса
    /// </summary>
    public class FileService : IFileService
    {
        private readonly ILogger<FileService> _logger;

        public FileService(ILogger<FileService> logger)
        {
            _logger = logger;
        }

        public async Task<bool> CopyFileAsync(string sourcePath, string targetPath)
        {
            try
            {
                if (!File.Exists(sourcePath))
                {
                    _logger.LogWarning($"Source file not found: {sourcePath}");
                    return false;
                }

                var targetDirectory = Path.GetDirectoryName(targetPath);
                if (!string.IsNullOrEmpty(targetDirectory) && !Directory.Exists(targetDirectory))
                {
                    Directory.CreateDirectory(targetDirectory);
                }

                File.Copy(sourcePath, targetPath, true);
                _logger.LogInformation($"Copied file: {sourcePath} -> {targetPath}");
                return true;
            }
            catch (Exception ex)
            {
                _logger.LogError(ex, $"Failed to copy file: {sourcePath} -> {targetPath}");
                return false;
            }
        }

        public async Task<bool> CreateDirectoryAsync(string path)
        {
            try
            {
                if (!Directory.Exists(path))
                {
                    Directory.CreateDirectory(path);
                    _logger.LogInformation($"Created directory: {path}");
                }
                return true;
            }
            catch (Exception ex)
            {
                _logger.LogError(ex, $"Failed to create directory: {path}");
                return false;
            }
        }

        public async Task<bool> FileExistsAsync(string path)
        {
            try
            {
                return File.Exists(path);
            }
            catch (Exception ex)
            {
                _logger.LogError(ex, $"Failed to check file existence: {path}");
                return false;
            }
        }

        public async Task<bool> DirectoryExistsAsync(string path)
        {
            try
            {
                return Directory.Exists(path);
            }
            catch (Exception ex)
            {
                _logger.LogError(ex, $"Failed to check directory existence: {path}");
                return false;
            }
        }

        public async Task<bool> DeleteFileAsync(string path)
        {
            try
            {
                if (File.Exists(path))
                {
                    File.Delete(path);
                    _logger.LogInformation($"Deleted file: {path}");
                }
                return true;
            }
            catch (Exception ex)
            {
                _logger.LogError(ex, $"Failed to delete file: {path}");
                return false;
            }
        }

        public async Task<bool> DeleteDirectoryAsync(string path, bool recursive = false)
        {
            try
            {
                if (Directory.Exists(path))
                {
                    Directory.Delete(path, recursive);
                    _logger.LogInformation($"Deleted directory: {path} (recursive: {recursive})");
                }
                return true;
            }
            catch (Exception ex)
            {
                _logger.LogError(ex, $"Failed to delete directory: {path} (recursive: {recursive})");
                return false;
            }
        }
    }
}
