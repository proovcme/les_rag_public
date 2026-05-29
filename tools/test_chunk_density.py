import os
import sys
import re
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from llama_index.core.node_parser import SentenceSplitter
from llama_index.core.schema import Document
from backend.converter import convert_to_markdown

class StructureAwareSplitter:
    """Structure-aware chunking for SP and GOST documents.
    Preserves numbered clauses (e.g. 5.2.1) as single indivisible blocks.
    Fits chunks within a target character length, and implements sentence-bounded overlap.
    """
    def __init__(self, chunk_size: int, chunk_overlap: int):
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        
        # Regex to detect lines that start a new numbered section or markdown header
        self.boundary_pattern = re.compile(
            r"^(?:#{1,6}\s+|"
            r"(?:Пункт|Раздел|Статья|п\.|§)\s*\d+(?:\.\d+)+|"
            r"\d+(?:\.\d+)+(?:\s+|\.|$))",
            re.IGNORECASE
        )

    def _split_into_atomic_blocks(self, text: str) -> list[str]:
        lines = text.split("\n")
        blocks = []
        current_block_lines = []
        
        for line in lines:
            stripped = line.strip()
            if not stripped:
                if current_block_lines:
                    current_block_lines.append(line)
                continue
                
            if self.boundary_pattern.match(stripped):
                if current_block_lines:
                    blocks.append("\n".join(current_block_lines).strip())
                    current_block_lines = []
            
            current_block_lines.append(line)
            
        if current_block_lines:
            blocks.append("\n".join(current_block_lines).strip())
            
        return [b for b in blocks if b]

    def _get_sentence_overlap(self, text_prev: str, max_overlap: int) -> str:
        if not text_prev or max_overlap <= 0:
            return ""
        sentences = re.split(r'(?<=[.!?])\s+', text_prev)
        overlap_sentences = []
        current_len = 0
        for s in reversed(sentences):
            s = s.strip()
            if not s:
                continue
            if current_len + len(s) + 1 <= max_overlap:
                overlap_sentences.append(s)
                current_len += len(s) + 1
            else:
                if not overlap_sentences:
                    return s[-max_overlap:]
                break
        if not overlap_sentences:
            return ""
        return " ".join(reversed(overlap_sentences)) + " "

    def _split_large_block(self, text: str, max_chars: int, overlap_chars: int) -> list[str]:
        sentences = re.split(r'(?<=[.!?])\s+', text)
        chunks = []
        current_chunk = []
        current_len = 0
        
        for s in sentences:
            s = s.strip()
            if not s:
                continue
            s_len = len(s)
            
            if s_len > max_chars:
                if current_chunk:
                    chunks.append(" ".join(current_chunk))
                    current_chunk = []
                    current_len = 0
                i = 0
                while i < s_len:
                    chunks.append(s[i:i + max_chars])
                    i += max_chars - overlap_chars
                    if i + overlap_chars >= s_len:
                        if i < s_len:
                            chunks.append(s[i:])
                        break
            else:
                separator_len = 1 if current_chunk else 0
                if current_len + separator_len + s_len <= max_chars:
                    current_chunk.append(s)
                    current_len += separator_len + s_len
                else:
                    chunks.append(" ".join(current_chunk))
                    overlap_prefix = self._get_sentence_overlap(chunks[-1], overlap_chars)
                    current_chunk = []
                    current_len = 0
                    if overlap_prefix:
                        current_chunk.append(overlap_prefix.strip())
                        current_len = len(overlap_prefix.strip())
                    
                    separator_len = 1 if current_chunk else 0
                    current_chunk.append(s)
                    current_len += separator_len + s_len
                    
        if current_chunk:
            chunks.append(" ".join(current_chunk))
        return chunks

    def get_nodes_from_documents(self, documents: list) -> list:
        from llama_index.core.schema import TextNode
        
        all_nodes = []
        for doc in documents:
            text = doc.text
            metadata = doc.metadata or {}
            doc_id = doc.node_id if hasattr(doc, "node_id") else doc.id_
            
            atomic_blocks = self._split_into_atomic_blocks(text)
            
            chunks = []
            current_chunk_blocks = []
            current_chunk_len = 0
            
            for block in atomic_blocks:
                block_len = len(block)
                
                if block_len > self.chunk_size:
                    if current_chunk_blocks:
                        chunks.append("\n\n".join(current_chunk_blocks))
                        current_chunk_blocks = []
                        current_chunk_len = 0
                    
                    sub_chunks = self._split_large_block(block, self.chunk_size, self.chunk_overlap)
                    chunks.extend(sub_chunks)
                else:
                    separator_len = 2 if current_chunk_blocks else 0
                    if current_chunk_len + separator_len + block_len <= self.chunk_size:
                        current_chunk_blocks.append(block)
                        current_chunk_len += separator_len + block_len
                    else:
                        chunks.append("\n\n".join(current_chunk_blocks))
                        overlap_prefix = self._get_sentence_overlap(chunks[-1], self.chunk_overlap)
                        
                        current_chunk_blocks = []
                        current_chunk_len = 0
                        if overlap_prefix:
                            current_chunk_blocks.append(overlap_prefix.strip())
                            current_chunk_len = len(overlap_prefix.strip())
                            
                        separator_len = 2 if current_chunk_blocks else 0
                        current_chunk_blocks.append(block)
                        current_chunk_len += separator_len + block_len
            
            if current_chunk_blocks:
                chunks.append("\n\n".join(current_chunk_blocks))
                
            for idx, chunk_text in enumerate(chunks):
                node = TextNode(
                    text=chunk_text,
                    id_=f"{doc_id}_chunk_{idx}",
                    metadata=metadata
                )
                all_nodes.append(node)
                
        return all_nodes

