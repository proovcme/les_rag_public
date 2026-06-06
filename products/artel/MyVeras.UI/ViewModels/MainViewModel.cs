using System;
using System.Collections.Generic;
using System.Collections.ObjectModel;
using System.ComponentModel;
using System.IO;
using System.Runtime.CompilerServices;
using System.Threading.Tasks;
using System.Windows;
using System.Windows.Input;
using System.Windows.Media.Imaging;
using Microsoft.Win32;
using MyVeras.Core;
using MyVeras.Settings;

namespace MyVeras.UI.ViewModels
{
    /// <summary>
    /// MainViewModel с поддержкой референсных изображений
    /// </summary>
    public class MainViewModel : INotifyPropertyChanged
    {
        #region Fields
        private readonly SettingsManager _settingsManager;
        private readonly AppSettings _settings;
        private readonly object _revitExternalEvent; // Используем object чтобы избежать зависимости
        private readonly object _revitDocument; // Используем object чтобы избежать зависимости
        
        private string _apiKey;
        private string _exportFolderPath;
        private string _selectedViewName;
        private string _status = "Готов к работе";
        private int _progressPercentage;
        
        // Reference Image Fields
        private string _referenceImagePath = string.Empty;
        private bool _isReferenceLoaded = false;
        private BitmapImage _referenceImagePreviewSource;
        private double _referenceInfluence = 0.75;
        private double _controlNetStrength = 0.8;
        private string _logContent = string.Empty;
        private string _userPrompt = string.Empty;
        private string _negativePrompt = string.Empty;
        private ICommand _loadReferenceCommand;
        #endregion

        #region Constructor
        public MainViewModel(object externalEvent, object revitDocument, List<string> availableViews)
        {
            _revitExternalEvent = externalEvent;
            _revitDocument = revitDocument;
            
            // Получаем SettingsManager с проверкой
            _settingsManager = SettingsManager.Instance;
            if (_settingsManager == null)
            {
                throw new InvalidOperationException("SettingsManager.Instance is null");
            }
            
            // ПРИНУДИТЕЛЬНАЯ загрузка настроек ПЕРЕД обращением
            _settingsManager.LoadSettings();
            
            // Теперь получаем настройки - они должны быть гарантированно не null
            _settings = _settingsManager.Settings;
            if (_settings == null)
            {
                throw new InvalidOperationException("SettingsManager.Settings is still null after LoadSettings()");
            }
            
            AvailableViews = new ObservableCollection<string>();
            ApiProviders = new ObservableCollection<string> { "OpenAI", "Stability AI", "Custom" };
            Qualities = new ObservableCollection<string> { "standard", "hd", "ultra" };
            Styles = new ObservableCollection<string> { "realistic", "artistic", "conceptual" };
            
            LoadSettings();
            LoadRealViews(availableViews);
        }
        #endregion

        #region Properties
        public ObservableCollection<string> AvailableViews { get; }
        public ObservableCollection<string> ApiProviders { get; }
        public ObservableCollection<string> Qualities { get; }
        public ObservableCollection<string> Styles { get; }

        public string ApiKey
        {
            get => _apiKey;
            set
            {
                if (SetProperty(ref _apiKey, value))
                {
                    _settings.ApiKey = value;
                    _settingsManager.SaveSettingsAsync();
                }
            }
        }

        public string ExportFolderPath
        {
            get => _exportFolderPath;
            set
            {
                if (SetProperty(ref _exportFolderPath, value))
                {
                    _settings.ExportFolderPath = value;
                    _settingsManager.SaveSettingsAsync();
                }
            }
        }

        public string SelectedViewName
        {
            get => _selectedViewName;
            set
            {
                if (SetProperty(ref _selectedViewName, value))
                {
                    _settings.SelectedViewName = value;
                    _settingsManager.SaveSettingsAsync();
                }
            }
        }

        public string Status
        {
            get => _status;
            set => SetProperty(ref _status, value);
        }

        public int ProgressPercentage
        {
            get => _progressPercentage;
            set => SetProperty(ref _progressPercentage, value);
        }

        // Reference Image Properties
        public string ReferenceImagePath
        {
            get => _referenceImagePath;
            set => SetProperty(ref _referenceImagePath, value);
        }

        public bool IsReferenceLoaded
        {
            get => _isReferenceLoaded;
            set => SetProperty(ref _isReferenceLoaded, value);
        }

        public BitmapImage ReferenceImagePreviewSource
        {
            get => _referenceImagePreviewSource;
            set => SetProperty(ref _referenceImagePreviewSource, value);
        }

        public double ReferenceInfluence
        {
            get => _referenceInfluence;
            set => SetProperty(ref _referenceInfluence, value);
        }

        public double ControlNetStrength
        {
            get => _controlNetStrength;
            set => SetProperty(ref _controlNetStrength, value);
        }

        public ICommand LoadReferenceCommand
        {
            get => _loadReferenceCommand ??= new RelayCommand(LoadReferenceImage);
        }
        
        public string LogContent
        {
            get => _logContent;
            private set => SetProperty(ref _logContent, value);
        }
        
