"""KnowledgeBase -- unified chip knowledge query interface.

Loads chip-specific reference data: registers, pins, bit-fields.

两个数据源，按优先级排列
------------------------

===========  =========================================================  ================
来源         路径                                                       生命周期
===========  =========================================================  ================
A 区（优先）  ``firmforge/data/knowledge/reference/<库>/<系列>/<芯片>/``  承诺级（入库）
B 区（兜底）  ``~/.firmforge/cache/knowledge/<库>/<系列>/<芯片>/``        派生物（生成器产出）
===========  =========================================================  ================

**系列层不能省**：STM32H7 与 STM32F1 的寄存器手册、SVD、HAL 版本互不相干，
平铺在 ``<库>/<芯片>/`` 下时「它们不是同一份数据」只存在于人脑里，迟早
拿 H7 的表去审 F1 的代码。系列与库同名时折叠（AVR 只有一个系列），
折叠规则见 ``infrastructure.paths.series_scope``。

A 区优先的理由：A 区是人工核验过、跟版本一起发布的「产品承诺」；B 区是
生成器按需重跑的骨架。同芯片两边都有时，入库的那份必须赢，否则
「重跑一次生成器」会静默改掉线上行为。

**读取顺序按文件粒度**（registers.json / pins*.json 各自找第一个命中），
不是整目录二选一 —— 这样「A 区有 pin 表、B 区有生成寄存器表」也能工作。

来源留痕：无论命中哪个区，都记进 ``reference_origin()``。静默回退到 B 区
是这类分层的已知风险（用户看不出「这份数据是谁给的」），留痕是补偿手段。

Example:
    knowledge_base = KnowledgeBase()
    knowledge_base.load_reference("avr", chip="atmega2560")
    reg = knowledge_base.lookup_register("PORTB")

    # 或直接从板卡定义路由（推荐 —— 平台由 board.yaml 决定，不由调用点猜）
    knowledge_base.load_for_board(board_config)
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def _build_field_index(qualified: dict[str, dict[str, Any]]
                        ) -> tuple[dict[str, list[dict[str, Any]]],
                                   dict[str, int]]:
    """位域名 → 归属寄存器，以及位宏前缀集合。

    两个索引服务于不同问题：

    - **全名索引**：源码里写了 ``USART_CR1_TE``，它是不是真位？—— 直接查名字。
    - **前缀索引**：源码里写了 ``GPIO_MODER_BOGUS``，名字查不到。此时要区分
      「HAL 常量，本来就不在寄存器库里」（``GPIO_PIN_7``）与「前缀对、位名错」
      （``GPIO_MODER_BOGUS``）—— 前者放过，后者是幻觉。判据只能是前缀：
      ``GPIO_MODER_`` 下确实有一批已知位，那就说明写的人知道自己要访问哪个
      寄存器，只是位名写错了。

    AVR 的位名（``RXEN0`` / ``C``）不含下划线，不进前缀表；它们靠全名索引
    就能判定，不会因为「前缀太短」误伤。
    """
    index: dict[str, list[dict[str, Any]]] = {}
    prefixes: dict[str, int] = {}
    for key, reg in qualified.items():
        group, _, reg_name = key.partition(".")
        for fld in reg.get("fields") or []:
            name = str(fld.get("name") or "").upper()
            if not name:
                continue
            index.setdefault(name, []).append({
                "peripheral": group,
                "register": reg_name,
                "bit": fld.get("bit"),
                "svd_name": fld.get("svd_name"),
            })
            if "_" in name:
                head = name.rsplit("_", 1)[0] + "_"
                prefixes[head] = prefixes.get(head, 0) + 1
    return index, prefixes


class KnowledgeBase:
    """Unified knowledge query interface.

    Usage:
        knowledge_base = KnowledgeBase()
        knowledge_base.load_reference("avr", chip="atmega328p")

        # Look up PORTB register definition
        reg = knowbase.lookup_register("PORTB")
        print(reg["address"])  # "0x05"

        # Look up Arduino pin 13 → AVR port/pin
        pin = knowbase.lookup_pin(13)
        print(pin["register"])  # "PORTB"

        for r in results:
            print(f"[{r.score:.4f}] {r.source}: {r.hit.get('name', '?')}")
    """

    def __init__(self, knowledge_dir: Path | str | None = None,
                 cache_dir: Path | str | None = None,
                 *, search_cache: bool = True) -> None:
        """
        Args:
            knowledge_dir: A 区知识库根（默认包内 ``firmforge/data/knowledge``）。
            cache_dir: B 区生成结果根（默认 ``~/.firmforge/cache/knowledge``，
                跟随 ``FIRMFORGE_HOME``）。**惰性解析**，避免导入期就绑定 home。
            search_cache: 是否允许回退到 B 区。单元测试要隔离时置 False。
        """
        from firmforge.core.resources import knowledge_dir as _default_knowledge
        self._dir = Path(knowledge_dir) if knowledge_dir else _default_knowledge()
        self._cache_dir = Path(cache_dir) if cache_dir is not None else None
        self._search_cache = search_cache
        # Reference library caches
        self._ref_cache: dict[str, dict[str, Any]] = {}  # platform -> registers.json
        self._register_index: dict[str, dict[str, Any]] = {}  # reg_name -> register entry
        # 限定键索引：STM32 的寄存器裸名跨外设重复（CR/SR/DR/CR1…），
        # 单靠裸名会互相覆盖。键形如 "USART1.CR1"（点号在 C 标识符里非法，
        # 永不与源码 token 撞车）。
        self._qualified_index: dict[str, dict[str, Any]] = {}
        self._duplicate_register_names: set[str] = set()
        # 位域全名索引：``USART_CR1_TE`` → 归属寄存器。STM32 的 CMSIS 位宏
        # 名字就是「外设_寄存器_位」，与源码里的写法国名，可以直接查；
        # 顺带解决审查器此前「遍历所有寄存器找位」的 O(n²) 扫描。
        self._field_index: dict[str, list[dict[str, Any]]] = {}
        # 位宏前缀：``USART_CR1_``。用来判定「前缀对、位名错」——
        # ``GPIO_MODER_BOGUS`` 不是凭空出现的常量，而是打错的位宏。
        self._field_prefixes: dict[str, int] = {}
        # 已知外设实例名（``USART1`` / ``GPIOA``），STM32 的限定名查找入口
        self._peripheral_names: set[str] = set()
        self._pin_index: dict[int, dict[str, Any]] = {}  # arduino_pin -> pin entry
        self._pin_map_cache: dict[str, dict[str, Any]] = {}  # board_id -> pins_*.json
        self._ref_origin: dict[str, dict[str, Any]] = {}  # platform -> 实际命中来源

    # ------------------------------------------------------------------
    # 数据源定位（A 区 → B 区）
    # ------------------------------------------------------------------

    def _cache_root(self) -> Path | None:
        """B 区生成结果根。惰性解析，失败不抛（缺 home 时只是没有 B 区）。"""
        if not self._search_cache:
            return None
        if self._cache_dir is None:
            try:
                from firmforge.infrastructure import paths
                self._cache_dir = paths.knowledge_cache_dir()
            except Exception:      # pragma: no cover - 环境异常兜底
                return None
        return self._cache_dir

    def reference_sources(self, platform: str, chip: str,
                          series: str | None = None,
                          ) -> list[tuple[str, Path]]:
        """候选目录，按优先级排列。``(区标记, 目录)``。

        层级 ``<平台>/<系列>/<芯片>``；系列与平台同名时折叠（AVR）。
        具体折叠规则见 ``paths.series_scope`` —— 全项目只在那里定义一次。

        Returns:
            ``[("A", <A 区目录>), ("B", <B 区目录>)]`` —— B 区按需省略。
        """
        from firmforge.infrastructure.paths import scoped_chip_dir
        if series is None:
            from firmforge.knowledge.platforms import device_series
            series = device_series(None, chip)
        out: list[tuple[str, Path]] = [
            ("A", scoped_chip_dir(self._dir / "reference", platform, series, chip))
        ]
        root = self._cache_root()
        if root is not None:
            out.append(("B", scoped_chip_dir(root, platform, series, chip)))
        return out

    @staticmethod
    def _first_match(sources: list[tuple[str, Path]],
                     pattern: str) -> tuple[str, list[Path]]:
        """按优先级取第一个含 ``pattern`` 的目录。返回 ``(区, 命中文件列表)``。"""
        for tag, d in sources:
            hits = sorted(d.glob(pattern)) if d.is_dir() else []
            if hits:
                return tag, hits
        return "", []

    # ------------------------------------------------------------------
    # Reference library (Stage 4, §3.2.1 P0-1 SVD映射 / P1-4 强类型引用)
    # ------------------------------------------------------------------

    def load_for_board(self, board: dict[str, Any] | None) -> bool:
        """按板卡定义加载 —— 平台与芯片都由 ``board.yaml`` 决定。

        调用方**不该**自己猜平台名：``board.yaml`` 的 ``platform`` 字段
        与 ``provider`` 注册表同键，而寄存器库目录名是另一个命名口径
        （``arduino`` → ``avr``）。映射收在 ``knowledge.platforms``。
        """
        if not board:
            return False
        from firmforge.knowledge.platforms import device_series, library_platform
        platform = library_platform(board)
        chip = (board.get("mcu") or {}).get("chip")
        if not chip:
            logger.warning("load_for_board(): board %r has no mcu.chip",
                           board.get("board_id") or board.get("board_name"))
            return False
        return self.load_reference(platform, chip=str(chip).lower(),
                                   series=device_series(board, str(chip)))

    def load_reference(self, platform: str = "avr",
                        chip: str | None = None,
                        series: str | None = None) -> bool:
        """Load register + pin reference data for a chip.

        Path, A 区优先: knowledge/reference/<平台>/<系列>/<芯片>/registers.json
                        B 区兜底: ~/.firmforge/cache/knowledge/<平台>/<系列>/<芯片>/

        系列层避免「同平台不同代」混放：STM32H7 与 STM32F1 的寄存器手册、
        SVD、HAL 版本互不相干，平铺在一层里迟早会被互相当成对方的数据。
        系列缺省时按芯片名推断（``STM32H743ZIT6`` → ``stm32h7``，见
        ``platforms.device_series``）；AVR 的系列与平台同名，路径上折叠。

        chip parameter is required — chip-level directories are the standard.
        """
        if not chip:
            logger.warning("load_reference() needs chip parameter; no platform-level data")
            return False
        chip = chip.lower()

        # 系列推断在 reference_sources 里做（唯一的路径拼接点），这里不重复
        sources = self.reference_sources(platform, chip, series)
        present = [(tag, d) for tag, d in sources if d.is_dir()]
        if not present:
            logger.warning("Reference directory not found: %s",
                           " | ".join(str(d) for _, d in sources))
            return False

        loaded_any = False
        origin: dict[str, Any] = {"registers": None, "pins": None}

        # Load registers.json
        reg_tag, reg_hits = self._first_match(present, "registers.json")
        if reg_hits:
            reg_path = reg_hits[0]
            with open(reg_path, "r", encoding="utf-8") as f:
                reg_data = json.load(f)
            self._ref_cache[platform] = reg_data

            # 索引是「当前芯片」的视图，整体替换而不是累加：同一实例先加载
            # H743 再加载 F103 时，累加会让两个系列的同名寄存器（CR/SR/DR）
            # 互相覆盖，且覆盖率看上去还很高 —— 这类错误没有报错，只有错值。
            new_index: dict[str, dict[str, Any]] = {}
            new_qualified: dict[str, dict[str, Any]] = {}
            new_dups: set[str] = set()

            for group_name, group in reg_data.get("register_groups", {}).items():
                for reg in group.get("registers", []):
                    name = reg.get("name", "")
                    if not name:
                        continue
                    reg_entry = dict(reg)
                    reg_entry["_group"] = group_name
                    reg_entry["_platform"] = platform
                    key = name.upper()
                    if key in new_index:
                        # 同名跨组（STM32 常态）。保留第一个命中的，并记为
                        # 歧义 —— 后续按裸名的查找结果不再可信，调用方
                        # 应改用限定键。
                        new_dups.add(key)
                    else:
                        new_index[key] = reg_entry
                        logger.debug("Indexed register: %s @ %s",
                                     name, reg.get("address", "?"))
                    new_qualified.setdefault(
                        f"{group_name}.{name}".upper(), reg_entry)

            self._register_index = new_index
            self._qualified_index = new_qualified
            self._duplicate_register_names = new_dups
            self._field_index, self._field_prefixes = _build_field_index(
                new_qualified)
            self._peripheral_names = {
                key.split(".", 1)[0] for key in new_qualified}

            logger.info("KnowledgeBase loaded %d registers (%d qualified, "
                        "%d field names) from %s",
                        len(self._register_index), len(self._qualified_index),
                        len(self._field_index), reg_path)
            origin["registers"] = {"zone": reg_tag, "path": str(reg_path)}
            loaded_any = True

        # Load pin mapping files (pins*.json)
        pin_tag, pin_files = self._first_match(present, "pins*.json")
        new_pins: dict[int, dict[str, Any]] = {}
        for pin_file in pin_files:
            with open(pin_file, "r", encoding="utf-8") as f:
                pin_data = json.load(f)
            board_id = pin_data.get("board", pin_file.stem)
            self._pin_map_cache[board_id] = pin_data
            # Chip alias key: pins.json board label may differ from board_id
            # (e.g. arduino_uno vs arduino_328p) — allow chip-level lookup.
            self._pin_map_cache.setdefault(chip, pin_data)

            # Build pin index: arduino_pin -> pin entry
            # pins may be a list of entry dicts OR a dict keyed by pin name
            pins = pin_data.get("pins", [])
            pin_items = pins.values() if isinstance(pins, dict) else pins
            for pin_entry in pin_items:
                arduino_pin = pin_entry.get("arduino_pin", -1)
                if arduino_pin >= 0:
                    new_pins[arduino_pin] = pin_entry

            logger.info("KnowledgeBase loaded %d pins from %s (board=%s)",
                         len(pin_data.get("pins", [])), pin_file, board_id)
            loaded_any = True
        # 当前芯片没有 pin 表时同样清空：留着上一个芯片的引脚映射，
        # 会让 lookup_pin(13) 在 STM32 上返回 AVR 的 PB5。
        self._pin_index = new_pins
        if pin_files:
            origin["pins"] = {"zone": pin_tag,
                              "path": str(pin_files[0].parent)}

        self._ref_origin[platform] = origin
        return loaded_any

    def reference_origin(self, platform: str | None = None
                          ) -> dict[str, Any]:
        """实际命中的数据源（含 A/B 区标记与路径）。

        「数据从哪来」在分区方案里是看不见的（A 区 / B 区都是普通目录），
        这个访问器是补偿手段 —— 与 ``paths.describe()`` 同一个理由。
        """
        if platform is None:
            return dict(self._ref_origin)
        return dict(self._ref_origin.get(platform, {}))

    def lookup_register(self, reg_name: str,
                         peripheral: str | None = None) -> dict[str, Any] | None:
        """Exact register lookup by name.

        Args:
            reg_name: e.g. "PORTB", "UCSR0A", "DDRB" (AVR)
                      或 "CR1" （STM32，建议同时给 ``peripheral``）
            peripheral: 外设实例名（如 "USART1"）。给了就先查限定键
                      ``USART1.CR1``，查不到再退回裸名。

        Returns:
            Register definition dict with fields, address, $ref, or None.
        """
        if peripheral:
            hit = self._qualified_index.get(f"{peripheral}.{reg_name}".upper())
            if hit is not None:
                return hit
        return self._register_index.get(reg_name.upper())

    def lookup_register_qualified(self, peripheral: str,
                                   reg_name: str) -> dict[str, Any] | None:
        """限定键查找（``外设.寄存器``）。STM32 上这是唯一无歧义的路径。"""
        return self._qualified_index.get(f"{peripheral}.{reg_name}".upper())

    def is_ambiguous_register(self, reg_name: str) -> bool:
        """裸名是否跨外设重复（重复时裸名查找结果不可信）。"""
        return reg_name.upper() in self._duplicate_register_names

    def search_registers(self, query: str, limit: int = 200
                          ) -> tuple[list[dict[str, Any]], bool]:
        """按用户的输入形态查寄存器，返回 ``(命中条目, 是否被截断)``。

        四档顺序，先精确后模糊：

        1. ``外设.寄存器``（``USART1.CR1``）—— 完全限定键
        2. 外设名（``USART1``）—— 该外设下全部寄存器
        3. 裸名（``PORTB`` / ``CR1``）—— **裸名有歧义时返回全部限定命中**，
           不是第一个。STM32 上 ``CR1`` 出现在四十多个外设里，随便挑一个
           返回和返回错值没有区别。
        4. 子串（``usart``）—— 兜底模糊匹配，限定键参与匹配

        三档都空才轮到下一档，避免 ``USART1`` 这样的输入被第 4 档的松散
        子串结果稀释。
        """
        q = (query or "").strip().upper()
        if not q:
            return [], False

        # 1. 完全限定键
        hit = self._qualified_index.get(q)
        if hit is not None:
            return [hit], False

        # 2. 外设名（是某个限定键的前缀）
        prefix = f"{q}."
        grouped = [v for k, v in self._qualified_index.items()
                   if k.startswith(prefix)]
        if grouped:
            return grouped[:limit], len(grouped) > limit

        # 3. 裸名。歧义时把同名的全部返回，让调用方按 group 挑
        if q in self._duplicate_register_names:
            dup = [v for k, v in self._qualified_index.items()
                   if k.endswith(f".{q}")]
            return dup[:limit], len(dup) > limit
        bare = self._register_index.get(q)
        if bare is not None:
            return [bare], False

        # 4. 子串兜底
        loose = [v for k, v in self._qualified_index.items() if q in k]
        return loose[:limit], len(loose) > limit

    def register_groups(self) -> dict[str, int]:
        """外设组名 → 寄存器数（当前已加载芯片）。

        统计口径走 ``_qualified_index`` 而不是 ``_register_index``：后者只留
        非歧义的裸名（STM32 上 1761 / 2955），拿它算分组会系统性少算。
        """
        counts: dict[str, int] = {}
        for key in self._qualified_index:
            group = key.split(".", 1)[0]
            counts[group] = counts.get(group, 0) + 1
        return counts

    def lookup_register_field(self, reg_name: str,
                               field_name: str,
                               peripheral: str | None = None
                               ) -> dict[str, Any] | None:
        """Look up a specific bit field within a register.

        Args:
            reg_name: Register name, e.g. "UCSR0B"
            field_name: Field name, e.g. "RXEN0"
            peripheral: Optional peripheral instance for qualified lookup.

        Returns:
            Field definition dict with bit, access, description, or None.
        """
        reg = self.lookup_register(reg_name, peripheral=peripheral)
        if not reg:
            return None
        for fld in reg.get("fields", []):
            if fld.get("name", "").upper() == field_name.upper():
                return fld
        return None

    def lookup_field(self, field_name: str) -> dict[str, Any] | None:
        """位域**全名**查找（``USART_CR1_TE`` / ``RXEN0``）。

        与 ``lookup_register_field(reg, field)`` 的分工：后者是「我知道是哪个
        寄存器，问它有没有这一位」；这个是「源码里出现了这个宏名，它是不是
        真位」。STM32 的 CMSIS 位宏自带外设与寄存器前缀，所以全名本身就
        足以定位，不需要先解析出所在寄存器。
        """
        hits = self._field_index.get((field_name or "").upper())
        return hits[0] if hits else None

    def field_prefix_of(self, identifier: str) -> str | None:
        """若标识符形如「已知位宏前缀 + 后缀」，返回该前缀。

        ``GPIO_MODER_BOGUS`` → ``"GPIO_MODER_"``（前缀下有一批真位，说明这是
        打错的位宏）；``GPIO_PIN_7`` → ``None``（寄存器库里没有 ``GPIO_PIN_``
        这一族，它是 HAL 常量，不该判错）。

        按 ``_`` 从右往左逐段截短，所以 ``USART_CR1_TE_BOGUS`` 也能落到
        ``USART_CR1_``。最短 4 字符，挡掉 ``A_`` 这类过短前缀。
        """
        ident = (identifier or "").upper()
        cut = ident.rfind("_")
        while cut > 0:
            head = ident[:cut + 1]
            if len(head) >= 4 and head in self._field_prefixes:
                return head
            cut = ident.rfind("_", 0, cut)
        return None

    def peripheral_names(self) -> set[str]:
        """已知外设实例名（``USART1`` / ``GPIOA`` / ``DMA1``）。"""
        return set(self._peripheral_names)

    def lookup_pin(self, arduino_pin: int) -> dict[str, Any] | None:
        """Look up Arduino pin number → AVR port/bit mapping.

        Args:
            arduino_pin: Arduino digital pin number (0-69 for Mega2560)

        Returns:
            Pin mapping dict with port, bit, register, ddr, pin_reg, $ref, or None.
        """
        return self._pin_index.get(arduino_pin)

    def get_pin_map(self, board_id: str) -> dict[str, Any]:
        """Get the full pin map for a board (read-only copy)."""
        return dict(self._pin_map_cache.get(board_id, {}))

    def get_all_registers(self) -> dict[str, dict[str, Any]]:
        """Get all loaded register entries (read-only snapshot)."""
        return dict(self._register_index)

    def lookup_baud_rate(self, baud: int,
                          board_id: str = "arduino_mega") -> dict[str, Any] | None:
        """Look up baud rate preset for a board.

        Args:
            baud: Baud rate (e.g. 9600, 115200)
            board_id: Board identifier for pin map lookup

        Returns:
            Baud rate preset dict with ubrr, ubrr_hex, error_pct, $ref, or None.
        """
        pin_map = self._pin_map_cache.get(board_id, {})
        presets = pin_map.get("baud_rate_presets", {})
        return presets.get(str(baud))

    def list_registers(self, group: str = "",
                        platform: str = "avr") -> list[dict[str, Any]]:
        """List all registers, optionally filtered by group.

        Args:
            group: Register group name (e.g. "gpio", "usart"). Empty = all.
            platform: Platform identifier

        Returns:
            List of register definition dicts.
        """
        ref_data = self._ref_cache.get(platform, {})
        groups = ref_data.get("register_groups", {})

        if group:
            return groups.get(group, {}).get("registers", [])

        result: list[dict[str, Any]] = []
        for g in groups.values():
            result.extend(g.get("registers", []))
        return result

    # Board knowledge (unchanged from Stage 2)
    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # Stats
    # ------------------------------------------------------------------

    def stats(self) -> dict[str, Any]:
        return {
            "platforms_loaded": list(self._ref_cache.keys()),
            "reference_platforms_loaded": list(self._ref_cache.keys()),
            "total_registers_indexed": len(self._register_index),
            "total_qualified_registers_indexed": len(self._qualified_index),
            "total_field_names_indexed": len(self._field_index),
            "total_peripherals_indexed": len(self._peripheral_names),
            "ambiguous_register_names": sorted(self._duplicate_register_names),
            "total_pins_indexed": len(self._pin_index),
            "pin_maps_loaded": list(self._pin_map_cache.keys()),
            "reference_origin": self.reference_origin(),
        }

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

