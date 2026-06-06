using System;
using System.Windows;
using Microsoft.Win32;

namespace MyVeras.UI.Windows
{
    public partial class ExportWindow : Window
    {
        private string _selectedPath;

        public ExportWindow()
        {
            InitializeComponent();
        }

        private void BrowseButton_Click(object sender, RoutedEventArgs e)
        {
            var saveFileDialog = new SaveFileDialog
            {
                Filter = "PNG Image|*.png|JPEG Image|*.jpg|All files|*.*",
                Title = "Export Generated Image",
                FileName = "MyVeras_Render.png"
            };

            if (saveFileDialog.ShowDialog() == true)
            {
                _selectedPath = saveFileDialog.FileName;
                PathTextBlock.Text = System.IO.Path.GetFileName(_selectedPath);
            }
        }

        private void ExportButton_Click(object sender, RoutedEventArgs e)
        {
            if (string.IsNullOrEmpty(_selectedPath))
            {
                MessageBox.Show("Please select export location first!", "Warning", MessageBoxButton.OK, MessageBoxImage.Warning);
                return;
            }

            try
            {
                // Заглушка для экспорта
                MessageBox.Show($"Image exported to:\n{_selectedPath}", "Export Complete", MessageBoxButton.OK, MessageBoxImage.Information);
                DialogResult = true;
                Close();
            }
            catch (Exception ex)
            {
                MessageBox.Show($"Error exporting image: {ex.Message}", "Error", MessageBoxButton.OK, MessageBoxImage.Error);
            }
        }
    }
}
