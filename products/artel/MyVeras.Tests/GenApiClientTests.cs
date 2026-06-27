using System;
using System.Collections.Generic;
using System.Net;
using System.Net.Http;
using System.Text;
using System.Text.Json;
using System.Threading;
using System.Threading.Tasks;
using FluentAssertions;
using Microsoft.Extensions.Http;
using Moq;
using Moq.Protected;
using MyVeras.Core;
using Xunit;

namespace MyVeras.Tests
{
    public class GenApiClientTests : IDisposable
    {
        private readonly Mock<HttpMessageHandler> _mockHttpHandler;
        private readonly GenApiClient _apiClient;

        public GenApiClientTests()
        {
            _mockHttpHandler = new Mock<HttpMessageHandler>();
            
            // Создаем HttpClient с мокированным обработчиком
            var httpClient = new HttpClient(_mockHttpHandler.Object);
            
            // Создаем GenApiClient через рефлексию, чтобы подменить HttpClient
            _apiClient = new GenApiClient("test-api-key");
            
            // Подменяем внутренний HttpClient через рефлексию
            var httpClientField = typeof(GenApiClient).GetField("_httpClient", 
                System.Reflection.BindingFlags.NonPublic | System.Reflection.BindingFlags.Instance);
            httpClientField?.SetValue(_apiClient, httpClient);
        }

        [Fact]
        public void Constructor_WithValidApiKey_ShouldCreateInstance()
        {
            // Act & Assert
            var client = new GenApiClient("valid-api-key");
            client.Should().NotBeNull();
        }

        [Fact]
        public void Constructor_WithNullApiKey_ShouldThrowArgumentNullException()
        {
            // Act & Assert
            Assert.Throws<ArgumentNullException>(() => new GenApiClient(null));
        }

        [Fact]
        public void Constructor_WithEmptyApiKey_ShouldThrowArgumentNullException()
        {
            // Act & Assert
            Assert.Throws<ArgumentNullException>(() => new GenApiClient(""));
        }

        [Fact]
        public void Constructor_WithWhitespaceApiKey_ShouldThrowArgumentNullException()
        {
            // Act & Assert
            Assert.Throws<ArgumentNullException>(() => new GenApiClient("   "));
        }

        public void Dispose()
        {
            // Освобождаем ресурсы
            _apiClient?.Dispose();
        }
    }
}
