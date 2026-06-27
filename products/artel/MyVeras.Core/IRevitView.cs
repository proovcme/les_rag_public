namespace MyVeras.Core
{
    /// <summary>
    /// Интерфейс для Revit View - позволяет тестировать с Mock объектами
    /// </summary>
    public interface IRevitView
    {
        string Name { get; }
        bool IsTemplate { get; }
        bool IsValidObject { get; }
        string ViewType { get; }
    }

    /// <summary>
    /// Реализация для реальных Revit View
    /// </summary>
    public class RevitViewAdapter : IRevitView
    {
        private readonly object _view;

        public RevitViewAdapter(object view)
        {
            _view = view ?? throw new System.ArgumentNullException(nameof(view));
        }

        public string Name => _view.GetType().GetProperty("Name")?.GetValue(_view)?.ToString() ?? string.Empty;
        
        public bool IsTemplate => _view.GetType().GetProperty("IsTemplate")?.GetValue(_view) as bool? ?? false;
        
        public bool IsValidObject => _view.GetType().GetProperty("IsValidObject")?.GetValue(_view) as bool? ?? false;
        
        public string ViewType => _view.GetType().GetProperty("ViewType")?.GetValue(_view)?.ToString() ?? "Unknown";
    }
}
