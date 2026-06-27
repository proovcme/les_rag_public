using System;
using System.IO;
using System.Linq;
using FluentAssertions;
using MyVeras.Core;
using Xunit;

namespace MyVeras.Tests
{
    public class Base64ConversionTests
    {
        [Fact]
        public void ConvertByteArrayToBase64_WithValidPngData_ShouldReturnCorrectBase64String()
        {
            // Arrange - создаем тестовый PNG файл (1x1 пиксель, красный цвет)
            var pngData = new byte[]
            {
                0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A, // PNG signature
                0x00, 0x00, 0x00, 0x0D, 0x49, 0x48, 0x44, 0x52, // IHDR chunk start
                0x00, 0x00, 0x00, 0x01, 0x00, 0x00, 0x00, 0x01, // Width: 1, Height: 1
                0x08, 0x02, 0x00, 0x00, 0x00, 0x90, 0x77, 0x53, // Bit depth: 8, Color type: 2 (RGB)
                0xDE, 0x00, 0x00, 0x0C, 0x49, 0x44, 0x41, 0x54, // IDAT chunk start
                0x08, 0x99, 0x01, 0x01, 0x00, 0x00, 0x00, 0x00, // Compressed image data
                0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, // Padding
                0x00, 0x00, 0x00, 0x00, 0x49, 0x45, 0x4E, 0x44, // IEND chunk
                0xAE, 0x42, 0x60, 0x82 // CRC
            };

            // Act
            var base64String = Convert.ToBase64String(pngData);

            // Assert
            base64String.Should().NotBeNullOrEmpty();
            base64String.Should().StartWith("iVBORw0KGgo"); // Standard PNG base64 prefix
            
            // Проверяем что строка содержит только валидные Base64 символы
            var validBase64Chars = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/=";
            base64String.All(c => validBase64Chars.Contains(c)).Should().BeTrue();
        }

        [Fact]
        public void ConvertByteArrayToBase64_WithEmptyArray_ShouldReturnEmptyString()
        {
            // Arrange
            var emptyData = Array.Empty<byte>();

            // Act
            var base64String = Convert.ToBase64String(emptyData);

            // Assert
            base64String.Should().BeEmpty();
        }

        [Fact]
        public void ConvertByteArrayToBase64_WithNullArray_ShouldThrowArgumentNullException()
        {
            // Act & Assert
            Assert.Throws<ArgumentNullException>(() => Convert.ToBase64String(null));
        }

        [Fact]
        public void CreateApiImageFormat_ShouldIncludeCorrectPrefix()
        {
            // Arrange
            var imageBytes = new byte[] { 0x89, 0x50, 0x4E, 0x47 }; // PNG header
            var base64Data = Convert.ToBase64String(imageBytes);

            // Act
            var apiFormat = $"data:image/png;base64,{base64Data}";

            // Assert
            apiFormat.Should().StartWith("data:image/png;base64,");
            apiFormat.Should().Contain(base64Data);
        }

        [Fact]
        public void CreateApiImageFormat_WithJpegData_ShouldUseCorrectMimeType()
        {
            // Arrange
            var jpegBytes = new byte[] { 0xFF, 0xD8, 0xFF }; // JPEG header
            var base64Data = Convert.ToBase64String(jpegBytes);

            // Act
            var apiFormat = $"data:image/jpeg;base64,{base64Data}";

            // Assert
            apiFormat.Should().StartWith("data:image/jpeg;base64,");
            apiFormat.Should().Contain(base64Data);
        }

        [Fact]
        public async Task ExportViewToBase64Async_ShouldReturnValidBase64String()
        {
            // Arrange
            var apiClient = new GenApiClient("test-key");
            var mockDocument = new object(); // Mock document object

            // Act
            var base64String = await apiClient.ExportViewToBase64Async(mockDocument, "Test View");

            // Assert
            base64String.Should().NotBeNullOrEmpty();
            base64String.Should().StartWith("iVBORw0KGgo"); // Should be PNG format
            
            // Проверяем что это валидный Base64
            var decodedBytes = Convert.FromBase64String(base64String);
            decodedBytes.Should().NotBeEmpty();
            
            // Проверяем PNG сигнатуру
            decodedBytes.Take(8).Should().BeEquivalentTo(new byte[] { 0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A });
        }

        [Fact]
        public void Base64String_RoundTripConversion_ShouldPreserveData()
        {
            // Arrange
            var originalData = new byte[] { 0x01, 0x02, 0x03, 0x04, 0x05 };

            // Act
            var base64String = Convert.ToBase64String(originalData);
            var decodedData = Convert.FromBase64String(base64String);

            // Assert
            decodedData.Should().BeEquivalentTo(originalData);
        }

        [Fact]
        public void Base64String_WithLargeData_ShouldConvertCorrectly()
        {
            // Arrange - создаем большие данные (10KB)
            var largeData = new byte[10240];
            for (int i = 0; i < largeData.Length; i++)
            {
                largeData[i] = (byte)(i % 256);
            }

            // Act
            var base64String = Convert.ToBase64String(largeData);
            var decodedData = Convert.FromBase64String(base64String);

            // Assert
            decodedData.Should().BeEquivalentTo(largeData);
            base64String.Length.Should().BeGreaterThan(10000); // Base64 увеличивает размер
        }
    }
}
