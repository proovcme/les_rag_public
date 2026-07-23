// Е.Ж.И.К. — read-only Windows sidecar for classic Outlook.
// Saves complete Unicode .msg snapshots and registers them in local LES.
// No MailItem properties, folders or flags are ever modified.

using System;
using System.Collections.Generic;
using System.IO;
using System.Net;
using System.Runtime.InteropServices;
using System.Security.Cryptography;
using System.Text;

namespace LesMailPoller
{
    internal static class Program
    {
        private const int BatchLimit = 200;
        private const string InternetMessageIdSchema =
            "http://schemas.microsoft.com/mapi/proptag/0x1035001F";

        private sealed class Cursor
        {
            public long NewestTicks;
            public long OldestTicks;
            public HashSet<string> NewestEntryIds = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
            public HashSet<string> OldestEntryIds = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        }

        private static string StateRoot()
        {
            string configured = Environment.GetEnvironmentVariable("LES_MAIL_STATE_ROOT");
            string root = String.IsNullOrWhiteSpace(configured)
                ? Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "LES", "mail")
                : configured;
            Directory.CreateDirectory(root);
            return root;
        }

        private static string LogPath()
        {
            string directory = Path.Combine(StateRoot(), "logs");
            Directory.CreateDirectory(directory);
            return Path.Combine(directory, "outlook_collector.log");
        }

        private static string CollectorUrl()
        {
            string path = Path.Combine(StateRoot(), "collector_url.txt");
            try
            {
                if (File.Exists(path))
                {
                    string value = File.ReadAllText(path).Trim();
                    if (value.Length > 0) return value;
                }
            }
            catch { }
            return "http://127.0.0.1:8050/api/mail/collector/import";
        }

        private static void Log(string message)
        {
            try
            {
                File.AppendAllText(LogPath(), DateTime.Now.ToString("s") + "  " + message + Environment.NewLine);
            }
            catch { }
        }

        private static int Main(string[] args)
        {
            dynamic app;
            try
            {
                if (args.Length > 0 && args[0] == "--open")
                {
                    app = GetOutlook(true);
                    return OpenOriginal(app, args);
                }
                app = GetOutlook(false);
                if (args.Length > 0 && args[0] == "--probe")
                {
                    dynamic session = app.Session;
                    Log("probe stores=" + SafeInt(delegate { return (int)session.Stores.Count; }));
                    return 0;
                }
            }
            catch (Exception error)
            {
                Log("Outlook unavailable in interactive session: " + error.Message);
                return 2;
            }

            int registered = 0;
            int scanned = 0;
            try
            {
                dynamic session = app.Session;
                int storeCount = SafeInt(delegate { return (int)session.Stores.Count; });
                for (int storeIndex = 1; storeIndex <= storeCount && registered < BatchLimit; storeIndex++)
                {
                    dynamic store = session.Stores[storeIndex];
                    string storeId = Safe(delegate { return (string)store.StoreID; });
                    string storeLabel = Safe(delegate { return (string)store.DisplayName; });
                    var excluded = ExcludedFolderIds(store);
                    dynamic root = store.GetRootFolder();
                    ScanFolder(root, storeId, storeLabel, excluded, ref scanned, ref registered);
                }
            }
            catch (Exception error)
            {
                Log("scan failed: " + error.Message);
                return 3;
            }
            Log("run complete scanned=" + scanned + " registered=" + registered);
            return 0;
        }

        private static dynamic GetOutlook(bool allowStart)
        {
            try { return Marshal.GetActiveObject("Outlook.Application"); }
            catch
            {
                if (!allowStart) throw;
                Type outlook = Type.GetTypeFromProgID("Outlook.Application");
                if (outlook == null) throw new InvalidOperationException("classic Outlook is not installed");
                return Activator.CreateInstance(outlook);
            }
        }

        private static int OpenOriginal(dynamic app, string[] args)
        {
            if (args.Length != 3) return 64;
            string storeId = DecodeArgument(args[1]);
            string entryId = DecodeArgument(args[2]);
            dynamic item = app.Session.GetItemFromID(entryId, storeId);
            item.Display();
            return 0;
        }

