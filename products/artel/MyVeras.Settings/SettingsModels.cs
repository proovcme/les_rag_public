using MyVeras.Models;

namespace MyVeras.Settings
{
    /// <summary>
    /// Основная модель настроек приложения
    /// </summary>
    public class AppSettings
    {
        /// <summary>
        /// Активный провайдер рендеринга
        /// </summary>
        public string ActiveProvider { get; set; } = "Cloud";

        /// <summary>
        /// Настройки облачного рендеринга
        /// </summary>
        public CloudSettings CloudSettings { get; set; } = new CloudSettings();

        /// <summary>
        /// Настройки локального рендеринга
        /// </summary>
        public LocalSettings LocalSettings { get; set; } = new LocalSettings();

        /// <summary>
        /// API провайдер
        /// </summary>
        public string ApiProvider { get; set; } = "OpenAI";

        /// <summary>
        /// API ключ
        /// </summary>
        public string ApiKey { get; set; }

        /// <summary>
        /// URL API
        /// </summary>
        public string ApiUrl { get; set; }

        /// <summary>
        /// Папка для выгрузки результатов
        /// </summary>
        public string ExportFolderPath { get; set; }

        /// <summary>
        /// Выбранный 3D вид для рендеринга
        /// </summary>
        public string SelectedViewName { get; set; }

        /// <summary>
        /// Промпт по умолчанию
        /// </summary>
        public string DefaultPrompt { get; set; } = "Architectural visualization, realistic, high quality";

        /// <summary>
        /// Качество по умолчанию
        /// </summary>
        public string DefaultQuality { get; set; } = "standard";

        /// <summary>
        /// Стиль по умолчанию
        /// </summary>
        public string DefaultStyle { get; set; } = "realistic";

        /// <summary>
        /// Пользовательский промпт (сохраняется между сессиями)
        /// </summary>
        public string UserPrompt { get; set; }

        /// <summary>
        /// Негативный промпт пользователя (сохраняется между сессиями)
        /// </summary>
        public string NegativePrompt { get; set; }

        /// <summary>
        /// Базовый URL API (динамическая конфигурация)
        /// </summary>
        public string ApiBaseUrl { get; set; } = "https://api.gen-api.ru/api/v1";

        /// <summary>
        /// Эндпоинт генерации (динамическая конфигурация)
        /// </summary>
        public string EndpointGenerate { get; set; } = "networks/restyle";

        /// <summary>
        /// Эндпоинт статуса (динамическая конфигурация)
        /// </summary>
        public string EndpointStatus { get; set; } = "request/get/{0}";
    }

    /// <summary>
    /// Настройки облачного рендеринга
    /// </summary>
    public class CloudSettings
    {
        /// <summary>
        /// URL API
        /// </summary>
        public string Url { get; set; } = "https://api.provider.com/v1";

        /// <summary>
        /// API ключ для авторизации
        /// </summary>
        public string Key { get; set; } = "";

        /// <summary>
        /// Таймаут запросов в секундах
        /// </summary>
        public int TimeoutSeconds { get; set; } = 900;

        /// <summary>
        /// Интервал проверки статуса в миллисекундах
        /// </summary>
        public int PollIntervalMs { get; set; } = 2000;
    }

    /// <summary>
    /// Настройки локального провайдера
    /// </summary>
    public class LocalSettings
    {
        /// <summary>
        /// URL локального API (ComfyUI/Automatic1111)
        /// </summary>
        public string Url { get; set; } = "http://localhost:7860";

        /// <summary>
        /// Модель для генерации
        /// </summary>
        public string Model { get; set; } = "SDXL_Architectural";

        /// <summary>
        /// Таймаут запросов в секундах
        /// </summary>
        public int TimeoutSeconds { get; set; } = 600;

        /// <summary>
        /// Использовать ControlNet
        /// </summary>
        public bool UseControlNet { get; set; } = true;

        /// <summary>
        /// Модель ControlNet
        /// </summary>
        public string ControlNetModel { get; set; } = "control_v11f1p_sd15_depth [cfd03158]";
    }

    /// <summary>
    /// Настройки пользовательского интерфейса
    /// </summary>
    public class UISettings
    {
        /// <summary>
        /// Количество последних рендеров в галерее
        /// </summary>
        public int GallerySize { get; set; } = 3;

        /// <summary>
        /// Автоматически собирать контекст из модели
        /// </summary>
        public bool AutoCollectContext { get; set; } = true;

        /// <summary>
        /// Показывать расширенные настройки
        /// </summary>
        public bool ShowAdvancedSettings { get; set; } = false;

        /// <summary>
        /// Язык интерфейса
        /// </summary>
        public string Language { get; set; } = "ru-RU";

        /// <summary>
        /// Тема оформления
        /// </summary>
        public string Theme { get; set; } = "Dark";
    }

    /// <summary>
    /// Настройки рендеринга по умолчанию
    /// </summary>
    public class RenderingDefaults
    {
        /// <summary>
        /// Ширина изображения по умолчанию
        /// </summary>
        public int Width { get; set; } = 1024;

        /// <summary>
        /// Высота изображения по умолчанию
        /// </summary>
        public int Height { get; set; } = 1024;

        /// <summary>
        /// Сила влияния ИИ по умолчанию
        /// </summary>
        public float DenoisingStrength { get; set; } = 0.75f;

        /// <summary>
        /// Количество шагов по умолчанию
        /// </summary>
        public int Steps { get; set; } = 20;

        /// <summary>
        /// CFG Scale по умолчанию
        /// </summary>
        public float CfgScale { get; set; } = 7.5f;

        /// <summary>
        /// Негативный промпт по умолчанию
        /// </summary>
        public string NegativePrompt { get; set; } = "blurry, low quality, distorted, ugly, bad architecture";

        /// <summary>
        /// Сэмплер по умолчанию
        /// </summary>
        public string Sampler { get; set; } = "DPM++ 2M Karras";
    }
}
