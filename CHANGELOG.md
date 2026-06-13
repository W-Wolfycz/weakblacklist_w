# 更新日志

## 1.1.0
> 2026-06-14

- 统一所有日志前缀为 `[WeakBlacklist]`
- 新增 `log_config` 配置组（替换原 `log_blocked_messages`）：
  - `log_with_bot_id`：日志前缀附加机器人实例 ID
  - `debug_to_info`：debug 日志（放行/冷却/计数）提级为 info 输出
- 拦截事件始终以 info 级别输出，不再受日志开关控制

---

## 1.0.0
> 2026-05-25

1. 初始版本，基于 astrbot_plugin_weakblacklist 重写
2. 指数衰减概率模型替代固定概率
3. 在 event_message_type 阶段 stop_event()，节省 Token
4. 拦截冷却机制，替代空闲重置
5. 仅处理 @/唤醒消息（is_at_or_wake_command）
6. 计数器 JSON 持久化
