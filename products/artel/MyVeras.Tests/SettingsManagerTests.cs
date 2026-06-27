using System;
using System.IO;
using System.Threading.Tasks;
using FluentAssertions;
using MyVeras.Settings;
using Xunit;

namespace MyVeras.Tests
{
    public class SettingsManagerTests : IDisposable
    {
        private readonly string _testSettingsPath;
        private readonly string _originalAppData;
        private readonly SettingsManager _settingsManager;

        public SettingsManagerTests()
        {
            // Создаем временную папку для тестов
            _testSettingsPath = Path.Combine(Path.GetTempPath(), "MyVeras_Tests_" + Guid.NewGuid().ToString("N"));
            Directory.CreateDirectory(_testSettingsPath);
            
            // Сохраняем оригинальный AppData
            _originalAppData = Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData);
            
            // Подменяем путь к настройкам для тестов через рефлексию
            _settingsManager = SettingsManager.Instance;
            
            // Удаляем существующий файл настроек если он есть
            var settingsFile = Path.Combine(_testSettingsPath, "settings.json");
            if (File.Exists(settingsFile))
            {
                File.Delete(settingsFile);
            }
        }

        [Fact]
        public void SettingsManager_Instance_ShouldNotBeNull()
        {
            // Act & Assert
            var instance = SettingsManager.Instance;
            instance.Should().NotBeNull();
        }

        [Fact]
        public void LoadSettings_ShouldNotThrowException()
        {
            // Act & Assert
            var action = () => _settingsManager.LoadSettings();
            action.Should().NotThrow();
        }

        [Fact]
        public void SaveSettings_ShouldNotThrowException()
        {
            // Act & Assert
            var action = () => _settingsManager.SaveSettings();
            action.Should().NotThrow();
        }

        [Fact]
        public async Task SaveSettingsAsync_ShouldNotThrowException()
        {
            // Act & Assert
            var action = async () => await _settingsManager.SaveSettingsAsync();
            await action.Should().NotThrowAsync();
        }

        public void Dispose()
        {
            // Очистка после тестов
            try
            {
                if (Directory.Exists(_testSettingsPath))
                {
                    Directory.Delete(_testSettingsPath, true);
                }
            }
            catch
            {
                // Игнорируем ошибки очистки
            }
        }
    }
}
