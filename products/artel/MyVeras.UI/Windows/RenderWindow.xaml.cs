using System;
using System.Threading.Tasks;
using System.Windows;
using MyVeras.Settings;

namespace MyVeras.UI.Windows
{
    public partial class RenderWindow : Window
    {
        private readonly object _document; // Используем object чтобы избежать зависимости
        private readonly AppSettings _settings;

        public RenderWindow(object document, AppSettings settings)
        {
            InitializeComponent();
            _document = document;
            _settings = settings;
        }

        private async void GenerateButton_Click(object sender, RoutedEventArgs e)
        {
            try
            {
                if (string.IsNullOrEmpty(PromptTextBox.Text))
                {
                    MessageBox.Show("Please enter a prompt!", "Warning", MessageBoxButton.OK, MessageBoxImage.Warning);
                    return;
                }

                GenerateButton.IsEnabled = false;
                GenerateButton.Content = "Generating...";

                // Имитация генерации (заглушка)
                await Task.Delay(3000);

                // Показываем заглушку изображения
                PlaceholderTextBlock.Visibility = Visibility.Collapsed;
                GeneratedImage.Visibility = Visibility.Visible;
                
                MessageBox.Show("Rendering generated successfully!", "Success", MessageBoxButton.OK, MessageBoxImage.Information);
            }
            catch (Exception ex)
            {
                MessageBox.Show($"Error generating rendering: {ex.Message}", "Error", MessageBoxButton.OK, MessageBoxImage.Error);
            }
            finally
            {
                GenerateButton.IsEnabled = true;
                GenerateButton.Content = "Generate";
            }
        }

        private void CancelButton_Click(object sender, RoutedEventArgs e)
        {
            DialogResult = false;
            Close();
        }
    }
}
