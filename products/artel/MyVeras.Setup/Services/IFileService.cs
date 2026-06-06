using System.Threading.Tasks;

namespace MyVeras.Setup.Services
{
    /// <summary>
    /// Интерфейс файлового сервиса
    /// </summary>
    public interface IFileService
    {
        /// <summary>
        /// Скопировать файл
        /// </summary>
        Task<bool> CopyFileAsync(string sourcePath, string targetPath);

        /// <summary>
        /// Создать директорию
        /// </summary>
        Task<bool> CreateDirectoryAsync(string path);

        /// <summary>
        /// Проверить существование файла
        /// </summary>
        Task<bool> FileExistsAsync(string path);

        /// <summary>
        /// Проверить существование директории
        /// </summary>
        Task<bool> DirectoryExistsAsync(string path);

        /// <summary>
        /// Удалить файл
        /// </summary>
        Task<bool> DeleteFileAsync(string path);

        /// <summary>
        /// Удалить директорию
        /// </summary>
        Task<bool> DeleteDirectoryAsync(string path, bool recursive = false);
    }
}
