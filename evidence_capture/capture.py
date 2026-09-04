from __future__ import annotations
import hashlib
import os
import threading
import time
from dataclasses import asdict
from pathlib import Path
from PIL import Image
from . import __version__
from .models import CaptureOptions, EvidenceInfo, Region, atomic_json, now_iso
from .native import WindowGuard, escape_pressed


class CaptureCancelled(Exception):
    pass


class DesktopBackend:
    def __enter__(self):
        import mss
        import pyautogui
        self.mouse = pyautogui
        self.mouse.FAILSAFE = True
        # Separate wheel detents so clients can process each input/animation.
        self.mouse.PAUSE = 0.12
        self.sct = mss.mss()
        return self

    def __exit__(self, *args):
        self.sct.close()

    def prepare(self, region):
        self.guard = WindowGuard(region)

    def check(self):
        self.guard.check()

    def grab(self, region):
        shot = self.sct.grab(asdict(region))
        return Image.frombytes("RGB", shot.size, shot.rgb)

    def scroll(self, region, clicks, direction, check_stop=lambda: None):
        # Never click: do not activate links or send a message.
        # PyAutoGUI 0.9.54 on Windows passes raw wheel delta to mouse_event,
        # and the x/y arguments do not move the cursor for MOUSEEVENTF_WHEEL.
        check_stop()
        self.mouse.moveTo(*region.center)
        delta = 120 * (1 if direction == "up" else -1)
        # Some chat clients treat a single large delta as only one scroll step.
        # Emit one Windows detent per event, with PyAutoGUI's PAUSE between them.
        for _ in range(clicks):
            check_stop()
            self.guard.check()
            self.mouse.scroll(delta)


def run_capture(folder: Path, info: EvidenceInfo, region: Region,
                options: CaptureOptions, stop: threading.Event,
                status=lambda message: None, progress=lambda record: None,
                backend_factory=DesktopBackend, key_stop=escape_pressed) -> dict:
    """Persist every unedited frame and journal it before continuing to scroll."""
    info.validate()
    manifest = dict(schema_version=1, app_version=__version__, started_at=now_iso(),
                    status="running", evidence=asdict(info), region=asdict(region),
                    options=asdict(options), capture_direction=options.direction, images=[],
                    pdf_exports=[], warnings=[])
    journal = folder / "manifest.json"
    atomic_json(journal, manifest)

    def check_stop():
        if stop.is_set() or key_stop():
            raise CaptureCancelled("用户停止采集")

    def wait(seconds, label):
        end = time.monotonic() + seconds
        last = -1
        while True:
            check_stop()
            remaining = end - time.monotonic()
            if remaining <= 0:
                break
            rounded = int(remaining) + 1
            if rounded != last:
                status(f"{label} · {rounded} 秒（Esc 停止）")
                last = rounded
            stop.wait(min(0.05, remaining))

    try:
        wait(options.start_delay, "请切换到微信或钉钉，并保持聊天窗口在前台")
        with backend_factory() as backend:
            check_stop()
            backend.prepare(region)
            previous_hash = None
            unchanged_count = 0
            for index in range(1, options.count + 1):
                wait(options.wait_seconds, f"等待图片加载，准备第 {index}/{options.count} 张")
                check_stop()
                backend.check()
                path = folder / f"{index:03d}.png"
                if path.exists():
                    raise FileExistsError(f"拒绝覆盖已有原图：{path.name}")
                shot = backend.grab(region)
                try:
                    temp = path.with_suffix(".png.tmp")
                    shot.save(temp, format="PNG")
                    os.replace(temp, path)
                    width, height = shot.size
                finally:
                    shot.close()
                digest = hashlib.sha256(path.read_bytes()).hexdigest()
                record = dict(index=index, file=path.name, captured_at=now_iso(),
                              width=width, height=height, sha256=digest,
                              same_as_previous=digest == previous_hash)
                manifest["images"].append(record)
                unchanged_count = unchanged_count + 1 if record["same_as_previous"] else 0
                if digest == previous_hash:
                    boundary = "顶部" if options.direction == "up" else "底部"
                    warning = f"第 {index:03d} 张与上一张完全相同，已保留；请检查是否到达{boundary}或未滚动"
                    manifest["warnings"].append(warning)
                    status(warning)
                previous_hash = digest
                atomic_json(journal, manifest)
                progress(record)
                if options.stop_on_unchanged and unchanged_count >= 2:
                    # Two separate scroll/load attempts produced no change. This
                    # can mean the boundary OR failed scrolling, never claim proof
                    # that all chat history has been captured. Keep every frame.
                    manifest["end_reason"] = "unchanged"
                    manifest["message"] = "滚动后画面连续两次未变化，已自动结束；请检查是否到达边界或未能滚动"
                    status(manifest["message"])
                    break
                if index < options.count:
                    check_stop()
                    backend.check()
                    backend.scroll(region, options.scroll_clicks, options.direction,
                                   check_stop=check_stop)
            manifest["status"] = "completed"
            manifest.setdefault("end_reason", "count_limit")
    except CaptureCancelled as exc:
        manifest["status"] = "stopped"
        manifest["message"] = str(exc)
    except Exception as exc:
        manifest["status"] = "error"
        manifest["message"] = f"{type(exc).__name__}: {exc}"
    finally:
        manifest["finished_at"] = now_iso()
        atomic_json(journal, manifest)
    return manifest
