using System;
using System.IO;
using System.Threading.Tasks;
using Newtonsoft.Json;

namespace MyVeras.Settings
{
    /// <summary>
    /// Менеджер настроек приложения
    /// </summary>
    public class SettingsManager
    {
        private static SettingsManager _instance;
        private static readonly object _lock = new object();
        private AppSettings _settings;
        private readonly string _settingsFilePath;

        private SettingsManager()
        {
            var appDataPath = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData), "MyVeras");
            Directory.CreateDirectory(appDataPath);
            _settingsFilePath = Path.Combine(appDataPath, "settings.json");
        }

        public static SettingsManager Instance
        {
            get
            {
                if (_instance == null)
                {
                    lock (_lock)
                    {
                        if (_instance == null)
                        {
                            _instance = new SettingsManager();
                        }
                    }
                }
                return _instance;
            }
        }

        public AppSettings Settings
        {
            get
            {
                // Ленивая инициализация - всегда возвращаем валидные настройки
                if (_settings == null)
                {
                    LoadSettings();
                    
                    // Если после загрузки все еще null, создаем дефолтные
                    if (_settings == null)
                    {
                        _settings = new AppSettings();
                        // ЗАПРЕТ СОХРАНЕНИЯ - НЕ ЗАТИРАЕМ КЛЮЧ ПОЛЬЗОВАТЕЛЯ!
                        System.Diagnostics.Debug.WriteLine("Created default settings with API URLs - NOT SAVING!");
                    }
                    else
                    {
                        System.Diagnostics.Debug.WriteLine("Settings loaded successfully from disk");
                    }
                }
                return _settings;
            }
        }

        /// <summary>
        /// Загрузка настроек из файла
        /// </summary>
        public AppSettings Load()
        {
            LoadSettings();
            return _settings;
        }

        /// <summary>
        /// Загрузка настроек из файла
        /// </summary>
        public void LoadSettings()
        {
            try
            {
                // Гарантируем создание папки
                var appDataPath = Path.GetDirectoryName(_settingsFilePath);
                if (!string.IsNullOrEmpty(appDataPath))
                {
                    Directory.CreateDirectory(appDataPath);
                }
                
                if (File.Exists(_settingsFilePath))
                {
                    try
                    {
                        var json = File.ReadAllText(_settingsFilePath);
                        _settings = JsonConvert.DeserializeObject<AppSettings>(json);
                        
                        // ЛОГИРОВАНИЕ ДЛЯ ОТЛАДКИ
                        System.Diagnostics.Debug.WriteLine($"Settings loaded from: {_settingsFilePath}");
                        System.Diagnostics.Debug.WriteLine($"Loaded content: {json}");
                        System.Diagnostics.Debug.WriteLine($"API Key length: {_settings?.ApiKey?.Length ?? 0}");
                    }
                    catch (Exception ex)
                    {
                        // ПРИКАЗ №5: ЗАЩИТА КЛЮЧА - СОЗДАЕМ РЕЗЕРВНУЮ КОПИЮ .bak
                        System.Diagnostics.Debug.WriteLine($"JSON deserialization failed: {ex.Message}");
                        
                        // СОЗДАЕМ РЕЗЕРВНУЮ КОПИЮ ПОВРЕЖДЕННОГО ФАЙЛА
                        if (File.Exists(_settingsFilePath))
                        {
                            var backupPath = _settingsFilePath + ".bak";
                            try
                            {
                                File.Copy(_settingsFilePath, backupPath, true);
                                System.Diagnostics.Debug.WriteLine($"Created backup of corrupted settings: {backupPath}");
                            }
                            catch (Exception backupEx)
                            {
                                System.Diagnostics.Debug.WriteLine($"Failed to create backup: {backupEx.Message}");
                            }
                        }
                        
                        _settings = new AppSettings();
                        System.Diagnostics.Debug.WriteLine("Created default settings (JSON error) - NOT SAVING to protect user API key");
                    }
                }
                else
                {
                    // Файл не существует - создаем дефолтные настройки БЕЗ СОХРАНЕНИЯ
                    _settings = new AppSettings();
                    System.Diagnostics.Debug.WriteLine("Created default settings (file not found) - NOT SAVING");
                    System.Diagnostics.Debug.WriteLine($"Default ApiBaseUrl: {_settings.ApiBaseUrl}");
                    System.Diagnostics.Debug.WriteLine($"Default EndpointGenerate: {_settings.EndpointGenerate}");
                    System.Diagnostics.Debug.WriteLine($"Default EndpointStatus: {_settings.EndpointStatus}");
                }
            }
            catch (Exception ex)
            {
                // При любой ошибке создаем дефолтные настройки
                _settings = new AppSettings();
                System.Diagnostics.Debug.WriteLine($"Error loading settings: {ex.Message}");
                System.Diagnostics.Debug.WriteLine("Created default settings (exception) - NOT SAVING!");
            }
        }

        /// <summary>
        /// Сохранение настроек в файл
        /// </summary>
        public void SaveSettings()
        {
            try
            {
                // Гарантируем создание папки перед сохранением
                var appDataPath = Path.GetDirectoryName(_settingsFilePath);
                if (!string.IsNullOrEmpty(appDataPath))
                {
                    Directory.CreateDirectory(appDataPath);
                }
                
                var json = JsonConvert.SerializeObject(_settings, Formatting.Indented);
                File.WriteAllText(_settingsFilePath, json);
                
                // ЛОГИРОВАНИЕ ДЛЯ ОТЛАДКИ
                System.Diagnostics.Debug.WriteLine($"Settings saved to: {_settingsFilePath}");
                System.Diagnostics.Debug.WriteLine($"Saved content: {json}");
            }
            catch (Exception ex)
            {
                System.Diagnostics.Debug.WriteLine($"ERROR saving to disk: {ex.Message}");
                throw new Exception($"Failed to save settings to disk: {ex.Message}", ex);
            }
        }

        /// <summary>
        /// Асинхронное сохранение настроек
        /// </summary>
        public async Task SaveSettingsAsync()
        {
            try
            {
                var json = JsonConvert.SerializeObject(_settings, Formatting.Indented);
                await Task.Run(() => File.WriteAllText(_settingsFilePath, json));
            }
            catch (Exception ex)
            {
                System.Diagnostics.Debug.WriteLine($"Error saving settings async: {ex.Message}");
            }
        }

        /// <summary>
        /// Сброс настроек к значениям по умолчанию
        /// </summary>
        public void ResetToDefaults()
        {
            _settings = new AppSettings();
            // ПРИКАЗ №3: ФИКС АМНЕЗИИ - НЕ СОХРАНЯЕМ при сбросе!
            // SaveSettings(); // ЗАПРЕЩЕНО!
            System.Diagnostics.Debug.WriteLine("Reset to defaults - NOT saving to disk");
        }

        /// <summary>
        /// Обновление настроек
        /// </summary>
        public void UpdateSettings(Action<AppSettings> updateAction)
        {
            updateAction(_settings);
            // ПРИКАЗ №3: ФИКС АМНЕЗИИ - НЕ СОХРАНЯЕМ при обновлении!
            // SaveSettings(); // ЗАПРЕЩЕНО!
            System.Diagnostics.Debug.WriteLine("Updated settings - NOT saving to disk");
        }

        /// <summary>
        /// Получение пути к файлу настроек
        /// </summary>
        public string GetSettingsFilePath()
        {
            return _settingsFilePath;
        }

        /// <summary>
        /// Проверка существования файла настроек
        /// </summary>
        public bool SettingsFileExists()
        {
            return File.Exists(_settingsFilePath);
        }

        /// <summary>
        /// Создание файла настроек по умолчанию
        /// </summary>
        public void CreateDefaultSettingsFile()
        {
            if (!File.Exists(_settingsFilePath))
            {
                _settings = new AppSettings();
                // ПРИКАЗ №3: ФИКС АМНЕЗИИ - НЕ СОХРАНЯЕМ при создании!
                // SaveSettings(); // ЗАПРЕЩЕНО!
                System.Diagnostics.Debug.WriteLine("Created default settings in memory - NOT saving to disk");
            }
        }
    }
}
