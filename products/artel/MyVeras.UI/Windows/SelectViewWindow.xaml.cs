using System;
using System.Collections.Generic;
using System.Linq;
using System.Windows;
using MyVeras.Core;

namespace MyVeras.UI.Windows
{
    public partial class SelectViewWindow : Window
    {
        public string SelectedView { get; private set; }

        public SelectViewWindow(List<string> viewNames)
        {
            InitializeComponent();
            
            // Заполняем список видов
            ViewsListBox.ItemsSource = viewNames.Where(v => !v.Contains("Нет доступных") && !v.Contains("Ошибка загрузки"));
            
            if (ViewsListBox.Items.Count > 0)
            {
                ViewsListBox.SelectedIndex = 0;
            }
        }

        private void SelectButton_Click(object sender, RoutedEventArgs e)
        {
            SelectedView = ViewsListBox.SelectedItem as string;
            DialogResult = true;
            Close();
        }

        private void CancelButton_Click(object sender, RoutedEventArgs e)
        {
            DialogResult = false;
            Close();
        }
    }
}
