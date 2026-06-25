// ЛЕС — поллер почты: отдельное приложение (НЕ COM-надстройка) для классического Outlook (Win).
//
// Почему так, а не аддин/IMAP:
//  - Office.js-аддин на корпоративном Outlook не сайдлоадится (только COM);
//  - managed-COM-надстройка на современном Outlook не грузится (шимлесс депрекейтнут, 0x80070002);
//  - IMAP на Exchange Online отключён (Basic Auth off).
// Поллер цепляется к УЖЕ ЗАЛОГИНЕННОМУ Outlook (COM-автоматизация, late binding) — ни IMAP,
// ни OAuth, ни паролей. Запускается ЗАДАЧЕЙ ПЛАНИРОВЩИКА в сессии пользователя (где живёт
// Outlook), каждые N минут: сканит «Входящие», новые письма (позже чекпойнта) → POST /api/mail/push.
//
// Сборка (голый csc .NET Framework, без Office-PIA; winexe — без окна):
//   csc /target:winexe /out:LesMailPoller.exe /r:System.dll /r:System.Core.dll /r:Microsoft.CSharp.dll LesMailPoller.cs
// Планировщик и URL — см. setup_task.ps1 / README.

using System;
using System.IO;
using System.Net;
using System.Runtime.InteropServices;
using System.Text;

namespace LesMailPoller
{
    internal static class Program
    {
        private static string Home()
        {
            string d = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "LES");
            Directory.CreateDirectory(d);
            return d;
        }
        private static string LogPath()
        {
            string d = Path.Combine(Home(), "logs");
            Directory.CreateDirectory(d);
            return Path.Combine(d, "mail_poller.log");
        }
        private static string CheckpointPath() { return Path.Combine(Home(), "mail_poller_checkpoint.txt"); }

        private static string Url()
        {
            try
            {
                string f = Path.Combine(Home(), "mail_addin_url.txt");
                if (File.Exists(f)) { string u = File.ReadAllText(f).Trim(); if (u.Length > 0) return u; }
            }
            catch { }
            return "http://localhost:8050/api/mail/push";
        }

        private static void Log(string m)
        {
            try { File.AppendAllText(LogPath(), DateTime.Now.ToString("s") + "  " + m + Environment.NewLine); }
            catch { }
        }

        private static int Main()
        {
            dynamic app = null;
            try { app = Marshal.GetActiveObject("Outlook.Application"); }
            catch
            {
                try { app = Activator.CreateInstance(Type.GetTypeFromProgID("Outlook.Application")); }
                catch (Exception e) { Log("no Outlook in session: " + e.Message); return 2; }
            }

            // Чекпойнт по ReceivedTime; первый запуск — последние 30 мин (чтобы свежий тест попал, без бэкафилла всего ящика).
            DateTime since;
            try
            {
                string cp = CheckpointPath();
                long ticks;
                if (File.Exists(cp) && long.TryParse(File.ReadAllText(cp).Trim(), out ticks)) since = new DateTime(ticks);
                else since = DateTime.Now.AddMinutes(-30);
            }
            catch { since = DateTime.Now.AddMinutes(-30); }

            int pushed = 0, scanned = 0;
            try
            {
                dynamic ns = app.Session;
                dynamic inbox = ns.GetDefaultFolder(6); // olFolderInbox
                dynamic items = inbox.Items;
                try { items.Sort("[ReceivedTime]", true); } catch { } // по убыванию
                int count = 0; try { count = (int)items.Count; } catch { }
                int max = count < 50 ? count : 50;
                DateTime newest = since;
                for (int i = 1; i <= max; i++)
                {
                    dynamic m = null;
                    try { m = items[i]; } catch { continue; }
                    DateTime rt;
                    try { rt = (DateTime)m.ReceivedTime; } catch { continue; }
                    if (rt <= since) break; // отсортировано убыванием → дальше старее
                    scanned++;
                    if (Push(m)) { pushed++; if (rt > newest) newest = rt; }
                }
                if (newest > since)
                {
                    try { File.WriteAllText(CheckpointPath(), newest.Ticks.ToString()); } catch { }
                }
            }
            catch (Exception e) { Log("scan error: " + e.Message); return 3; }

            Log("run done: scanned=" + scanned + " pushed=" + pushed + " url=" + Url());
            return 0;
        }

        private static bool Push(dynamic m)
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
                req.Method = "POST"; req.ContentType = "application/json"; req.Timeout = 25000;
                byte[] data = Encoding.UTF8.GetBytes(json);
                req.ContentLength = data.Length;
                using (var s = req.GetRequestStream()) s.Write(data, 0, data.Length);
                using (var r = (HttpWebResponse)req.GetResponse()) Log("pushed [" + (int)r.StatusCode + "]: " + subj);
                return true;
            }
            catch (Exception ex) { Log("push error (" + subj + "): " + ex.Message); return false; }
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
