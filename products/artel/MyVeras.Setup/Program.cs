using System;
using System.IO;
using System.Diagnostics;
using System.Reflection;
using System.Windows;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.Logging;
using MyVeras.Setup.Services;

namespace MyVeras.Setup
{
    /// <summary>
    /// Основной класс установщика MyVeras
    /// </summary>
    public class Program
    {
        [STAThread]
        public static void Main(string[] args)
        {
            try
            {
                var services = ConfigureServices();
                var logger = services.GetRequiredService<ILogger<Program>>();
                
                logger.LogInformation("Starting MyVeras Setup v1.1.0");

                if (args.Length > 0 && args[0] == "--silent")
                {
                    RunSilentInstallation(services);
                }
                else
                {
                    // Сохраняем сервисы в статическом свойстве для доступа из окна
                    App.Services = services;
                    
                    // Запускаем WPF приложение
                    var app = new App();
                    app.Run();
                }
            }
            catch (Exception ex)
            {
                MessageBox.Show($"Ошибка установки: {ex.Message}", "MyVeras Setup Error", 
                    MessageBoxButton.OK, MessageBoxImage.Error);
                Environment.Exit(1);
            }
        }

        private static IServiceProvider ConfigureServices()
        {
            var services = new ServiceCollection();

            services.AddLogging(configure => configure.AddConsole());

            services.AddSingleton<IInstallationService, InstallationService>();
            services.AddSingleton<IRevitService, RevitService>();
            services.AddSingleton<IFileService, FileService>();

            return services.BuildServiceProvider();
        }

        private static void RunSilentInstallation(IServiceProvider services)
        {
            var installationService = services.GetRequiredService<IInstallationService>();
            var logger = services.GetRequiredService<ILogger<Program>>();

            try
            {
                logger.LogInformation("Running silent installation...");
                var result = installationService.InstallAsync().GetAwaiter().GetResult();
                
                if (result.Success)
                {
                    logger.LogInformation("Installation completed successfully");
                    Environment.Exit(0);
                }
                else
                {
                    logger.LogError($"Installation failed: {result.ErrorMessage}");
                    Environment.Exit(1);
                }
            }
            catch (Exception ex)
            {
                logger.LogError($"Silent installation failed: {ex.Message}");
                Environment.Exit(1);
            }
        }
    }
}
