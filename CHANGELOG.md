# 更新日志

## 1.0.0
> 2026-05-25

1. 初始版本，基于 astrbot_plugin_weakblacklist 重写
2. 指数衰减概率模型替代固定概率
3. 在 event_message_type 阶段 stop_event()，节省 Token
4. 拦截冷却机制，替代空闲重置
5. 仅处理 @/唤醒消息（is_at_or_wake_command）
6. 计数器 JSON 持久化
