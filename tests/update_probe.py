"""CI probe: run the EXE updater script outside the frozen app to see which launch step fails."""
import importlib.machinery
import importlib.util
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

app_dir = Path(__file__).resolve().parents[1] / "app"
sys.path.insert(0, str(app_dir))
loader = importlib.machinery.SourceFileLoader("app_under_test", str(app_dir / "blythe_a4_maker.pyw"))
spec = importlib.util.spec_from_loader(loader.name, loader)
app = importlib.util.module_from_spec(spec)
loader.exec_module(app)

work = Path(tempfile.mkdtemp(prefix="probe_"))
script = work / "updater.ps1"
script.write_text(app.EXE_UPDATER_SCRIPT, encoding="utf-8-sig")
target = work / "target.exe"
incoming = work / "incoming.exe"
log = work / "probe.log"


HARMLESS_EXE = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "whoami.exe"


def reset() -> None:
    # A real program so Start-Process succeeds without opening anything.
    target.write_bytes(HARMLESS_EXE.read_bytes())
    incoming.write_bytes(HARMLESS_EXE.read_bytes() + b"")
    log.unlink(missing_ok=True)


def args(pid: int) -> list[str]:
    return [
        "powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script),
        "-ProcessId", str(pid), "-UpdatedExe", str(incoming), "-InstallExe", str(target),
        "-WorkDir", str(work / "nowork"), "-LogFile", str(log),
    ]


for name, kwargs in (
    ("sync", {}),
    ("detached", {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS, "close_fds": True}),
    ("no_window", {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW, "close_fds": True}),
):
    reset()
    result = subprocess.run(args(0), capture_output=True, text=True, timeout=120, **kwargs)
    time.sleep(1)
    print(f"=== {name}: exit={result.returncode}")
    print("stdout:", result.stdout.strip())
    print("stderr:", result.stderr.strip())
    print("log:", log.read_text(encoding="utf-8-sig") if log.exists() else "<none>")
    print("target exists:", target.exists(), "old copy:", Path(f"{target}.old").exists(), "incoming left:", incoming.exists())
