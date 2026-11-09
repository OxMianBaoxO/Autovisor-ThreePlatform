"""Build a clean portable Windows distribution from an explicit source allowlist."""
import argparse
import configparser
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import struct
import subprocess
import sys
import tempfile
from zipfile import ZipFile, ZIP_DEFLATED

from modules.version import __version__

ROOT = Path(__file__).resolve().parent
BASE_COMMIT = "5c715623030877d1daac0eaa14ac91f0abb2d003"


def run(command, log, cwd=ROOT):
    env = dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
    with log.open("w", encoding="utf-8") as stream:
        result = subprocess.run(command, cwd=cwd, env=env, stdout=stream, stderr=subprocess.STDOUT)
    if result.returncode:
        raise RuntimeError(f"Command failed (exit {result.returncode}); inspect {log}")
    return log.read_text(encoding="utf-8", errors="replace")


def archive_tree(folder, target):
    with ZipFile(target, "w", ZIP_DEFLATED, compresslevel=6) as archive:
        for path in sorted(folder.rglob("*")):
            if path.is_file():
                archive.write(path, str(Path(folder.name) / path.relative_to(folder)))


def check_archive(target):
    with ZipFile(target) as archive:
        bad = archive.testzip()
        if bad:
            raise RuntimeError(f"ZIP integrity error: {bad}")
        for name in archive.namelist():
            parts = set(Path(name).parts)
            if parts.intersection({"logs", ".git", ".venv", "__pycache__", "chaoxing-profile",
                                   "chaoxing-profile-chrome", "chaoxing-profile-edge"}):
                raise RuntimeError(f"Private/runtime path in release: {name}")
            if Path(name).name.lower() in {"cookies.json", "smoke.ini", "xxt-course-state.json"}:
                raise RuntimeError(f"Private config in release: {name}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT.parent.parent / "outputs")
    args = parser.parse_args()
    if os.name != "nt" or struct.calcsize("P") != 8:
        raise SystemExit("This release builder requires 64-bit Windows Python")
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    job = Path(tempfile.mkdtemp(prefix="release-three-", dir=ROOT.parent))
    release_name = f"Autovisor-{__version__}-Windows-x64"
    # No user application folder, config.ini, data profile, cookies, or logs are copied.
    print(f"Build workspace: {job}", flush=True)
    tests = run([sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"], job / "tests.txt")
    match = re.search(r"Ran (\d+) tests", tests)
    if not match or not re.search(r"^OK(?:\s|$)", tests, re.M):
        raise RuntimeError("Missing passing test result")
    for script in ("polymas_offline_check", "native_controls_browser_check"):
        run([sys.executable, "-m", f"tests.{script}"], job / f"{script}.txt")
    print("Unit and offline browser checks passed; building executable...", flush=True)
    run([sys.executable, "-m", "PyInstaller", "--noconfirm", "--log-level", "WARN", "--onedir",
         "--contents-directory", "internal", "--name", "Autovisor", "--icon", str(ROOT / "resources/zhs.ico"),
         "--exclude-module", "cv2", "--exclude-module", "numpy",
         "--distpath", str(job / "dist"), "--workpath", str(job / "build"),
         "--specpath", str(job / "spec"), str(ROOT / "Autovisor.py")], job / "build.txt")

    stage = job / release_name
    shutil.copytree(job / "dist/Autovisor", stage)
    for rel in ("resources/QRcode.jpg", "resources/zhs.ico", "data/mirrors.json", "LICENSE"):
        target = stage / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / rel, target)
    shutil.copytree(ROOT / "resources/mixue", stage / "resources/mixue")
    shutil.copy2(ROOT / "MIXUE_UPDATE.md", stage / "蜜雪移植说明.md")
    shutil.copy2(ROOT / "DISTRIBUTION.md", stage / "使用说明.md")
    shutil.copy2(ROOT / "DISTRIBUTION.md", stage / "使用说明.txt")
    shutil.copy2(ROOT / "README.md", stage / "README.md")
    shutil.copytree(ROOT / "docs", stage / "docs")
    (stage / "config.ini").write_text((ROOT / "config.ini.example").read_text(encoding="utf-8"), encoding="utf-8-sig")
    python_dll = Path(sys.base_prefix) / "python3.dll"
    if python_dll.is_file():
        shutil.copy2(python_dll, stage / "internal/python3.dll")
    for name, command in {
        "Start.cmd": '"%~dp0Autovisor.exe" --config "%~dp0config.ini"',
        "Edit-config.cmd": 'start "" notepad.exe "%~dp0config.ini"',
        "Check-environment.cmd": '"%~dp0Autovisor.exe" --config "%~dp0config.ini" --self-check',
    }.items():
        (stage / name).write_text('@echo off\nchcp 65001 >nul\ncd /d "%~dp0"\n' + command + '\n', encoding="ascii")
    settings = configparser.ConfigParser()
    settings.read(stage / "config.ini", encoding="utf-8-sig")
    for section in settings.sections():
        if section.endswith("account"):
            assert not any(settings.get(section, key, raw=True, fallback="").strip() for key in ("username", "password"))
    assert not any(settings["course-url"].values())

    # Full project sources, selected by public code/resource paths, never a directory dump.
    source_files = [ROOT / name for name in (
        "Autovisor.py", "GUI.py", "LICENSE", "README.md", "DISTRIBUTION.md", "POLYMAS_UPDATE.md",
        "build.py", "package_release.py", "pyproject.toml", "uv.lock", ".python-version", ".gitignore",
        "run_macos.sh", "MIXUE_UPDATE.md", "config.ini.example", "config.macos.ini.example", "data/mirrors.json",
        "resources/QRcode.jpg", "resources/stealth.min.js", "resources/zhs.ico")]
    source_files += list((ROOT / "modules").glob("*.py")) + list((ROOT / "tests").glob("*.py"))
    source_files += list((ROOT / "resources/mixue").glob("*"))
    source_files += [p for p in (ROOT / "docs").rglob("*") if p.is_file()]
    with ZipFile(stage / "Autovisor-source.zip", "w", ZIP_DEFLATED) as archive:
        for path in sorted(set(source_files)):
            if path.is_file():
                archive.write(path, str(Path("Autovisor-source") / path.relative_to(ROOT)))
    check_archive(stage / "Autovisor-source.zip")

    # Smoke in a separate folder with spaces: the distributable remains pristine.
    smoke = job / "smoke extracted with spaces"
    shutil.copytree(stage, smoke)
    result = run([str(smoke / "Autovisor.exe"), "--version"], job / "version.txt", cwd=job)
    assert result.strip() == __version__
    run([str(smoke / "Autovisor.exe"), "--help"], job / "help.txt", cwd=job)
    run([str(smoke / "Autovisor.exe"), "--self-check"], job / "frozen-edge-self-check.txt", cwd=job)
    chrome_config = smoke / "chrome-check.ini"
    chrome_config.write_text((stage / "config.ini").read_text(encoding="utf-8-sig").replace("driver = Edge", "driver = Chrome"), encoding="utf-8-sig")
    run([str(smoke / "Autovisor.exe"), "--self-check", "--config", str(chrome_config)], job / "frozen-chrome-self-check.txt", cwd=job)

    info = {"version": __version__, "upstream": "https://github.com/CXRunfree/Autovisor",
            "upstream_base_commit": BASE_COMMIT, "platforms": ["zhihuishu", "chaoxing", "polymas"],
            "python": sys.version.split()[0], "architecture": "Windows x64",
            "mixue": {"upstream_script": 533346, "version": "1.1.0", "live_api_verified": False},
            "validation": {"unit_tests_run": int(match[1]), "unit_tests_result": "OK (see tests.txt for skips)",
                "offline_browser_checks": ["official ZHS legacy popups, answered-skip and cross-platform isolation; newer wisdom manual wait", "Polymas DOM", "Chaoxing native controls and ebook scroll", "dummy login forms"],
                "frozen_smoke_checks": ["--version", "--help", "Edge offline self-check", "Chrome offline self-check"],
                "limits": "Offline release validation does not establish compatibility with every real course or account."},
            "private_account_data_included": False, "automatic_hibernation_or_watchdog_included": False}
    (stage / "release-info.json").write_text(json.dumps(info, ensure_ascii=False, indent=2), encoding="utf-8")
    manifest = {str(path.relative_to(stage)).replace("\\", "/"): hashlib.sha256(path.read_bytes()).hexdigest()
                for path in sorted(stage.rglob("*")) if path.is_file()}
    (stage / "SHA256SUMS.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    target = output / f"{release_name}.zip"
    archive_tree(stage, target)
    check_archive(target)
    digest = hashlib.sha256(target.read_bytes()).hexdigest()
    target.with_suffix(".zip.sha256").write_text(f"{digest}  {target.name}\n", encoding="ascii")
    print(json.dumps({"archive": str(target), "bytes": target.stat().st_size, "sha256": digest,
                      "build_workspace": str(job), "test_count": int(match[1]), "validation": "passed"}, indent=2), flush=True)


if __name__ == "__main__":
    main()
