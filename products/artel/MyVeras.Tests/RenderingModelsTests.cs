using System;
using MyVeras.Models;
using Xunit;

namespace MyVeras.Tests
{
    /// <summary>
    /// Unit-тесты для моделей рендеринга
    /// </summary>
    public class RenderingModelsTests
    {
        [Fact]
        public void RenderingRequest_WithDefaultValues_ShouldHaveCorrectProperties()
        {
            // Arrange & Act
            var request = new RenderingRequest();

            // Assert
            Assert.Equal(1024, request.Width);
            Assert.Equal(1024, request.Height);
            Assert.Equal("standard", request.Quality);
            Assert.Equal("realistic", request.Style);
            Assert.Null(request.Prompt);
            Assert.Null(request.SourceImage);
        }

        [Fact]
        public void RenderingRequest_WithCustomValues_ShouldSetPropertiesCorrectly()
        {
            // Arrange
            var prompt = "Modern architectural visualization";
            var imageData = new byte[] { 0x89, 0x50, 0x4E, 0x47 };

            // Act
            var request = new RenderingRequest
            {
                Prompt = prompt,
                Width = 2048,
                Height = 1080,
                Quality = "hd",
                Style = "artistic",
                SourceImage = imageData
            };

            // Assert
            Assert.Equal(prompt, request.Prompt);
            Assert.Equal(2048, request.Width);
            Assert.Equal(1080, request.Height);
            Assert.Equal("hd", request.Quality);
            Assert.Equal("artistic", request.Style);
            Assert.Equal(imageData, request.SourceImage);
        }

        [Fact]
        public void RenderingResult_WithSuccess_ShouldHaveCorrectProperties()
        {
            // Arrange
            var imageData = new byte[] { 0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A };

            // Act
            var result = new RenderingResult
            {
                Success = true,
                ImageData = imageData,
                ExecutionTimeMs = 1500,
                Seed = 12345
            };

            // Assert
            Assert.True(result.Success);
            Assert.Equal(imageData, result.ImageData);
            Assert.Equal(1500, result.ExecutionTimeMs);
            Assert.Equal(12345, result.Seed);
            Assert.Null(result.ErrorMessage);
        }

        [Fact]
        public void RenderingResult_WithFailure_ShouldHaveErrorInformation()
        {
            // Arrange & Act
            var result = new RenderingResult
            {
                Success = false,
                ErrorMessage = "API key is invalid",
                ExecutionTimeMs = 500
            };

            // Assert
            Assert.False(result.Success);
            Assert.Equal("API key is invalid", result.ErrorMessage);
            Assert.Equal(500, result.ExecutionTimeMs);
            Assert.Null(result.ImageData);
        }

        [Fact]
        public void BIMDataContext_WithValidData_ShouldStorePropertiesCorrectly()
        {
            // Arrange
            var materials = new[] { "Concrete", "Steel", "Glass" };
            var categories = new[] { "Walls", "Doors", "Windows" };
            var screenshot = new byte[] { 0x89, 0x50, 0x4E, 0x47 };

            // Act
            var context = new BIMDataContext
            {
                ViewCategory = "3D View",
                Materials = new System.Collections.Generic.List<string>(materials),
                ElementCategories = new System.Collections.Generic.List<string>(categories),
                Screenshot = screenshot,
                DepthMap = null
            };

            // Assert
            Assert.Equal("3D View", context.ViewCategory);
            Assert.Equal(materials.Length, context.Materials.Count);
            Assert.Contains("Concrete", context.Materials);
            Assert.Contains("Steel", context.Materials);
            Assert.Contains("Glass", context.Materials);
            Assert.Equal(categories.Length, context.ElementCategories.Count);
            Assert.Contains("Walls", context.ElementCategories);
            Assert.Equal(screenshot, context.Screenshot);
            Assert.Null(context.DepthMap);
        }

        [Theory]
        [InlineData("standard")]
        [InlineData("hd")]
        [InlineData("ultra")]
        public void RenderingRequest_QualityValues_ShouldAcceptValidValues(string quality)
        {
            // Arrange & Act
            var request = new RenderingRequest
            {
                Quality = quality
            };

            // Assert
            Assert.Equal(quality, request.Quality);
        }

        [Theory]
        [InlineData("realistic")]
        [InlineData("artistic")]
        [InlineData("conceptual")]
        public void RenderingRequest_StyleValues_ShouldAcceptValidValues(string style)
        {
            // Arrange & Act
            var request = new RenderingRequest
            {
                Style = style
            };

            // Assert
            Assert.Equal(style, request.Style);
        }

        [Fact]
        public void RenderingRequest_WithNegativeDimensions_ShouldStillWork()
        {
            // Arrange & Act
            var request = new RenderingRequest
            {
                Width = -1,
                Height = -1
            };

            // Assert - в реальном коде должна быть валидация, но для тестов проверяем что свойства устанавливаются
            Assert.Equal(-1, request.Width);
            Assert.Equal(-1, request.Height);
        }

        [Fact]
        public void RenderingResult_WithEmptyImageData_ShouldStillBeValid()
        {
            // Arrange & Act
            var result = new RenderingResult
            {
                Success = true,
                ImageData = new byte[0],
                ExecutionTimeMs = 100
            };

            // Assert
            Assert.True(result.Success);
            Assert.Empty(result.ImageData);
            Assert.Equal(100, result.ExecutionTimeMs);
        }
    }
}
