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
    /// Облачный движок рендеринга (внешний REST API)
    /// </summary>
    public class CloudEngine : IRenderingEngine
    {
        private readonly HttpClient _httpClient;
        private string _baseUrl;
        private string _apiKey;
        private CancellationTokenSource _cancellationTokenSource;

        public string Name => "Cloud API";

        public event EventHandler<RenderingProgressEventArgs> ProgressChanged;
        public event EventHandler<RenderingCompletedEventArgs> RenderingCompleted;

        public CloudEngine(string baseUrl, string apiKey)
        {
            _baseUrl = baseUrl.TrimEnd('/');
            _apiKey = apiKey;
            _httpClient = new HttpClient();
            _httpClient.Timeout = TimeSpan.FromMinutes(15);
            _httpClient.DefaultRequestHeaders.Add("Authorization", $"Bearer {_apiKey}");
        }

        public async Task<bool> IsAvailableAsync()
        {
            try
            {
                var response = await _httpClient.GetAsync($"{_baseUrl}/health");
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

                var requestData = BuildCloudRequest(request);
                var json = JsonConvert.SerializeObject(requestData);
                var content = new StringContent(json, Encoding.UTF8, "application/json");

                ProgressChanged?.Invoke(this, new RenderingProgressEventArgs 
                { 
                    ProgressPercentage = 10, 
                    Status = "Отправка запроса..." 
                });

                var response = await _httpClient.PostAsync($"{_baseUrl}/v1/generate", content, _cancellationTokenSource.Token);
                response.EnsureSuccessStatusCode();

                var responseContent = await response.Content.ReadAsStringAsync();
                var jobResponse = JsonConvert.DeserializeObject<CloudJobResponse>(responseContent);

                ProgressChanged?.Invoke(this, new RenderingProgressEventArgs 
                { 
                    ProgressPercentage = 20, 
                    Status = "Задача поставлена в очередь..." 
                });

                var result = await PollJobCompletion(jobResponse.JobId, _cancellationTokenSource.Token);

                var renderingResult = new RenderingResult
                {
                    ImageData = result.ImageData,
                    ExecutionTimeMs = (long)(DateTime.Now - startTime).TotalMilliseconds,
                    Seed = result.Seed,
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

        private async Task<CloudJobResult> PollJobCompletion(string jobId, CancellationToken cancellationToken)
        {
            var lastProgress = 20;

            while (!cancellationToken.IsCancellationRequested)
            {
                var statusResponse = await _httpClient.GetAsync($"{_baseUrl}/v1/jobs/{jobId}", cancellationToken);
                statusResponse.EnsureSuccessStatusCode();

                var statusContent = await statusResponse.Content.ReadAsStringAsync();
                var status = JsonConvert.DeserializeObject<CloudJobStatus>(statusContent);

                if (status.Progress > lastProgress)
                {
                    lastProgress = status.Progress;
                    ProgressChanged?.Invoke(this, new RenderingProgressEventArgs 
                    { 
                        ProgressPercentage = status.Progress, 
                        Status = status.Status 
                    });
                }

                if (status.Status == "completed")
                {
                    var imageResponse = await _httpClient.GetAsync($"{_baseUrl}/v1/jobs/{jobId}/result", cancellationToken);
                    imageResponse.EnsureSuccessStatusCode();

                    var imageContent = await imageResponse.Content.ReadAsStringAsync();
                    var imageResult = JsonConvert.DeserializeObject<CloudImageResult>(imageContent);

                    return new CloudJobResult
                    {
                        ImageData = Convert.FromBase64String(imageResult.Image),
                        Seed = imageResult.Seed
                    };
                }
                else if (status.Status == "failed")
                {
                    throw new Exception($"Job failed: {status.Error}");
                }

                await Task.Delay(2000, cancellationToken);
            }

            throw new OperationCanceledException();
        }

        private object BuildCloudRequest(RenderingRequest request)
        {
            return new
            {
                prompt = request.Prompt,
                negative_prompt = "blurry, low quality, distorted, ugly, bad architecture",
                width = request.Width,
                height = request.Height,
                steps = request.Steps,
                cfg_scale = 7.5f,
                sampler = "DPM++ 2M Karras",
                seed = request.Seed ?? -1,
                denoising_strength = request.DenoisingStrength,
                init_image = request.SourceImage != null ? Convert.ToBase64String(request.SourceImage) : null,
                control_image = request.SourceImage != null ? Convert.ToBase64String(request.SourceImage) : null,
                controlnet_conditioning_scale = 1.0f,
                model = "sdxl-architectural-v1"
            };
        }
    }

    /// <summary>
    /// Модели для работы с облачным API
    /// </summary>
    public class CloudJobResponse
    {
        public string JobId { get; set; }
        public string Status { get; set; }
    }

    public class CloudJobStatus
    {
        public string JobId { get; set; }
        public string Status { get; set; }
        public int Progress { get; set; }
        public string Error { get; set; }
        public DateTime CreatedAt { get; set; }
        public DateTime? CompletedAt { get; set; }
    }

    public class CloudImageResult
    {
        public string Image { get; set; }
        public int Seed { get; set; }
        public Dictionary<string, object> Metadata { get; set; }
    }

    public class CloudJobResult
    {
        public byte[] ImageData { get; set; }
        public int Seed { get; set; }
    }
}
