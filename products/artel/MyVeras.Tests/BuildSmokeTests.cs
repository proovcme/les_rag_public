using System;
using System.IO;
using System.Linq;
using FluentAssertions;
using Xunit;

namespace MyVeras.Tests
{
    public class BuildSmokeTests
    {
        private readonly string _solutionDir;
        private readonly string _outputPath;

        public BuildSmokeTests()
        {
            // Определяем пути к решению и выходной папке
            _solutionDir = Path.GetFullPath(Path.Combine(AppDomain.CurrentDomain.BaseDirectory, "..", "..", ".."));
            _outputPath = Path.Combine(_solutionDir, "MyVeras.RevitAPI", "bin", "Debug", "net8.0-windows");
        }

        [Fact]
        public void BuildOutput_ShouldContainAllRequiredDlls()
        {
            // Arrange - проверяем что выходная папка существует
            Directory.Exists(_outputPath).Should().BeTrue($"Output directory should exist: {_outputPath}");

            // Act - получаем все DLL файлы
            var dllFiles = Directory.GetFiles(_outputPath, "*.dll")
                .Select(Path.GetFileName)
                .ToList();

            // Assert - проверяем наличие всех необходимых DLL
            var requiredDlls = new[]
            {
                "MyVeras.RevitAPI.dll",
                "MyVeras.UI.dll", 
                "MyVeras.Core.dll",
                "MyVeras.Models.dll",
                "MyVeras.Settings.dll",
                "MyVeras.Engines.dll",
                "Newtonsoft.Json.dll"
            };

            foreach (var requiredDll in requiredDlls)
            {
                dllFiles.Should().Contain(requiredDll, $"Required DLL should be present: {requiredDll}");
            }

            // Дополнительная проверка - общее количество DLL должно быть разумным
            dllFiles.Count.Should().BeGreaterThan(7, "Should have at least the required DLLs plus dependencies");
        }

        [Fact]
        public void BuildOutput_ShouldContainConfigFiles()
        {
            // Arrange
            Directory.Exists(_outputPath).Should().BeTrue($"Output directory should exist: {_outputPath}");

            // Act
            var configFiles = Directory.GetFiles(_outputPath, "*.config")
                .Select(Path.GetFileName)
                .ToList();

            // Assert
            configFiles.Should().Contain("MyVeras.RevitAPI.dll.config", "Should contain RevitAPI config file");
        }

        [Fact]
        public void BuildOutput_ShouldContainPdbFiles()
        {
            // Arrange
            Directory.Exists(_outputPath).Should().BeTrue($"Output directory should exist: {_outputPath}");

            // Act
            var pdbFiles = Directory.GetFiles(_outputPath, "*.pdb")
                .Select(Path.GetFileName)
                .ToList();

            // Assert - проверяем наличие PDB для основных DLL
            var requiredPdbs = new[]
            {
                "MyVeras.RevitAPI.pdb",
                "MyVeras.UI.pdb",
                "MyVeras.Core.pdb"
            };

            foreach (var requiredPdb in requiredPdbs)
            {
                pdbFiles.Should().Contain(requiredPdb, $"Should contain PDB file for debugging: {requiredPdb}");
            }
        }

        [Fact]
        public void BuildOutput_ShouldHaveValidFileSizes()
        {
            // Arrange
            Directory.Exists(_outputPath).Should().BeTrue($"Output directory should exist: {_outputPath}");

            // Act & Assert - проверяем что основные DLL имеют разумный размер
            var coreDllPath = Path.Combine(_outputPath, "MyVeras.Core.dll");
            var uiDllPath = Path.Combine(_outputPath, "MyVeras.UI.dll");
            var revitApiDllPath = Path.Combine(_outputPath, "MyVeras.RevitAPI.dll");

            if (File.Exists(coreDllPath))
            {
                var coreSize = new FileInfo(coreDllPath).Length;
                coreSize.Should().BeGreaterThan(5000, "Core DLL should be substantial (at least 5KB)");
            }

            if (File.Exists(uiDllPath))
            {
                var uiSize = new FileInfo(uiDllPath).Length;
                uiSize.Should().BeGreaterThan(10000, "UI DLL should be substantial (at least 10KB)");
            }

            if (File.Exists(revitApiDllPath))
            {
                var revitSize = new FileInfo(revitApiDllPath).Length;
                revitSize.Should().BeGreaterThan(15000, "RevitAPI DLL should be substantial (at least 15KB)");
            }
        }

        [Fact]
        public void BuildOutput_ShouldNotHaveDuplicateDlls()
        {
            // Arrange
            Directory.Exists(_outputPath).Should().BeTrue($"Output directory should exist: {_outputPath}");

            // Act
            var dllFiles = Directory.GetFiles(_outputPath, "*.dll")
                .Select(Path.GetFileName)
                .ToList();

            // Assert - проверяем отсутствие дубликатов
            var uniqueDlls = dllFiles.Distinct().ToList();
            dllFiles.Count.Should().Be(uniqueDlls.Count, "Should not have duplicate DLL files");
        }

        [Fact]
        public void SolutionDirectory_ShouldExist()
        {
            // Act & Assert
            Directory.Exists(_solutionDir).Should().BeTrue($"Solution directory should exist: {_solutionDir}");
            
            // Проверяем наличие ключевых файлов решения
            var slnFile = Directory.GetFiles(_solutionDir, "*.sln").FirstOrDefault();
            slnFile.Should().NotBeNull("Should find .sln file in solution directory");
        }

        [Fact]
        public void ProjectDirectories_ShouldExist()
        {
            // Arrange
            var requiredProjects = new[]
            {
                "MyVeras.RevitAPI",
                "MyVeras.UI", 
                "MyVeras.Core",
                "MyVeras.Models",
                "MyVeras.Settings",
                "MyVeras.Engines"
            };

            // Act & Assert
            foreach (var project in requiredProjects)
            {
                var projectPath = Path.Combine(_solutionDir, project);
                Directory.Exists(projectPath).Should().BeTrue($"Project directory should exist: {projectPath}");
                
                var csprojFile = Path.Combine(projectPath, $"{project}.csproj");
                File.Exists(csprojFile).Should().BeTrue($"Project file should exist: {csprojFile}");
            }
        }
    }
}
