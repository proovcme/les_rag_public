using System;
using System.Globalization;
using System.Windows;
using System.Windows.Data;

namespace MyVeras.UI.Converters
{
    /// <summary>
    /// Конвертер Boolean в Visibility с поддержкой инверсии
    /// </summary>
    public class BooleanToVisibilityConverter : IValueConverter
    {
        public object Convert(object value, Type targetType, object parameter, CultureInfo culture)
        {
            if (value is bool boolValue)
            {
                // Если параметр "Invert", инвертируем значение
                bool invert = parameter?.ToString() == "Invert";
                bool result = invert ? !boolValue : boolValue;
                
                return result ? Visibility.Visible : Visibility.Collapsed;
            }
            
            return Visibility.Collapsed;
        }

        public object ConvertBack(object value, Type targetType, object parameter, CultureInfo culture)
        {
            if (value is Visibility visibility)
            {
                bool invert = parameter?.ToString() == "Invert";
                bool result = visibility == Visibility.Visible;
                return invert ? !result : result;
            }
            
            return false;
        }
    }
}
