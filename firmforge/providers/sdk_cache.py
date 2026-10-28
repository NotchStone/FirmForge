"""SDK 归档缓存（core.a / hal.a）的共享约定。

两平台的缓存**策略**不同，但**约定**必须一致：

  - AVR core.a：按源文件增量 —— Arduino Core 有几十个文件，lock 记
    ``{相对路径: sha256}``，改一个文件只重编那一个。
  - STM32 hal.a：按整档 —— lock 记单个 ``__key__``（全部源内容 + 编译
    参数 + 链接脚本 + hal_conf + 工具链版本的 SHA256），命中即整档复用。

策略归各 provider，约定归这里：

  - 声明文件叫 lock.json 而不是 manifest.json：缓存目录是**派生物**
    （标准 §5.2），manifest 这个名字留给 vendor 子树（「厂家物，可整块
    删除重下」），两者语义不同，同名会让「这个目录能不能安全删掉」
    失去唯一答案。
  - 旧缓存里的 manifest.json 读时回退、写时改名，不让旧缓存白丢一次；
    同时避免两个声明文件并存各说一套。
  - 归档重建前必须先删旧档：``ar rcs`` 是**追加**语义。
  - ar 一律走 run_text（``check=True`` 会抛未捕获的 CalledProcessError
    且绕过 UTF-8/replace 解码 —— textio 事故的复发条件）。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from firmforge.providers.textio import run_text


def read_lock(cache_dir: Path) -> dict[str, Any] | None:
    """读缓存声明文件；无声明或损坏返回 None（视为缓存失效）。"""
    lock = cache_dir / "lock.json"
    legacy = cache_dir / "manifest.json"
    if not lock.is_file() and legacy.is_file():
        lock = legacy          # 旧缓存兼容，写时改回 lock
    if not lock.is_file():
        return None
    try:
        return json.loads(lock.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def write_lock(cache_dir: Path, payload: dict[str, Any]) -> Path:
    """写 lock.json；若旧名 manifest.json 还在，顺手清掉。"""
    lock_path = cache_dir / "lock.json"
    lock_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    legacy = cache_dir / "manifest.json"
    if legacy.is_file():
        legacy.unlink()
    return lock_path


def build_archive(archive: Path, objs: list[str], ar_tool: str,
                  ) -> tuple[str, str, int]:
    """（重）建静态归档。返回 (stdout, stderr, returncode)。

    ``ar rcs`` 对已存在的归档是追加语义，必须先删旧档再建。
    """
    if archive.exists():
        archive.unlink()
    r = run_text([ar_tool, "rcs", str(archive)] + list(objs))
    return r.stdout, r.stderr, r.returncode
