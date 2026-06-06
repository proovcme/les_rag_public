using System.Threading.Tasks;

namespace MyVeras.Setup.Services
{
    /// <summary>
    /// Интерфейс сервиса установки
    /// </summary>
    public interface IInstallationService
    {
        /// <summary>
        /// Выполнить полную установку
        /// </summary>
        Task<InstallationResult> InstallAsync();

        /// <summary>
        /// Скопировать файлы плагина
        /// </summary>
        Task<InstallationResult> CopyPluginFilesAsync();

        /// <summary>
        /// Зарегистрировать плагин в Revit
        /// </summary>
        Task<InstallationResult> RegisterPluginAsync();

        /// <summary>
        /// Удалить плагин
        /// </summary>
        Task<InstallationResult> UninstallAsync();
    }

    /// <summary>
    /// Результат операции установки
    /// </summary>
    public class InstallationResult
    {
        public bool Success { get; set; }
        public string ErrorMessage { get; set; }
        public string Details { get; set; }
    }
}
