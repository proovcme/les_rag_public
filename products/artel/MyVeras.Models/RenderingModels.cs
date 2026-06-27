using System;
using System.Collections.Generic;

namespace MyVeras.Models
{
    /// <summary>
    /// Модель запроса на рендеринг с поддержкой референсных изображений
    /// </summary>
    public class RenderingRequest
    {
        /// <summary>
        /// Текстовый промпт для генерации
        /// </summary>
        public string Prompt { get; set; }

        /// <summary>
        /// Негативный промпт (опционально)
        /// </summary>
        public string NegativePrompt { get; set; }

        /// <summary>
        /// Изображение для обработки (скриншот Revit)
        /// </summary>
        public byte[] SourceImage { get; set; }

        /// <summary>
        /// Референсное изображение в Base64 (опционально)
        /// </summary>
        public string ReferenceImage { get; set; }

        /// <summary>
        /// Влияние референсного изображения (0.1 - 1.0)
        /// </summary>
        public double ReferenceInfluence { get; set; } = 0.75;

        /// <summary>
        /// Ширина изображения
        /// </summary>
        public int Width { get; set; } = 1024;

        /// <summary>
        /// Высота изображения
        /// </summary>
        public int Height { get; set; } = 1024;

        /// <summary>
        /// Качество изображения (standard, hd)
        /// </summary>
        public string Quality { get; set; } = "standard";

        /// <summary>
        /// Стиль изображения (realistic, artistic, conceptual)
        /// </summary>
        public string Style { get; set; } = "realistic";

        /// <summary>
        /// Сила влияния ИИ (Denoising strength)
        /// </summary>
        public float DenoisingStrength { get; set; } = 0.75f;

        /// <summary>
        /// Количество шагов генерации
        /// </summary>
        public int Steps { get; set; } = 20;

        /// <summary>
        /// Seed для воспроизводимости
        /// </summary>
        public int? Seed { get; set; }

        /// <summary>
        /// Дополнительные параметры
        /// </summary>
        public Dictionary<string, object> AdditionalParameters { get; set; } = new Dictionary<string, object>();
    }

    /// <summary>
    /// Модель результата рендеринга
    /// </summary>
    public class RenderingResult
    {
        /// <summary>
        /// Сгенерированное изображение
        /// </summary>
        public byte[] ImageData { get; set; }

        /// <summary>
        /// Время выполнения в миллисекундах
        /// </summary>
        public long ExecutionTimeMs { get; set; }

        /// <summary>
        /// Успешность операции
        /// </summary>
        public bool Success { get; set; }

        /// <summary>
        /// Сообщение об ошибке
        /// </summary>
        public string ErrorMessage { get; set; }

        /// <summary>
        /// Использованный seed (если доступно)
        /// </summary>
        public int Seed { get; set; }
    }

    /// <summary>
    /// Модель для хранения истории рендеров
    /// </summary>
    public class RenderHistoryItem
    {
        public string Id { get; set; } = Guid.NewGuid().ToString();
        public DateTime CreatedAt { get; set; } = DateTime.Now;
        public string Prompt { get; set; }
        public byte[] Thumbnail { get; set; }
        public byte[] FullImage { get; set; }
        public RenderingEngineType EngineType { get; set; }
        public int Width { get; set; }
        public int Height { get; set; }
        public float DenoisingStrength { get; set; }
        public int Seed { get; set; }
        public long ExecutionTimeMs { get; set; }
    }

    /// <summary>
    /// Тип движка рендеринга
    /// </summary>
    public enum RenderingEngineType
    {
        Local,
        Cloud
    }

    /// <summary>
    /// Модель для BIM данных из Revit
    /// </summary>
    public class BIMDataContext
    {
        /// <summary>
        /// Скриншот активного вида
        /// </summary>
        public byte[] Screenshot { get; set; }

        /// <summary>
        /// Карта глубины
        /// </summary>
        public byte[] DepthMap { get; set; }

        /// <summary>
        /// Категория активного вида
        /// </summary>
        public string ViewCategory { get; set; }

        /// <summary>
        /// Список материалов элементов
        /// </summary>
        public List<string> Materials { get; set; } = new List<string>();

        /// <summary>
        /// Список категорий элементов
        /// </summary>
        public List<string> ElementCategories { get; set; } = new List<string>();

        /// <summary>
        /// Дополнительные метаданные
        /// </summary>
        public Dictionary<string, object> Metadata { get; set; } = new Dictionary<string, object>();
    }
}