        private static string DecodeArgument(string value)
        {
            string padded = value.Replace('-', '+').Replace('_', '/');
            while (padded.Length % 4 != 0) padded += "=";
            return Encoding.UTF8.GetString(Convert.FromBase64String(padded));
        }

        private static HashSet<string> ExcludedFolderIds(dynamic store)
        {
            var ids = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
            // Outlook OlDefaultFolders identifiers: Deleted Items=3, Drafts=16, Junk=23.
            foreach (int identifier in new int[] { 3, 16, 23 })
            {
                try
                {
                    dynamic folder = store.GetDefaultFolder(identifier);
                    string entryId = Safe(delegate { return (string)folder.EntryID; });
                    if (entryId.Length > 0) ids.Add(entryId);
                }
                catch { }
            }
            return ids;
        }

        private static void ScanFolder(
            dynamic folder,
            string storeId,
            string storeLabel,
            HashSet<string> excluded,
            ref int scanned,
            ref int registered)
        {
            if (registered >= BatchLimit) return;
            string folderId = Safe(delegate { return (string)folder.EntryID; });
            if (excluded.Contains(folderId)) return;
            ScanItems(folder, storeId, storeLabel, folderId, ref scanned, ref registered);
            if (registered >= BatchLimit) return;
            int childCount = SafeInt(delegate { return (int)folder.Folders.Count; });
            for (int index = 1; index <= childCount && registered < BatchLimit; index++)
            {
                try
                {
                    dynamic child = folder.Folders[index];
                    ScanFolder(child, storeId, storeLabel, excluded, ref scanned, ref registered);
                }
                catch (Exception error) { Log("folder scan error: " + error.Message); }
            }
        }

        private static void ScanItems(
            dynamic folder,
            string storeId,
            string storeLabel,
            string folderId,
            ref int scanned,
            ref int registered)
        {
            Cursor cursor = LoadCursor(storeId, folderId);
            dynamic items = folder.Items;
            try { items.Sort("[ReceivedTime]", true); } catch { }
            int count = SafeInt(delegate { return (int)items.Count; });
            long baselineNewest = cursor.NewestTicks;
            long baselineOldest = cursor.OldestTicks;

            // Outlook is sorted newest-first. Incremental items are confirmed
            // oldest-first so a failure can never be hidden by a newer cursor.
            var incremental = new List<int>();
            if (baselineNewest > 0)
            {
                for (int index = 1; index <= count; index++)
                {
                    DateTime received;
                    string entryId;
                    if (!TryReceived(items, index, out received, out entryId)) continue;
                    if (received.Ticks < baselineNewest) break;
                    if (received.Ticks == baselineNewest && cursor.NewestEntryIds.Contains(entryId)) continue;
                    incremental.Add(index);
                }
                for (int position = incremental.Count - 1; position >= 0 && registered < BatchLimit; position--)
                {
                    if (!RegisterItemAt(
                        items, incremental[position], storeId, storeLabel, folder, folderId,
                        true, ref cursor, ref scanned, ref registered)) return;
                }
            }

            // Backfill is confirmed newest-to-oldest. The oldest cursor moves
            // after every HTTP 2xx, so a failed item is retried on the next run.
            for (int index = 1; index <= count && registered < BatchLimit; index++)
            {
                DateTime received;
                string entryId;
                if (!TryReceived(items, index, out received, out entryId)) continue;
                if (baselineOldest > 0 && received.Ticks > baselineOldest) continue;
                if (received.Ticks == baselineOldest && cursor.OldestEntryIds.Contains(entryId)) continue;
                if (!RegisterItemAt(
                    items, index, storeId, storeLabel, folder, folderId,
                    false, ref cursor, ref scanned, ref registered)) return;
            }
        }

