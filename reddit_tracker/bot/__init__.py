"""Telegram bot 模組 — M4 推送層。

`formatter` 是純函式（測試用）；`handlers` 是 async callbacks；`sender` 把
record_pushes() 寫過的 DailyPush row 真送出去並回寫 pushed_at；`app` 是
Application bootstrap 跟指令註冊。
"""
