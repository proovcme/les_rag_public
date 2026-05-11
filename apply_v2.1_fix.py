import re
import os
import shutil

# --- 0. Бэкапы ---
if os.path.exists("proxy_server.py"): shutil.copy("proxy_server.py", "proxy_server.py.bak_v2.1")
if os.path.exists("frontend/sovushka.html"): shutil.copy("frontend/sovushka.html", "frontend/sovushka.html.bak_v2.1")

# --- 1. Backend: proxy_server.py ---
print("🔧 Патчинг proxy_server.py...")
with open("proxy_server.py", "r", encoding="utf-8") as f:
    py_content = f.read()

# Добавляем импорт requests, если нет
if "import requests" not in py_content:
    py_content = py_content.replace("import os", "import os\nimport requests", 1)

# Логика сбора RAG-статистики перед return в /api/metrics
rag_stats_block = """
    # --- Сбор RAG-статистики (Qdrant REST + SQLite) ---
    chunks_count = 0
    try:
        q_res = requests.get("http://qdrant:6333/collections/les_rag", timeout=2)
        if q_res.status_code == 200:
            chunks_count = q_res.json().get("result", {}).get("points_count", 0)
    except Exception:
        pass

    datasets_count = 0
    files_count = 0
    try:
        meta_conn = sqlite3.connect("./data/les_meta.db")
        datasets_count = meta_conn.execute("SELECT COUNT(*) FROM datasets").fetchone()[0]
        files_count = meta_conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
        meta_conn.close()
    except Exception:
        pass
    # ----------------------------------------------------
"""

if "Сбор RAG-статистики" not in py_content:
    # Вставляем перед return { в функции get_metrics
    py_content = re.sub(
        r'(    return \{)',
        rag_stats_block + r'\n\1',
        py_content,
        count=1
    )

# Добавляем ключ "rag" в return dict
if '"rag":' not in py_content:
    py_content = re.sub(
        r'("system": \{)',
        r'"rag": {\n            "datasets": datasets_count,\n            "files": files_count,\n            "chunks": chunks_count\n        },\n        \1',
        py_content,
        count=1
    )

with open("proxy_server.py", "w", encoding="utf-8") as f:
    f.write(py_content)

