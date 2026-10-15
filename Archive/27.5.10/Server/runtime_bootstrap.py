from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent
RUNTIME_ROOT = Path(os.environ.get("LOCALAPPDATA") or (Path.home() / ".local")) / "POSProfessionalRuntime"
VENV_DIR = RUNTIME_ROOT / ".venv"
VENV_BIN_DIR = VENV_DIR / ("Scripts" if os.name == "nt" else "bin")
VENV_PY = VENV_BIN_DIR / ("python.exe" if os.name == "nt" else "python")
VENV_CFG = VENV_DIR / "pyvenv.cfg"
REQUIREMENTS = APP_DIR / "requirements.txt"
STATE_FILE = RUNTIME_ROOT / "runtime_state.json"
BOOTSTRAPPED_ENV = "POS_RUNTIME_BOOTSTRAPPED"


def _log(msg: str) -> None:
    print(f"[POS RUNTIME] {msg}", flush=True)


def _load_state() -> dict:
    try:
        if STATE_FILE.is_file():
            data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
    except Exception:
        pass
    return {"components": {}}


def _save_state(state: dict) -> None:
    RUNTIME_ROOT.mkdir(parents=True, exist_ok=True)
    tmp = STATE_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(STATE_FILE)


def _requirements_hash() -> str:
    if not REQUIREMENTS.is_file():
        return ""
    return hashlib.sha256(REQUIREMENTS.read_bytes()).hexdigest()


def _healthy_runtime() -> bool:
    if not VENV_CFG.is_file() or not VENV_PY.is_file():
        return False
    try:
        p = subprocess.run(
            [str(VENV_PY), "-c", "import sys; print(sys.executable)"],
            cwd=APP_DIR,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=12,
            check=False,
        )
        return p.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def _remove_broken_runtime() -> None:
    if not VENV_DIR.exists():
        return
    _log("shared runtime غير صالح؛ يتم إعادة إنشائه مرة واحدة...")
    try:
        shutil.rmtree(VENV_DIR)
    except OSError:
        if os.name == "nt":
            subprocess.run(["cmd", "/c", "rmdir", "/s", "/q", str(VENV_DIR)], cwd=APP_DIR,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
        if VENV_DIR.exists():
            raise


def _run(cmd: list[str], cwd: Path = APP_DIR) -> None:
    _log(" ".join(map(str, cmd)))
    p = subprocess.run(cmd, cwd=cwd, check=False)
    if p.returncode:
        raise RuntimeError(f"فشل تنفيذ الأمر ({p.returncode})")


def _create_runtime() -> None:
    _log("إنشاء Shared Runtime لأول مرة فقط...")
    _run([sys.executable, "-m", "venv", str(VENV_DIR)])
    if not VENV_PY.is_file() or not VENV_CFG.is_file():
        raise RuntimeError(f"تعذر إنشاء Python runtime: {VENV_DIR}")
    pip_probe = subprocess.run([str(VENV_PY), "-m", "pip", "--version"], cwd=APP_DIR,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
    if pip_probe.returncode != 0:
        _run([str(VENV_PY), "-m", "ensurepip", "--upgrade"])


def ensure_runtime(script_name: str | None = None) -> int | None:
    if os.environ.get(BOOTSTRAPPED_ENV) == "1":
        return None

    RUNTIME_ROOT.mkdir(parents=True, exist_ok=True)
    _log(f"Runtime location: {RUNTIME_ROOT}")

    if not _healthy_runtime():
        _remove_broken_runtime()
        _create_runtime()

    wanted = _requirements_hash()
    component = APP_DIR.name or "unknown"
    state = _load_state()
    components = state.setdefault("components", {})
    record = components.get(component, {}) if isinstance(components, dict) else {}
    installed_hash = record.get("requirements_sha256", "") if isinstance(record, dict) else ""

    if wanted and installed_hash != wanted:
        if REQUIREMENTS.is_file():
            _log(f"تثبيت المتطلبات للمكوّن {component} لأول مرة أو بعد تغيير requirements.txt...")
            _run([str(VENV_PY), "-m", "pip", "install", "--disable-pip-version-check", "-r", str(REQUIREMENTS)])
            components[component] = {"requirements_sha256": wanted}
            state["runtime_python"] = str(VENV_PY)
            _save_state(state)
    elif wanted:
        _log(f"المتطلبات جاهزة للمكوّن {component} — لن تتم إعادة التثبيت.")

    current = Path(sys.executable).resolve()
    runtime_py = VENV_PY.resolve()
    if current != runtime_py:
        target = APP_DIR / (script_name or Path(sys.argv[0]).name)
        if not target.is_file():
            raise RuntimeError(f"تعذر العثور على ملف التشغيل: {target}")
        env = os.environ.copy()
        env[BOOTSTRAPPED_ENV] = "1"
        env["PYTHONPATH"] = str(APP_DIR) + os.pathsep + env.get("PYTHONPATH", "")
        _log(f"بدء التشغيل باستخدام Shared Runtime: {target.name}")
        result = subprocess.run([str(runtime_py), "-u", str(target), *sys.argv[1:]],
                                cwd=APP_DIR, env=env, check=False)
        return result.returncode
    return None