def run_density_test():
    ntd_dir = Path("RAG_Content/NTD")
    candidates = list(ntd_dir.rglob("*.docx")) + list(ntd_dir.rglob("*.md"))
    test_files = []
    for f in candidates:
        if f.name == "test_gost.md":
            test_files.append(f)
            continue
        if len(test_files) < 5 and f.stat().st_size < 300000:
            test_files.append(f)
            
    if not test_files:
        print("No test files found in RAG_Content/NTD!")
        return

    print(f"Running character-bounded density calibration test on {len(test_files)} files:")
    for f in test_files:
        print(f" - {f.name} ({f.stat().st_size / 1024:.1f} KB)")

    old_splitter = SentenceSplitter(chunk_size=1400, chunk_overlap=100)
    new_splitter = StructureAwareSplitter(chunk_size=1550, chunk_overlap=70)

    for i, file_path in enumerate(test_files, 1):
        print("\n" + "="*80)
        print(f"FILE {i}: {file_path.name}")
        print("="*80)
        
        try:
            content = convert_to_markdown(file_path)
            if not content:
                print("Skipped (empty content)")
                continue
                
            doc = Document(text=content, metadata={"file_name": file_path.name})
            
            # Old geometry
            old_nodes = old_splitter.get_nodes_from_documents([doc])
            old_lens = [len(n.text) for n in old_nodes]
            
            # New geometry
            new_nodes = new_splitter.get_nodes_from_documents([doc])
            new_lens = [len(n.text) for n in new_nodes]
            
            print(f"Old Geometry (chunk_size=1400, overlap=100 - TOKENS):")
            print(f"  - Total Chunks: {len(old_nodes)}")
            print(f"  - Avg Length:   {sum(old_lens)/len(old_lens):.1f} chars" if old_lens else "N/A")
            print(f"  - Max Length:   {max(old_lens)} chars" if old_lens else "N/A")
            
            print(f"New Geometry (chunk_size=1550, overlap=70 - CHARS - structure-aware):")
            print(f"  - Total Chunks: {len(new_nodes)}")
            print(f"  - Avg Length:   {sum(new_lens)/len(new_lens):.1f} chars" if new_lens else "N/A")
            print(f"  - Max Length:   {max(new_lens)} chars" if new_lens else "N/A")
            
            # Print structure conservation snippet
            if new_nodes:
                print("\nSample chunk snippet from New Geometry:")
                sample = new_nodes[min(len(new_nodes)-1, 2)].text
                print(sample[:600] + "\n[... truncated snippet ...]" if len(sample) > 600 else sample)
                
        except Exception as e:
            print(f"Error processing {file_path.name}: {e}")

if __name__ == "__main__":
    run_density_test()
