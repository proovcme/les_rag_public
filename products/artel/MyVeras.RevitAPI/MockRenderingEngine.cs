using System;
using System.Threading.Tasks;
using MyVeras.Core;
using MyVeras.Models;
using MyVeras.Settings;

namespace MyVeras.RevitAPI
{
    /// <summary>
    /// Mock движок рендеринга для демонстрации
    /// </summary>
    public class MockRenderingEngine : IRenderingEngine
    {
        private readonly SettingsManager _settingsManager;

        public string Name => "Mock Rendering Engine";

        public event EventHandler<RenderingProgressEventArgs> ProgressChanged;
        public event EventHandler<RenderingCompletedEventArgs> RenderingCompleted;

        public MockRenderingEngine()
        {
            _settingsManager = SettingsManager.Instance;
        }

        public async Task<bool> IsAvailableAsync()
        {
            if (_settingsManager == null) return false;
            
            var settings = _settingsManager.Settings;
            if (settings == null) return false;
            
            // Проверяем наличие API ключа
            return !string.IsNullOrEmpty(settings.ApiKey);
        }

        public async Task<RenderingResult> RenderAsync(RenderingRequest request)
        {
            if (request == null)
            {
                return new RenderingResult 
                { 
                    Success = false, 
                    ErrorMessage = "Request is null" 
                };
            }

            try
            {
                if (_settingsManager == null)
                {
                    return new RenderingResult 
                    { 
                        Success = false, 
                        ErrorMessage = "SettingsManager is null" 
                    };
                }

                var settings = _settingsManager.Settings;
                if (settings == null)
                {
                    return new RenderingResult 
                    { 
                        Success = false, 
                        ErrorMessage = "Settings are null" 
                    };
                }

                // Проверяем API ключ
                if (string.IsNullOrEmpty(settings.ApiKey))
                {
                    return new RenderingResult
                    {
                        Success = false,
                        ErrorMessage = "API key is not configured"
                    };
                }

                // Имитация процесса рендеринга
                for (int i = 0; i <= 100; i += 10)
                {
                    ProgressChanged?.Invoke(this, new RenderingProgressEventArgs 
                    { 
                        ProgressPercentage = i, 
                        Status = $"Mock rendering: {i}%" 
                    });
                    await Task.Delay(50);
                }

                // Создаем фиктивное изображение
                var mockImageData = CreateTestImage();

                var result = new RenderingResult
                {
                    Success = true,
                    ImageData = mockImageData,
                    ExecutionTimeMs = 5000,
                    Seed = 12345
                };

                RenderingCompleted?.Invoke(this, new RenderingCompletedEventArgs 
                { 
                    Result = result 
                });
                return result;
            }
            catch (Exception ex)
            {
                return new RenderingResult
                {
                    Success = false,
                    ErrorMessage = ex.Message
                };
            }
        }

        public void CancelRendering()
        {
            // Mock implementation
        }

        private byte[] CreateTestImage()
        {
            // Создаем простое тестовое PNG изображение
            var pngHeader = new byte[] { 0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A };
            var imageData = new byte[1024]; // 1KB тестовое изображение
            
            // Копируем заголовок
            Array.Copy(pngHeader, imageData, pngHeader.Length);
            
            return imageData;
        }
    }
}
