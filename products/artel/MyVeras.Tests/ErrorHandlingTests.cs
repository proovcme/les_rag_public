using System;
using System.Net;
using System.Net.Http;
using System.Text;
using System.Text.Json;
using System.Threading;
using System.Threading.Tasks;
using FluentAssertions;
using Moq;
using Moq.Protected;
using MyVeras.Core;
using Xunit;

namespace MyVeras.Tests
{
    public class ErrorHandlingTests : IDisposable
    {
        private readonly Mock<HttpMessageHandler> _mockHttpHandler;
        private readonly HttpClient _httpClient;
        private readonly GenApiClient _apiClient;

        public ErrorHandlingTests()
        {
            _mockHttpHandler = new Mock<HttpMessageHandler>();
            _httpClient = new HttpClient(_mockHttpHandler.Object);
            _apiClient = new GenApiClient("test-api-key");
        }

        [Fact]
        public async Task StartGenerationAsync_WithUnauthorized_ShouldThrowFriendlyException()
        {
            // Arrange
            var unauthorizedResponse = new HttpResponseMessage(HttpStatusCode.Unauthorized)
            {
                Content = new StringContent(JsonSerializer.Serialize(new
                {
                    error = "Invalid API key"
                }), Encoding.UTF8, "application/json")
            };

            _mockHttpHandler.Protected()
                .Setup<Task<HttpResponseMessage>>(
                    "SendAsync",
                    ItExpr.IsAny<HttpRequestMessage>(),
                    ItExpr.IsAny<CancellationToken>())
                .ReturnsAsync(unauthorizedResponse);

            // Act & Assert
            var exception = await Assert.ThrowsAsync<Exception>(() => 
                _apiClient.StartGenerationAsync("test prompt", "negative prompt", "base64-image"));

            exception.Message.Should().Contain("Failed to start generation");
            exception.InnerException.Should().BeOfType<HttpRequestException>();
        }

        [Fact]
        public async Task CheckStatusAsync_WithUnauthorized_ShouldThrowFriendlyException()
        {
            // Arrange
            var unauthorizedResponse = new HttpResponseMessage(HttpStatusCode.Unauthorized)
            {
                Content = new StringContent(JsonSerializer.Serialize(new
                {
                    error = "API key expired"
                }), Encoding.UTF8, "application/json")
            };

            _mockHttpHandler.Protected()
                .Setup<Task<HttpResponseMessage>>(
                    "SendAsync",
                    ItExpr.IsAny<HttpRequestMessage>(),
                    ItExpr.IsAny<CancellationToken>())
                .ReturnsAsync(unauthorizedResponse);

            // Act & Assert
            var exception = await Assert.ThrowsAsync<Exception>(() => 
                _apiClient.CheckStatusAsync("test-request-id"));

            exception.Message.Should().Contain("Failed to check status");
            exception.InnerException.Should().BeOfType<HttpRequestException>();
        }

        [Fact]
        public async Task DownloadImageAsync_WithUnauthorized_ShouldThrowFriendlyException()
        {
            // Arrange
            var unauthorizedResponse = new HttpResponseMessage(HttpStatusCode.Unauthorized);

            _mockHttpHandler.Protected()
                .Setup<Task<HttpResponseMessage>>(
                    "SendAsync",
                    ItExpr.IsAny<HttpRequestMessage>(),
                    ItExpr.IsAny<CancellationToken>())
                .ReturnsAsync(unauthorizedResponse);

            // Act & Assert
            var exception = await Assert.ThrowsAsync<Exception>(() => 
                _apiClient.DownloadImageAsync("https://example.com/image.png"));

            exception.Message.Should().Contain("Failed to download image");
            exception.InnerException.Should().BeOfType<HttpRequestException>();
        }

        [Fact]
        public async Task StartGenerationAsync_WithBadRequest_ShouldThrowFriendlyException()
        {
            // Arrange
            var badRequestResponse = new HttpResponseMessage(HttpStatusCode.BadRequest)
            {
                Content = new StringContent(JsonSerializer.Serialize(new
                {
                    error = "Invalid prompt format"
                }), Encoding.UTF8, "application/json")
            };

            _mockHttpHandler.Protected()
                .Setup<Task<HttpResponseMessage>>(
                    "SendAsync",
                    ItExpr.IsAny<HttpRequestMessage>(),
                    ItExpr.IsAny<CancellationToken>())
                .ReturnsAsync(badRequestResponse);

            // Act & Assert
            var exception = await Assert.ThrowsAsync<Exception>(() => 
                _apiClient.StartGenerationAsync("test prompt", "negative prompt", "base64-image"));

            exception.Message.Should().Contain("Failed to start generation");
        }

