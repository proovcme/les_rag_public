// ЛЕС — сборщик почты: COM-надстройка для КЛАССИЧЕСКОГО Outlook (Windows).
//
// Зачем COM, а не Office.js/IMAP: на корпоративном Outlook веб-аддины не сайдлоадятся
// (только COM-надстройки), а IMAP на Exchange Online режется (Basic Auth off). COM-аддин
// едет ВНУТРИ уже залогиненного Outlook — ни IMAP, ни OAuth, ни паролей не нужно.
//
// Что делает: по таймеру сканит «Входящие», новые письма (позже чекпойнта) шлёт в локальный
// ЛЕС POST {LES}/api/mail/push (тема/отправитель/дата/тело; вложения — задел v2). Контракт —
// тот же, что у Office.js-аддина (clients/outlook_addin). Чекпойнт по ReceivedTime в
// %LOCALAPPDATA%\LES\mail_addin_checkpoint.txt — на первом запуске старое НЕ заливает.
//
// Late binding (dynamic) — чтобы НЕ зависеть от Office-PIA при компиляции: собирается голым
//   csc /target:library /r:System.dll /r:System.Core.dll /r:Microsoft.CSharp.dll Connect.cs
// Регистрация — per-user (HKCU), без админа: см. build_register.ps1.

using System;
using System.Collections.Generic;
using System.IO;
using System.Net;
using System.Reflection;
using System.Runtime.InteropServices;
using System.Text;
using System.Threading;

[assembly: AssemblyVersion("1.0.0.0")]
[assembly: AssemblyFileVersion("1.0.0.0")]
[assembly: ComVisible(false)]

namespace LesMailCollector
{
    // Стандартный COM-интерфейс надстроек Office (Add-in Designer).
    [ComImport, Guid("B65AD801-ABAF-11D0-BB8B-00A0C90F2744"),
     InterfaceType(ComInterfaceType.InterfaceIsIDispatch)]
    public interface IDTExtensibility2
    {
        void OnConnection([MarshalAs(UnmanagedType.IDispatch)] object Application,
                          int ConnectMode,
                          [MarshalAs(UnmanagedType.IDispatch)] object AddInInst,
                          ref Array custom);
        void OnDisconnection(int RemoveMode, ref Array custom);
        void OnAddInsUpdate(ref Array custom);
        void OnStartupComplete(ref Array custom);
        void OnBeginShutdown(ref Array custom);
    }

    [ComVisible(true)]
    [Guid("7E9A1C40-3D2B-4E55-9F12-8A6C0B3D5E71")]
    [ProgId("LES.MailCollector")]
    [ClassInterface(ClassInterfaceType.None)]
    public class Connect : IDTExtensibility2
    {
        private dynamic _app;
        private Timer _timer;
        private readonly object _lock = new object();
        private readonly HashSet<string> _seen = new HashSet<string>();
        private DateTime _since = DateTime.Now;

        private static string Home
        {
            get
            {
                string d = Path.Combine(
                    Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "LES");
                Directory.CreateDirectory(d);
                return d;
            }
        }
        private string CheckpointPath { get { return Path.Combine(Home, "mail_addin_checkpoint.txt"); } }
        private string LogPath { get { return Path.Combine(Home, "logs", "mail_addin.log"); } }

        private string Url()
        {
            try
            {
                string f = Path.Combine(Home, "mail_addin_url.txt");
                if (File.Exists(f)) { string u = File.ReadAllText(f).Trim(); if (u.Length > 0) return u; }
            }
            catch { }
            return "http://localhost:8050/api/mail/push";
        }

        private void Log(string m)
        {
            try
            {
                Directory.CreateDirectory(Path.GetDirectoryName(LogPath));
                File.AppendAllText(LogPath, DateTime.Now.ToString("s") + "  " + m + Environment.NewLine);
            }
            catch { }
        }

