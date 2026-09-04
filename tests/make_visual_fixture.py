"""Build clearly marked synthetic data for local visual QA only."""
from pathlib import Path
import hashlib
from PIL import Image, ImageDraw, ImageFont
from evidence_capture.models import EvidenceInfo, atomic_json
from evidence_capture.pdf_export import export_pdf

root = Path(__file__).resolve().parent.parent
folder = root / 'tmp' / 'qa' / '排版测试_模拟聊天'
folder.mkdir(parents=True, exist_ok=True)
font_path = 'C:/Windows/Fonts/msyh.ttc'
font = ImageFont.truetype(font_path, 22)
small = ImageFont.truetype(font_path, 17)
records = []
for index in range(1, 4):
    image = Image.new('RGB', (960, 1200), '#f5f7f9')
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, 960, 84), fill='white')
    draw.text((30, 25), '模拟聊天 / 仅用于软件排版测试', font=font, fill='#203044')
    draw.text((335, 114), f'测试画面 {index:03d} · 非真实证据', font=small, fill='#64748b')
    for row in range(6):
        y = 180 + row * 144
        right = row % 2
        left = 220 if right else 72
        draw.rounded_rectangle((left, y, left + 600, y + 100), radius=12,
                               fill='#d9ecff' if right else 'white')
        draw.text((left + 20, y + 15), f'第 {index}-{row + 1} 条模拟内容：检查中文与上下文。', font=font, fill='#203044')
        draw.text((left + 20, y + 54), '相邻截图需保留重叠，图片需等待加载。', font=small, fill='#475569')
    draw.text((35, 1120), '保留原始像素 · 打印前请预览并试印一页', font=small, fill='#64748b')
    path = folder / f'{index:03d}.png'
    image.save(path)
    records.append(dict(file=path.name, sha256=hashlib.sha256(path.read_bytes()).hexdigest()))
info = EvidenceInfo('排版测试（模拟材料）', '测试对象', '测试身份', '测试时间范围',
                    '本材料仅用于验证中文封面、截图页序、原始像素嵌入与 A4 竖版排版。\n不包含真实聊天内容。')
atomic_json(folder / 'manifest.json', dict(images=records, evidence=vars(info), pdf_exports=[]))
print(export_pdf(folder, info))
icon = Image.new('RGBA', (256, 256))
draw = ImageDraw.Draw(icon)
draw.rounded_rectangle((4, 4, 252, 252), radius=55, fill='#205e9f')
draw.rounded_rectangle((70, 43, 186, 211), radius=10, fill='white')
for y in (88, 123, 158):
    draw.rounded_rectangle((91, y, 162, y + 9), radius=3, fill='#205e9f')
icon.save(root / 'assets' / 'app.ico', sizes=[(16,16), (32,32), (48,48), (64,64), (128,128), (256,256)])
