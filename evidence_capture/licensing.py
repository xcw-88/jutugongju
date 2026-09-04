"""Offline, machine-bound licenses verified with an embedded RSA public key."""
from __future__ import annotations

import base64
import ctypes
import hashlib
import json
import os
import re
import uuid
from ctypes import wintypes
from datetime import date, timedelta
from pathlib import Path

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding

from .models import atomic_json, config_path

PRODUCT = "EvidenceCapture"
TOKEN_PREFIX = "EVC1"
PUBLIC_KEY_PEM = b"""-----BEGIN PUBLIC KEY-----
MIIBojANBgkqhkiG9w0BAQEFAAOCAY8AMIIBigKCAYEA0UYkQtu6p/kldS76IzbX
jF9POFwhhOvRP7ORTUEib6+eOLrlAcyXe0e7kLhQMGYqg6bsMBgsUFLr7sGYorB0
Igdo6bv6OXbhdmhYGKOB+S2FOG1l806JPd1/kwIaI0fSQUQdGd/wWXuqbVOMoyzz
Cpv73j9QRoDjwI+m/t2uwn02Ip2u/8jjoA7amIKYUW0Cl756l6r8yfUpQ0cWnyL2
VS3Jp2Be2a+h6vNQ7VD0ZiCTo1fzmOpjsBgyJZu7h9ZyHpDk52ihzu9R0B5nZt0y
ptdx//g2m8NnB7QOUpq+zonemoiz0SPPX9+C8LbyBlr1bAXgCKZUM/+hCn8wztrM
xNhiIm+qrYu8B4B4w09BAoBRAvjoPWRxXhz8uY899i9fxeh2d9GMGDuYjeihK0Lu
tiJW23TdhHheeA401Fs5VVglcFkSWMPaTTcXg8PisSCethkgi/ncWbTO8Hp6f8bg
t/Vjt2kkATGgZ8Z3ZfLxHrUbHTdSs231hJzGb1gPl2z3AgMBAAE=
-----END PUBLIC KEY-----
"""
MACHINE_RE = re.compile(r"^[A-F0-9]{8}(?:-[A-F0-9]{8}){3}$")


class LicenseError(ValueError):
    pass


def _b64encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _b64decode(value: str) -> bytes:
    try:
        return base64.b64decode(value + "=" * (-len(value) % 4), altchars=b"-_", validate=True)
    except (ValueError, TypeError) as exc:
        raise LicenseError("授权码格式不正确") from exc


def _canonical(payload: dict) -> bytes:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":")).encode("utf-8")


def _machine_source() -> str:
    if os.name != "nt":
        return f"non-windows|{uuid.getnode()}"
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                            r"SOFTWARE\Microsoft\Cryptography") as key:
            machine_guid = str(winreg.QueryValueEx(key, "MachineGuid")[0])
    except OSError as exc:
        raise LicenseError("无法读取 Windows 设备标识，请使用普通用户权限重试") from exc
    root = (os.environ.get("SystemDrive") or "C:") + "\\"
    serial = wintypes.DWORD()
    ctypes.windll.kernel32.GetVolumeInformationW(
        root, None, 0, ctypes.byref(serial), None, None, None, 0)
    return f"{machine_guid}|{serial.value}|{os.environ.get('PROCESSOR_ARCHITECTURE', '')}"


def machine_code(source: str | None = None) -> str:
    digest = hashlib.sha256(("EvidenceCapture-machine-v1|" +
                             (source if source is not None else _machine_source())).encode("utf-8")).hexdigest()
    value = digest[:32].upper()
    return "-".join(value[i:i + 8] for i in range(0, 32, 8))


def normalize_machine_code(value: str) -> str:
    compact = re.sub(r"[^A-Fa-f0-9]", "", value).upper()
    if len(compact) != 32:
        raise LicenseError("机器码应为 32 位十六进制字符")
    result = "-".join(compact[i:i + 8] for i in range(0, 32, 8))
    if not MACHINE_RE.fullmatch(result):
        raise LicenseError("机器码格式不正确")
    return result


def issue_license(private_key_pem: bytes, customer: str, machine: str,
                  expires_on: date | None = None, issued_on: date | None = None) -> str:
    customer = customer.strip()
    if not customer or len(customer) > 100:
        raise LicenseError("授权对象应为 1 至 100 个字符")
    machine = normalize_machine_code(machine)
    issued_on = issued_on or date.today()
    if expires_on is not None and expires_on < issued_on:
        raise LicenseError("到期日期不能早于签发日期")
    payload = {
        "version": 1,
        "product": PRODUCT,
        "license_id": str(uuid.uuid4()),
        "customer": customer,
        "machine_code": machine,
        "issued_on": issued_on.isoformat(),
        "expires_on": expires_on.isoformat() if expires_on else None,
    }
    try:
        key = serialization.load_pem_private_key(private_key_pem, password=None)
        signature = key.sign(_canonical(payload), padding.PSS(
            mgf=padding.MGF1(hashes.SHA256()), salt_length=padding.PSS.DIGEST_LENGTH),
            hashes.SHA256())
    except (ValueError, TypeError) as exc:
        raise LicenseError("授权私钥无效") from exc
    return f"{TOKEN_PREFIX}.{_b64encode(_canonical(payload))}.{_b64encode(signature)}"


