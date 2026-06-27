using System;
using System.Collections.Generic;
using System.Net;
using System.Net.Http;
using System.Text;
using System.Text.Json;
using System.Threading.Tasks;
using FluentAssertions;
using Moq;
using Moq.Protected;
using MyVeras.Core;
using Xunit;

namespace MyVeras.Tests
{
    public class UserInputValidationTests : IDisposable
    {
        private readonly Mock<HttpMessageHandler> _mockHttpHandler;
        private readonly HttpClient _httpClient;
        private readonly GenApiClient _apiClient;

        public UserInputValidationTests()
        {
            _mockHttpHandler = new Mock<HttpMessageHandler>();
            _httpClient = new HttpClient(_mockHttpHandler.Object);
            _apiClient = new GenApiClient("test-api-key");
        }

        [Fact]
        public async Task StartGenerationAsync_WithEmptyPrompt_ShouldThrowFriendlyException()
        {
            // Act & Assert
            var exception = await Assert.ThrowsAsync<ArgumentNullException>(() => 
                _apiClient.StartGenerationAsync("", "negative prompt", "base64-image"));

            exception.Message.Should().Contain("prompt");
            exception.ParamName.Should().Be("prompt");
        }

        [Fact]
        public async Task StartGenerationAsync_WithNullPrompt_ShouldThrowArgumentNullException()
        {
            // Act & Assert
            var exception = await Assert.ThrowsAsync<ArgumentNullException>(() => 
                _apiClient.StartGenerationAsync(null, "negative prompt", "base64-image"));

            exception.Message.Should().Contain("prompt");
            exception.ParamName.Should().Be("prompt");
        }

        [Fact]
        public async Task StartGenerationAsync_WithEmptyBase64_ShouldThrowFriendlyException()
        {
            // Act & Assert
            var exception = await Assert.ThrowsAsync<ArgumentNullException>(() => 
                _apiClient.StartGenerationAsync("test prompt", "negative prompt", ""));

            exception.Message.Should().Contain("base64Image");
            exception.ParamName.Should().Be("base64Image");
        }

        [Fact]
        public async Task StartGenerationAsync_WithNullBase64_ShouldThrowArgumentNullException()
        {
            // Act & Assert
            var exception = await Assert.ThrowsAsync<ArgumentNullException>(() => 
                _apiClient.StartGenerationAsync("test prompt", "negative prompt", null));

            exception.Message.Should().Contain("base64Image");
            exception.ParamName.Should().Be("base64Image");
        }

        [Fact]
        public async Task StartGenerationAsync_With500ServerError_ShouldThrowFriendlyException()
        {
            // Arrange
            var serverErrorResponse = new HttpResponseMessage(HttpStatusCode.InternalServerError)
            {
                Content = new StringContent("Internal server error occurred")
            };

            _mockHttpHandler.Protected()
                .Setup<Task<HttpResponseMessage>>(
                    "SendAsync",
                    ItExpr.IsAny<HttpRequestMessage>(),
                    ItExpr.IsAny<CancellationToken>())
                .ReturnsAsync(serverErrorResponse);

            // Act & Assert
            var exception = await Assert.ThrowsAsync<Exception>(() => 
                _apiClient.StartGenerationAsync("test prompt", "negative prompt", "base64-image"));

            exception.Message.Should().Contain("Failed to start generation");
            exception.InnerException.Should().BeOfType<HttpRequestException>();
        }

        [Fact]
        public async Task CheckStatusAsync_With500ServerError_ShouldThrowFriendlyException()
        {
            // Arrange
            var serverErrorResponse = new HttpResponseMessage(HttpStatusCode.InternalServerError)
            {
                Content = new StringContent("Internal server error occurred")
            };

            _mockHttpHandler.Protected()
                .Setup<Task<HttpResponseMessage>>(
                    "SendAsync",
                    ItExpr.IsAny<HttpRequestMessage>(),
                    ItExpr.IsAny<CancellationToken>())
                .ReturnsAsync(serverErrorResponse);

            // Act & Assert
            var exception = await Assert.ThrowsAsync<Exception>(() => 
                _apiClient.CheckStatusAsync("test-request-id"));

            exception.Message.Should().Contain("Failed to check status");
            exception.InnerException.Should().BeOfType<HttpRequestException>();
        }

        [Fact]
        public async Task DownloadImageAsync_With500ServerError_ShouldThrowFriendlyException()
        {
            // Arrange
            var serverErrorResponse = new HttpResponseMessage(HttpStatusCode.InternalServerError)
            {
                Content = new StringContent("Internal server error occurred")
            };

            _mockHttpHandler.Protected()
                .Setup<Task<HttpResponseMessage>>(
                    "SendAsync",
                    ItExpr.IsAny<HttpRequestMessage>(),
                    ItExpr.IsAny<CancellationToken>())
                .ReturnsAsync(serverErrorResponse);

            // Act & Assert
            var exception = await Assert.ThrowsAsync<Exception>(() => 
                _apiClient.DownloadImageAsync("https://example.com/image.png"));

            exception.Message.Should().Contain("Failed to download image");
            exception.InnerException.Should().BeOfType<HttpRequestException>();
        }

        [Fact]
        public async Task StartGenerationAsync_WithTimeout_ShouldThrowFriendlyException()
        {
            // Arrange
            _mockHttpHandler.Protected()
                .Setup<Task<HttpResponseMessage>>(
                    "SendAsync",
                    ItExpr.IsAny<HttpRequestMessage>(),
                    ItExpr.IsAny<CancellationToken>())
                .ThrowsAsync(new TaskCanceledException("Request timeout"));

            // Act & Assert
            var exception = await Assert.ThrowsAsync<Exception>(() => 
                _apiClient.StartGenerationAsync("test prompt", "negative prompt", "base64-image"));

            exception.Message.Should().Contain("Failed to start generation");
            exception.InnerException.Should().BeOfType<TaskCanceledException>();
        }

        [Fact]
        public async Task ExportViewToBase64Async_WithInvalidDocument_ShouldThrowFriendlyException()
        {
            // Act & Assert
            var exception = await Assert.ThrowsAsync<ArgumentNullException>(() => 
                _apiClient.ExportViewToBase64Async(null, "test view"));

            exception.Message.Should().Contain("document");
            exception.ParamName.Should().Be("document");
        }

        [Fact]
        public async Task ExportViewToBase64Async_WithInvalidViewName_ShouldThrowFriendlyException()
        {
            // Act & Assert
            var exception = await Assert.ThrowsAsync<ArgumentNullException>(() => 
                _apiClient.ExportViewToBase64Async(new object(), null));

            exception.Message.Should().Contain("viewName");
            exception.ParamName.Should().Be("viewName");
        }

        [Fact]
        public async Task ExportViewToBase64Async_WithEmptyViewName_ShouldThrowFriendlyException()
        {
            // Act & Assert
            var exception = await Assert.ThrowsAsync<ArgumentNullException>(() => 
                _apiClient.ExportViewToBase64Async(new object(), ""));

            exception.Message.Should().Contain("viewName");
            exception.ParamName.Should().Be("viewName");
        }

        [Fact]
        public void Constructor_WithInvalidApiKey_ShouldThrowFriendlyException()
        {
            // Act & Assert
            var exception = Assert.Throws<ArgumentNullException>(() => new GenApiClient(null));

            exception.Message.Should().Contain("apiKey");
            exception.ParamName.Should().Be("apiKey");
        }

        public void Dispose()
        {
            _httpClient?.Dispose();
            _apiClient?.Dispose();
        }
    }
}
