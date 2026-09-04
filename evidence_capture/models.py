from __future__ import annotations
import json
import os
import re
import sys
import tempfile
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path


@dataclass(frozen=True)
class Region:
    left: int
    top: int
    width: int
    height: int

    def __post_init__(self):
        if any(type(v) is not int for v in asdict(self).values()):
            raise ValueError("区域坐标必须为整数")
        if not (30 <= self.width <= 16384 and 30 <= self.height <= 16384):
            raise ValueError("请框选至少 30 × 30 像素的区域")

    @property
    def center(self):
        return self.left + self.width // 2, self.top + self.height // 2

    def inside(self, monitor: dict) -> bool:
        return (monitor["left"] <= self.left and monitor["top"] <= self.top
                and self.left + self.width <= monitor["left"] + monitor["width"]
                and self.top + self.height <= monitor["top"] + monitor["height"])


@dataclass(frozen=True)
class CaptureOptions:
    wait_seconds: float = 3.0
    scroll_clicks: int = 3
    count: int = 20
    start_delay: int = 5
    direction: str = "up"
    stop_on_unchanged: bool = True

    def __post_init__(self):
        if self.direction not in ("up", "down"):
            raise ValueError("滚动方向必须为向上或向下")
        if type(self.stop_on_unchanged) is not bool:
            raise ValueError("自动结束选项必须为开或关")
        if not (0.5 <= self.wait_seconds <= 120):
            raise ValueError("加载等待时间应为 0.5 至 120 秒")
        if not (1 <= self.scroll_clicks <= 20 and 1 <= self.count <= 9999):
            raise ValueError("滚轮幅度应为 1 至 20 格，截图数量为 1 至 9999 张")
        if not (3 <= self.start_delay <= 30):
            raise ValueError("开始倒计时应为 3 至 30 秒")


@dataclass(frozen=True)
class EvidenceInfo:
    name: str
    subject: str = ""
    identity: str = ""
    time_range: str = ""
    purpose: str = ""
    material_title: str = "项目工作沟通记录"

    def validate(self):
        if not self.name.strip():
            raise ValueError("请填写证据名称")
        for key, value in asdict(self).items():
            if len(value) > (3000 if key == "purpose" else 160):
                raise ValueError("证据名称和说明字段过长，请精简后重试")


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def safe_name(value: str) -> str:
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", value).strip(" .")[:64].rstrip(" .")
    if not name:
        name = "未命名证据"
    if re.match(r"^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\.|$)", name, re.I):
        name = "_" + name
    return name


def atomic_json(path: Path, data: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(prefix="." + path.name, suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(data, stream, ensure_ascii=False, indent=2)
        os.replace(temp, path)
    finally:
        Path(temp).unlink(missing_ok=True)


def create_session(root: Path, name: str) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    base = safe_name(name)
    for number in range(10000):
        folder = root / (base + ("" if number == 0 else f"_{number + 1:02d}"))
        try:
            folder.mkdir()
            return folder
        except FileExistsError:
            continue
    raise OSError("同名证据目录过多，请换一个证据名称")


def config_path() -> Path:
    return Path(os.environ.get("LOCALAPPDATA", Path.home())) / "EvidenceCapture" / "config.json"


def default_output() -> Path:
    base = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent.parent
    return base / "output"


def load_config() -> tuple[dict, str]:
    try:
        value = json.loads(config_path().read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise ValueError("配置内容应为 JSON 对象")
        return value, ""
    except FileNotFoundError:
        return {}, ""
    except (OSError, ValueError) as exc:
        return {}, f"配置读取失败，已使用默认设置：{exc}"
