#!/usr/bin/env python3
import os
import sys
import time
import subprocess
from pathlib import Path

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import psutil

def main():
    print("=== Автоматический мониторинг конвейера LES ===")
    print("Ожидаем завершения активной кампании переиндексации Fire...")
    
    while True:
        running = False
        for p in psutil.process_iter(['cmdline']):
            try:
                cmdline = p.info.get('cmdline') or []
                # Ищем процесс, выполняющий переиндексацию Fire
                if any('reindex_datasets_guarded.py' in part for part in cmdline) and any('NTD_FIRE_Index' in part for part in cmdline):
                    running = True
                    break
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        
        if not running:
            break
            
        time.sleep(15)
        
    print("\n[ОК] Кампания Fire успешно завершена!")
    print("Запускаем чистую переиндексацию датасета BOOKS_Index с очисткой состояния (--reset-state)...")
    
    try:
        # Запуск переиндексации Books
        res = subprocess.run([
            "uv", "run", "python", "tools/reindex_datasets_guarded.py",
            "--datasets", "BOOKS_Index",
            "--reset-state",
            "--min-free-gb", "6.0"
        ], check=True, cwd=str(PROJECT_ROOT))
        
        print("\n=== [ОК] Переиндексация книг BOOKS_Index завершена успешно! ===")
        return 0
    except subprocess.CalledProcessError as e:
        print(f"\n[ОШИБКА] Переиндексация книг BOOKS_Index завершилась с ошибкой: {e}")
        return 1

if __name__ == "__main__":
    sys.exit(main())
