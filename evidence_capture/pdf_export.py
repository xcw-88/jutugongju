from __future__ import annotations
import hashlib
import json
import os
import re
import tempfile
from pathlib import Path
from xml.sax.saxutils import escape
from PIL import Image
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib.utils import ImageReader
from reportlab.platypus import Paragraph
from reportlab.pdfgen import canvas
from .models import EvidenceInfo, atomic_json, now_iso, safe_name

FONT = "EvidenceChinese"


def register_font() -> str:
    if FONT not in pdfmetrics.getRegisteredFontNames():
        fonts = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts"
        for filename in ("simsun.ttc", "simhei.ttf", "simfang.ttf"):
            path = fonts / filename
            if path.exists():
                try:
                    pdfmetrics.registerFont(TTFont(FONT, str(path), subfontIndex=0))
                    return FONT
                except Exception:
                    continue
        raise RuntimeError("未找到可嵌入的中文字体，请在 Windows 中安装宋体、黑体或仿宋")
    return FONT


def numbered_images(folder: Path) -> list[Path]:
    return sorted((p for p in folder.glob("*.png") if re.fullmatch(r"[0-9]{3,}\.png", p.name, re.I)),
                  key=lambda p: int(p.stem))


def export_pdf(folder: Path, info: EvidenceInfo, reverse=True, status=lambda message: None) -> Path:
    info.validate()
    paths = numbered_images(folder)
    if not paths:
        raise ValueError("该目录内没有 001.png、002.png 形式的截图")
    journal = folder / "manifest.json"
    manifest = json.loads(journal.read_text(encoding="utf-8")) if journal.exists() else None
    if manifest is not None:
        expected = manifest.get("images", [])
        if {item["file"] for item in expected} != {p.name for p in paths}:
            raise ValueError("原图与采集记录不一致：存在缺失或新增文件，请检查证据目录")
        for item in expected:
            if Path(item["file"]).name != item["file"]:
                raise ValueError("采集记录包含非法文件名")
            if hashlib.sha256((folder / item["file"]).read_bytes()).hexdigest() != item["sha256"]:
                raise ValueError(f"原图内容已变更：{item['file']}，请检查后再生成 PDF")
    if reverse:
        paths.reverse()
    register_font()
    material_title = info.material_title.strip()
    stem = safe_name(info.name)
    if material_title and not stem.endswith(safe_name(material_title)):
        stem += safe_name(material_title)
    filename = folder / f"{stem}.pdf"
    number = 1
    while True:
        candidate = filename if number == 1 else folder / f"{stem}_{number:02d}.pdf"
        try:
            with candidate.open("xb"):
                pass
            break
        except FileExistsError:
            number += 1
    fd, temporary = tempfile.mkstemp(prefix=".evidence-", suffix=".pdf", dir=folder)
    os.close(fd)
    width, height = A4
    margin = 18 * mm
    body_width = width - 2 * margin
    text_style = ParagraphStyle("body", fontName=FONT, fontSize=12, leading=21,
                                wordWrap="CJK", textColor=colors.HexColor("#182233"))
    title_style = ParagraphStyle("title", parent=text_style, fontSize=20, leading=30, alignment=TA_CENTER)
    page = 1

    def paragraph(value, style=text_style):
        return Paragraph(escape(value or "（填写）").replace("\n", "<br/>"), style)

    try:
        pdf = canvas.Canvas(temporary, pagesize=A4, pageCompression=1)
        pdf.setTitle(f"{info.name} - {material_title}" if material_title else info.name)
        pdf.setAuthor("聊天软件截屏助手")

        y = height - 32 * mm
        titles = [("证据材料", 24)]
        if material_title:
            titles.append((material_title, 20))
        for title, size in titles:
            style = ParagraphStyle("heading", parent=title_style, fontSize=size, leading=36)
            p = paragraph(title, style)
            _, ph = p.wrap(body_width, height)
            p.drawOn(pdf, margin, y - ph)
            y -= ph + 8 * mm
        y -= 8 * mm
        fields = [("证据名称", info.name), ("对象", info.subject), ("身份", info.identity),
                  ("时间范围", info.time_range), ("证明目的", info.purpose)]
        for label, value in fields:
            chunks = [paragraph(f"{label}：\n{value or '（填写）'}")]
            while chunks:
                p = chunks.pop(0)
                available = y - 28 * mm
                _, ph = p.wrap(body_width, height)
                if ph > available:
                    pieces = p.split(body_width, available)
                    if pieces:
                        first = pieces.pop(0)
                        _, ph = first.wrap(body_width, available)
                        first.drawOn(pdf, margin, y - ph)
                        chunks = pieces + chunks
                    else:
                        chunks.insert(0, p)
                    pdf.showPage()
                    page += 1
                    pdf.setFont(FONT, 14)
                    pdf.setFillColor(colors.HexColor("#182233"))
                    pdf.drawString(margin, height - 22 * mm, "证据说明（续）")
                    y = height - 34 * mm
                else:
                    p.drawOn(pdf, margin, y - ph)
                    y -= ph + 7 * mm
        pdf.showPage()
        page += 1
        image_pages = []
        for index, path in enumerate(paths, 1):
            status(f"生成 PDF · {index}/{len(paths)} 张")
            image_top = height - margin
            if material_title:
                header_style = ParagraphStyle("screenshot_header", parent=text_style,
                                              fontSize=10, leading=15)
                header = paragraph(material_title, header_style)
                _, header_height = header.wrap(body_width, height)
                header.drawOn(pdf, margin, height - 15 * mm - header_height)
                image_top = height - 15 * mm - header_height - 7 * mm
            available_height = image_top - margin
            with Image.open(path) as original:
                original.load()
                scale = min(body_width / original.width, available_height / original.height)
                draw_width, draw_height = original.width * scale, original.height * scale
                pdf.drawImage(ImageReader(original), (width - draw_width) / 2,
                              image_top - draw_height, draw_width, draw_height, mask="auto")
                image_pages.append(dict(file=path.name, page=page,
                                        effective_ppi=round(72 / scale, 1)))
            pdf.showPage()
            page += 1
        pdf.save()
        os.replace(temporary, candidate)
    except Exception:
        Path(temporary).unlink(missing_ok=True)
        candidate.unlink(missing_ok=True)
        raise
    if manifest is not None:
        manifest.setdefault("pdf_exports", []).append(dict(file=candidate.name, created_at=now_iso(),
            order="reverse_capture" if reverse else "capture", evidence=vars(info),
            pages=image_pages, page_count=page - 1,
            sha256=hashlib.sha256(candidate.read_bytes()).hexdigest()))
        atomic_json(journal, manifest)
    return candidate
