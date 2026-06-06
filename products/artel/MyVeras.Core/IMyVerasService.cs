using System;

namespace MyVeras.Core
{
    /// <summary>
    /// Интерфейс для сервиса управления окнами MyVeras
    /// </summary>
    public interface IMyVerasService
    {
        /// <summary>
        /// Показать или активировать главное окно приложения
        /// </summary>
        void ShowMainWindow();
        
        /// <summary>
        /// Обновить данные в UI
        /// </summary>
        void UpdateUIData(UIDataTransfer data);
        
        /// <summary>
        /// Получить текущие данные из UI
        /// </summary>
        UIDataTransfer GetUIData();
    }
}