        [Fact]
        public async Task StartGenerationAsync_WithServerError_ShouldThrowFriendlyException()
        {
            // Arrange
            var serverErrorResponse = new HttpResponseMessage(HttpStatusCode.InternalServerError)
            {
                Content = new StringContent("Internal server error")
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
        }

        [Fact]
        public async Task StartGenerationAsync_WithNetworkTimeout_ShouldThrowFriendlyException()
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
        }

        [Fact]
        public async Task CheckStatusAsync_WithInvalidJson_ShouldThrowFriendlyException()
        {
            // Arrange
            var invalidJsonResponse = new HttpResponseMessage(HttpStatusCode.OK)
            {
                Content = new StringContent("{ invalid json content")
            };

            _mockHttpHandler.Protected()
                .Setup<Task<HttpResponseMessage>>(
                    "SendAsync",
                    ItExpr.IsAny<HttpRequestMessage>(),
                    ItExpr.IsAny<CancellationToken>())
                .ReturnsAsync(invalidJsonResponse);

            // Act & Assert
            var exception = await Assert.ThrowsAsync<Exception>(() => 
                _apiClient.CheckStatusAsync("test-request-id"));

            exception.Message.Should().Contain("Failed to check status");
        }

        [Fact]
        public async Task StartGenerationAsync_WithNullRequestId_ShouldThrowFriendlyException()
        {
            // Arrange
            var responseContent = new
            {
                status = "starting",
                request_id = (string)null // Null request_id
            };
            
            var httpResponse = new HttpResponseMessage(HttpStatusCode.OK)
            {
                Content = new StringContent(JsonSerializer.Serialize(responseContent), Encoding.UTF8, "application/json")
            };

            _mockHttpHandler.Protected()
                .Setup<Task<HttpResponseMessage>>(
                    "SendAsync",
                    ItExpr.IsAny<HttpRequestMessage>(),
                    ItExpr.IsAny<CancellationToken>())
                .ReturnsAsync(httpResponse);

            // Act & Assert
            var exception = await Assert.ThrowsAsync<Exception>(() => 
                _apiClient.StartGenerationAsync("test prompt", "negative prompt", "base64-image"));

            exception.Message.Should().Be("No request_id received");
        }

        [Fact]
        public void Constructor_WithNullApiKey_ShouldThrowFriendlyException()
        {
            // Act & Assert
            var exception = Assert.Throws<ArgumentNullException>(() => new GenApiClient(null));

            exception.Message.Should().Contain("apiKey");
            exception.ParamName.Should().Be("apiKey");
        }

        [Fact]
        public void Constructor_WithEmptyApiKey_ShouldThrowFriendlyException()
        {
            // Act & Assert
            var exception = Assert.Throws<ArgumentNullException>(() => new GenApiClient(""));

            exception.Message.Should().Contain("apiKey");
            exception.ParamName.Should().Be("apiKey");
        }

        [Fact]
        public void Constructor_WithWhitespaceApiKey_ShouldThrowFriendlyException()
        {
            // Act & Assert
            var exception = Assert.Throws<ArgumentNullException>(() => new GenApiClient("   "));

            exception.Message.Should().Contain("apiKey");
            exception.ParamName.Should().Be("apiKey");
        }

        [Fact]
        public async Task ExportViewToBase64Async_WithNullDocument_ShouldThrowArgumentNullException()
        {
            // Act & Assert
            await Assert.ThrowsAsync<ArgumentNullException>(() => 
                _apiClient.ExportViewToBase64Async(null, "test view"));
        }

        [Fact]
        public async Task ExportViewToBase64Async_WithNullViewName_ShouldThrowArgumentNullException()
        {
            // Act & Assert
            await Assert.ThrowsAsync<ArgumentNullException>(() => 
                _apiClient.ExportViewToBase64Async(new object(), null));
        }

        public void Dispose()
        {
            _httpClient?.Dispose();
            _apiClient?.Dispose();
        }
    }
}
