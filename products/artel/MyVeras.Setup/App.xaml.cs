using System;
using System.Windows;
using Microsoft.Extensions.DependencyInjection;

namespace MyVeras.Setup
{
    public partial class App : Application
    {
        public static IServiceProvider Services { get; set; }

        protected override void OnStartup(StartupEventArgs e)
        {
            base.OnStartup(e);
            
            // Устанавливаем обработку непойманных исключений
            this.DispatcherUnhandledException += App_DispatcherUnhandledException;
            AppDomain.CurrentDomain.UnhandledException += CurrentDomain_UnhandledException;
            
            // Создаем и показываем главное окно
            var setupWindow = new SetupWindow(Services);
            setupWindow.Show();
        }

        private void App_DispatcherUnhandledException(object sender, System.Windows.Threading.DispatcherUnhandledExceptionEventArgs e)
        {
            MessageBox.Show($"Произошла непредвиденная ошибка: {e.Exception.Message}", 
                "Ошибка приложения", MessageBoxButton.OK, MessageBoxImage.Error);
            e.Handled = true;
        }

        private void CurrentDomain_UnhandledException(object sender, UnhandledExceptionEventArgs e)
        {
            if (e.ExceptionObject is Exception ex)
            {
                MessageBox.Show($"Критическая ошибка: {ex.Message}", 
                    "Критическая ошибка", MessageBoxButton.OK, MessageBoxImage.Error);
            }
        }
    }
}
