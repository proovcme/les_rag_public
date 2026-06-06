using System;
using System.Collections.Generic;
using System.Linq;
using Autodesk.Revit.Attributes;
using Autodesk.Revit.DB;
using Autodesk.Revit.UI;

namespace MyVeras.RevitAPI
{
    /// <summary>
    /// External Event Handler для безопасного доступа к Revit API из UI потока
    /// </summary>
    [Regeneration(RegenerationOption.Manual)]
    [Transaction(TransactionMode.Manual)]
    public class RevitExternalEventHandler : IExternalEventHandler
    {
        private List<string> _view3DNames = new List<string>();
        private List<ElementId> _view3DIds = new List<ElementId>();

        public string GetName()
        {
            return "MyVeras External Event Handler";
        }

        public void Execute(UIApplication uiApp)
        {
            try
            {
                // Получаем активный документ
                var uidoc = uiApp.ActiveUIDocument;
                var doc = uidoc?.Document;

                if (doc == null)
                {
                    System.Diagnostics.Debug.WriteLine("Нет активного документа Revit");
                    return;
                }

                // Собираем все 3D виды
                var collector = new FilteredElementCollector(doc);
                var view3Ds = collector.OfClass(typeof(View3D)).Cast<View3D>().ToList();

                _view3DNames.Clear();
                _view3DIds.Clear();

                foreach (var view3D in view3Ds)
                {
                    _view3DNames.Add(view3D.Name);
                    _view3DIds.Add(view3D.Id);
                }

                // Логируем для отладки
                System.Diagnostics.Debug.WriteLine($"Found {_view3DNames.Count} 3D views");
                foreach (var name in _view3DNames)
                {
                    System.Diagnostics.Debug.WriteLine($"3D View: {name}");
                }
            }
            catch (Exception ex)
            {
                System.Diagnostics.Debug.WriteLine($"Ошибка получения 3D видов: {ex.Message}");
                System.Diagnostics.Debug.WriteLine($"Error in RevitExternalEventHandler: {ex}");
            }
        }

        /// <summary>
        /// Получает список имен 3D видов
        /// </summary>
        public List<string> GetView3DNames()
        {
            return new List<string>(_view3DNames);
        }

        /// <summary>
        /// Получает список ID 3D видов
        /// </summary>
        public List<ElementId> GetView3DIds()
        {
            return new List<ElementId>(_view3DIds);
        }
    }
}
