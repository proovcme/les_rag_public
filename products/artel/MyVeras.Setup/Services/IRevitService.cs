using System.Threading.Tasks;
using MyVeras.Setup.Models;

namespace MyVeras.Setup.Services
{
    /// <summary>
    /// Интерфейс сервиса работы с Revit
    /// </summary>
    public interface IRevitService
    {
        /// <summary>
        /// Получить информацию о Revit
        /// </summary>
        Task<RevitInfo> GetRevitInfoAsync();

        /// <summary>
        /// Проверить установку Revit
        /// </summary>
        Task<bool> IsRevitInstalledAsync();

        /// <summary>
        /// Получить путь установки Revit
        /// </summary>
        Task<string> GetRevitInstallPathAsync();

        /// <summary>
        /// Получить версию Revit
        /// </summary>
        Task<string> GetRevitVersionAsync();
    }
}
