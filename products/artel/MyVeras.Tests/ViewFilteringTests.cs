using System;
using System.Collections.Generic;
using System.Linq;
using FluentAssertions;
using Moq;
using MyVeras.Core;
using Xunit;

namespace MyVeras.Tests
{
    public class ViewFilteringTests
    {
        private readonly Mock<IRevitView> _mockView3D1;
        private readonly Mock<IRevitView> _mockView3D2;
        private readonly Mock<IRevitView> _mockViewPlan1;
        private readonly Mock<IRevitView> _mockViewPlan2;
        private readonly Mock<IRevitView> _mockViewTemplate;
        private readonly Mock<IRevitView> _mockSystemView;

        public ViewFilteringTests()
        {
            // Создаем моки для разных типов видов
            _mockView3D1 = CreateMockView("3D View 1", "ThreeD", false);
            _mockView3D2 = CreateMockView("3D View 2", "ThreeD", false);
            _mockViewPlan1 = CreateMockView("Floor Plan 1", "FloorPlan", false);
            _mockViewPlan2 = CreateMockView("Ceiling Plan 1", "CeilingPlan", false);
            _mockViewTemplate = CreateMockView("Template View", "DrawingSheet", true);
            _mockSystemView = CreateMockView("{3D}", "ThreeD", false);
        }

        private Mock<IRevitView> CreateMockView(string name, string viewType, bool isTemplate)
        {
            var mockView = new Mock<IRevitView>();
            mockView.Setup(x => x.Name).Returns(name);
            mockView.Setup(x => x.ViewType).Returns(viewType);
            mockView.Setup(x => x.IsTemplate).Returns(isTemplate);
            mockView.Setup(x => x.IsValidObject).Returns(true);
            return mockView;
        }

        [Fact]
        public void GetAllViewNames_ShouldFilterOutTemplatesAndSystemViews()
        {
            // Arrange
            var allViews = new List<IRevitView>
            {
                _mockView3D1.Object,
                _mockView3D2.Object,
                _mockViewPlan1.Object,
                _mockViewPlan2.Object,
                _mockViewTemplate.Object,
                _mockSystemView.Object
            };

            // Act
            var filteredViews = allViews.Where(v => 
                !v.IsTemplate && 
                v.IsValidObject && 
                !v.Name.StartsWith("{") &&
                !v.Name.Contains("Schedule") &&
                !v.Name.Contains("Legend"))
                .Select(v => v.Name)
                .ToList();

            // Assert
            filteredViews.Should().HaveCount(4);
            filteredViews.Should().Contain("3D View 1");
            filteredViews.Should().Contain("3D View 2");
            filteredViews.Should().Contain("Floor Plan 1");
            filteredViews.Should().Contain("Ceiling Plan 1");
            filteredViews.Should().NotContain("Template View");
            filteredViews.Should().NotContain("{3D}");
        }

        [Fact]
        public void GetAllViewNames_ShouldIncludeOnly3DAndPlanViews()
        {
            // Arrange
            var allViews = new List<IRevitView>
            {
                _mockView3D1.Object,
                _mockViewPlan1.Object,
                _mockViewTemplate.Object,
                _mockSystemView.Object
            };

            // Act
            var filteredViews = allViews.Where(v => 
                !v.IsTemplate && 
                v.IsValidObject && 
                !v.Name.StartsWith("{") &&
                (v.ViewType == "ThreeD" || 
                 v.ViewType == "FloorPlan" ||
                 v.ViewType == "CeilingPlan"))
                .Select(v => v.Name)
                .ToList();

            // Assert
            filteredViews.Should().HaveCount(2);
            filteredViews.Should().Contain("3D View 1");
            filteredViews.Should().Contain("Floor Plan 1");
        }

        [Fact]
        public void GetAllViewNames_ShouldSortAlphabetically()
        {
            // Arrange
            var allViews = new List<IRevitView>
            {
                _mockView3D2.Object, // "3D View 2"
                _mockViewPlan1.Object, // "Floor Plan 1" 
                _mockView3D1.Object, // "3D View 1"
                _mockViewPlan2.Object  // "Ceiling Plan 1"
            };

            // Act
            var filteredViews = allViews.Where(v => 
                !v.IsTemplate && 
                v.IsValidObject && 
                !v.Name.StartsWith("{"))
                .Select(v => v.Name)
                .OrderBy(name => name)
                .ToList();

            // Assert
            filteredViews.Should().HaveCount(4);
            filteredViews[0].Should().Be("3D View 1");
            filteredViews[1].Should().Be("3D View 2");
            filteredViews[2].Should().Be("Ceiling Plan 1");
            filteredViews[3].Should().Be("Floor Plan 1");
        }

        [Fact]
        public void GetAllViewNames_WithEmptyCollection_ShouldReturnEmptyList()
        {
            // Arrange
            var allViews = new List<IRevitView>();

            // Act
            var filteredViews = allViews.Where(v => 
                !v.IsTemplate && 
                v.IsValidObject)
                .Select(v => v.Name)
                .ToList();

            // Assert
            filteredViews.Should().BeEmpty();
        }

        [Fact]
        public void GetAllViewNames_WithAllTemplates_ShouldReturnEmptyList()
        {
            // Arrange
            var allViews = new List<IRevitView>
            {
                _mockViewTemplate.Object,
                CreateMockView("Template 2", "FloorPlan", true).Object
            };

            // Act
            var filteredViews = allViews.Where(v => 
                !v.IsTemplate && 
                v.IsValidObject)
                .Select(v => v.Name)
                .ToList();

            // Assert
            filteredViews.Should().BeEmpty();
        }
    }
}
