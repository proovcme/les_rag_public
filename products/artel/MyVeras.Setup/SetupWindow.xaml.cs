using System;
using System.Threading.Tasks;
using System.Windows;
using System.Windows.Media;
using System.Windows.Shapes;
using System.Windows.Threading;
using Microsoft.Extensions.DependencyInjection;
using MyVeras.Setup.Services;

namespace MyVeras.Setup
{
    public partial class SetupWindow : Window
    {
        private readonly IServiceProvider _services;
        private readonly IInstallationService _installationService;
        private readonly IRevitService _revitService;

        public SetupWindow(IServiceProvider services)
        {
            InitializeComponent();
            _services = services;
            _installationService = services.GetRequiredService<IInstallationService>();
            _revitService = services.GetRequiredService<IRevitService>();
            
            InitializeAsync();
        }

        private async void InitializeAsync()
        {
            try
            {
                UpdateStep(1, "Проверка системы...", Colors.Yellow);
                StatusText.Text = "Проверка системы...";
                
                await Task.Delay(1000);
                
                var revitInfo = await _revitService.GetRevitInfoAsync();
                
                if (revitInfo.IsInstalled)
                {
                    RevitStatusText.Text = "Найден";
                    RevitStatusText.Foreground = new SolidColorBrush(Colors.LimeGreen);
                    InstallPathText.Text = revitInfo.InstallPath;
                    InstallPathText.Foreground = new SolidColorBrush(Colors.LimeGreen);
                    InstallButton.IsEnabled = true;
                    UpdateStep(1, "Проверка системы", Colors.LimeGreen);
                }
                else
                {
                    RevitStatusText.Text = "Не найден";
                    RevitStatusText.Foreground = new SolidColorBrush(Colors.Red);
                    InstallPathText.Text = "Требуется Revit 2025";
                    InstallPathText.Foreground = new SolidColorBrush(Colors.Red);
                    InstallButton.IsEnabled = false;
                    UpdateStep(1, "Revit 2025 не найден", Colors.Red);
                }

                StatusText.Text = revitInfo.IsInstalled ? "Готов к установке" : "Требуется Revit 2025";
            }
            catch (Exception ex)
            {
                ShowError($"Ошибка инициализации: {ex.Message}");
            }
        }

        private async void InstallButton_Click(object sender, RoutedEventArgs e)
        {
            try
            {
                // Проверка прав администратора
                if (!IsAdministrator())
                {
                    var result = MessageBox.Show(
                        "Для установки плагина требуются права администратора.\n\n" +
                        "Перезапустить установщик от имени администратора?",
                        "Требуются права администратора",
                        MessageBoxButton.YesNo,
                        MessageBoxImage.Warning);

                    if (result == MessageBoxResult.Yes)
                    {
                        RestartAsAdmin();
                        return;
                    }
                    else
                    {
                        return;
                    }
                }

                InstallButton.IsEnabled = false;
                CancelButton.IsEnabled = false;

                await PerformInstallation();
            }
            catch (Exception ex)
            {
                ShowError($"Ошибка установки: {ex.Message}");
                InstallButton.IsEnabled = true;
                CancelButton.IsEnabled = true;
            }
        }

        private async Task PerformInstallation()
        {
            UpdateProgress(0);

            UpdateStep(2, "Поиск Revit 2025...", Colors.Yellow);
            StatusText.Text = "Поиск установки Revit 2025...";
            UpdateProgress(10);

            await Task.Delay(1000);
            UpdateStep(2, "Revit 2025 найден", Colors.LimeGreen);

            UpdateStep(3, "Копирование файлов...", Colors.Yellow);
            StatusText.Text = "Копирование файлов плагина...";
            UpdateProgress(30);

            var copyResult = await _installationService.CopyPluginFilesAsync();
            if (!copyResult.Success)
            {
                throw new Exception(copyResult.ErrorMessage);
            }

            await Task.Delay(1000);
            UpdateStep(3, "Файлы скопированы", Colors.LimeGreen);
            UpdateProgress(60);

            UpdateStep(4, "Регистрация плагина...", Colors.Yellow);
            StatusText.Text = "Регистрация плагина в Revit...";
            UpdateProgress(70);

            var registerResult = await _installationService.RegisterPluginAsync();
            if (!registerResult.Success)
            {
                throw new Exception(registerResult.ErrorMessage);
            }

            await Task.Delay(1000);
            UpdateStep(4, "Плагин зарегистрирован", Colors.LimeGreen);
            UpdateProgress(90);

            StatusText.Text = "Завершение установки...";
            UpdateProgress(100);

            await Task.Delay(500);

            MessageBox.Show("MyVeras AI Rendering успешно установлен!\n\n" +
                          "Плагин доступен во вкладке 'MyVeras' в Revit 2025.", 
                          "Установка завершена", MessageBoxButton.OK, MessageBoxImage.Information);

            Close();
        }

        private void CancelButton_Click(object sender, RoutedEventArgs e)
        {
            var result = MessageBox.Show("Отменить установку?", "Подтверждение", 
                MessageBoxButton.YesNo, MessageBoxImage.Question);
            
            if (result == MessageBoxResult.Yes)
            {
                Close();
            }
        }

        private void UpdateStep(int stepNumber, string text, Color color)
        {
            Dispatcher.InvokeAsync(() =>
            {
                Ellipse indicator = null;
                switch (stepNumber)
                {
                    case 1:
                        indicator = Step1Indicator;
                        break;
                    case 2:
                        indicator = Step2Indicator;
                        break;
                    case 3:
                        indicator = Step3Indicator;
                        break;
                    case 4:
                        indicator = Step4Indicator;
                        break;
                }

                if (indicator != null)
                {
                    indicator.Fill = new SolidColorBrush(color);
                }
            });
        }

        private void UpdateProgress(int percentage)
        {
            Dispatcher.InvokeAsync(() =>
            {
                InstallationProgress.Value = percentage;
            });
        }

        private void ShowError(string message)
        {
            Dispatcher.InvokeAsync(() =>
            {
                MessageBox.Show(message, "Ошибка установки", MessageBoxButton.OK, MessageBoxImage.Error);
            });
        }

        private bool IsAdministrator()
        {
            var identity = System.Security.Principal.WindowsIdentity.GetCurrent();
            var principal = new System.Security.Principal.WindowsPrincipal(identity);
            return principal.IsInRole(System.Security.Principal.WindowsBuiltInRole.Administrator);
        }

        private void RestartAsAdmin()
        {
            try
            {
                var startInfo = new System.Diagnostics.ProcessStartInfo
                {
                    UseShellExecute = true,
                    WorkingDirectory = Environment.CurrentDirectory,
                    FileName = System.Reflection.Assembly.GetExecutingAssembly().Location,
                    Verb = "runas"
                };

                System.Diagnostics.Process.Start(startInfo);
                System.Windows.Application.Current.Shutdown();
            }
            catch (Exception ex)
            {
                ShowError($"Не удалось перезапустить от имени администратора: {ex.Message}");
            }
        }
    }
}
