"""Offscreen widget integration tests; never control or alter the user's desktop."""
import json
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import pytest
from PIL import Image
from PySide6.QtWidgets import QApplication
from evidence_capture import ui
from evidence_capture.models import atomic_json


@pytest.fixture(scope='module')
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def window(app, monkeypatch, tmp_path):
    monkeypatch.setattr(ui, 'load_config', lambda: ({}, ''))
    monkeypatch.setattr(ui, 'config_path', lambda: tmp_path / 'config.json')
    window = ui.MainWindow(auto_select=False)
    assert window.windowTitle() == '聊天软件截屏助手'
    yield window
    window.close()


def test_switch_direction_sets_default_order_and_persists(window, tmp_path):
    assert window.settings().direction == 'up' and window.order.currentIndex() == 0
    window.direction.setCurrentIndex(1)
    assert window.settings().direction == 'down' and window.order.currentIndex() == 1
    window.save_config()
    saved = json.loads((tmp_path / 'config.json').read_text(encoding='utf-8'))
    assert saved['options']['direction'] == 'down' and saved['reverse'] is False
    window.config = saved
    window.direction.setCurrentIndex(0)
    window.restore_config()
    assert window.direction.currentData() == 'down' and window.order.currentIndex() == 1
    window.order.setCurrentIndex(0)  # Manual override remains possible.
    window.save_config()
    assert json.loads((tmp_path / 'config.json').read_text(encoding='utf-8'))['reverse'] is True


@pytest.mark.parametrize('record,expected_direction,expected_order', [
    ({'capture_direction': 'down'}, 'down', 1),
    ({}, 'up', 0),  # Old V1 directories carry no direction when manually assembled.
    ({'capture_direction': 'down', 'pdf_exports': [{'order': 'reverse_capture'}]}, 'down', 0),
])
def test_reopen_session_uses_its_own_direction(window, monkeypatch, tmp_path,
                                            record, expected_direction, expected_order):
    session = tmp_path / 'evidence'
    session.mkdir()
    Image.new('RGB', (60, 80), 'white').save(session / '001.png')
    atomic_json(session / 'manifest.json', dict(evidence={'name': '测试'}, **record))
    monkeypatch.setattr(ui.QFileDialog, 'getExistingDirectory', lambda *args: str(session))
    window.direction.setCurrentIndex(0 if expected_direction == 'down' else 1)
    window.load_session()
    assert window.direction.currentData() == expected_direction
    assert window.order.currentIndex() == expected_order


def test_custom_title_and_auto_stop_settings_restore(window, tmp_path):
    window.fields['name'].setText('测试材料')
    window.fields['material_title'].setText('工资结算沟通记录')
    assert window.info().material_title == '工资结算沟通记录'
    assert window.settings().stop_on_unchanged is True
    window.stop_unchanged.setChecked(False)
    window.save_config()
    saved = json.loads((tmp_path / 'config.json').read_text(encoding='utf-8'))
    assert saved['material_title'] == '工资结算沟通记录'
    assert saved['options']['stop_on_unchanged'] is False
    window.config = saved
    window.fields['material_title'].clear()
    window.stop_unchanged.setChecked(True)
    window.restore_config()
    assert window.info().material_title == '工资结算沟通记录'
    assert window.settings().stop_on_unchanged is False


def test_reopen_restores_last_export_title(window, monkeypatch, tmp_path):
    session = tmp_path / 'evidence'
    session.mkdir()
    Image.new('RGB', (60, 80), 'white').save(session / '001.png')
    atomic_json(session / 'manifest.json', dict(evidence={'name': '旧采集'},
        pdf_exports=[{'order': 'capture', 'evidence': {'name': '新说明', 'material_title': '工资沟通'}}]))
    monkeypatch.setattr(ui.QFileDialog, 'getExistingDirectory', lambda *args: str(session))
    window.load_session()
    assert window.info().material_title == '工资沟通'
    assert window.info().name == '新说明'


def test_auto_boundary_finish_returns_to_ui_and_schedules_pdf(window, app, monkeypatch, tmp_path):
    from types import SimpleNamespace
    from evidence_capture.models import EvidenceInfo
    calls = []
    info = EvidenceInfo('自动保存测试')
    window.job = SimpleNamespace(deleteLater=lambda: None, error='', kind='capture',
        result=dict(status='completed', end_reason='unchanged', capture_direction='down',
                    images=[{}, {}, {}], warnings=['重复', '重复']))
    window.active_info = info
    window.auto_pdf_for_job = True
    window.reverse_for_job = False
    monkeypatch.setattr(window, 'restore_window', lambda: calls.append('restored'))
    monkeypatch.setattr(window, 'generate_pdf', lambda info, reverse: calls.append(('pdf', info, reverse)))
    window.job_finished()
    app.processEvents()
    assert window.job is None and window.start_button.isEnabled()
    assert calls == ['restored', ('pdf', info, False)]
    assert '自动结束并保存' in window.status_label.text()
