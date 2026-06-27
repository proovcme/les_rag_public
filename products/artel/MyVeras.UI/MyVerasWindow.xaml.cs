using System;
using System.Diagnostics;
using System.Runtime.InteropServices;
using System.Windows;
using System.Windows.Interop;
using MyVeras.UI.ViewModels;

namespace MyVeras.UI
{
    /// <summary>
    /// Modeless окно для MyVeras AI Rendering
    /// </summary>
    public partial class MyVerasWindow : Window
    {
        private MainViewModel _viewModel;
        private static MyVerasWindow _instance;

        public static MyVerasWindow Instance => _instance;

        public MyVerasWindow()
        {
            InitializeComponent();
            _viewModel = DataContext as MainViewModel;
            _instance = this;
            
            // Обработчики событий
            Loaded += MyVerasWindow_Loaded;
            Closing += MyVerasWindow_Closing;
        }

        private void MyVerasWindow_Loaded(object sender, RoutedEventArgs e)
        {
            // Устанавливаем владельцем окно Revit (если доступно)
            SetRevitOwner();
        }

        private void MyVerasWindow_Closing(object sender, System.ComponentModel.CancelEventArgs e)
        {
            // Скрываем вместо закрытия для modeless окна
            e.Cancel = true;
            Hide();
        }

        /// <summary>
        /// Показать или активировать существующее окно
        /// </summary>
        public static void ShowOrActivate(IntPtr revitHandle = default)
        {
            if (_instance == null)
            {
                _instance = new MyVerasWindow();
                
                // Устанавливаем владельцем Revit
                if (revitHandle != IntPtr.Zero)
                {
                    var helper = new WindowInteropHelper(_instance);
                    helper.Owner = revitHandle;
                }
                
                _instance.Show();
            }
            else
            {
                _instance.Show();
                _instance.WindowState = WindowState.Normal;
                _instance.Activate();
                
                // Принудительно выводим на передний план
                SetForegroundWindow(new WindowInteropHelper(_instance).Handle);
            }
        }

        /// <summary>
        /// Установить владельцем окно Revit
        /// </summary>
        private void SetRevitOwner()
        {
            try
            {
                // Попытка найти главное окно Revit
                var processes = Process.GetProcessesByName("Revit");
                if (processes.Length > 0)
                {
                    var revitProcess = processes[0];
                    var helper = new WindowInteropHelper(this);
                    helper.Owner = revitProcess.MainWindowHandle;
                }
            }
            catch (Exception ex)
            {
                Debug.WriteLine($"Failed to set Revit owner: {ex.Message}");
            }
        }

        #region Button Event Handlers

        private void RefreshViewsButton_Click(object sender, RoutedEventArgs e)
        {
            _viewModel?.LoadMockViews();
        }

        private void BrowseFolderButton_Click(object sender, RoutedEventArgs e)
        {
            _viewModel?.BrowseExportFolder();
        }

        private void OpenFolderButton_Click(object sender, RoutedEventArgs e)
        {
            try
            {
                var folderPath = _viewModel?.ExportFolderPath;
                if (!string.IsNullOrEmpty(folderPath) && System.IO.Directory.Exists(folderPath))
                {
                    Process.Start(new ProcessStartInfo
                    {
                        FileName = folderPath,
                        UseShellExecute = true
                    });
                }
                else
                {
                    MessageBox.Show("Папка не найдена", "Ошибка", MessageBoxButton.OK, MessageBoxImage.Warning);
                }
            }
            catch (Exception ex)
            {
                MessageBox.Show($"Ошибка открытия папки: {ex.Message}", "Ошибка", MessageBoxButton.OK, MessageBoxImage.Error);
            }
        }

        private void ApiKeyPasswordBox_PasswordChanged(object sender, RoutedEventArgs e)
        {
            if (_viewModel != null && sender is System.Windows.Controls.PasswordBox passwordBox)
            {
                _viewModel.ApiKey = passwordBox.Password;
            }
        }

        private void TestApiButton_Click(object sender, RoutedEventArgs e)
        {
            _viewModel?.TestApiConnection();
        }

        private void StartRenderButton_Click(object sender, RoutedEventArgs e)
        {
            _viewModel?.StartRendering();
        }

        private void CloseButton_Click(object sender, RoutedEventArgs e)
        {
            Hide();
        }

        #endregion

        protected override void OnClosed(EventArgs e)
        {
            _instance = null;
            base.OnClosed(e);
        }

        [DllImport("user32.dll")]
        private static extern IntPtr SetForegroundWindow(IntPtr hWnd);
    }
}