# --- 2. Frontend: sovushka.html ---
print("🎨 Патчинг frontend/sovushka.html...")
html_file = "frontend/sovushka.html"
if os.path.exists(html_file):
    with open(html_file, "r", encoding="utf-8") as f:
        html_content = f.read()

    # Новый JS-мост
    new_js = """
<script>
(function() {
  const API = '';
  let sse = null;
  const recentEvents = [];

  window.showTab = (id) => {
    document.querySelectorAll('.tab-content').forEach(el => el.classList.remove('active'));
    document.querySelectorAll('.nav-btn').forEach(el => el.classList.remove('active'));
    document.getElementById('tab-' + id)?.classList.add('active');
    const idx = {overview:0, prorab:1, chat:2, logs:3, datasets:4}[id];
    if (idx !== undefined) document.querySelectorAll('.nav-btn')[idx]?.classList.add('active');
    if (id === 'datasets') loadDatasets();
    if (id === 'logs' && !sse) connectSSE();
  };

  window.toggleTheme = () => document.body.classList.toggle('light');

  async function fetchMetrics() {
    try {
      const res = await fetch(API + '/api/metrics');
      if (!res.ok) return;
      const d = await res.json();
      const s = d.system || {};
      const r = d.rag || {};
      const p = d.pipeline || {};
      const q = d.queue || {};
      const hb = d.heartbeats || {};

      document.getElementById('h-cpu').innerText = (s.cpu||0).toFixed(1) + '%';
      document.getElementById('h-ram').innerText = (s.ram_used||0).toFixed(1) + '/' + (s.ram_total||0).toFixed(1) + ' GB';
      
      const swapMB = (s.swap_used||0) * 1000;
      const swapEl = document.getElementById('h-swap');
      swapEl.innerText = swapMB.toFixed(0) + ' MB';
      swapEl.style.color = swapMB > 100 ? 'var(--danger)' : 'var(--success)';

      document.getElementById('h-queue').innerText = q.llm_waiting || 0;
      document.getElementById('h-net').innerText = s.network_ok === 2 ? '✅' : (s.network_ok === 1 ? '⚠️ 1/2' : '❌');
      
      const now = Date.now() / 1000;
      const hbEl = document.getElementById('h-hb');
      hbEl.innerText = (now - (hb.collector||0) < 10) ? '🟢' : '🔴';

      document.getElementById('ov-docs').innerText = r.files || 0;
      document.getElementById('ov-chunks').innerText = r.chunks || 0;
      document.getElementById('ov-crag').innerText = ((p.crag_pass_rate||0)*100).toFixed(0) + '%';
      document.getElementById('ov-status').innerText = 'Live';

      const ramO = s.ollama_ram || 0;
      const ramS = Math.max(0, (s.ram_used||0) - ramO);
      const ramT = s.ram_total || 1;
      document.getElementById('p-ram-ollama').innerText = ramO.toFixed(1);
      document.getElementById('p-ram-sys').innerText = ramS.toFixed(1);
      document.getElementById('p-ram-total').innerText = ramT.toFixed(1);
      document.getElementById('bar-ollama').style.width = (ramO/ramT*100) + '%';
      document.getElementById('bar-sys').style.width = (ramS/ramT*100) + '%';

      const dU = s.disk_used || 0; const dT = s.disk_total || 1;
      document.getElementById('p-disk-val').innerText = (dU/1000).toFixed(1) + ' / ' + (dT/1000).toFixed(1) + ' TB';
      document.getElementById('bar-disk').style.width = (dU/dT*100) + '%';

      const lS = p.latency_search?.length ? p.latency_search.at(-1) : 0;
      const lG = p.latency_gen?.length ? p.latency_gen.at(-1) : 0;
      document.getElementById('p-lat-search').innerText = lS.toFixed(2) + 's';
      document.getElementById('p-lat-gen').innerText = lG.toFixed(2) + 's';
      document.getElementById('bar-lat-search').style.width = Math.min(100, lS/5*100) + '%';
      document.getElementById('bar-lat-gen').style.width = Math.min(100, lG/5*100) + '%';
      
      const tok = p.tokens?.length ? p.tokens.at(-1) : 0;
      document.getElementById('p-tokens').innerText = tok;
      document.getElementById('bar-tokens').style.width = Math.min(100, tok/8192*100) + '%';

      const fmtHB = (id, ts) => {
        const st = document.getElementById(id + '-status');
        const tm = document.getElementById(id + '-time');
        if (!st || !tm) return;
        if (!ts || ts === 0) { st.innerText = '⚪ Idle'; tm.innerText = '-'; return; }
        const diff = now - ts;
        st.innerText = diff < 10 ? '🟢 Alive' : '🔴 Stale';
        tm.innerText = new Date(ts*1000).toLocaleTimeString();
      };
      fmtHB('hb-col', hb.collector);
      fmtHB('hb-sse', hb.sse_emitter);
      fmtHB('hb-watch', hb.folder_watcher);

    } catch(e) { console.warn('[METRICS]', e); }
  }

  window.loadDatasets = async () => {
    const tbody = document.getElementById('datasets-body');
    tbody.innerHTML = '<tr><td colspan="4">Загрузка...</td></tr>';
    try {
      const res = await fetch(API + '/api/rag/sources');
      const data = await res.json();
      tbody.innerHTML = '';
      if (!Array.isArray(data) || data.length === 0) {
        tbody.innerHTML = '<tr><td colspan="4">Нет источников</td></tr>';
        return;
      }
      data.forEach(ds => {
        const name = ds.name || ds.folder || ds.source || ds.path?.split('/').pop() || ds.id || 'Источник';
        const count = ds.file_count || ds.files || ds.count || 0;
        const status = ds.status || 'IDLE';
        const tr = document.createElement('tr');
        tr.innerHTML = `
          <td>${name}</td>
          <td>${count}</td>
          <td>${status}</td>
          <td><button class="btn" style="padding:4px 8px; font-size:0.8rem" onclick="syncFolder('${name}')">🔄 Sync</button></td>
        `;
        tbody.appendChild(tr);
      });
    } catch(e) {
      tbody.innerHTML = '<tr><td colspan="4" style="color:var(--danger)">Ошибка загрузки</td></tr>';
    }
  };

  window.syncFolder = async (name) => {
    if (!confirm(`Запустить синхронизацию ${name}?`)) return;
    try {
      const res = await fetch(API + `/api/rag/sync/${encodeURIComponent(name)}`, { method: 'POST' });
      const d = await res.json();
      alert(`Задача запущена: ${d.job_id || 'OK'}`);
      loadDatasets();
    } catch(e) { alert('Ошибка: ' + e.message); }
  };

  window.sendChat = async () => {
    const input = document.getElementById('chat-input');
    const query = input.value.trim();
    if (!query) return;
    input.value = '';
    const box = document.getElementById('chat-messages');
    
    const uMsg = document.createElement('div'); uMsg.className = 'msg user'; uMsg.innerText = query;
    box.appendChild(uMsg);
    
    const bMsg = document.createElement('div'); bMsg.className = 'msg bot';
    bMsg.innerHTML = '<span class="typing-cursor">Думаю...</span>';
    box.appendChild(bMsg);
    box.scrollTop = box.scrollHeight;
    document.getElementById('chat-send-btn').disabled = true;

    try {
      const res = await fetch(API + '/api/chat', {
        method: 'POST', headers: {'Content-Type':'application/json'},
        body: JSON.stringify({ query })
      });
      const d = await res.json();
      const ans = d.answer || d.response || 'Нет ответа';
      const src = d.sources || [];
      
      bMsg.innerHTML = '';
      let i = 0;
      const iv = setInterval(() => {
        bMsg.innerHTML += ans.charAt(i); i++;
        box.scrollTop = box.scrollHeight;
        if (i >= ans.length) {
          clearInterval(iv);
          if (src.length) {
            const sDiv = document.createElement('div'); sDiv.className = 'source';
            sDiv.innerHTML = '📚 Источники: ' + src.slice(0,3).map(s => `<b>${s.file || s.name || s}</b>`).join(', ');
            bMsg.appendChild(sDiv);
          }
          document.getElementById('chat-send-btn').disabled = false;
        }
      }, 15);
    } catch(e) {
      bMsg.innerText = 'Ошибка: ' + e.message;
      document.getElementById('chat-send-btn').disabled = false;
    }
  };

  function connectSSE() {
    if (sse) sse.close();
    sse = new EventSource(API + '/api/logs/stream');
    const logBox = document.getElementById('log-container');
    const evtBox = document.getElementById('ov-events');

    sse.onmessage = (e) => {
      try {
        const d = JSON.parse(e.data);
        const time = new Date().toLocaleTimeString();
        const line = `[${time}] ${d.message || d.event || JSON.stringify(d)}`;
        
        if (logBox) {
          const div = document.createElement('div'); div.className = 'log-entry'; div.innerText = line;
          logBox.appendChild(div); logBox.scrollTop = logBox.scrollHeight;
        }
        recentEvents.unshift(line);
        if (recentEvents.length > 5) recentEvents.pop();
        if (evtBox) evtBox.innerHTML = recentEvents.map(l => `<div style="margin-bottom:4px">${l}</div>`).join('');
      } catch(err) {}
    };
    sse.onerror = () => { if(logBox) logBox.innerHTML += '<div style="color:var(--danger)">SSE lost. Reconnecting...</div>'; };
  }

  setInterval(fetchMetrics, 3000);
  fetchMetrics();
  connectSSE();
})();
</script>
"""

    # Замена старого скрипта
    html_content = re.sub(r'<script>.*?</script>', new_js.strip(), html_content, flags=re.DOTALL)
    
    with open(html_file, "w", encoding="utf-8") as f:
        f.write(html_content)
    print("✅ Frontend обновлён.")
else:
    print("❌ frontend/sovushka.html не найден.")

print("✅ Готово. Запускаем пересборку...")
