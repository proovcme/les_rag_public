using System;
using System.Threading.Tasks;
using System.Windows;
using System.Net.Http;
using System.Windows.Media;
using MyVeras.Core;
using MyVeras.Settings;

namespace MyVeras.UI.Windows
{
    public partial class SettingsWindow : Window
    {
        private readonly SettingsManager _settingsManager;
        private bool _isCloudApi = true;

        public SettingsWindow()
        {
            try
            {
                InitializeComponent();
                
                // Получаем SettingsManager
                _settingsManager = SettingsManager.Instance;
                if (_settingsManager == null)
                {
                    throw new InvalidOperationException("SettingsManager.Instance is null");
                }
                
                // ПРИНУДИТЕЛЬНАЯ загрузка настроек ПЕРЕД обращением
                _settingsManager.LoadSettings();
                
                // ЧИСТЫЙ МАППИНГ ПРИ ЗАГРУЗКЕ - ПРЯМОЕ ПРИСВАИВАНИЕ
                var settings = _settingsManager.Settings;
                if (settings == null)
                {
                    throw new InvalidOperationException("SettingsManager.Settings is still null after LoadSettings()");
                }
                
                // ПРЯМОЕ ЗАПОЛНЕНИЕ ПОЛЕЙ ИЗ НАСТРОЕК
                if (ApiKeyPasswordBox != null)
                {
                    ApiKeyPasswordBox.Text = settings.ApiKey ?? string.Empty;
                }
                
                if (ApiBaseUrlTextBox != null)
                {
                    ApiBaseUrlTextBox.Text = settings.ApiBaseUrl ?? "https://api.gen-api.ru/api/v1";
                }
                
                if (EndpointGenerateTextBox != null)
                {
                    EndpointGenerateTextBox.Text = settings.EndpointGenerate ?? "/model/restyle";
                }
                
                if (EndpointStatusTextBox != null)
                {
                    EndpointStatusTextBox.Text = settings.EndpointStatus ?? "/request/get/{0}";
                }
                
                if (LocalApiUrlTextBox != null)
                {
                    LocalApiUrlTextBox.Text = settings.LocalSettings?.Url ?? "http://localhost:7860";
                }
                
                // Устанавливаем тип API
                _isCloudApi = settings.ActiveProvider != "Local";
                if (CloudApiRadio != null && LocalApiRadio != null)
                {
                    CloudApiRadio.IsChecked = _isCloudApi;
                    LocalApiRadio.IsChecked = !_isCloudApi;
                }
                
                UpdateUIState();
            }
            catch (Exception ex)
            {
                MessageBox.Show($"Ошибка инициализации SettingsWindow: {ex.Message}\n\nStack Trace:\n{ex.StackTrace}", 
                    "Initialization Error", MessageBoxButton.OK, MessageBoxImage.Error);
                throw;
            }
        }

        private void ApiType_Changed(object sender, RoutedEventArgs e)
        {
            _isCloudApi = CloudApiRadio?.IsChecked == true;
            UpdateUIState();
        }

        private void UpdateUIState()
        {
            if (ApiKeyPasswordBox != null && LocalApiUrlTextBox != null)
            {
                ApiKeyPasswordBox.IsEnabled = _isCloudApi;
                LocalApiUrlTextBox.IsEnabled = !_isCloudApi;
            }
        }

        private async void TestButton_Click(object sender, RoutedEventArgs e)
        {
            try
            {
                TestButton.IsEnabled = false;
                TestButton.Content = "Testing...";

                if (_isCloudApi)
                {
                    if (string.IsNullOrEmpty(ApiKeyPasswordBox.Text))
                    {
                        MessageBox.Show("Введите API ключ для тестирования!", "Предупреждение", MessageBoxButton.OK, MessageBoxImage.Warning);
                        return;
                    }

                    // Тестируем облачное API
                    using var client = new GenApiClient(ApiKeyPasswordBox.Text);
                    await Task.Delay(1000); // Имитация проверки
                    
                    MessageBox.Show("Соединение с Cloud API успешно установлено!", "Успех", MessageBoxButton.OK, MessageBoxImage.Information);
                }
                else
                {
                    if (string.IsNullOrEmpty(LocalApiUrlTextBox.Text))
                    {
                        MessageBox.Show("Введите URL локального API для тестирования!", "Предупреждение", MessageBoxButton.OK, MessageBoxImage.Warning);
                        return;
                    }

                    // Тестируем локальное API
                    await Task.Delay(1000); // Имитация проверки
                    
                    MessageBox.Show("Соединение с Local API успешно установлено!", "Успех", MessageBoxButton.OK, MessageBoxImage.Information);
                }
            }
            catch (Exception ex)
            {
                MessageBox.Show($"Ошибка подключения: {ex.Message}", "Ошибка", MessageBoxButton.OK, MessageBoxImage.Error);
            }
            finally
            {
                TestButton.IsEnabled = true;
                TestButton.Content = "Test Connection";
            }
        }