        public void OnConnection(object Application, int ConnectMode, object AddInInst, ref Array custom)
        {
            _app = Application;
            try
            {
                if (File.Exists(CheckpointPath))
                {
                    long ticks;
                    if (long.TryParse(File.ReadAllText(CheckpointPath).Trim(), out ticks)) _since = new DateTime(ticks);
                }
            }
            catch { }
            Log("OnConnection mode=" + ConnectMode + " since=" + _since.ToString("s") + " url=" + Url());
            _timer = new Timer(Poll, null, 8000, 60000); // первый скан через 8с, далее каждые 60с
        }

        public void OnDisconnection(int RemoveMode, ref Array custom)
        {
            try { if (_timer != null) _timer.Dispose(); } catch { }
            Log("OnDisconnection mode=" + RemoveMode);
        }
        public void OnAddInsUpdate(ref Array custom) { }
        public void OnStartupComplete(ref Array custom) { }
        public void OnBeginShutdown(ref Array custom) { }

        private void Poll(object state)
        {
            if (!Monitor.TryEnter(_lock)) return;
            try
            {
                dynamic ns = _app.Session;
                dynamic inbox = ns.GetDefaultFolder(6); // olFolderInbox = 6
                dynamic items = inbox.Items;
                try { items.Sort("[ReceivedTime]", true); } catch { } // по убыванию даты
                int count = 0; try { count = (int)items.Count; } catch { }
                int max = count < 30 ? count : 30; // не больше 30 свежих за тик
                DateTime newest = _since;
                for (int i = 1; i <= max; i++)
                {
                    dynamic m = null;
                    try { m = items[i]; } catch { continue; }
                    DateTime rt;
                    try { rt = (DateTime)m.ReceivedTime; } catch { continue; }
                    if (rt <= _since) break; // отсортировано убыванием → дальше только старее
                    string id = ""; try { id = (string)m.EntryID; } catch { }
                    if (id.Length > 0 && _seen.Contains(id)) continue;
                    if (Push(m)) { if (id.Length > 0) _seen.Add(id); if (rt > newest) newest = rt; }
                }
                if (newest > _since)
                {
                    _since = newest;
                    try { File.WriteAllText(CheckpointPath, _since.Ticks.ToString()); } catch { }
                }
            }
            catch (Exception ex) { Log("Poll error: " + ex.Message); }
            finally { Monitor.Exit(_lock); }
        }

        private bool Push(dynamic m)
        {
            string subj = S(delegate { return (string)m.Subject; });
            try
            {
                string sname = S(delegate { return (string)m.SenderName; });
                string saddr = S(delegate { return (string)m.SenderEmailAddress; });
                string from = (sname + " <" + saddr + ">").Trim();
                string date = S(delegate { return ((DateTime)m.ReceivedTime).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ss.fffZ"); });
                string body = S(delegate { return (string)m.Body; });
                string json = "{\"subject\":" + J(subj) + ",\"from\":" + J(from) +
                              ",\"date\":" + J(date) + ",\"body\":" + J(body) + ",\"attachments\":[]}";
                var req = (HttpWebRequest)WebRequest.Create(Url());
                req.Method = "POST"; req.ContentType = "application/json"; req.Timeout = 20000;
                byte[] data = Encoding.UTF8.GetBytes(json);
                req.ContentLength = data.Length;
                using (var s = req.GetRequestStream()) s.Write(data, 0, data.Length);
                using (var r = (HttpWebResponse)req.GetResponse()) Log("pushed [" + (int)r.StatusCode + "]: " + subj);
                return true;
            }
            catch (Exception ex) { Log("Push error (" + subj + "): " + ex.Message); return false; }
        }

        private static string S(Func<string> f) { try { string v = f(); return v ?? ""; } catch { return ""; } }

        private static string J(string s)
        {
            if (s == null) s = "";
            var sb = new StringBuilder("\"");
            foreach (char c in s)
            {
                if (c == '"' || c == '\\') sb.Append('\\').Append(c);
                else if (c == '\n') sb.Append("\\n");
                else if (c == '\r') sb.Append("\\r");
                else if (c == '\t') sb.Append("\\t");
                else if (c < 32) sb.Append("\\u").Append(((int)c).ToString("x4"));
                else sb.Append(c);
            }
            sb.Append('"');
            return sb.ToString();
        }
    }
}
