import hashlib
import json
import threading
from pathlib import Path
import pytest
from PIL import Image
from pypdf import PdfReader
from evidence_capture.models import Region, CaptureOptions, EvidenceInfo, create_session, safe_name, atomic_json
from evidence_capture.capture import run_capture
from evidence_capture.pdf_export import export_pdf


class Clock:
    def __init__(self):
        self.value = 0
        self.stopped = False

    def is_set(self):
        return self.stopped

    def set(self):
        self.stopped = True

    def wait(self, seconds):
        self.value += seconds


@pytest.fixture
def clock(monkeypatch):
    clock = Clock()
    monkeypatch.setattr('evidence_capture.capture.time.monotonic', lambda: clock.value)
    return clock


class Backend:
    def __init__(self, clock, fail_scroll=False):
        self.clock, self.fail_scroll = clock, fail_scroll
        self.events = []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.events.append(('close', self.clock.value))

    def prepare(self, region):
        self.events.append(('prepare', self.clock.value))

    def check(self):
        pass

    def grab(self, region):
        self.events.append(('grab', self.clock.value))
        return Image.new('RGB', (region.width, region.height), '#347586')

    def scroll(self, region, clicks, direction, check_stop=lambda: None):
        check_stop()
        self.events.append(('scroll', self.clock.value, clicks, direction))
        if self.fail_scroll:
            raise RuntimeError('simulated scroll failure')


def capture(tmp_path, clock, backend=None, progress=lambda record: None):
    backend = backend or Backend(clock)
    result = run_capture(tmp_path, EvidenceInfo('测试材料'), Region(-100, 30, 80, 90),
                         CaptureOptions(wait_seconds=3, count=3, start_delay=5), clock,
                         progress=progress, backend_factory=lambda: backend, key_stop=lambda: False)
    return result, backend


def test_load_wait_order_and_no_final_scroll(tmp_path, clock):
    result, backend = capture(tmp_path, clock)
    assert result['status'] == 'completed'
    shots = [e for e in backend.events if e[0] == 'grab']
    scrolls = [e for e in backend.events if e[0] == 'scroll']
    assert shots[0][1] >= 8
    assert len(shots) == 3 and len(scrolls) == 2
    assert all(shots[i + 1][1] - scrolls[i][1] >= 2.999 for i in range(2))
    assert [p.name for p in sorted(tmp_path.glob('*.png'))] == ['001.png', '002.png', '003.png']
    assert len(result['warnings']) == 2  # Exact repeats are preserved, never discarded.
    saved = json.loads((tmp_path / 'manifest.json').read_text(encoding='utf-8'))
    for record in saved['images']:
        assert record['sha256'] == hashlib.sha256((tmp_path / record['file']).read_bytes()).hexdigest()


def test_cancel_retains_last_frame_without_extra_scroll(tmp_path, clock):
    result, backend = capture(tmp_path, clock, progress=lambda record: clock.set())
    assert result['status'] == 'stopped'
    assert len(result['images']) == 1
    assert not any(e[0] == 'scroll' for e in backend.events)
    assert (tmp_path / '001.png').is_file()


def test_cancel_before_capture_does_not_touch_desktop(tmp_path, clock):
    clock.set()
    result, backend = capture(tmp_path, clock)
    assert result['status'] == 'stopped'
    assert not backend.events
    assert not result['images']


def test_scroll_error_preserves_partial_evidence(tmp_path, clock):
    result, backend = capture(tmp_path, clock, Backend(clock, fail_scroll=True))
    assert result['status'] == 'error'
    assert len(result['images']) == 1
    assert 'simulated scroll failure' in result['message']
    assert backend.events[-1][0] == 'close'


def test_existing_original_is_not_overwritten(tmp_path, clock):
    (tmp_path / '001.png').write_bytes(b'original')
    result, _ = capture(tmp_path, clock)
    assert result['status'] == 'error'
    assert (tmp_path / '001.png').read_bytes() == b'original'


@pytest.mark.parametrize('direction,delta', [('up', 120), ('down', -120)])
def test_windows_wheel_moves_cursor_and_uses_full_detents(direction, delta):
    from types import SimpleNamespace
    from evidence_capture.capture import DesktopBackend
    events = []
    desktop = DesktopBackend()
    desktop.mouse = SimpleNamespace(
        moveTo=lambda x, y: events.append(('move', x, y)),
        scroll=lambda delta: events.append(('wheel', delta)))
    desktop.guard = SimpleNamespace(check=lambda: events.append(('guard',)))
    desktop.scroll(Region(-800, 100, 600, 800), 3, direction)
    assert events == [('move', -500, 500)] + [('guard',), ('wheel', delta)] * 3