def verify_license(token: str, expected_machine: str | None = None,
                   today: date | None = None) -> dict:
    parts = "".join(token.split()).split(".")
    if len(parts) != 3 or parts[0] != TOKEN_PREFIX:
        raise LicenseError("授权码格式不正确")
    raw_payload, signature = _b64decode(parts[1]), _b64decode(parts[2])
    try:
        payload = json.loads(raw_payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise LicenseError("授权内容损坏") from exc
    if not isinstance(payload, dict) or _canonical(payload) != raw_payload:
        raise LicenseError("授权内容格式不正确")
    try:
        public_key = serialization.load_pem_public_key(PUBLIC_KEY_PEM)
        public_key.verify(signature, raw_payload, padding.PSS(
            mgf=padding.MGF1(hashes.SHA256()), salt_length=padding.PSS.DIGEST_LENGTH),
            hashes.SHA256())
    except InvalidSignature as exc:
        raise LicenseError("授权签名无效，内容可能已被修改") from exc
    except (ValueError, TypeError) as exc:
        raise LicenseError("授权内容无法验证") from exc
    required = {"version", "product", "license_id", "customer", "machine_code",
                "issued_on", "expires_on"}
    if set(payload) != required or payload["version"] != 1 or payload["product"] != PRODUCT:
        raise LicenseError("授权版本或产品不匹配")
    if not isinstance(payload["customer"], str) or not payload["customer"] or len(payload["customer"]) > 100:
        raise LicenseError("授权对象无效")
    try:
        uuid.UUID(payload["license_id"])
        issued = date.fromisoformat(payload["issued_on"])
        expires = date.fromisoformat(payload["expires_on"]) if payload["expires_on"] else None
    except (ValueError, TypeError) as exc:
        raise LicenseError("授权日期或编号无效") from exc
    current = today or date.today()
    if issued > current + timedelta(days=1):
        raise LicenseError("系统日期早于授权签发日期，请校准 Windows 日期")
    if expires is not None and current > expires:
        raise LicenseError(f"授权已于 {expires.isoformat()} 到期")
    expected = normalize_machine_code(expected_machine or machine_code())
    if payload["machine_code"] != expected:
        raise LicenseError("授权不适用于这台电脑")
    return payload


def license_path() -> Path:
    return config_path().parent / "license.json"


def state_path() -> Path:
    return config_path().parent / "license_state.bin"


class _Blob(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_byte))]


def _crypt(value: bytes, protect: bool) -> bytes:
    if os.name != "nt":
        return value
    buffer = ctypes.create_string_buffer(value)
    incoming = _Blob(len(value), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_byte)))
    outgoing = _Blob()
    crypt32 = ctypes.windll.crypt32
    function = crypt32.CryptProtectData if protect else crypt32.CryptUnprotectData
    if protect:
        ok = function(ctypes.byref(incoming), "EvidenceCapture license state", None,
                      None, None, 1, ctypes.byref(outgoing))
    else:
        ok = function(ctypes.byref(incoming), None, None, None, None, 1,
                      ctypes.byref(outgoing))
    if not ok:
        raise OSError("Windows DPAPI 授权状态保护失败")
    try:
        return ctypes.string_at(outgoing.pbData, outgoing.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(outgoing.pbData)


def _check_and_record_clock(payload: dict, today: date | None = None):
    current = today or date.today()
    path = state_path()
    try:
        state = json.loads(_crypt(path.read_bytes(), False).decode("utf-8"))
        if state.get("license_id") == payload["license_id"]:
            last_seen = date.fromisoformat(state["last_seen"])
            if current + timedelta(days=1) < last_seen:
                raise LicenseError("检测到系统日期回拨，请校准 Windows 日期")
    except FileNotFoundError:
        pass
    except LicenseError:
        raise
    except (OSError, ValueError, KeyError, UnicodeDecodeError, json.JSONDecodeError):
        # Corrupt or foreign-user state cannot grant access; reset from the
        # independently signed license and current date.
        pass
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = json.dumps({"license_id": payload["license_id"],
                      "last_seen": current.isoformat()}, separators=(",", ":")).encode()
    temporary = path.with_suffix(".tmp")
    temporary.write_bytes(_crypt(raw, True))
    os.replace(temporary, path)


def validate_installed_license(today: date | None = None, record_clock: bool = True) -> dict:
    try:
        data = json.loads(license_path().read_text(encoding="utf-8"))
        token = data["token"]
    except FileNotFoundError as exc:
        raise LicenseError("本机尚未激活") from exc
    except (OSError, KeyError, TypeError, json.JSONDecodeError) as exc:
        raise LicenseError("本机授权文件损坏") from exc
    payload = verify_license(token, today=today)
    if record_clock:
        _check_and_record_clock(payload, today)
    return payload


def install_license(token: str) -> dict:
    payload = verify_license(token)
    atomic_json(license_path(), {"token": "".join(token.split())})
    _check_and_record_clock(payload)
    return payload


def license_summary(payload: dict) -> str:
    expiry = payload["expires_on"] or "永久"
    return (f"授权对象：{payload['customer']}\n有效期至：{expiry}\n"
            f"授权编号：{payload['license_id']}\n机器码：{payload['machine_code']}")
