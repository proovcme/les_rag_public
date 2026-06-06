using System;
using System.Threading.Tasks;
using MyVeras.Models;

namespace MyVeras.Core
{
    /// <summary>
    /// Абстрактный интерфейс для движков рендеринга
    /// Реализует паттерн "Стратегия"
    /// </summary>
    public interface IRenderingEngine
    {
        /// <summary>
        /// Название движка (для отображения в UI)
        /// </summary>
        string Name { get; }

        /// <summary>
        /// Проверка доступности движка
        /// </summary>
        /// <returns>True если движок доступен</returns>
        Task<bool> IsAvailableAsync();

        /// <summary>
        /// Выполнение рендеринга изображения
        /// </summary>
        /// <param name="request">Параметры рендеринга</param>
        /// <returns>Результат рендеринга</returns>
        Task<RenderingResult> RenderAsync(RenderingRequest request);

        /// <summary>
        /// Отмена текущей операции рендеринга
        /// </summary>
        void CancelRendering();

        /// <summary>
        /// Событие прогресса рендеринга
        /// </summary>
        event EventHandler<RenderingProgressEventArgs> ProgressChanged;

        /// <summary>
        /// Событие завершения рендеринга
        /// </summary>
        event EventHandler<RenderingCompletedEventArgs> RenderingCompleted;
    }

    /// <summary>
    /// Аргументы события прогресса рендеринга
    /// </summary>
    public class RenderingProgressEventArgs : EventArgs
    {
        public int ProgressPercentage { get; set; }
        public string Status { get; set; }
    }

    /// <summary>
    /// Аргументы события завершения рендеринга
    /// </summary>
    public class RenderingCompletedEventArgs : EventArgs
    {
        public RenderingResult Result { get; set; }
        public bool Success { get; set; }
        public string ErrorMessage { get; set; }
    }
}
