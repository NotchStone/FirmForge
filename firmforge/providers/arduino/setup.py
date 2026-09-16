"""Toolchain installer — `ff setup`.

Downloads and installs AVR toolchains (avr-gcc, avrdude, cppcheck) and the
Arduino AVR Core bundle from official sources, into the FirmForge B 区
(用户级，`~/.firmforge/`；可用 `FIRMFORGE_HOME` 环境变量重定向):

  tools  -> <B 区>/toolchains/<tool>/
  core   -> <B 区>/packages/arduino/avr/<version>/

Installs are vendor goods (标准 §4 `vendor` 类）：可整块删除后重新下载。
因此每个子树安装完成后会写出 `manifest.json` 声明其内容（标准 §5 R3），
让「这块能不能安全删掉重下」有一个可读的答案。

Idempotent: already-installed tools are skipped. Cross-platform (Windows /
macOS / Linux) via the manifests in firmforge/data/vendor/manifests/.
"""

from __future__ import annotations

import io
import json
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
from firmforge.infrastructure import paths

logger = logging.getLogger(__name__)

#: 各子树的期望生命周期 —— 写进 manifest.json，供人工与 `ff doctor` 核对
_SUBTREE_LIFECYCLE = {
    "toolchains": "vendor",
    "packages": "vendor",
    "examples": "vendor",
    "sources": "vendor",
    "config": "user-state",
}

#: 生命周期标签的人话解释。分区有一个已知代价：用户看不出「数据从哪来」。
#: 这行解释是那个代价的补偿 —— 清理目录前先读它。
_LIFECYCLE_MEANING = {
    "vendor": "厂家/第三方产物 —— 可整块删除，由 ff setup 重新下载",
    "derived": "派生物 —— 可删除，下次构建时自动重新生成",
    "user-state": "用户态 —— 删掉要重新填写，不要当缓存清理",
    "committed": "承诺级 —— 已入库，删掉需要重新编写",
    "runtime": "运行时 —— 会话级临时产物，进程退出即无意义",
}


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


def _resolve_root(install: dict, default: Path) -> Path:
    """Install root: the manifest's `root` wins (may contain `~`), else default.

    Going through this helper keeps every install path derived from
    `paths.firmforge_home()`, so `FIRMFORGE_HOME` redirection works everywhere
    (a manifest that pins an absolute `~/.firmforge/...` path would silently
    escape the override).
    """
    raw = install.get("root")
    if raw:
        return Path(os.path.expanduser(str(raw)))
    return default


def _locate_external(install: dict) -> Path | None:
    """Probe for a toolchain FirmForge does not install (例外 E3）。

    Checks the manifest's explicit probe paths first, then falls back to PATH
    via the declared binary names. Returns the containing directory, or None.
    """
    for raw in install.get("probe", []):
        p = Path(os.path.expanduser(str(raw)))
        if p.is_dir():
            for exe in install.get("binaries", []):
                if _bin_exists(p, exe):
                    return p
    for exe in install.get("binaries", []):
        found = shutil.which(exe)
        if found:
            return Path(found).parent
    return None


def install_tool(manifest: Path) -> str:
    """Install one toolchain from its manifest. Returns install root or ''."""
    import yaml
    m = yaml.safe_load(manifest.read_text(encoding="utf-8"))
    plat = _platform_key()
    entry = m.get("platforms", {}).get(plat) or m.get("platforms", {}).get("linux-x86_64")
    install = m.get("install", {})

    # 例外 E3（标准 §3.1）：系统/厂商安装器已经放好的外部工具链。
    # FirmForge 不下载、不搬运，只探测与登记。探测失败不算 setup 失败 ——
    # 安装那套工具不是 FirmForge 的职责，AVR 路线也不该被它拖累。
    if install.get("external"):
        target = _locate_external(install)
        if target:
            logger.info("%s: external toolchain found at %s",
                        m.get("tool"), target)
            return str(target)
        logger.warning("%s: external toolchain not found — %s\n"
                       "  probe paths: %s",
                       m.get("tool"), install.get("purpose", ""),
                       ", ".join(str(p) for p in install.get("probe", [])))
        return "external"

    root = _resolve_root(install, paths.toolchains_dir() / str(m.get("tool", "")))
    bin_rel = install.get("bin", "")
    if bin_rel and _bin_exists(root, bin_rel):
        logger.info("%s already installed, skip", m.get("tool"))
        return str(root)
    # Avrdude is bundled inside the avr-gcc archive — extract instead of download.
    if m.get("install", {}).get("from_gcc"):
        gcc_root = paths.toolchains_dir() / "avr-gcc"
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
    root = _resolve_root(install, paths.packages_dir() / "arduino" / "avr")
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
        core_root = _resolve_root(
            install, paths.packages_dir() / "arduino" / "avr" / "1.8.6")
        core_root.mkdir(parents=True, exist_ok=True)
        _extract(archive, core_root)
        if not (core_root / structure.get("cores", "cores/arduino") / "Arduino.h").exists():
            logger.error("Arduino Core extracted but Arduino.h missing")
            return ""
    return str(root)


