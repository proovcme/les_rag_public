namespace MyVeras.Setup.Models
{
    /// <summary>
    /// Информация о Revit
    /// </summary>
    public class RevitInfo
    {
        /// <summary>
        /// Установлен ли Revit
        /// </summary>
        public bool IsInstalled { get; set; }

        /// <summary>
        /// Путь установки
        /// </summary>
        public string InstallPath { get; set; }

        /// <summary>
        /// Версия Revit
        /// </summary>
        public string Version { get; set; }

        /// <summary>
        /// Год версии
        /// </summary>
        public int Year { get; set; } = 2025;

        /// <summary>
        /// Дополнительная информация
        /// </summary>
        public string AdditionalInfo { get; set; }

        /// <summary>
        /// Путь к папке Addins (рекомендованный Autodesk)
        /// </summary>
        public string AddinsPath { get; set; }
    }
}
