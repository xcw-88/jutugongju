import base64
import json
from datetime import date

import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives import serialization

from evidence_capture import licensing


_TEST_PRIVATE_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
_TEST_PRIVATE_PEM = _TEST_PRIVATE_KEY.private_bytes(
    serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
    serialization.NoEncryption())
_TEST_PUBLIC_PEM = _TEST_PRIVATE_KEY.public_key().public_bytes(
    serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)


@pytest.fixture(autouse=True)
def test_signing_key(monkeypatch):
    # Tests use an ephemeral key generated in memory. The production signing
    # key remains outside Git and is never required to run the test suite.
    monkeypatch.setattr(licensing, 'PUBLIC_KEY_PEM', _TEST_PUBLIC_PEM)


@pytest.fixture
def private_key():
    return _TEST_PRIVATE_PEM


@pytest.fixture
def test_machine():
    return licensing.machine_code('test-computer')


def test_machine_code_is_stable_and_normalized(test_machine):
    assert test_machine == licensing.machine_code('test-computer')
    assert licensing.normalize_machine_code(test_machine.lower().replace('-', ' ')) == test_machine
    assert len(test_machine) == 35


def test_signed_perpetual_license(private_key, test_machine):
    token = licensing.issue_license(private_key, '授权测试对象', test_machine,
                                    issued_on=date(2026, 9, 4))
    payload = licensing.verify_license(token, test_machine, date(2036, 1, 1))
    assert payload['customer'] == '授权测试对象'
    assert payload['expires_on'] is None


def test_expiring_license_is_valid_through_last_day(private_key, test_machine):
    token = licensing.issue_license(private_key, '期限测试', test_machine,
                                    expires_on=date(2026, 12, 31), issued_on=date(2026, 9, 4))
    assert licensing.verify_license(token, test_machine, date(2026, 12, 31))['expires_on'] == '2026-12-31'
    with pytest.raises(licensing.LicenseError, match='到期'):
        licensing.verify_license(token, test_machine, date(2027, 1, 1))


def test_license_rejects_other_machine(private_key, test_machine):
    token = licensing.issue_license(private_key, '机器绑定测试', test_machine,
                                    issued_on=date(2026, 9, 4))
    with pytest.raises(licensing.LicenseError, match='不适用于'):
        licensing.verify_license(token, licensing.machine_code('another-computer'), date(2026, 9, 4))


def test_modified_payload_fails_signature(private_key, test_machine):
    token = licensing.issue_license(private_key, '原授权对象', test_machine,
                                    issued_on=date(2026, 9, 4))
    prefix, encoded, signature = token.split('.')
    raw = base64.urlsafe_b64decode(encoded + '=' * (-len(encoded) % 4))
    payload = json.loads(raw)
    payload['customer'] = '被修改的对象'
    changed = base64.urlsafe_b64encode(licensing._canonical(payload)).rstrip(b'=').decode()
    with pytest.raises(licensing.LicenseError, match='签名无效'):
        licensing.verify_license(f'{prefix}.{changed}.{signature}', test_machine, date(2026, 9, 4))


@pytest.mark.parametrize('token', ['', 'fixed-password', 'EVC1.bad.bad', 'EVC2.a.b'])
def test_malformed_license_is_rejected(token, test_machine):
    with pytest.raises(licensing.LicenseError):
        licensing.verify_license(token, test_machine, date(2026, 9, 4))


def test_future_issued_license_detects_clock_problem(private_key, test_machine):
    token = licensing.issue_license(private_key, '日期测试', test_machine,
                                    issued_on=date(2026, 9, 10))
    with pytest.raises(licensing.LicenseError, match='系统日期'):
        licensing.verify_license(token, test_machine, date(2026, 9, 4))


def test_install_validate_and_clock_rollback(tmp_path, monkeypatch, private_key, test_machine):
    token = licensing.issue_license(private_key, '安装测试', test_machine,
                                    issued_on=date(2026, 9, 4))
    monkeypatch.setattr(licensing, 'license_path', lambda: tmp_path / 'license.json')
    monkeypatch.setattr(licensing, 'state_path', lambda: tmp_path / 'state.bin')
    monkeypatch.setattr(licensing, 'machine_code', lambda source=None: test_machine)
    monkeypatch.setattr(licensing, 'date', type('FixedDate', (date,), {
        'today': classmethod(lambda cls: cls(2026, 9, 4))
    }))
    installed = licensing.install_license(token)
    assert installed['customer'] == '安装测试'
    assert licensing.validate_installed_license(today=date(2026, 9, 8))['license_id'] == installed['license_id']
    with pytest.raises(licensing.LicenseError, match='日期回拨'):
        licensing.validate_installed_license(today=date(2026, 9, 4))
