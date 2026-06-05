using System;
using System.Collections;
using System.Collections.Generic;
using System.Globalization;
using System.Linq;
using System.Text;

namespace LES.Navisworks.JsonExport;

internal static class LesJsonWriter
{
    public static string Serialize(CadBimGraph graph)
    {
        var writer = new Writer();
        WriteGraph(writer, graph);
        return writer.ToString();
    }

    public static string SerializeImportBody(CadBimGraph graph, string sourceType, int maxObjects)
    {
        var writer = new Writer();
        writer.Object(() =>
        {
            writer.Property("source_type", sourceType);
            writer.PropertyName("payload");
            WriteGraph(writer, graph);
            writer.Property("max_objects", maxObjects);
        });
        return writer.ToString();
    }

    public static string Serialize(LesUploadSettings settings)
    {
        var writer = new Writer();
        writer.Object(() =>
        {
            writer.Property("les_urls", settings.LesUrls);
            writer.Property("custom_urls", settings.CustomUrls);
            writer.Property("local_output_dir", settings.LocalOutputDir);
            writer.Property("api_key", settings.ApiKey);
            writer.Property("timeout_sec", settings.TimeoutSec);
        });
        return writer.ToString();
    }

    public static LesUploadSettings DeserializeSettings(string json)
    {
        var settings = new LesUploadSettings
        {
            LesUrls = ExtractStringArray(json, "les_urls"),
            CustomUrls = ExtractStringArray(json, "custom_urls"),
            LocalOutputDir = ExtractString(json, "local_output_dir") ?? string.Empty,
            ApiKey = ExtractString(json, "api_key") ?? string.Empty,
            TimeoutSec = ExtractInt(json, "timeout_sec") ?? 60,
        };
        if (settings.LesUrls.Count == 0)
        {
            settings.LesUrls = LesUploadSettings.DefaultUrls();
        }

        return settings;
    }

    private static void WriteGraph(Writer writer, CadBimGraph graph)
    {
        writer.Object(() =>
        {
            writer.Property("id", graph.Id);
            writer.Property("type", graph.Type);
            writer.Property("name", graph.Name);
            writer.Property("source_format", graph.SourceFormat);
            writer.Property("source_path", graph.SourcePath);
            writer.Property("extracted_at", graph.ExtractedAt);
            writer.Property("properties", graph.Properties);
            writer.PropertyName("elements");
            writer.Array(graph.Elements, element => WriteElement(writer, element));
            writer.PropertyName("relations");
            writer.Array(graph.Relations, relation => WriteRelation(writer, relation));
        });
    }

    private static void WriteElement(Writer writer, CadBimElement element)
    {
        writer.Object(() =>
        {
            writer.Property("id", element.Id);
            writer.Property("type", element.Type);
            writer.Property("name", element.Name);
            writer.Property("category", element.Category);
            writer.Property("family", element.Family);
            writer.Property("level", element.Level);
            writer.Property("layer", element.Layer);
            writer.Property("material", element.Material);
            writer.Property("properties", element.Properties);
            if (element.Geometry != null)
            {
                writer.PropertyName("geometry");
                WriteGeometry(writer, element.Geometry);
            }
        });
    }

    private static void WriteGeometry(Writer writer, CadBimGeometry geometry)
    {
        writer.Object(() =>
        {
            writer.Property("type", geometry.Type);
            writer.Property("units", geometry.Units);
            writer.Property("vertices", geometry.Vertices);
            writer.Property("faces", geometry.Faces);
            writer.Property("material", geometry.Material);
            writer.Property("stats", geometry.Stats);
            writer.Property("truncated", geometry.Truncated);
        });
    }

    private static void WriteRelation(Writer writer, CadBimRelation relation)
    {
        writer.Object(() =>
        {
            writer.Property("source_id", relation.SourceId);
            writer.Property("target_id", relation.TargetId);
            writer.Property("relation_type", relation.RelationType);
        });
    }

    private static string? ExtractString(string json, string name)
    {
        var marker = "\"" + name + "\"";
        var pos = json.IndexOf(marker, StringComparison.Ordinal);
        if (pos < 0) return null;
        pos = json.IndexOf(':', pos);
        if (pos < 0) return null;
        pos = SkipWhitespace(json, pos + 1);
        return pos < json.Length && json[pos] == '"' ? ReadString(json, pos, out _) : null;
    }

    private static int? ExtractInt(string json, string name)
    {
        var marker = "\"" + name + "\"";
        var pos = json.IndexOf(marker, StringComparison.Ordinal);
        if (pos < 0) return null;
        pos = json.IndexOf(':', pos);
        if (pos < 0) return null;
        pos = SkipWhitespace(json, pos + 1);
        var end = pos;
        while (end < json.Length && char.IsDigit(json[end])) end++;
        return int.TryParse(json.Substring(pos, end - pos), NumberStyles.Integer, CultureInfo.InvariantCulture, out var value)
            ? value
            : null;
    }