def test_stop_between_detents_preserves_capture(tmp_path, clock):
    from types import SimpleNamespace
    from evidence_capture.capture import DesktopBackend

    class StopDuringScroll(Backend):
        scroll = DesktopBackend.scroll

        def __init__(self, clock):
            super().__init__(clock)
            self.mouse = SimpleNamespace(moveTo=lambda *args: None, scroll=self.wheel)
            self.guard = SimpleNamespace(check=lambda: None)

        def wheel(self, delta):
            self.events.append(('wheel', delta))
            self.clock.set()

    backend = StopDuringScroll(clock)
    result, _ = capture(tmp_path, clock, backend)
    assert result['status'] == 'stopped'
    assert len(result['images']) == 1 and (tmp_path / '001.png').is_file()
    assert [e for e in backend.events if e[0] == 'wheel'] == [('wheel', 120)]
    assert backend.events[-1][0] == 'close'


def test_focus_loss_between_detents_prevents_more_input():
    from types import SimpleNamespace
    from evidence_capture.capture import DesktopBackend
    emitted = []

    def guard():
        if emitted:
            raise RuntimeError('目标窗口失去焦点')

    backend = DesktopBackend()
    backend.mouse = SimpleNamespace(moveTo=lambda *args: None, scroll=emitted.append)
    backend.guard = SimpleNamespace(check=guard)
    with pytest.raises(RuntimeError, match='失去焦点'):
        backend.scroll(Region(0, 0, 500, 800), 6, 'down')
    assert emitted == [-120]


def test_downward_capture_records_direction_and_waits(tmp_path, clock):
    backend = Backend(clock)
    result = run_capture(tmp_path, EvidenceInfo('向下测试'), Region(10, 10, 80, 90),
                         CaptureOptions(count=3, direction='down'), clock,
                         backend_factory=lambda: backend, key_stop=lambda: False)
    assert result['status'] == 'completed'
    assert result['capture_direction'] == result['options']['direction'] == 'down'
    scrolls = [e for e in backend.events if e[0] == 'scroll']
    shots = [e for e in backend.events if e[0] == 'grab']
    assert len(scrolls) == 2 and all(e[3] == 'down' for e in scrolls)
    assert len(shots) == 3
    assert all(shots[i + 1][1] - scrolls[i][1] >= 2.999 for i in range(2))
    assert all('底部' in warning for warning in result['warnings'])


def test_old_settings_default_upward_and_reject_invalid_direction():
    assert CaptureOptions(**{'count': 3}).direction == 'up'
    with pytest.raises(ValueError, match='方向'):
        CaptureOptions(direction='sideways')


def test_session_names_cannot_escape_output(tmp_path):
    for name in ['../陈庆<>', 'CON', 'NUL.txt', '..', '叶亚运/吴森', '监理']:
        first = create_session(tmp_path, name)
        second = create_session(tmp_path, name)
        assert first.parent == tmp_path and second.parent == tmp_path
        assert first != second
        assert first.exists() and second.exists()
    assert safe_name('CON').startswith('_')


def test_pdf_a4_chinese_order_and_lossless_pixels(tmp_path, clock):
    class ColoredBackend(Backend):
        def grab(self, region):
            frame = super().grab(region)
            frame.paste((len(self.events) * 20, 80, 90), (0, 0, frame.width, frame.height))
            return frame
    result, _ = capture(tmp_path, clock, ColoredBackend(clock))
    info = EvidenceInfo('排版测试', '陈庆、叶亚运、吴森、监理', '测试身份', '测试时间范围', '排版验证，不作为真实证据。')
    path = export_pdf(tmp_path, info, reverse=True)
    reader = PdfReader(path)
    assert reader.metadata.author == '聊天软件截屏助手'
    assert len(reader.pages) == 4
    cover = reader.pages[0].extract_text()
    assert '证据材料' in cover and '项目工作沟通记录' in cover
    assert '陈庆' in cover and '证明目的' in cover
    assert all(page.extract_text().strip() == '项目工作沟通记录' for page in reader.pages[1:])
    assert '原图' not in cover and '第 1 页' not in cover
    for page in reader.pages:
        assert abs(float(page.mediabox.width) - 595.276) < 0.01
        assert abs(float(page.mediabox.height) - 841.89) < 0.01
    for number, page in zip([3, 2, 1], reader.pages[1:]):
        with Image.open(tmp_path / f'{number:03d}.png') as original:
            embedded = page.images[0].image.convert('RGB')
            assert embedded.size == original.size
            assert embedded.tobytes() == original.tobytes()
    previous = path.read_bytes()
    second = export_pdf(tmp_path, info, reverse=False)
    assert path != second and path.read_bytes() == previous
    with Image.open(tmp_path / '001.png') as original:
        assert PdfReader(second).pages[1].images[0].image.convert('RGB').tobytes() == original.tobytes()


def test_pdf_refuses_changed_or_missing_original(tmp_path, clock):
    capture(tmp_path, clock)
    Image.new('RGB', (80, 90), 'red').save(tmp_path / '001.png')
    with pytest.raises(ValueError, match='已变更'):
        export_pdf(tmp_path, EvidenceInfo('测试'))
    (tmp_path / '001.png').unlink()
    with pytest.raises(ValueError, match='不一致'):
        export_pdf(tmp_path, EvidenceInfo('测试'))
    assert not list(tmp_path.glob('*.pdf'))


