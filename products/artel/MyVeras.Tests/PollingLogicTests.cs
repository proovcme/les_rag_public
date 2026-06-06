using System;
using System.Collections.Generic;
using System.Threading.Tasks;
using FluentAssertions;
using MyVeras.Core;
using Xunit;

namespace MyVeras.Tests
{
    public class PollingLogicTests
    {
        [Fact]
        public void GenerationStatus_ShouldCorrectlyIdentifyCompletedStatus()
        {
            // Arrange
            var status = new GenerationStatus
            {
                Status = "success",
                ImageUrl = "https://example.com/image.png",
                Error = null
            };

            // Act & Assert
            status.IsCompleted.Should().BeTrue();
            status.IsFailed.Should().BeFalse();
            status.IsInProgress.Should().BeFalse();
        }

        [Fact]
        public void GenerationStatus_ShouldCorrectlyIdentifyFailedStatus()
        {
            // Arrange
            var status = new GenerationStatus
            {
                Status = "failed",
                ImageUrl = null,
                Error = "API error"
            };

            // Act & Assert
            status.IsCompleted.Should().BeFalse();
            status.IsFailed.Should().BeTrue();
            status.IsInProgress.Should().BeFalse();
        }

        [Fact]
        public void GenerationStatus_ShouldCorrectlyIdentifyInProgressStatus()
        {
            // Arrange
            var status = new GenerationStatus
            {
                Status = "processing",
                ImageUrl = null,
                Error = null
            };

            // Act & Assert
            status.IsCompleted.Should().BeFalse();
            status.IsFailed.Should().BeFalse();
            status.IsInProgress.Should().BeTrue();
        }

        [Fact]
        public void GenerationStatus_ShouldCorrectlyIdentifyStartingStatus()
        {
            // Arrange
            var status = new GenerationStatus
            {
                Status = "starting",
                ImageUrl = null,
                Error = null
            };

            // Act & Assert
            status.IsCompleted.Should().BeFalse();
            status.IsFailed.Should().BeFalse();
            status.IsInProgress.Should().BeTrue();
        }

        [Fact]
        public void GenerationStatus_ShouldHandleUnknownStatus()
        {
            // Arrange
            var status = new GenerationStatus
            {
                Status = "unknown",
                ImageUrl = null,
                Error = null
            };

            // Act & Assert
            status.IsCompleted.Should().BeFalse();
            status.IsFailed.Should().BeFalse();
            status.IsInProgress.Should().BeFalse();
        }

        [Fact]
        public async Task SimpleDelayTask_ShouldCompleteSuccessfully()
        {
            // Arrange
            var delayMs = 100;

            // Act
            var startTime = DateTime.UtcNow;
            await Task.Delay(delayMs);
            var endTime = DateTime.UtcNow;

            // Assert
            var elapsed = endTime - startTime;
            elapsed.TotalMilliseconds.Should().BeGreaterOrEqualTo(delayMs - 10); // Allow small tolerance
        }

        [Fact]
        public async Task TaskWhenAll_ShouldCompleteAllTasks()
        {
            // Arrange
            var tasks = new List<Task>
            {
                Task.Delay(50),
                Task.Delay(100),
                Task.Delay(25)
            };

            // Act
            var startTime = DateTime.UtcNow;
            await Task.WhenAll(tasks);
            var endTime = DateTime.UtcNow;

            // Assert
            var elapsed = endTime - startTime;
            elapsed.TotalMilliseconds.Should().BeGreaterOrEqualTo(100 - 10); // Should wait for longest task
        }

        [Fact]
        public void GenApiResponse_ShouldHandleNullValues()
        {
            // Arrange
            var response = new GenApiResponse
            {
                request_id = null,
                status = "success",
                output_image_url = null,
                error = null
            };

            // Act & Assert
            response.request_id.Should().BeNull();
            response.status.Should().Be("success");
            response.output_image_url.Should().BeNull();
            response.error.Should().BeNull();
        }

        [Fact]
        public void GenApiResponse_ShouldHandleValidValues()
        {
            // Arrange
            var response = new GenApiResponse
            {
                request_id = "test-123",
                status = "processing",
                output_image_url = "https://example.com/image.png",
                error = null
            };

            // Act & Assert
            response.request_id.Should().Be("test-123");
            response.status.Should().Be("processing");
            response.output_image_url.Should().Be("https://example.com/image.png");
            response.error.Should().BeNull();
        }
    }
}
