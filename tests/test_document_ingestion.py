import unittest
from unittest.mock import patch

from document_parser import extract_text
from knowledge_base import KnowledgeBaseService


class UploadedFileStub:
    def __init__(self, name: str, content: bytes):
        self.name = name
        self._content = content

    def getvalue(self) -> bytes:
        return self._content


class FailingChromaStub:
    def __init__(self):
        self.calls = 0
        self.deleted_ids = []

    def add_texts(self, texts, metadatas, ids):
        self.calls += 1
        if self.calls == 2:
            raise RuntimeError("embedding failed")

    def delete(self, ids):
        self.deleted_ids.extend(ids)


class DocumentIngestionTest(unittest.TestCase):
    def test_empty_file_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "上传文件为空"):
            extract_text(UploadedFileStub("empty.txt", b""))

    def test_utf8_text_is_extracted(self):
        result = extract_text(UploadedFileStub("demo.txt", "企业制度".encode()))
        self.assertEqual(result, "企业制度")

    def test_partial_vector_write_is_rolled_back(self):
        service = KnowledgeBaseService.__new__(KnowledgeBaseService)
        service.chroma = FailingChromaStub()
        service.splitter = type(
            "SplitterStub", (), {"split_text": lambda self, text: ["A", "B"]}
        )()
        with (
            patch("knowledge_base.check_md5", return_value=False),
            patch("knowledge_base.save_md5"),
            patch("knowledge_base.load_registry", return_value={}),
            patch("knowledge_base.save_registry"),
            patch("knowledge_base.config.max_spliter_char_number", 1),
            patch("knowledge_base.config.embedding_batch_size", 1),
        ):
            with self.assertRaisesRegex(RuntimeError, "embedding failed"):
                service.upload_by_str("AB", "demo.txt")

        self.assertEqual(len(service.chroma.deleted_ids), 1)


if __name__ == "__main__":
    unittest.main()
