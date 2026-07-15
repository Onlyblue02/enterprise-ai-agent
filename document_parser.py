"""Uploaded document parsing independent from the Streamlit UI."""

from io import BytesIO
from pathlib import Path

from docx import Document
from pypdf import PdfReader


def extract_text(uploaded_file) -> str:
    """Extract plain text from a Streamlit uploaded TXT, Markdown, PDF or DOCX file."""
    suffix = Path(uploaded_file.name).suffix.lower()
    content = uploaded_file.getvalue()
    if not content:
        raise ValueError("上传文件为空")

    if suffix in {".txt", ".md"}:
        try:
            text = content.decode("utf-8")
        except UnicodeDecodeError:
            text = content.decode("gb18030")

    elif suffix == ".pdf":
        text = "\n".join(
            page.extract_text() or "" for page in PdfReader(BytesIO(content)).pages
        )

    elif suffix == ".docx":
        text = "\n".join(
            paragraph.text for paragraph in Document(BytesIO(content)).paragraphs
        )

    else:
        raise ValueError(f"暂不支持 {suffix} 格式")

    if not text.strip():
        raise ValueError("未提取到可入库文本；扫描版 PDF 需要先进行 OCR")
    return text
