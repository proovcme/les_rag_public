import logging
import json
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

def convert_to_markdown(file_path: Path) -> Optional[str]:
    suffix = file_path.suffix.lower()
    logger.info(f"[CONVERT] Processing {file_path.name} ({suffix})")
    try:
        if suffix == '.pdf': return _parse_pdf(file_path)
        elif suffix == '.docx': return _parse_docx(file_path)
        elif suffix in ['.eml', '.msg']: return _parse_email(file_path)
        elif suffix in ['.xlsx', '.xls', '.csv']: return _parse_spreadsheet(file_path)
        elif suffix in ['.json', '.jsonl']: return _parse_json(file_path)
        elif suffix == '.md': return file_path.read_text(encoding='utf-8', errors='ignore')
        else:
            logger.warning(f"[CONVERT] Unsupported format: {suffix}")
            return None
    except Exception as e:
        logger.error(f"[CONVERT] Failed {file_path.name}: {e}")
        return None

def _parse_pdf(path: Path) -> str:
    try:
        import pymupdf4llm
        md = pymupdf4llm.to_markdown(path, pages=None, write_images=False)
        return md if md.strip() else f"[WARN] {path.name} appears scanned."
    except Exception as e:
        logger.warning(f"pymupdf4llm failed: {e}, fallback to fitz")
        import fitz
        doc = fitz.open(path)
        text = "\n\n".join(page.get_text() for page in doc)
        doc.close()
        return text

def _parse_docx(path: Path) -> str:
    import mammoth
    with open(path, "rb") as f:
        return mammoth.convert_to_markdown(f).value

def _parse_email(path: Path) -> str:
    if path.suffix.lower() == '.msg':
        import extract_msg
        msg = extract_msg.Message(path)
        return f"# {msg.subject}\n\nFrom: {msg.sender}\nDate: {msg.date}\n\n{msg.body}"
    else:
        import email
        from email import policy
        with open(path, "rb") as f:
            msg = email.message_from_binary_file(f, policy=policy.default)
        body = ""
        if msg.is_multipart():
            for part in msg.walk():
                if part.get_content_type() == "text/plain": body += part.get_content()
        else:
            body = msg.get_content()
        return f"# {msg.get('Subject', 'No Subject')}\n\nFrom: {msg.get('From')}\n\n{body}"

def _parse_spreadsheet(path: Path) -> str:
    import pandas as pd
    md = []
    if path.suffix == '.csv':
        df = pd.read_csv(path)
        md.append(f"## Sheet: Main\n{df.to_markdown()}")
    else:
        xls = pd.ExcelFile(path)
        for sheet in xls.sheet_names:
            df = pd.read_excel(xls, sheet_name=sheet)
            md.append(f"## Sheet: {sheet}\n{df.to_markdown()}")
    return "\n\n".join(md)

def _parse_json(path: Path) -> str:
    md = []
    try:
        size_mb = path.stat().st_size / (1024*1024)
        logger.info(f"[CONVERT] JSON size: {size_mb:.1f} MB")
        
        with open(path, 'r', encoding='utf-8', errors='ignore') as f:
            first_line = f.readline().strip()
            f.seek(0)
            is_jsonl = False
            try:
                json.loads(first_line)
                is_jsonl = True
            except: pass

            if is_jsonl or size_mb > 50:
                logger.info("[CONVERT] Using streaming mode for large/JSONL file")
                for i, line in enumerate(f):
                    if i >= 3000: break
                    try:
                        obj = json.loads(line)
                        txt = _extract_json_text(obj)
                        if txt: md.append(f"### Entry {i+1}\n{txt}")
                    except: pass
            else:
                data = json.load(f)
                items = data if isinstance(data, list) else [data]
                for i, item in enumerate(items[:1500]):
                    txt = _extract_json_text(item)
                    if txt: md.append(f"### Entry {i+1}\n{txt}")
                    
        return "\n\n".join(md) if md else f"[WARN] {path.name}: no extractable text"
    except Exception as e:
        return f"[ERROR] JSON parse failed: {e}"

def _extract_json_text(obj) -> str:
    if not isinstance(obj, dict): return ""
    parts = []
    for k in ['role', 'user', 'assistant', 'system', 'prompt', 'response', 'content', 'message', 'text', 'subject', 'body', 'delta']:
        if k in obj and isinstance(obj[k], str) and len(obj[k]) > 5:
            parts.append(f"**{k}:** {obj[k][:1500]}")
        elif k in obj and isinstance(obj[k], dict):
            nested = _extract_json_text(obj[k])
            if nested: parts.append(nested)
    return "\n".join(parts) if parts else ""
