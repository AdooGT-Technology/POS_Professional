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



def _webview_env() -> dict[str, str]:
    '''Build a deterministic Windows environment for EdgeChromium.'''
    env = os.environ.copy()
    env["PYTHONNET_RUNTIME"] = "netfx"
    env["PYWEBVIEW_GUI"] = "edgechromium"
    env["WEBVIEW2_USER_DATA_FOLDER"] = str(RUNTIME_ROOT / "WebView2Data")
    return env


def _webview_native_dir() -> Path | None:
    '''Return the architecture-specific WebView2 loader directory shipped by pywebview.'''
    site_packages = VENV_DIR / "Lib" / "site-packages"
    if not site_packages.is_dir():
        return None
    import struct
    arch = "win-x64" if struct.calcsize("P") == 8 else "win-x86"
    candidate = site_packages / "webview" / "lib" / "runtimes" / arch / "native"
    return candidate if candidate.is_dir() else None


def _prepare_webview_env(env: dict[str, str]) -> dict[str, str]:
    native = _webview_native_dir()
    if native:
        native_s = str(native)
        env["PATH"] = native_s + os.pathsep + env.get("PATH", "")
        env["PYWEBVIEW_NATIVE_DLL_DIR"] = native_s
    return env


def _cleanup_stale_webview_distribution() -> None:
    '''Remove pip's stale '~ywebview' remnants before reinstalling pywebview.'''
    if os.name != "nt":
        return
    site_packages = VENV_DIR / "Lib" / "site-packages"
    if not site_packages.is_dir():
        return
    for path in site_packages.glob("~ywebview*"):
        try:
            if path.is_dir() and not path.is_symlink():
                shutil.rmtree(path)
            else:
                path.unlink()
            _log(f"إزالة بقايا pywebview تالفة: {path.name}")
        except OSError as exc:
            _log(f"تعذر إزالة بقايا {path.name}: {exc}")


def _webview_probe() -> subprocess.CompletedProcess[str]:
    '''Validate CLR + pywebview + the installed WebView2 Runtime itself.'''
    env = _prepare_webview_env(_webview_env())
    probe = r"""import os, sys, struct, traceback
native = os.environ.get("PYWEBVIEW_NATIVE_DLL_DIR")
if native and hasattr(os, "add_dll_directory"):
    os.add_dll_directory(native)
try:
    import pythonnet
    pythonnet.load("netfx")
    import clr
    import webview
    import webview.platforms.edgechromium as edge
    from webview import util
    from Microsoft.Web.WebView2.Core import CoreWebView2Environment
    version = CoreWebView2Environment.GetAvailableBrowserVersionString()
    print("WEBVIEW_OK")
    print("PYTHON=", sys.version.replace("\n", " "))
    print("ARCH=", struct.calcsize("P") * 8)
    print("PYWEBVIEW=", getattr(webview, "__version__", ""))
    print("PYTHONNET=", pythonnet.get_runtime_info())
    print("WEBVIEW2_RUNTIME=", version)
    print("NATIVE_DLL_DIR=", native or "")
    print("INTEROP_CORE=", util.interop_dll_path("Microsoft.Web.WebView2.Core.dll"))
except Exception:
    traceback.print_exc()
    raise
"""
    return subprocess.run([str(VENV_PY), "-c", probe], cwd=APP_DIR, env=env,
                          capture_output=True, text=True, check=False)


def _webview_healthcheck(state: dict, requirements_hash: str) -> None:
    '''Validate/repair EdgeChromium and persist the real failure details.'''
    if os.name != "nt" or not VENV_PY.is_file():
        return
    record = state.setdefault("webview_health", {})
    if record.get("requirements_sha256") == requirements_hash and record.get("ok") is True:
        os.environ.update(_prepare_webview_env(_webview_env()))
        return

    _cleanup_stale_webview_distribution()
    probe = _webview_probe()
    if probe.returncode != 0:
        _log("pywebview/pythonnet EdgeChromium backend غير صالح؛ سيتم إصلاحه مرة واحدة...")
        _run([str(VENV_PY), "-m", "pip", "install", "--disable-pip-version-check",
              "--force-reinstall", "pywebview==6.2.1", "pythonnet==3.2.0", "clr-loader==0.3.1"])
        probe = _webview_probe()

    record.update({
        "requirements_sha256": requirements_hash,
        "ok": probe.returncode == 0,
        "pythonnet_runtime": "netfx",
        "probe_stdout": probe.stdout[-8000:],
        "probe_stderr": probe.stderr[-12000:],
    })
    _save_state(state)
    if probe.returncode != 0:
        raise RuntimeError("تعذر تشغيل Windows WebView2 backend باستخدام .NET Framework. "
                           "تم حفظ التشخيص الكامل في " + str(STATE_FILE))
    os.environ.update(_prepare_webview_env(_webview_env()))

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

    # pywebview can be left in a mixed/corrupt state after package upgrades.
    # Repair is hash-gated, so it is not repeated on every launch.
    if wanted:
        _webview_healthcheck(state, wanted)
        _save_state(state)

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
