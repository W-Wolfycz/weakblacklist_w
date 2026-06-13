import re as _re
import time
import random
import json
from pathlib import Path
from typing import Dict, Optional, Tuple

from astrbot.api import logger, AstrBotConfig
from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star
from astrbot.core.message.components import Plain


class WeakBlacklistPlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.config = config

        self.base_probability = float(config.get("base_probability", 0.9))
        self.decay_rate = float(config.get("decay_rate", 0.55))
        self.cooldown = self._parse_duration(config.get("cooldown", "10m"))

        log_conf = config.get("log_config", {})
        self.log_with_bot_id = log_conf.get("log_with_bot_id", False)
        self.debug_to_info = log_conf.get("debug_to_info", False)

        # 计数器: {bot_id: {target_id: {"count": int, "block_time": float}}}
        self._counters: Dict[str, Dict[str, Dict]] = {}
        self._data_dir = Path(
            context.get_config().get("plugin.data_dir", "./data")
        ) / "plugin_data" / "weakblacklist"
        self._data_dir.mkdir(parents=True, exist_ok=True)
        self._counters_path = self._data_dir / "counters.json"
        self._load_counters()

        users = set(str(uid) for uid in config.get("blacklisted_users", []))
        groups = set(str(gid) for gid in config.get("blacklisted_groups", []))
        logger.info(
            f"[WeakBlacklist] 已加载，用户: {len(users)} 个，群: {len(groups)} 个"
        )

    # ===================== 日志 =====================

    def _tag(self, event=None) -> str:
        if self.log_with_bot_id and event is not None:
            try:
                return f"[WeakBlacklist:{event.get_platform_id()}]"
            except Exception:
                pass
        return "[WeakBlacklist]"

    def _log_debug(self, event: AstrMessageEvent, msg: str):
        if self.debug_to_info:
            logger.info(f"{self._tag(event)} {msg}")
        else:
            logger.debug(f"{self._tag(event)} {msg}")

    @staticmethod
    def _parse_duration(s: str) -> int:
        """解析 1h30m、5m30s、90s 格式为秒数。"""
        if not s:
            return 0
        s = str(s).strip()
        if s.isdigit():
            return int(s) * 60
        total = 0
        for match in _re.finditer(r'(\d+)\s*(h|m|s)', s.lower()):
            val = int(match.group(1))
            unit = match.group(2)
            if unit == 'h':
                total += val * 3600
            elif unit == 'm':
                total += val * 60
            else:
                total += val
        return total

    # ===================== 持久化 =====================

    def _load_counters(self):
        try:
            if self._counters_path.exists():
                with open(self._counters_path, "r", encoding="utf-8") as f:
                    self._counters = json.load(f)
        except Exception as e:
            logger.error(f"[WeakBlacklist] 加载计数器失败: {e}")
            self._counters = {}

    def _save_counters(self):
        try:
            with open(self._counters_path, "w", encoding="utf-8") as f:
                json.dump(self._counters, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"[WeakBlacklist] 保存计数器失败: {e}")

    # ===================== 计数器操作 =====================

    def _get_counter(self, bot_id: str, target_id: str) -> Tuple[int, float]:
        user_data = self._counters.get(bot_id, {}).get(target_id, {})
        return user_data.get("count", 0), user_data.get("block_time", 0.0)

    def _set_counter(self, bot_id: str, target_id: str, count: int, block_time: float = 0.0):
        if bot_id not in self._counters:
            self._counters[bot_id] = {}
        self._counters[bot_id][target_id] = {
            "count": count,
            "block_time": block_time,
        }

    # ===================== 黑名单检查 =====================

    def _check_blacklist(self, event: AstrMessageEvent) -> Optional[str]:
        sender_id = str(event.get_sender_id())
        group_id = event.get_group_id()

        blacklisted_users = set(
            str(uid) for uid in self.config.get("blacklisted_users", [])
        )
        if sender_id in blacklisted_users:
            return "user", sender_id

        if group_id:
            blacklisted_groups = set(
                str(gid) for gid in self.config.get("blacklisted_groups", [])
            )
            if str(group_id) in blacklisted_groups:
                return "group", str(group_id)

        return None, None

    # ===================== 概率计算 =====================

    def _calc_probability(self, count: int) -> float:
        return self.base_probability * (self.decay_rate ** count)

    # ===================== 钩子 =====================

    @filter.event_message_type(filter.EventMessageType.ALL, priority=5)
    async def check_weak_blacklist(self, event: AstrMessageEvent):
        """唤醒/@ 阶段判定：黑名单用户/群按指数衰减概率决定是否放行，未放行则 stop_event 阻断 LLM 调用。"""
        if not getattr(event, 'is_at_or_wake_command', False):
            return

        bl_type, target_id = self._check_blacklist(event)
        if bl_type is None:
            return

        bot_id = event.get_platform_id()
        count, block_time = self._get_counter(bot_id, target_id)
        now = time.time()

        # 冷却期内直接拦截
        if self.cooldown > 0 and block_time > 0 and (now - block_time) < self.cooldown:
            event.stop_event()
            remaining = int(self.cooldown - (now - block_time))
            self._log_debug(event, f"冷却中 {bl_type}:{target_id} 剩余 {remaining}s")
            return

        # 冷却结束，计数器归零
        if block_time > 0:
            count = 0

        prob = self._calc_probability(count)
        roll = random.random()

        if roll < prob:
            # 放行
            event.set_extra("wb_track", True)
            event.set_extra("wb_bot_id", bot_id)
            event.set_extra("wb_target_id", target_id)
            event.set_extra("wb_count", count)
            self._log_debug(
                event,
                f"放行 {bl_type}:{target_id} count={count} P={prob:.3f} roll={roll:.3f}"
            )
        else:
            # 拦截，记录 block_time 进入冷却
            self._set_counter(bot_id, target_id, 0, block_time=now)
            event.stop_event()
            msg_preview = event.message_str[:50]
            if len(event.message_str) > 50:
                msg_preview += "..."
            logger.info(
                f"{self._tag(event)} 拦截 {bl_type}:{target_id} "
                f"count={count} P={prob:.3f} roll={roll:.3f} 消息:{msg_preview}"
            )

    @filter.on_decorating_result(priority=10)
    async def track_reply(self, event: AstrMessageEvent):
        """BOT 成功回复后递增计数器（连续回复越多，下次放行概率越低）。"""
        if not event.get_extra("wb_track"):
            return

        res = event.get_result()
        if not res or not res.chain:
            return

        reply_text = "".join(
            comp.text for comp in res.chain if isinstance(comp, Plain)
        )
        if not reply_text.strip():
            return

        bot_id = event.get_extra("wb_bot_id")
        target_id = event.get_extra("wb_target_id")
        old_count = event.get_extra("wb_count") or 0

        self._set_counter(bot_id, target_id, old_count + 1)
        self._log_debug(event, f"计数 {target_id} {old_count}->{old_count + 1}")

        event.set_extra("wb_track", False)
        event.set_extra("wb_bot_id", None)
        event.set_extra("wb_target_id", None)
        event.set_extra("wb_count", None)

    async def terminate(self):
        self._save_counters()
        logger.info("[WeakBlacklist] 已停用，计数器已保存")