        public string UserPrompt
        {
            get => _userPrompt;
            set => SetProperty(ref _userPrompt, value);
        }
        
        public string NegativePrompt
        {
            get => _negativePrompt;
            set => SetProperty(ref _negativePrompt, value);
        }
        #endregion

        #region Methods
        private void LoadSettings()
        {
            // Перезагружаем настройки из SettingsManager
            _settingsManager.LoadSettings();
            var currentSettings = _settingsManager.Settings;
            
            ApiKey = currentSettings.ApiKey ?? string.Empty;
            ExportFolderPath = currentSettings.ExportFolderPath ?? GetDefaultExportPath();
            SelectedViewName = currentSettings.SelectedViewName ?? string.Empty;
            UserPrompt = currentSettings.UserPrompt ?? string.Empty;
            NegativePrompt = currentSettings.NegativePrompt ?? string.Empty;
            ReferenceInfluence = 0.75; // Временно захардкожено, т.к. RenderingDefaults еще не реализован
        }

        /// <summary>
        /// Инициализация при открытии окна
        /// </summary>
        public void Initialize()
        {
            LoadSettings();
            AddLog("MyVeras initialized successfully");
        }

        /// <summary>
        /// Сохраняет промпты в настройки
        /// </summary>
        public void SavePrompts()
        {
            try
            {
                var settings = _settingsManager.Settings;
                settings.UserPrompt = UserPrompt;
                settings.NegativePrompt = NegativePrompt;
                _settingsManager.SaveSettings();
                AddLog("Prompts saved successfully");
            }
            catch (Exception ex)
            {
                AddLog($"Failed to save prompts: {ex.Message}");
            }
        }

        /// <summary>
        /// Добавляет логовое сообщение с отметкой времени
        /// </summary>
        public void AddLog(string message)
        {
            var timestamp = DateTime.Now.ToString("HH:mm:ss.fff");
            var logEntry = $"[{timestamp}] {message}\n";
            
            // ПРИКАЗ №1: ЗАЩИТА ЛОГОВ - КРИТИЧЕСКИ ВАЖНО обернуть в Dispatcher.Invoke
            Application.Current.Dispatcher.Invoke(() => {
                LogContent += logEntry;
            });
        }

        /// <summary>
        /// Загружает референсное изображение
        /// </summary>
        private void LoadReferenceImage()
        {
            try
            {
                var openFileDialog = new OpenFileDialog
                {
                    Title = "Select Reference Image",
                    Filter = "Image Files|*.jpg;*.jpeg;*.png;*.bmp|All files|*.*",
                    FilterIndex = 1
                };

                if (openFileDialog.ShowDialog() == true)
                {
                    var filePath = openFileDialog.FileName;
                    
                    // Загружаем изображение для предпросмотра
                    var bitmap = new BitmapImage();
                    bitmap.BeginInit();
                    bitmap.UriSource = new Uri(filePath);
                    bitmap.CacheOption = BitmapCacheOption.OnLoad;
                    bitmap.EndInit();
                    bitmap.Freeze();

                    ReferenceImagePath = filePath;
                    ReferenceImagePreviewSource = bitmap;
                    IsReferenceLoaded = true;
                }
            }
            catch (Exception ex)
            {
                MessageBox.Show($"Error loading reference image: {ex.Message}", "Error", 
                    MessageBoxButton.OK, MessageBoxImage.Error);
            }
        }

        /// <summary>
        /// Конвертирует референсное изображение в Base64
        /// </summary>
        private string ConvertReferenceToBase64()
        {
            if (!IsReferenceLoaded || string.IsNullOrEmpty(ReferenceImagePath))
                return null;

            try
            {
                var bytes = File.ReadAllBytes(ReferenceImagePath);
                return Convert.ToBase64String(bytes);
            }
            catch (Exception ex)
            {
                System.Diagnostics.Debug.WriteLine($"Error converting reference to Base64: {ex.Message}");
                return null;
            }
        }

        /// <summary>
        /// Загружает реальные 3D виды из Revit
        /// </summary>
        private void LoadRealViews(List<string> viewNames)
        {
            AvailableViews.Clear();
            
            if (viewNames != null && viewNames.Count > 0)
            {
                foreach (var viewName in viewNames)
                {
                    AvailableViews.Add(viewName);
                }
                
                if (AvailableViews.Count > 0)
                {
                    SelectedViewName = AvailableViews[0];
                }
            }
            else
            {
                AvailableViews.Add("Нет доступных 3D видов");
            }
            
            OnPropertyChanged(nameof(AvailableViews));
        }

        public void LoadMockViews()
        {
            AvailableViews.Clear();
            AvailableViews.Add("3D View 1");
            AvailableViews.Add("3D View 2");
            AvailableViews.Add("3D View 3");
        }

        private string GetDefaultExportPath()
        {
            var documents = Environment.GetFolderPath(Environment.SpecialFolder.MyDocuments);
            return System.IO.Path.Combine(documents, "MyVeras", "Renderings");
        }

        public void BrowseExportFolder()
        {
            // Временно упрощенная версия без диалога
            ExportFolderPath = GetDefaultExportPath();
        }

