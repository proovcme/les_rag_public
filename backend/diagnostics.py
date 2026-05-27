import json
import subprocess
import re
from pathlib import Path
from datetime import datetime

from backend.rag_config import rag_collection_name

DIAG_DIR = Path('./data/diagnostics')
DIAG_DIR.mkdir(parents=True, exist_ok=True)

def run_cmd(cmd: list[str], timeout=10):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.stdout.strip(), r.returncode
    except Exception as e:
        return str(e), 1


def _count_files(path: Path) -> int:
    if not path.exists():
        return 0
    return sum(1 for item in path.rglob("*") if item.is_file())


def _mlx_processes() -> str:
    out, rc = run_cmd(["ps", "aux"])
    if rc != 0:
        return out
    rows = []
    for line in out.splitlines():
        lower = line.lower()
        if "mlx" not in lower or "grep" in lower:
            continue
        parts = line.split(None, 10)
        if len(parts) >= 11:
            rss_gb = int(parts[5]) / 1024 / 1024
            rows.append(f"{parts[1]} {rss_gb:.2f} {parts[10].split()[0]}")
    return "\n".join(rows)

def parse_vmstat():
    out, rc = run_cmd(["vm_stat"])
    if rc != 0: return {}
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
    mlx = _mlx_processes()
    mlx_health, _ = run_cmd(["curl", "-s", "http://localhost:8080/api/health"])
    qdrant, _ = run_cmd(["curl", "-s", f"http://localhost:6333/collections/{rag_collection_name()}"])
    health, _ = run_cmd(["curl", "-s", "http://localhost:8050/api/health"])
    rag_files = _count_files(Path("./RAG_Content"))
    sto_files = _count_files(Path("./storage/datasets"))

    report = {
        'timestamp': datetime.now().isoformat(),
        'macos_memory': vm,
        'docker_runtime': 'removed; Qdrant/proxy/UI/MLX run on host LaunchAgents',
        'mlx_health_raw': mlx_health,
        'mlx_processes': mlx or 'None',
        'qdrant_raw': qdrant,
        'health_raw': health,
        'rag_source_files': rag_files,
        'storage_indexed_files': sto_files
    }

    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    json_path = DIAG_DIR / f'diag_{ts}.json'
    md_path = DIAG_DIR / f'diag_{ts}.md'
    
    json_path.write_text(json.dumps(report, indent=2, ensure_ascii=False))
    md_content = f'# Диагностика Л.Е.С. {ts}\n\n' + '\n'.join(f'**{k}:** {v}' for k, v in report.items())
    md_path.write_text(md_content)

    alerts = []
    if vm.get('Compressed', 0) > 8: alerts.append(f"КРИТИЧНО: Compressed RAM {vm.get('Compressed', 0):.1f} GB")
    if vm.get('Free', 0) < 1: alerts.append('КРИТИЧНО: Free RAM < 1 GB')
    if report['rag_source_files'] > report['storage_indexed_files'] + 50: alerts.append('РАССИНХРОН: Файлы в RAG_Content не попали в индекс')
    if health and 'error' in health.lower(): alerts.append('ОШИБКА: Health endpoint вернул ошибку')

    return {'status': 'ok', 'report': report, 'alerts': alerts, 'json_path': str(json_path)}
