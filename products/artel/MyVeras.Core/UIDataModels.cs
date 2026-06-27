using System.Collections.Generic;

namespace MyVeras.Core
{
    /// <summary>
    /// DTO для передачи данных UI между RevitAPI и UI
    /// </summary>
    public class UIDataTransfer
    {
        /// <summary>
        /// Список доступных 3D видов
        /// </summary>
        public List<string> AvailableViews { get; set; } = new List<string>();

        /// <summary>
        /// Текущий выбранный вид
        /// </summary>
        public string SelectedViewName { get; set; }

        /// <summary>
        /// Путь для экспорта
        /// </summary>
        public string ExportFolderPath { get; set; }

        /// <summary>
        /// API ключ
        /// </summary>
        public string ApiKey { get; set; }

        /// <summary>
        /// Провайдер API
        /// </summary>
        public string ApiProvider { get; set; }

        /// <summary>
        /// URL API
        /// </summary>
        public string ApiUrl { get; set; }

        /// <summary>
        /// Статус операции
        /// </summary>
        public string Status { get; set; }

        /// <summary>
        /// Прогресс операции (0-100)
        /// </summary>
        public int ProgressPercentage { get; set; }
    }

    /// <summary>
    /// События для обновления UI
    /// </summary>
    public interface IUIEventNotifier
    {
        event System.Action<UIDataTransfer> DataUpdated;
        void UpdateData(UIDataTransfer data);
    }
}