        private static bool TryReceived(dynamic items, int index, out DateTime received, out string entryId)
        {
            received = DateTime.MinValue;
            entryId = "";
            try
            {
                dynamic item = items[index];
                string messageClass = Safe(delegate { return (string)item.MessageClass; });
                if (!messageClass.StartsWith("IPM.Note", StringComparison.OrdinalIgnoreCase)) return false;
                received = (DateTime)item.ReceivedTime;
                entryId = Safe(delegate { return (string)item.EntryID; });
                return true;
            }
            catch { return false; }
        }

        private static bool RegisterItemAt(
            dynamic items,
            int index,
            string storeId,
            string storeLabel,
            dynamic folder,
            string folderId,
            bool incremental,
            ref Cursor cursor,
            ref int scanned,
            ref int registered)
        {
            dynamic item;
            DateTime received;
            try
            {
                item = items[index];
                received = (DateTime)item.ReceivedTime;
            }
            catch { return true; }
            scanned++;
            if (!Register(item, storeId, storeLabel, folder, folderId, received)) return false;
            registered++;
            long ticks = received.Ticks;
            if (incremental || cursor.NewestTicks == 0)
            {
                if (cursor.NewestTicks == 0 || ticks > cursor.NewestTicks)
                {
                    cursor.NewestTicks = ticks;
                    cursor.NewestEntryIds.Clear();
                }
                if (ticks == cursor.NewestTicks) cursor.NewestEntryIds.Add(Safe(delegate { return (string)item.EntryID; }));
            }
            if (!incremental || cursor.OldestTicks == 0)
            {
                if (cursor.OldestTicks == 0 || ticks < cursor.OldestTicks)
                {
                    cursor.OldestTicks = ticks;
                    cursor.OldestEntryIds.Clear();
                }
                if (ticks == cursor.OldestTicks) cursor.OldestEntryIds.Add(Safe(delegate { return (string)item.EntryID; }));
            }
            SaveCursor(storeId, folderId, cursor);
            return true;
        }

        private static bool Register(
            dynamic item,
            string storeId,
            string storeLabel,
            dynamic folder,
            string folderId,
            DateTime received)
        {
            string subject = Safe(delegate { return (string)item.Subject; });
            string entryId = Safe(delegate { return (string)item.EntryID; });
            string internetMessageId = "";
            try { internetMessageId = (string)item.PropertyAccessor.GetProperty(InternetMessageIdSchema); }
            catch { }
            string temp = Path.Combine(Path.GetTempPath(), "les-mail-" + Guid.NewGuid().ToString("N") + ".msg");
            try
            {
                item.SaveAs(temp, 9); // olMSGUnicode: body and attachments remain in the evidence snapshot.
                var fields = new Dictionary<string, string>();
                fields["store_id"] = storeId;
                fields["entry_id"] = entryId;
                fields["store_label"] = storeLabel;
                fields["folder_id"] = folderId;
                fields["folder_path"] = FolderPath(folder);
                fields["internet_message_id"] = internetMessageId;
                fields["received_at"] = received.ToUniversalTime().ToString("o");
                UploadMultipart(temp, fields);
                Log("registered: " + subject);
                return true;
            }
            catch (Exception error)
            {
                Log("register failed (" + subject + "): " + error.Message);
                return false;
            }
            finally
            {
                try { if (File.Exists(temp)) File.Delete(temp); } catch { }
            }
        }

        private static string FolderPath(dynamic folder)
        {
            var values = new List<string>();
            dynamic current = folder;
            for (int depth = 0; depth < 64 && current != null; depth++)
            {
                string name = Safe(delegate { return (string)current.Name; });
                if (name.Length > 0) values.Add(name);
                try { current = current.Parent; }
                catch { break; }
                string typeName = Safe(delegate { return (string)current.GetType().Name; });
                if (!typeName.ToLowerInvariant().Contains("folder")) break;
            }
            values.Reverse();
            return String.Join("/", values.ToArray());
        }