    private static List<string> ExtractStringArray(string json, string name)
    {
        var values = new List<string>();
        var marker = "\"" + name + "\"";
        var pos = json.IndexOf(marker, StringComparison.Ordinal);
        if (pos < 0) return values;
        pos = json.IndexOf('[', pos);
        if (pos < 0) return values;
        pos++;
        while (pos < json.Length)
        {
            pos = SkipWhitespace(json, pos);
            if (pos >= json.Length || json[pos] == ']') break;
            if (json[pos] == '"') values.Add(ReadString(json, pos, out pos));
            else pos++;
            pos = SkipWhitespace(json, pos);
            if (pos < json.Length && json[pos] == ',') pos++;
        }

        return values;
    }

    private static int SkipWhitespace(string text, int pos)
    {
        while (pos < text.Length && char.IsWhiteSpace(text[pos])) pos++;
        return pos;
    }

    private static string ReadString(string text, int startQuote, out int next)
    {
        var value = new StringBuilder();
        for (var i = startQuote + 1; i < text.Length; i++)
        {
            var ch = text[i];
            if (ch == '"')
            {
                next = i + 1;
                return value.ToString();
            }

            if (ch == '\\' && i + 1 < text.Length)
            {
                i++;
                value.Append(text[i] switch
                {
                    '"' => '"',
                    '\\' => '\\',
                    '/' => '/',
                    'b' => '\b',
                    'f' => '\f',
                    'n' => '\n',
                    'r' => '\r',
                    't' => '\t',
                    _ => text[i],
                });
                continue;
            }

            value.Append(ch);
        }

        next = text.Length;
        return value.ToString();
    }

    private sealed class Writer
    {
        private readonly StringBuilder _builder = new();
        private readonly Stack<bool> _first = new();
        private int _indent;

        public override string ToString() => _builder.ToString();

        public void Object(Action body)
        {
            _builder.Append('{');
            _first.Push(true);
            _indent++;
            body();
            _indent--;
            NewLine();
            _builder.Append('}');
            _first.Pop();
        }

        public void Array<T>(IEnumerable<T> values, Action<T> writeItem)
        {
            _builder.Append('[');
            _first.Push(true);
            _indent++;
            foreach (var value in values)
            {
                BeforeValue();
                writeItem(value);
            }

            _indent--;
            NewLine();
            _builder.Append(']');
            _first.Pop();
        }

        public void Property(string name, object? value)
        {
            PropertyName(name);
            Value(value);
        }

        public void PropertyName(string name)
        {
            BeforeValue();
            String(name);
            _builder.Append(": ");
        }

        private void Value(object? value)
        {
            switch (value)
            {
                case null:
                    _builder.Append("null");
                    break;
                case string text:
                    String(text);
                    break;
                case bool boolean:
                    _builder.Append(boolean ? "true" : "false");
                    break;
                case int or long or short or byte or double or float or decimal:
                    _builder.Append(Convert.ToString(value, CultureInfo.InvariantCulture));
                    break;
                case IDictionary<string, object?> dictionary:
                    Object(() =>
                    {
                        foreach (var pair in dictionary.OrderBy(item => item.Key, StringComparer.Ordinal))
                        {
                            Property(pair.Key, pair.Value);
                        }
                    });
                    break;
                case IEnumerable enumerable:
                    _builder.Append('[');
                    _first.Push(true);
                    _indent++;
                    foreach (var item in enumerable)
                    {
                        BeforeValue();
                        Value(item);
                    }

                    _indent--;
                    NewLine();
                    _builder.Append(']');
                    _first.Pop();
                    break;
                default:
                    String(value.ToString() ?? string.Empty);
                    break;
            }
        }

        private void BeforeValue()
        {
            var isFirst = _first.Pop();
            if (!isFirst) _builder.Append(',');
            _first.Push(false);
            NewLine();
        }

        private void NewLine()
        {
            _builder.AppendLine();
            _builder.Append(new string(' ', _indent * 2));
        }

        private void String(string value)
        {
            _builder.Append('"');
            foreach (var ch in value)
            {
                switch (ch)
                {
                    case '"':
                        _builder.Append("\\\"");
                        break;
                    case '\\':
                        _builder.Append("\\\\");
                        break;
                    case '\b':
                        _builder.Append("\\b");
                        break;
                    case '\f':
                        _builder.Append("\\f");
                        break;
                    case '\n':
                        _builder.Append("\\n");
                        break;
                    case '\r':
                        _builder.Append("\\r");
                        break;
                    case '\t':
                        _builder.Append("\\t");
                        break;
                    default:
                        if (char.IsControl(ch))
                        {
                            _builder.Append("\\u");
                            _builder.Append(((int)ch).ToString("x4", CultureInfo.InvariantCulture));
                        }
                        else
                        {
                            _builder.Append(ch);
                        }

                        break;
                }
            }

            _builder.Append('"');
        }
    }
}
