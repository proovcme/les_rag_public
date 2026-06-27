using System;
using System.Reflection;
using System.Windows.Media.Imaging;
using Autodesk.Revit.Attributes;
using Autodesk.Revit.UI;
using Autodesk.Revit.DB;

namespace MyVeras.RevitAPI
{
    /// <summary>
    /// Application класс для создания ленты MyVeras с 2 кнопками
    /// </summary>
    [Regeneration(RegenerationOption.Manual)]
    [Transaction(TransactionMode.Manual)]
    public class App : IExternalApplication
    {
        public Result OnStartup(UIControlledApplication application)
        {
            try
            {
                // Создаем вкладку MyVeras
                application.CreateRibbonTab("MyVeras");
                
                // Создаем панель на вкладке MyVeras
                var ribbonPanel = application.CreateRibbonPanel("MyVeras", "AI Rendering");

                // Создаем кнопку Settings
                var settingsButton = new PushButtonData(
                    "MyVeras_Settings", 
                    "⚙️ Settings", 
                    Assembly.GetExecutingAssembly().Location,
                    "MyVeras.RevitAPI.Commands.SettingsCommand"
                );
                settingsButton.ToolTip = "Open API Settings";
                settingsButton.LongDescription = "Configure API key and rendering settings";
                
                // Добавляем иконку для Settings
                try
                {
                    var settingsIconUri = new Uri("pack://application:,,,/MyVeras.RevitAPI;component/Resources/icon_32.png");
                    settingsButton.LargeImage = new BitmapImage(settingsIconUri);
                }
                catch
                {
                    // Игнорируем ошибки с иконками
                }

                // Создаем кнопку Open MyVeras
                var openButton = new PushButtonData(
                    "MyVeras_Open", 
                    "🚀 Open MyVeras", 
                    Assembly.GetExecutingAssembly().Location,
                    "MyVeras.RevitAPI.Commands.OpenCommand"
                );
                openButton.ToolTip = "Open MyVeras AI Rendering Interface";
                openButton.LongDescription = "Start AI-powered rendering process";
                
                // Добавляем иконку для Open MyVeras
                try
                {
                    var openIconUri = new Uri("pack://application:,,,/MyVeras.RevitAPI;component/Resources/icon_32.png");
                    openButton.LargeImage = new BitmapImage(openIconUri);
                }
                catch
                {
                    // Игнорируем ошибки с иконками
                }

                // Добавляем кнопки на панель
                ribbonPanel.AddItem(settingsButton);
                ribbonPanel.AddItem(openButton);
                
                return Result.Succeeded;
            }
            catch (Exception ex)
            {
                TaskDialog.Show("MyVeras Startup Error", 
                    $"Failed to initialize MyVeras plugin: {ex.Message}\n\n{ex.StackTrace}");
                return Result.Failed;
            }
        }

        public Result OnShutdown(UIControlledApplication application)
        {
            return Result.Succeeded;
        }
    }
}
