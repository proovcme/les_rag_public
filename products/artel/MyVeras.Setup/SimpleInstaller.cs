using System;
using System.IO;
using System.Reflection;

namespace MyVeras.Setup
{
    public class SimpleInstaller
    {
        public static void Main(string[] args)
        {
            Console.WriteLine("Starting MyVeras Setup v1.1.0");
            
            try
            {
                // Правильный путь Autodesk
                var addinsPath = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.CommonApplicationData), 
                    "Autodesk", "Revit", "Addins", "2025");
                var pluginPath = Path.Combine(addinsPath, "MyVeras");

                Console.WriteLine($"Addins path: {addinsPath}");
                Console.WriteLine($"Plugin path: {pluginPath}");

                // Создаем папки
                Directory.CreateDirectory(addinsPath);
                Directory.CreateDirectory(pluginPath);

                // Копируем файлы
                var currentPath = Path.GetDirectoryName(Assembly.GetExecutingAssembly().Location);
                var dllFiles = Directory.GetFiles(currentPath, "*.dll");
                
                Console.WriteLine($"Found {dllFiles.Length} DLL files to copy");
                
                foreach (var sourcePath in dllFiles)
                {
                    var fileName = Path.GetFileName(sourcePath);
                    var targetPath = Path.Combine(pluginPath, fileName);
                    
                    try
                    {
                        File.Copy(sourcePath, targetPath, true);
                        Console.WriteLine($"Copied: {fileName} -> {targetPath}");
                    }
                    catch (Exception ex)
                    {
                        Console.WriteLine($"Failed to copy {fileName}: {ex.Message}");
                    }
                }

                // Копируем .addin файл
                var sourceAddinPath = Path.Combine(currentPath, "MyVeras.addin");
                var targetAddinPath = Path.Combine(addinsPath, "MyVeras.addin");
                
                if (File.Exists(sourceAddinPath))
                {
                    File.Copy(sourceAddinPath, targetAddinPath, true);
                    Console.WriteLine($"Copied addin file to: {targetAddinPath}");
                }

                Console.WriteLine("Installation completed successfully!");
                Console.WriteLine("Press any key to exit...");
                Console.ReadKey();
            }
            catch (Exception ex)
            {
                Console.WriteLine($"Installation failed: {ex.Message}");
                Console.WriteLine("Press any key to exit...");
                Console.ReadKey();
            }
        }
    }
}
