using System;
using System.Collections.Generic;

namespace LES.Revit.JsonExport;

public sealed class CadBimGraph
{
    public string Id { get; set; } = string.Empty;

    public string Type { get; set; } = "RVTModel";

    public string Name { get; set; } = string.Empty;

    public string SourceFormat { get; set; } = "rvt";

    public string SourcePath { get; set; } = string.Empty;

    public string ExtractedAt { get; set; } = string.Empty;

    public Dictionary<string, object?> Properties { get; set; } = new();

    public List<CadBimElement> Elements { get; set; } = new();

    public List<CadBimRelation> Relations { get; set; } = new();
}

public sealed class CadBimElement
{
    public string Id { get; set; } = string.Empty;

    public string Type { get; set; } = string.Empty;

    public string Name { get; set; } = string.Empty;

    public string Category { get; set; } = string.Empty;

    public string Family { get; set; } = string.Empty;

    public string Level { get; set; } = string.Empty;

    public string Layer { get; set; } = string.Empty;

    public string Material { get; set; } = string.Empty;

    public Dictionary<string, object?> Properties { get; set; } = new();

    public CadBimGeometry? Geometry { get; set; }
}

public sealed class CadBimGeometry
{
    public string Type { get; set; } = "mesh";

    public string Units { get; set; } = "revit_internal_ft";

    public double[] Vertices { get; set; } = Array.Empty<double>();

    public int[] Faces { get; set; } = Array.Empty<int>();

    public Dictionary<string, object?> Material { get; set; } = new();

    public Dictionary<string, object?> Stats { get; set; } = new();

    public bool Truncated { get; set; }
}

public sealed class CadBimRelation
{
    public string SourceId { get; set; } = string.Empty;

    public string TargetId { get; set; } = string.Empty;

    public string RelationType { get; set; } = "contains";
}
