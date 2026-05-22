import re

FILE = "frontend/sovushka.html"
with open(FILE, "r", encoding="utf-8") as f:
    content = f.read()

# 1. Кнопка вкладки (после последней кнопки навигации)
tab_btn = '<button class="tab-btn" onclick="showTab(\'prorab\')">🏗 ПРОРАБ</button>'
if "🏗 ПРОРАБ" not in content:
    content = re.sub(
        r'(<button class="tab-btn" onclick="showTab\([^)]+\)">[^<]+</button>\s*)(?!.*<button class="tab-btn")',
        r'\1' + tab_btn + '\n',
        content,
        count=1,
        flags=re.DOTALL
    )

# 2. Содержимое вкладки (перед закрывающим </main> или последним tab-content)
prorab_html = """
<div id="tab-prorab" class="tab-content hidden">
    <h2>🏗 П.Р.О.Р.А.Б. — Панель управления ресурсами</h2>
    
    <!-- KPI Карточки -->
    <div class="metrics-grid" style="grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); gap: 10px; margin-bottom: 20px;">
        <div class="card"><h3>CPU</h3><p id="p-cpu" class="metric-value">-</p></div>
        <div class="card"><h3>RAM</h3><p id="p-ram" class="metric-value">-</p></div>
        <div class="card"><h3>Swap</h3><p id="p-swap" class="metric-value" style="color:var(--success)">0</p></div>
        <div class="card"><h3>Disk</h3><p id="p-disk" class="metric-value">-</p></div>
        <div class="card"><h3>Сеть</h3><p id="p-net" class="metric-value">-</p></div>
        <div class="card"><h3>Очередь LLM</h3><p id="p-queue" class="metric-value">0</p></div>
    </div>

    <!-- Графики -->
    <div class="charts-grid" style="display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 20px;">
        <div class="card"><h3>RAM Breakdown (GB)</h3><canvas id="chart-ram"></canvas></div>
        <div class="card"><h3>Storage Usage</h3><canvas id="chart-disk"></canvas></div>
        <div class="card"><h3>Latency Pipeline (sec)</h3><canvas id="chart-latency"></canvas></div>
        <div class="card"><h3>CRAG Pass Rate</h3><canvas id="chart-crag"></canvas></div>
        <div class="card"><h3>Token Usage</h3><canvas id="chart-tokens"></canvas></div>
        <div class="card"><h3>Errors (4xx/5xx)</h3><canvas id="chart-errors"></canvas></div>
    </div>

    <!-- Таблица здоровья -->
    <div class="card" style="margin-top: 20px;">
        <h3>Background Tasks Health</h3>
        <table style="width:100%; text-align: left;">
            <tr><th>Task</th><th>Status</th><th>Last Beat</th></tr>
            <tr><td>Metrics Collector</td><td id="hb-collector">⚪</td><td id="hb-collector-time">-</td></tr>
            <tr><td>SSE Emitter</td><td id="hb-sse">⚪</td><td id="hb-sse-time">-</td></tr>
            <tr><td>Folder Watcher</td><td id="hb-watcher">⚪</td><td id="hb-watcher-time">-</td></tr>
        </table>
    </div>
</div>
"""
if "tab-prorab" not in content:
    content = re.sub(
        r'(</main>)',
        prorab_html + r'\n\1',
        content,
        count=1
    )

