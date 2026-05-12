import json
import subprocess
import asyncio
import re
import os
import time
from pathlib import Path
from datetime import datetime

DIAG_DIR = Path('./data/diagnostics')
DIAG_DIR.mkdir(parents=True, exist_ok=True)

def run_cmd(cmd, timeout=10):
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
        return r.stdout.strip(), r.returncode
    except Exception as e:
        return str(e), 1

def parse_vmstat():
    out, rc = run_cmd('vm_stat')
    if rc != 0: return {}
    import re
    ps = re.search(r'page size of (\d+) bytes', out)
    sz = int(ps.group(1)) if ps else 4096
    res = {}
    for line in out.splitlines():
        if ':' in line:
            k, v = line.split(':', 1)
            try: res[k.strip()] = int(v.strip().rstrip('.')) * sz / 1024**3
            except: pass
    return res

async def run_diagnostics():
    vm = parse_vmstat()
    dock, _ = run_cmd('docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"')
    stats, _ = run_cmd('docker stats --no-stream --format "table {{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}"')
    oll_ps, _ = run_cmd('ollama ps 2>/dev/null')
    
    # FIX: AWK command corrected
    mlx_cmd = "ps aux | grep -i mlx | grep -v grep | awk '{print $2, $6/1024/1024, $11}'"
    mlx, _ = run_cmd(mlx_cmd)
    
    qdrant, _ = run_cmd('curl -s http://localhost:6333/collections/les_rag')
    health, _ = run_cmd('curl -s http://localhost:8050/api/health')
    rag_files, _ = run_cmd('find ./RAG_Content -type f 2>/dev/null | wc -l')
    sto_files, _ = run_cmd('find ./storage/datasets -type f 2>/dev/null | wc -l')

    report = {
        'timestamp': datetime.now().isoformat(),
        'macos_memory': vm,
        'docker_processes': dock,
        'docker_stats': stats,
        'ollama_ps': oll_ps or 'Empty',
        'mlx_processes': mlx or 'None',
        'qdrant_raw': qdrant,
        'health_raw': health,
        'rag_source_files': int(rag_files.strip() or 0),
        'storage_indexed_files': int(sto_files.strip() or 0)
    }

    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    json_path = DIAG_DIR / f'diag_{ts}.json'
    md_path = DIAG_DIR / f'diag_{ts}.md'
    
    json_path.write_text(json.dumps(report, indent=2, ensure_ascii=False))
    md_content = f'# Диагностика Л.Е.С. {ts}\n\n' + '\n'.join(f'**{{k}}:** {{v}}' for k,v in report.items())
    md_path.write_text(md_content)

    alerts = []
    if vm.get('Compressed', 0) > 8: alerts.append(f"КРИТИЧНО: Compressed RAM {vm.get('Compressed', 0):.1f} GB")
    if vm.get('Free', 0) < 1: alerts.append('КРИТИЧНО: Free RAM < 1 GB')
    if report['rag_source_files'] > report['storage_indexed_files'] + 50: alerts.append('РАССИНХРОН: Файлы в RAG_Content не попали в индекс')
    if health and 'error' in health.lower(): alerts.append('ОШИБКА: Health endpoint вернул ошибку')

    return {'status': 'ok', 'report': report, 'alerts': alerts, 'json_path': str(json_path)}