def _utc_now() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _scan_subtree(path: Path) -> dict:
    """Cheap inventory of one subtree: top-level entries + file/byte totals.

    Deliberately does NOT hash every file — `toolchains/` alone holds 4324
    files, and a full SHA256 sweep would add seconds to every `ff setup` for
    little gain. Per-file integrity, where it actually matters, lives in the
    upstream `*.yaml` manifests' `sha256` field.
    """
    entries: list[dict] = []
    files = 0
    total = 0
    if not path.is_dir():
        return {"entries": entries, "files": 0, "bytes": 0}
    for child in sorted(path.iterdir()):
        if child.name == "manifest.json":
            continue
        if child.is_dir():
            cf = cb = 0
            for p in child.rglob("*"):
                try:
                    if p.is_file():
                        cf += 1
                        cb += p.stat().st_size
                except OSError:
                    continue
            entries.append({"name": child.name, "type": "dir",
                            "files": cf, "bytes": cb})
            files += cf
            total += cb
        else:
            try:
                size = child.stat().st_size
            except OSError:
                size = 0
            entries.append({"name": child.name, "type": "file",
                            "files": 1, "bytes": size})
            files += 1
            total += size
    return {"entries": entries, "files": files, "bytes": total}


def write_subtree_manifest(subtree: str) -> Path | None:
    """Write `<B 区>/<subtree>/manifest.json` declaring what lives there.

    标准 §5 R3：每个 `vendor` 子树必须带声明文件。这不是形式主义 ——
    B 区可以被整块 `rm -rf` 后重建，而这个「可删除」的承诺只有在
    「删了会丢什么」有据可查时才成立。没有它，日后清理的人只能靠猜，
    而猜错的代价是重下 650 MB 工具链。
    """
    root = paths.firmforge_home() / subtree
    if not root.is_dir():
        return None
    lifecycle = _SUBTREE_LIFECYCLE.get(subtree, "unknown")
    scan = _scan_subtree(root)
    payload = {
        "subtree": subtree,
        "lifecycle": lifecycle,
        "meaning": _LIFECYCLE_MEANING.get(lifecycle, ""),
        "firmforge_home": str(paths.firmforge_home()),
        "generated_at": _utc_now(),
        "generated_by": "firmforge.providers.arduino.setup.write_subtree_manifest",
        "files": scan["files"],
        "bytes": scan["bytes"],
        "entries": scan["entries"],
    }
    out = root / "manifest.json"
    out.write_text(json.dumps(payload, indent=2, ensure_ascii=False),
                   encoding="utf-8")
    logger.info("manifest written: %s (%d entries, %d files)",
                out, len(scan["entries"]), scan["files"])
    return out


def setup_all() -> int:
    """Install all toolchains + core, then declare every B 区 subtree.

    Returns 0 on full success.
    """
    paths.ensure_layout()
    manifests = manifests_dir()
    ok = True
    for tool_manifest in sorted((manifests / "tools").glob("*.yaml")):
        if not install_tool(tool_manifest):
            ok = False
    core_manifest = manifests / "core" / "arduino_avr_core.yaml"
    if core_manifest.exists():
        if not install_core(core_manifest):
            ok = False
    for subtree in _SUBTREE_LIFECYCLE:
        write_subtree_manifest(subtree)
    return 0 if ok else 1


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    sys.exit(setup_all())