# 3. JS Логика (перед </script>)
prorab_js = """
// Charts instances
let charts = {};

function initProrabCharts() {
    if (charts.ram) return; // Already init
    const commonOpts = { responsive: true, maintainAspectRatio: false };
    
    charts.ram = new Chart(document.getElementById('chart-ram'), {
        type: 'bar',
        data: { labels: ['Used'], datasets: [
            { label: 'Ollama', data: [0], backgroundColor: '#f87171' },
            { label: 'System', data: [0], backgroundColor: '#60a5fa' },
            { label: 'Free', data: [0], backgroundColor: '#34d399' }
        ]},
        options: { ...commonOpts, scales: { x: { stacked: true }, y: { stacked: true } } }
    });

    charts.disk = new Chart(document.getElementById('chart-disk'), {
        type: 'doughnut',
        data: { labels: ['Used', 'Free'], datasets: [{ data: [0, 100], backgroundColor: ['#ef4444', '#10b981'] }] },
        options: commonOpts
    });

    charts.latency = new Chart(document.getElementById('chart-latency'), {
        type: 'line',
        data: { labels: [], datasets: [
            { label: 'Search', data: [], borderColor: '#60a5fa', fill: false },
            { label: 'Gen', data: [], borderColor: '#f87171', fill: false }
        ]},
        options: commonOpts
    });

    charts.crag = new Chart(document.getElementById('chart-crag'), {
        type: 'pie',
        data: { labels: ['Pass', 'Fail'], datasets: [{ data: [1, 0], backgroundColor: ['#10b981', '#ef4444'] }] },
        options: commonOpts
    });

    charts.tokens = new Chart(document.getElementById('chart-tokens'), {
        type: 'bar',
        data: { labels: [], datasets: [{ label: 'Tokens', data: [], backgroundColor: '#a78bfa' }] },
        options: commonOpts
    });

    charts.errors = new Chart(document.getElementById('chart-errors'), {
        type: 'bar',
        data: { labels: ['4xx', '5xx'], datasets: [{ label: 'Count', data: [0, 0], backgroundColor: ['#fbbf24', '#ef4444'] }] },
        options: commonOpts
    });
}

function updateProrab(data) {
    if (!data || document.getElementById('tab-prorab').classList.contains('hidden')) return;
    initProrabCharts();

    const s = data.system;
    document.getElementById('p-cpu').innerText = s.cpu.toFixed(1) + '%';
    document.getElementById('p-ram').innerText = (s.ram_used).toFixed(1) + ' / ' + (s.ram_total).toFixed(1) + ' GB';
    
    const swapEl = document.getElementById('p-swap');
    swapEl.innerText = (s.swap_used * 1000).toFixed(0) + ' MB';
    swapEl.style.color = s.swap_used > 0.1 ? '#ef4444' : 'var(--success)';

    document.getElementById('p-disk').innerText = (s.disk_used/1000).toFixed(1) + ' TB';
    document.getElementById('p-net').innerText = s.network_ok === 2 ? '✅ OK' : '⚠️ ' + s.network_ok;
    document.getElementById('p-queue').innerText = data.queue.llm_waiting;

    // RAM Chart
    charts.ram.data.datasets[0].data = [s.ollama_ram];
    charts.ram.data.datasets[1].data = [s.ram_used - s.ollama_ram];
    charts.ram.data.datasets[2].data = [Math.max(0, s.ram_total - s.ram_used)];
    charts.ram.update();

    // Disk Chart
    charts.disk.data.datasets[0].data = [s.disk_used, s.disk_total - s.disk_used];
    charts.disk.update();

    // Latency
    if (data.pipeline.latency_search.length > 0) {
        charts.latency.data.labels = data.pipeline.latency_search.map((_, i) => i+1);
        charts.latency.data.datasets[0].data = data.pipeline.latency_search;
        charts.latency.data.datasets[1].data = data.pipeline.latency_gen;
        charts.latency.update();
    }

    // CRAG
    const cragRate = data.pipeline.crag_pass_rate;
    charts.crag.data.datasets[0].data = [cragRate * 100, (1 - cragRate) * 100];
    charts.crag.update();

    // Tokens
    if (data.pipeline.tokens.length > 0) {
        charts.tokens.data.labels = data.pipeline.tokens.map((_, i) => i+1);
        charts.tokens.data.datasets[0].data = data.pipeline.tokens;
        charts.tokens.update();
    }

    // Errors
    const errs = data.errors || {};
    const e4 = Object.keys(errs).filter(k => k.startsWith('4')).reduce((a, k) => a + errs[k], 0);
    const e5 = Object.keys(errs).filter(k => k.startsWith('5')).reduce((a, k) => a + errs[k], 0);
    charts.errors.data.datasets[0].data = [e4, e5];
    charts.errors.update();

    // Heartbeats
    const now = Date.now() / 1000;
    const hb = data.heartbeats;
    document.getElementById('hb-collector').innerText = (now - hb.collector < 10) ? '🟢 Alive' : '🔴 Dead';
    document.getElementById('hb-collector-time').innerText = new Date(hb.collector * 1000).toLocaleTimeString();
}

// Hook into existing polling if possible, or add standalone
if (typeof updateMetrics === 'function') {
    const originalUpdate = updateMetrics;
    updateMetrics = async function() {
        await originalUpdate();
        try {
            const res = await fetch('/api/metrics');
            const data = await res.json();
            updateProrab(data);
        } catch(e) {}
    };
}
"""
if "initProrabCharts" not in content:
    content = content.replace("</script>", prorab_js + "\n</script>")

with open(FILE, "w", encoding="utf-8") as f:
    f.write(content)

print("✅ UI Tab 'ПРОРАБ' successfully injected")