        private static void UploadMultipart(string filePath, Dictionary<string, string> fields)
        {
            string boundary = "----LESMAIL" + Guid.NewGuid().ToString("N");
            HttpWebRequest request = (HttpWebRequest)WebRequest.Create(CollectorUrl());
            request.Method = "POST";
            request.ContentType = "multipart/form-data; boundary=" + boundary;
            request.Timeout = 60000;
            using (Stream stream = request.GetRequestStream())
            {
                foreach (KeyValuePair<string, string> field in fields)
                {
                    WriteUtf8(stream, "--" + boundary + "\r\nContent-Disposition: form-data; name=\"" +
                        field.Key + "\"\r\n\r\n" + (field.Value ?? "") + "\r\n");
                }
                WriteUtf8(stream, "--" + boundary +
                    "\r\nContent-Disposition: form-data; name=\"message\"; filename=\"message.msg\"" +
                    "\r\nContent-Type: application/vnd.ms-outlook\r\n\r\n");
                using (FileStream file = File.OpenRead(filePath)) file.CopyTo(stream);
                WriteUtf8(stream, "\r\n--" + boundary + "--\r\n");
            }
            using (HttpWebResponse response = (HttpWebResponse)request.GetResponse())
            {
                if ((int)response.StatusCode < 200 || (int)response.StatusCode >= 300)
                    throw new WebException("LES returned HTTP " + (int)response.StatusCode);
            }
        }

        private static void WriteUtf8(Stream stream, string value)
        {
            byte[] bytes = Encoding.UTF8.GetBytes(value);
            stream.Write(bytes, 0, bytes.Length);
        }

        private static Cursor LoadCursor(string storeId, string folderId)
        {
            var cursor = new Cursor();
            try
            {
                string[] values = File.ReadAllText(CursorPath(storeId, folderId)).Trim().Split('|');
                if (values.Length > 0) Int64.TryParse(values[0], out cursor.NewestTicks);
                if (values.Length > 1) Int64.TryParse(values[1], out cursor.OldestTicks);
                if (values.Length > 2) cursor.NewestEntryIds = DecodeSet(values[2]);
                if (values.Length > 3) cursor.OldestEntryIds = DecodeSet(values[3]);
            }
            catch { }
            return cursor;
        }

        private static void SaveCursor(string storeId, string folderId, Cursor cursor)
        {
            string path = CursorPath(storeId, folderId);
            Directory.CreateDirectory(Path.GetDirectoryName(path));
            string temporary = path + ".tmp";
            string value = cursor.NewestTicks + "|" + cursor.OldestTicks + "|" +
                EncodeSet(cursor.NewestEntryIds) + "|" + EncodeSet(cursor.OldestEntryIds);
            File.WriteAllText(temporary, value, Encoding.ASCII);
            if (File.Exists(path)) File.Replace(temporary, path, null);
            else File.Move(temporary, path);
        }

        private static string CursorPath(string storeId, string folderId)
        {
            byte[] bytes = Encoding.UTF8.GetBytes(storeId + "|" + folderId);
            string digest;
            using (SHA256 sha = SHA256.Create()) digest = BitConverter.ToString(sha.ComputeHash(bytes)).Replace("-", "");
            return Path.Combine(StateRoot(), "cursors", digest + ".cursor");
        }

        private static string EncodeSet(HashSet<string> values)
        {
            return Convert.ToBase64String(Encoding.UTF8.GetBytes(String.Join("\n", new List<string>(values).ToArray())));
        }

        private static HashSet<string> DecodeSet(string value)
        {
            var result = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
            try
            {
                string decoded = Encoding.UTF8.GetString(Convert.FromBase64String(value));
                foreach (string item in decoded.Split(new char[] { '\n' }, StringSplitOptions.RemoveEmptyEntries))
                    result.Add(item);
            }
            catch { }
            return result;
        }

        private static string Safe(Func<string> value)
        {
            try { return value() ?? ""; }
            catch { return ""; }
        }

        private static int SafeInt(Func<int> value)
        {
            try { return value(); }
            catch { return 0; }
        }
    }
}
