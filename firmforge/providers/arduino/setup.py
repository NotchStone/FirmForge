"""Toolchain installer — `ff setup`.

Downloads and installs AVR toolchains (avr-gcc, avrdude) and the Arduino AVR
Core bundle from Arduino's official downloads, into the FirmForge canonical
paths:

  tools  -> ~/.firmforge/toolchains/<tool>/
  core   -> ~/.firmforge/packages/arduino/avr/<version>/

Idempotent: already-installed tools are skipped. Cross-platform (Windows /
macOS / Linux) via the manifests in firmforge/data/vendor/manifests/.
"""

from __future__ import annotations

import io
import logging
import os
import platform
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
import zipfile
from pathlib import Path

from firmforge.core.resources import manifests_dir

logger = logging.getLogger(__name__)

_FIRMFORGE_HOME = Path(os.path.expanduser("~/.firmforge"))


def _platform_key() -> str:
    sys_plat = sys.platform
    if sys_plat.startswith("win"):
        return "windows"
    if sys_plat == "darwin":
        return "macos"
    mach = platform.machine().lower()
    if "aarch64" in mach or "arm64" in mach:
        return "linux-aarch64"
    return "linux-x86_64"


def _download(url: str, dest_dir: Path) -> Path:
    """Download url into dest_dir, return local file path."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    fname = url.rsplit("/", 1)[-1]
    local = dest_dir / fname
    if local.exists():
        logger.info("cached: %s", local)
        return local
    logger.info("downloading %s", url)
    req = urllib.request.Request(url, headers={"User-Agent": "firmforge/0.2"})
    with urllib.request.urlopen(req, timeout=300) as resp, open(local, "wb") as f:
        shutil.copyfileobj(resp, f)
    return local


def _extract(archive: Path, dest: Path) -> None:
    """Extract zip / tar.bz2 / tar.gz into dest (strips single top-level dir)."""
    if archive.name.endswith(".zip"):
        with zipfile.ZipFile(archive) as z:
            top = {p.split("/")[0] for p in z.namelist() if "/" in p or p.endswith("/")}
            if len(top) == 1 and not archive.name.startswith("."):
                # strip single top dir
                for member in z.namelist():
                    parts = member.split("/", 1)
                    target = dest / (parts[1] if len(parts) > 1 else ".")
                    if parts[1:]:
                        if member.endswith("/"):
                            target.mkdir(parents=True, exist_ok=True)
                        else:
                            target.parent.mkdir(parents=True, exist_ok=True)
                            target.write_bytes(z.read(member))
            else:
                z.extractall(dest)
        return
    # tar.bz2 / tar.gz
    with tarfile.open(archive) as t:
        top = {p.split("/")[0] for p in t.getnames() if "/" in p}
        if len(top) == 1:
            base = dest / top.pop()
            base.mkdir(parents=True, exist_ok=True)
            for member in t.getmembers():
                parts = member.name.split("/", 1)
                if len(parts) > 1:
                    target = dest / parts[1]
                    if member.isdir():
                        target.mkdir(parents=True, exist_ok=True)
                    elif member.isfile():
                        target.parent.mkdir(parents=True, exist_ok=True)
                        f = t.extractfile(member)
                        if f:
                            target.write_bytes(f.read())
        else:
            t.extractall(dest)


def _bin_exists(root: Path, bin_rel: str) -> bool:
    """True if bin_rel (or bin_rel.exe on Windows) exists under root."""
    p = root / bin_rel
    if p.exists():
        return True
    if os.name == "nt" and not bin_rel.lower().endswith(".exe"):
        return (root / (bin_rel + ".exe")).exists()
    return False


def install_tool(manifest: Path) -> str:
    """Install one toolchain from its manifest. Returns install root or ''."""
    import yaml
    m = yaml.safe_load(manifest.read_text(encoding="utf-8"))
    plat = _platform_key()
    entry = m.get("platforms", {}).get(plat) or m.get("platforms", {}).get("linux-x86_64")
    install = m.get("install", {})
    root = Path(os.path.expanduser(install.get("root", f"~/.firmforge/toolchains/{m.get('tool')}/")))
    bin_rel = install.get("bin", "")
    if bin_rel and _bin_exists(root, bin_rel):
        logger.info("%s already installed, skip", m.get("tool"))
        return str(root)
    # Avrdude is bundled inside the avr-gcc archive — extract instead of download.
    if m.get("install", {}).get("from_gcc"):
        gcc_root = Path(os.path.expanduser("~/.firmforge/toolchains/avr-gcc/"))
        src_bin = gcc_root / "bin"
        if src_bin.exists():
            root.mkdir(parents=True, exist_ok=True)
            (root / "bin").mkdir(parents=True, exist_ok=True)
            copied = 0
            for f in src_bin.glob("avrdude*"):
                shutil.copy2(f, root / "bin" / f.name)
                copied += 1
            # avrdude.conf lives at the bundle root (not bin/) in ZakKemble builds
            conf_rel = install.get("conf", "")
            conf_src = gcc_root / "avrdude.conf"
            conf_dst = root / "bin" / "avrdude.conf"
            if conf_src.exists() and not conf_dst.exists():
                shutil.copy2(conf_src, conf_dst)
                copied += 1
            if copied:
                logger.info("avrdude extracted from avr-gcc bundle (%d files)", copied)
                return str(root)
        logger.warning("avr-gcc bundle not found — cannot extract avrdude; "
                       "run `ff setup` after avr-gcc, or install avrdude via system package")
        return ""
    if not entry or not entry.get("url"):
        logger.warning("%s: no download URL for platform %s — install via system package "
                       "(apt/brew)", m.get("tool"), plat)
        return ""
    with tempfile.TemporaryDirectory() as td:
        archive = _download(entry["url"], Path(td))
        if m.get("install", {}).get("msi_extract"):
            _extract_msi(archive, root)
        else:
            _extract(archive, root)
    if bin_rel and not _bin_exists(root, bin_rel):
        logger.warning("%s: installed but %s not found (structure may differ)",
                       m.get("tool"), bin_rel)
    return str(root)


def _extract_msi(msi: Path, dest: Path) -> None:
    """Extract a Windows MSI via msiexec administrative install into dest."""
    if os.name != "nt":
        raise RuntimeError("MSI extraction is Windows-only")
    with tempfile.TemporaryDirectory() as td:
        target = Path(td) / "out"
        target.mkdir(parents=True, exist_ok=True)
        r = subprocess.run(
            ["msiexec", "/a", str(msi), "/qn", f"TARGETDIR={target}"],
            capture_output=True, text=True,
        )
        if r.returncode != 0:
            raise RuntimeError(f"msiexec failed: {r.returncode} {r.stderr}")
        # Files land under <TARGETDIR>/PFiles/cppcheck*/ — locate cppcheck.exe and copy
        for p in target.rglob("cppcheck.exe"):
            src_root = p.parent
            dest.mkdir(parents=True, exist_ok=True)
            for f in src_root.iterdir():
                if f.is_file():
                    shutil.copy2(f, dest / f.name)
            return
        # fallback: copy the whole extracted tree
        dest.mkdir(parents=True, exist_ok=True)
        for p in target.rglob("*"):
            if p.is_file():
                rel = p.relative_to(target)
                dst = dest / rel
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(p, dst)


def install_core(manifest: Path) -> str:
    """Install Arduino AVR Core bundle. Returns install root or ''."""
    import yaml
    m = yaml.safe_load(manifest.read_text(encoding="utf-8"))
    install = m.get("install", {})
    root = Path(os.path.expanduser(install.get("root", "~/.firmforge/packages/arduino/avr/")))
    structure = install.get("structure", {})
    # Already present?
    marker = Path(root) / structure.get("cores", "cores/arduino") / "Arduino.h"
    if marker.exists():
        logger.info("Arduino Core %s already installed, skip", m.get("version"))
        return str(root)
    src = m.get("source", {})
    url = src.get("url", "")
    if not url:
        logger.warning("Arduino Core: no source URL")
        return ""
    logger.info("downloading Arduino Core index...")
    with tempfile.TemporaryDirectory() as td:
        idx = _download(url, Path(td))
        # Extract embedded archive if present in the json (core zip referenced)
        # Fallback: look for archive name in the index json.
        text = idx.read_text(encoding="utf-8", errors="replace")
        # The Arduino package index embeds the core URL; extract it.
        import re
        core_url = None
        arch = m.get("arch", "avr")
        # find platform archive url for the avr core (latest 1.8.x)
        matches = re.findall(r'"url"\s*:\s*"([^"]*avr[^"]*\.zip)"', text)
        if matches:
            core_url = matches[-1]
        if not core_url:
            logger.error("Arduino Core URL not found in package index")
            return ""
        archive = _download(core_url, Path(td))
        core_root = Path(os.path.expanduser(install.get("root", "~/.firmforge/packages/arduino/avr/1.8.6/")))
        core_root.mkdir(parents=True, exist_ok=True)
        _extract(archive, core_root)
        if not (core_root / structure.get("cores", "cores/arduino") / "Arduino.h").exists():
            logger.error("Arduino Core extracted but Arduino.h missing")
            return ""
    return str(root)


def setup_all() -> int:
    """Install all toolchains + core. Returns 0 on full success."""
    manifests = manifests_dir()
    ok = True
    for tool_manifest in sorted((manifests / "tools").glob("*.yaml")):
        if not install_tool(tool_manifest):
            ok = False
    core_manifest = manifests / "core" / "arduino_avr_core.yaml"
    if core_manifest.exists():
        if not install_core(core_manifest):
            ok = False
    return 0 if ok else 1


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    sys.exit(setup_all())