        public void TestApiConnection()
        {
            if (string.IsNullOrEmpty(ApiKey))
            {
                MessageBox.Show("Введите API ключ", "Ошибка", MessageBoxButton.OK, MessageBoxImage.Warning);
                return;
            }

            Status = "Проверка соединения...";
            
            // Имитация проверки API
            Task.Run(async () =>
            {
                await Task.Delay(2000);
                
                // Используем Dispatcher.Current вместо App.Current
                if (Application.Current != null)
                {
                    Application.Current.Dispatcher.Invoke(() =>
                    {
                        var isValid = ApiKey.StartsWith("sk-") || ApiKey.Contains("test");
                        
                        if (isValid)
                        {
                            Status = "✅ Соединение успешно!";
                            MessageBox.Show("Соединение с API успешно!", "Успех", MessageBoxButton.OK, MessageBoxImage.Information);
                        }
                        else
                        {
                            Status = "❌ Неверный ключ";
                            MessageBox.Show("Неверный API ключ", "Ошибка", MessageBoxButton.OK, MessageBoxImage.Error);
                        }
                    });
                }
            });
        }

        public void StartRendering()
        {
            if (string.IsNullOrEmpty(ApiKey))
            {
                MessageBox.Show("Сначала настройте API ключ!", "Ошибка", MessageBoxButton.OK, MessageBoxImage.Warning);
                return;
            }

            if (string.IsNullOrEmpty(SelectedViewName))
            {
                MessageBox.Show("Выберите 3D вид для рендеринга!", "Ошибка", MessageBoxButton.OK, MessageBoxImage.Warning);
                return;
            }

            Status = "🚀 Запуск рендеринга...";
            ProgressPercentage = 0;

            // Имитация процесса рендеринга
            Task.Run(async () =>
            {
                for (int i = 0; i <= 100; i += 10)
                {
                    if (Application.Current != null)
                    {
                        Application.Current.Dispatcher.Invoke(() =>
                        {
                            ProgressPercentage = i;
                            
                            if (i == 30) Status = "📸 Анализ сцены...";
                            if (i == 60) Status = "🤖 Обработка AI...";
                            if (i == 90) Status = "💾 Сохранение результата...";
                        });
                    }
                    
                    await Task.Delay(300);
                }

                if (Application.Current != null)
                {
                    Application.Current.Dispatcher.Invoke(() =>
                    {
                        Status = "✅ Рендеринг завершен!";
                        MessageBox.Show($"Рендеринг завершен!\nСохранено в: {ExportFolderPath}", "Успех", MessageBoxButton.OK, MessageBoxImage.Information);
                        
                        ProgressPercentage = 0;
                        Status = "Готов к работе";
                    });
                }
            });
        }

        public void UpdateUIData(UIDataTransfer data)
        {
            if (!string.IsNullOrEmpty(data.ApiKey)) ApiKey = data.ApiKey;
            if (!string.IsNullOrEmpty(data.ExportFolderPath)) ExportFolderPath = data.ExportFolderPath;
            if (!string.IsNullOrEmpty(data.SelectedViewName)) SelectedViewName = data.SelectedViewName;
            if (!string.IsNullOrEmpty(data.Status)) Status = data.Status;
            if (data.ProgressPercentage > 0) ProgressPercentage = data.ProgressPercentage;
        }

        public UIDataTransfer GetUIData()
        {
            return new UIDataTransfer
            {
                ApiKey = ApiKey ?? string.Empty,
                ExportFolderPath = ExportFolderPath ?? string.Empty,
                SelectedViewName = SelectedViewName ?? string.Empty,
                Status = Status ?? string.Empty,
                ProgressPercentage = ProgressPercentage,
                AvailableViews = new System.Collections.Generic.List<string>(AvailableViews)
            };
        }
        #endregion

        #region INotifyPropertyChanged
        public event PropertyChangedEventHandler PropertyChanged;
        protected bool SetProperty<T>(ref T field, T value, [CallerMemberName] string propertyName = null)
        {
            if (Equals(field, value)) return false;
            field = value;
            OnPropertyChanged(propertyName);
            return true;
        }

        protected void OnPropertyChanged([CallerMemberName] string propertyName = null)
        {
            PropertyChanged?.Invoke(this, new PropertyChangedEventArgs(propertyName));
        }
        #endregion
    }

    /// <summary>
    /// Simple RelayCommand implementation
    /// </summary>
    public class RelayCommand : ICommand
    {
        private readonly Action _execute;
        private readonly Func<bool> _canExecute;

        public RelayCommand(Action execute, Func<bool> canExecute = null)
        {
            _execute = execute ?? throw new ArgumentNullException(nameof(execute));
            _canExecute = canExecute;
        }

        public event EventHandler CanExecuteChanged
        {
            add { CommandManager.RequerySuggested += value; }
            remove { CommandManager.RequerySuggested -= value; }
        }

        public bool CanExecute(object parameter) => _canExecute?.Invoke() ?? true;

        public void Execute(object parameter) => _execute();
    }
}
