from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class ParsedPage:
    page: int | None  # 1-based 페이지, 텍스트 원본은 None
    text: str


@dataclass
class ParsedDocument:
    pages: list[ParsedPage] = field(default_factory=list)

    @property
    def text(self) -> str:
        parts = []
        for p in self.pages:
            if p.page is not None:
                parts.append(f"\n\n<!-- page {p.page} -->\n\n")
            parts.append(p.text)
        return "\n".join(parts).strip()


class DocumentParser:
    def parse(self, file: Path) -> ParsedDocument:
        raise NotImplementedError


class MarkdownParser(DocumentParser):
    def parse(self, file: Path) -> ParsedDocument:
        return ParsedDocument([ParsedPage(None, file.read_text(encoding="utf-8", errors="replace"))])


class PdfParser(DocumentParser):
    """텍스트 기반 PDF 전용. 스캔 이미지 PDF는 텍스트가 없으므로 unsupported로 보고한다."""

    def parse(self, file: Path) -> ParsedDocument:
        import fitz  # PyMuPDF

        pages: list[ParsedPage] = []
        with fitz.open(file) as doc:
            for page in doc:
                text = page.get_text("text")
                if text.strip():
                    pages.append(ParsedPage(page.number + 1, text))
        if not pages:
            raise ValueError("no extractable text (scanned/image-only PDF는 지원하지 않음)")
        return ParsedDocument(pages)


def parser_for(path: Path) -> DocumentParser | None:
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        return PdfParser()
    if suffix in (".md", ".markdown", ".txt"):
        return MarkdownParser()
    return None
