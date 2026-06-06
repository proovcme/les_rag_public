using System;
using System.Diagnostics;
using System.Runtime.InteropServices;
using System.Windows;
using System.Windows.Interop;
using MyVeras.Core;
using MyVeras.UI.ViewModels;

namespace MyVeras.UI
{
    /// <summary>
    /// Реализация сервиса управления окнами MyVeras
    /// </summary>
    public class MyVerasService : IMyVerasService
    {
        private static MyVerasWindow _instance;
        private static MainViewModel _viewModel;

        public void ShowMainWindow()
        {
            try
            {
                if (_instance == null)
                {
                    _instance = new MyVerasWindow();
                    _viewModel = _instance.DataContext as MainViewModel;
                    _instance.Show();
                }
                else
                {
                    _instance.Show();
                    _instance.WindowState = WindowState.Normal;
                    _instance.Activate();
                    
                    // Принудительно выводим на передний план
                    SetForegroundWindow(new WindowInteropHelper(_instance).Handle);
                }
            }
            catch (Exception ex)
            {
                MessageBox.Show($"Ошибка окна: {ex.Message}", "MyVeras Error", MessageBoxButton.OK, MessageBoxImage.Error);
            }
        }

        public void UpdateUIData(UIDataTransfer data)
        {
            try
            {
                if (_viewModel != null)
                {
                    Application.Current.Dispatcher.Invoke(() =>
                    {
                        _viewModel.UpdateUIData(data);
                    });
                }
            }
            catch (Exception ex)
            {
                Debug.WriteLine($"Error updating UI data: {ex.Message}");
            }
        }

        public UIDataTransfer GetUIData()
        {
            try
            {
                return _viewModel?.GetUIData() ?? new UIDataTransfer();
            }
            catch (Exception ex)
            {
                Debug.WriteLine($"Error getting UI data: {ex.Message}");
                return new UIDataTransfer();
            }
        }

        [DllImport("user32.dll")]
        private static extern IntPtr SetForegroundWindow(IntPtr hWnd);
    }
}
