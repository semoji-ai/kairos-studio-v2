import zipfile

import pytest

from core.doc_convert import SUPPORTED_EXTS, extract_text


def _docx(path, paragraphs):
    body = "".join(
        f'<w:p><w:pPr><w:pStyle w:val="{s}"/></w:pPr><w:r><w:t>{t}</w:t></w:r></w:p>'
        for s, t in paragraphs)
    xml = ('<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
           f'<w:body>{body}</w:body></w:document>')
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("word/document.xml", xml)


def _hwpx(path, paragraphs):
    ps = "".join(f"<hp:p><hp:run><hp:t>{t}</hp:t></hp:run></hp:p>" for t in paragraphs)
    xml = f'<hs:sec xmlns:hs="urn:hs" xmlns:hp="urn:hp">{ps}</hs:sec>'
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("Contents/section0.xml", xml)


def test_supported_extensions():
    assert SUPPORTED_EXTS == {".pdf", ".docx", ".hwp", ".hwpx", ".md", ".markdown", ".txt"}


def test_docx_headings_and_paragraphs(tmp_path):
    src = tmp_path / "설교.docx"
    _docx(src, [("Heading1", "정죄함이 없는 자유"), ("Normal", "본문 첫 문단")])
    text, assets = extract_text(src, tmp_path / "work")
    assert "# 정죄함이 없는 자유" in text
    assert "본문 첫 문단" in text
    assert assets == []


def test_hwpx_paragraphs(tmp_path):
    src = tmp_path / "설교.hwpx"
    _hwpx(src, ["첫째 문단", "둘째 문단"])
    text, _ = extract_text(src, tmp_path / "work")
    assert "첫째 문단" in text and "둘째 문단" in text


def test_txt_utf8_bom_and_cp949(tmp_path):
    a = tmp_path / "a.txt"
    a.write_bytes("\ufeff은혜".encode("utf-8"))
    b = tmp_path / "b.txt"
    b.write_bytes("말씀".encode("cp949"))
    assert extract_text(a, tmp_path / "w1")[0].strip() == "은혜"
    assert extract_text(b, tmp_path / "w2")[0].strip() == "말씀"


def test_unsupported_extension(tmp_path):
    src = tmp_path / "x.xlsx"
    src.write_bytes(b"x")
    with pytest.raises(ValueError):
        extract_text(src, tmp_path / "work")


def test_hwp_without_converter_raises_runtime_error(tmp_path, monkeypatch):
    import core.doc_convert as dc
    monkeypatch.setattr(dc.shutil, "which", lambda name: None)
    monkeypatch.setattr(dc.os, "name", "posix")
    src = tmp_path / "x.hwp"
    src.write_bytes(b"not really hwp")
    with pytest.raises(RuntimeError, match="HWP"):
        extract_text(src, tmp_path / "work")


def test_pdf_when_library_available(tmp_path):
    fitz = pytest.importorskip("fitz")
    doc = fitz.open()
    doc.new_page().insert_text((72, 72), "Grace alone")
    src = tmp_path / "x.pdf"
    doc.save(src)
    text, _ = extract_text(src, tmp_path / "work")
    assert "Grace alone" in text