def test_long_cover_flows_without_losing_text(tmp_path):
    Image.new('RGB', (600, 1800), 'white').save(tmp_path / '001.png')
    purpose = ('这是用于验证跨页排版的完整说明。' * 160) + '说明最后一行必须保留。'
    path = export_pdf(tmp_path, EvidenceInfo('长说明 <&> 测试', purpose=purpose))
    reader = PdfReader(path)
    assert len(reader.pages) > 3
    text = ''.join(p.extract_text() for p in reader.pages)
    assert '说明最后一行必须保留。' in text
    assert '长说明 <&> 测试' in text
    assert reader.pages[-1].extract_text().strip() == '项目工作沟通记录'
    assert len(reader.pages[-1].images) == 1


@pytest.mark.parametrize('title', ['工资结算沟通记录', '工资结算与工作安排记录' * 10, ''])
def test_custom_title_and_no_filename_or_page_numbers(tmp_path, title):
    import re
    Image.new('RGB', (800, 1200), 'white').save(tmp_path / '001.png')
    path = export_pdf(tmp_path, EvidenceInfo('标题测试', material_title=title))
    reader = PdfReader(path)
    texts = [p.extract_text() for p in reader.pages]
    assert len(reader.pages) == 2
    assert all('001.png' not in text and '原图' not in text for text in texts)
    assert all(not re.search(r'第\s*\d+\s*页', text) for text in texts)
    assert all('项目工作沟通记录' not in text for text in texts)
    if title:
        # PDF extraction may insert spaces for centered, wrapped CJK lines.
        assert all(title in re.sub(r'\s+', '', text) for text in texts)
        assert safe_name(title) in path.name
        assert title in reader.metadata.title
    else:
        assert texts[-1].strip() == ''
        assert path.name == '标题测试.pdf'


@pytest.mark.parametrize('direction', ['up', 'down'])
def test_unchanged_frames_end_capture_and_preserve_all_files(tmp_path, clock, direction):
    backend = Backend(clock)
    result = run_capture(tmp_path, EvidenceInfo('边界测试'), Region(0, 0, 80, 90),
                         CaptureOptions(count=20, direction=direction), clock,
                         backend_factory=lambda: backend, key_stop=lambda: False)
    assert result['status'] == 'completed' and result['end_reason'] == 'unchanged'
    assert len(result['images']) == 3
    assert len(list(tmp_path.glob('*.png'))) == 3
    assert len([e for e in backend.events if e[0] == 'scroll']) == 2
    assert backend.events[-1][0] == 'close'
    assert json.loads((tmp_path / 'manifest.json').read_text(encoding='utf-8'))['end_reason'] == 'unchanged'


def test_unchanged_counter_resets_after_movement(tmp_path, clock):
    class SequenceBackend(Backend):
        def __init__(self, clock):
            super().__init__(clock)
            self.colors = iter(['red', 'red', 'blue', 'blue', 'green', 'green', 'green'])
        def grab(self, region):
            frame = super().grab(region)
            frame.paste(next(self.colors), (0, 0, frame.width, frame.height))
            return frame
    backend = SequenceBackend(clock)
    result = run_capture(tmp_path, EvidenceInfo('加载变化测试'), Region(0, 0, 80, 90),
                         CaptureOptions(count=20), clock,
                         backend_factory=lambda: backend, key_stop=lambda: False)
    assert result['status'] == 'completed' and result['end_reason'] == 'unchanged'
    assert len(result['images']) == 7


def test_unchanged_stop_can_be_disabled(tmp_path, clock):
    backend = Backend(clock)
    result = run_capture(tmp_path, EvidenceInfo('关闭自动结束'), Region(0, 0, 80, 90),
                         CaptureOptions(count=5, stop_on_unchanged=False), clock,
                         backend_factory=lambda: backend, key_stop=lambda: False)
    assert result['status'] == 'completed' and result['end_reason'] == 'count_limit'
    assert len(result['images']) == 5


def test_invalid_region_and_empty_export(tmp_path):
    with pytest.raises(ValueError):
        Region(0, 0, 0, 30)
    with pytest.raises(ValueError):
        Region(0, 0, 30.0, 30)
    with pytest.raises(ValueError, match='没有'):
        export_pdf(tmp_path, EvidenceInfo('测试'))


@pytest.mark.parametrize('scale', [1, 1.25, 1.5, 2])
def test_high_dpi_negative_monitor_coordinates(scale):
    from PySide6.QtCore import QPoint
    from evidence_capture.selector import region_from_drag
    monitor = dict(left=-1920, top=-200, width=1920, height=1080)
    r = region_from_drag(QPoint(200, 300), QPoint(100, 100), 1920 / scale, 1080 / scale, monitor)
    assert r.left == -1920 + round(100 * scale)
    assert r.top == -200 + round(100 * scale)
    assert r.width == round(100 * scale) and r.height == round(200 * scale)
