using System;
using System.Collections.Generic;
using System.Net.Http;
using System.Text;
using System.Threading;
using System.Threading.Tasks;
using MyVeras.Core;
using MyVeras.Models;
using Newtonsoft.Json;

namespace MyVeras.Engines
{
    /// <summary>
    /// Локальный движок рендеринга (ComfyUI/Automatic1111)
    /// </summary>
    public class LocalEngine : IRenderingEngine
    {
        private readonly HttpClient _httpClient;
        private string _baseUrl;
        private string _model;
        private CancellationTokenSource _cancellationTokenSource;

        public string Name => "Local (ComfyUI)";

        public event EventHandler<RenderingProgressEventArgs> ProgressChanged;
        public event EventHandler<RenderingCompletedEventArgs> RenderingCompleted;

        public LocalEngine(string baseUrl = "http://localhost:7860", string model = "SDXL_Architectural")
        {
            _baseUrl = baseUrl;
            _model = model;
            _httpClient = new HttpClient();
            _httpClient.Timeout = TimeSpan.FromMinutes(10);
        }

        public async Task<bool> IsAvailableAsync()
        {
            try
            {
                var response = await _httpClient.GetAsync($"{_baseUrl}/sdapi/v1/samplers");
                return response.IsSuccessStatusCode;
            }
            catch
            {
                return false;
            }
        }

        public async Task<RenderingResult> RenderAsync(RenderingRequest request)
        {
            var startTime = DateTime.Now;
            _cancellationTokenSource = new CancellationTokenSource();

            try
            {
                ProgressChanged?.Invoke(this, new RenderingProgressEventArgs 
                { 
                    ProgressPercentage = 0, 
                    Status = "Подготовка запроса..." 
                });

                var requestData = BuildComfyUIRequest(request);
                var json = JsonConvert.SerializeObject(requestData);
                var content = new StringContent(json, Encoding.UTF8, "application/json");

                ProgressChanged?.Invoke(this, new RenderingProgressEventArgs 
                { 
                    ProgressPercentage = 10, 
                    Status = "Отправка запроса..." 
                });

                var response = await _httpClient.PostAsync($"{_baseUrl}/sdapi/v1/txt2img", content, _cancellationTokenSource.Token);
                response.EnsureSuccessStatusCode();

                ProgressChanged?.Invoke(this, new RenderingProgressEventArgs 
                { 
                    ProgressPercentage = 50, 
                    Status = "Обработка..." 
                });

                var responseContent = await response.Content.ReadAsStringAsync();
                var result = JsonConvert.DeserializeObject<ComfyUIResponse>(responseContent);

                ProgressChanged?.Invoke(this, new RenderingProgressEventArgs 
                { 
                    ProgressPercentage = 90, 
                    Status = "Завершение..." 
                });

                var imageData = Convert.FromBase64String(result.Images[0]);

                var renderingResult = new RenderingResult
                {
                    ImageData = imageData,
                    ExecutionTimeMs = (long)(DateTime.Now - startTime).TotalMilliseconds,
                    Seed = result.Info.Seed,
                    Success = true
                };

                ProgressChanged?.Invoke(this, new RenderingProgressEventArgs 
                { 
                    ProgressPercentage = 100, 
                    Status = "Завершено" 
                });

                RenderingCompleted?.Invoke(this, new RenderingCompletedEventArgs 
                { 
                    Result = renderingResult, 
                    Success = true 
                });

                return renderingResult;
            }
            catch (OperationCanceledException)
            {
                var cancelledResult = new RenderingResult
                {
                    Success = false,
                    ErrorMessage = "Операция отменена"
                };

                RenderingCompleted?.Invoke(this, new RenderingCompletedEventArgs 
                { 
                    Result = cancelledResult, 
                    Success = false,
                    ErrorMessage = "Операция отменена"
                });

                return cancelledResult;
            }
            catch (Exception ex)
            {
                var errorResult = new RenderingResult
                {
                    Success = false,
                    ErrorMessage = ex.Message
                };

                RenderingCompleted?.Invoke(this, new RenderingCompletedEventArgs 
                { 
                    Result = errorResult, 
                    Success = false,
                    ErrorMessage = ex.Message
                });

                return errorResult;
            }
        }

        public void CancelRendering()
        {
            _cancellationTokenSource?.Cancel();
        }

        private object BuildComfyUIRequest(RenderingRequest request)
        {
            return new
            {
                prompt = request.Prompt,
                negative_prompt = "blurry, low quality, distorted, ugly",
                width = request.Width,
                height = request.Height,
                steps = request.Steps,
                cfg_scale = 7.5f,
                sampler_name = "DPM++ 2M Karras",
                scheduler = "Karras",
                seed = request.Seed ?? -1,
                denoising_strength = request.DenoisingStrength,
                init_images = request.SourceImage != null ? new[] { Convert.ToBase64String(request.SourceImage) } : null,
                controlnet_units = request.SourceImage != null ? new[]
                {
                    new
                    {
                        input_image = Convert.ToBase64String(request.SourceImage),
                        module = "depth",
                        model = "control_v11f1p_sd15_depth [cfd03158]",
                        weight = 1.0f,
                        resize_mode = 1,
                        low_vram = false,
                        processor_res = 512,
                        threshold_a = 64,
                        threshold_b = 64,
                        guidance_start = 0.0f,
                        guidance_end = 1.0f,
                        pixel_perfect = false
                    }
                } : null
            };
        }
    }

    /// <summary>
    /// Модель ответа от ComfyUI/Automatic1111
    /// </summary>
    public class ComfyUIResponse
    {
        public List<string> Images { get; set; }
        public ComfyUIInfo Info { get; set; }
        public List<string> Parameters { get; set; }
    }

    public class ComfyUIInfo
    {
        public int Seed { get; set; }
        public List<string> AllSeeds { get; set; }
        public List<string> AllSubseeds { get; set; }
        public float CfgScale { get; set; }
        public List<string> SamplerName { get; set; }
        public int Steps { get; set; }
        public int BatchSize { get; set; }
    }
}