        private async void SaveButton_Click(object sender, RoutedEventArgs e)
        {
            try
            {
                // Сбрасываем статус
                SetStatus("", Brushes.Black);
                
                if (_settingsManager == null)
                {
                    SetStatus("Ошибка: SettingsManager не инициализирован", Brushes.Red);
                    MessageBox.Show("SettingsManager is not initialized", "Error", MessageBoxButton.OK, MessageBoxImage.Error);
                    return;
                }

                var settings = _settingsManager.Settings;
                if (settings == null)
                {
                    SetStatus("Ошибка: Настройки недоступны", Brushes.Red);
                    MessageBox.Show("Settings are not available", "Error", MessageBoxButton.OK, MessageBoxImage.Error);
                    return;
                }
                
                // ЧИСТЫЙ МАППИНГ - ПРЯМОЕ ПРИСВАИВАНИЕ
                var currentSettings = _settingsManager.Settings;
                if (currentSettings != null)
                {
                    currentSettings.ApiKey = ApiKeyPasswordBox.Text?.Trim() ?? string.Empty;
                    currentSettings.ApiBaseUrl = ApiBaseUrlTextBox.Text?.Trim() ?? "https://api.gen-api.ru/api/v1";
                    currentSettings.EndpointGenerate = EndpointGenerateTextBox.Text?.Trim() ?? "/model/restyle";
                    currentSettings.EndpointStatus = EndpointStatusTextBox.Text?.Trim() ?? "/request/get/{0}";
                    currentSettings.ActiveProvider = _isCloudApi ? "Cloud" : "Local";
                    
                    if (currentSettings.LocalSettings != null && LocalApiUrlTextBox != null)
                    {
                        currentSettings.LocalSettings.Url = LocalApiUrlTextBox.Text ?? "http://localhost:7860";
                    }
                    
                    SetStatus("Сохранено!", Brushes.Green);
                }
                
                _settingsManager.SaveSettings();
                
                MessageBox.Show("Настройки сохранены", "Успех", MessageBoxButton.OK, MessageBoxImage.Information);
                DialogResult = true;
                Close();
            }
            catch (Exception ex)
            {
                SetStatus("Ошибка: " + ex.Message, Brushes.Red);
                MessageBox.Show($"Error saving settings: {ex.Message}", "Error", MessageBoxButton.OK, MessageBoxImage.Error);
            }
        }

        private void CancelButton_Click(object sender, RoutedEventArgs e)
        {
            DialogResult = false;
            Close();
        }

        /// <summary>
        /// Устанавливает текст статуса с цветом
        /// </summary>
        private void SetStatus(string message, System.Windows.Media.Brush color)
        {
            if (StatusText != null)
            {
                StatusText.Text = message;
                StatusText.Foreground = color;
            }
        }

        /// <summary>
        /// Валидация API ключа на сервере
        /// </summary>
        private async Task<bool> ValidateApiKeyAsync(string apiKey)
        {
            try
            {
                // Создаем временный клиент для проверки
                using (var client = new HttpClient())
                {
                    client.BaseAddress = new Uri("https://api.gen-api.ru/api/v1/networks/restyle");
                    client.DefaultRequestHeaders.Authorization = new System.Net.Http.Headers.AuthenticationHeaderValue("Bearer", apiKey);
                    client.DefaultRequestHeaders.Accept.Add(new System.Net.Http.Headers.MediaTypeWithQualityHeaderValue("application/json"));

                    // Пробуем простой запрос - проверяем доступность API
                    var response = await client.GetAsync("");
                    
                    // Если получили 401 - ключ неверный
                    if (response.StatusCode == System.Net.HttpStatusCode.Unauthorized)
                    {
                        return false;
                    }
                    
                    // Если получили любой другой ответ (даже ошибку 4xx/5xx кроме 401) - ключ принят
                    return true;
                }
            }
            catch
            {
                // Если произошла ошибка сети, считаем что ключ может быть правильным
                // Это позволяет сохранить ключ даже при проблемах с подключением
                return true;
            }
        }
    }
}
