#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把报告链接发到邮箱（默认 163 SMTP）。

凭据优先级：
1. 环境变量 SMTP_USER / SMTP_AUTH_CODE
2. %USERPROFILE%\\.trae-mail.json  ->  {"user": "zhshy@163.com", "auth_code": "..."}

用法：
python scripts/send_mail.py --subject "深度纪要 · 2026-11-17 午间" \
    --url "https://zhshy.github.io/..." --note "0 触发 / 1 等待 / 2 过期不追 / 8 无结构"
"""

import argparse
import json
import os
from pathlib import Path
import smtplib
import ssl
import sys
from email.message import EmailMessage
from email.utils import formataddr, formatdate


CONFIG = Path(os.path.expanduser("~")) / ".trae-mail.json"
HOST = "smtp.163.com"
PORT = 465


def credentials():
    user = os.environ.get("SMTP_USER", "").strip()
    code = os.environ.get("SMTP_AUTH_CODE", "").strip()
    if user and code:
        return user, code
    if CONFIG.exists():
        data = json.loads(CONFIG.read_text(encoding="utf-8"))
        return data.get("user", "").strip(), data.get("auth_code", "").strip()
    return "", ""


def build(subject, url, note, as_of):
    html = f"""<!DOCTYPE html>
<html><body style="margin:0;background:#f5f6f8;font-family:-apple-system,'PingFang SC','Microsoft YaHei',sans-serif">
<div style="max-width:600px;margin:0 auto;padding:28px 22px">
  <div style="background:#0f172a;color:#f8fafc;border-radius:12px 12px 0 0;padding:20px 22px">
    <div style="font-size:12px;color:#94a3b8;letter-spacing:.08em">深度投研 · 每日纪要</div>
    <div style="font-size:20px;font-weight:600;margin-top:6px">{subject}</div>
  </div>
  <div style="background:#fff;border:1px solid #e5e7eb;border-top:none;border-radius:0 0 12px 12px;padding:22px">
    <p style="font-size:14px;color:#334155;margin:0 0 8px">{note}</p>
    <p style="font-size:13px;color:#64748b;margin:0 0 18px">数据日：{as_of}</p>
    <a href="{url}" style="display:inline-block;background:#3730a3;color:#fff;text-decoration:none;
       padding:11px 22px;border-radius:8px;font-size:14px">查看完整报告</a>
    <p style="font-size:12px;color:#94a3b8;margin:20px 0 0;word-break:break-all">{url}</p>
  </div>
  <p style="font-size:11px;color:#94a3b8;margin:14px 0 0;text-align:center">
    由 divergence-trade-signals / deep-research-reports 自动发送 · 不构成投资建议
  </p>
</div></body></html>"""
    return html


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--subject", required=True)
    parser.add_argument("--url", required=True)
    parser.add_argument("--note", default="")
    parser.add_argument("--as-of", default="")
    parser.add_argument("--to", default="zhshy@163.com")
    args = parser.parse_args()

    user, code = credentials()
    if not user or not code:
        print("缺少邮箱凭据：请设置环境变量 SMTP_USER / SMTP_AUTH_CODE，"
              f"或写入 {CONFIG}")
        return 2

    message = EmailMessage()
    message["Subject"] = args.subject
    message["From"] = formataddr(("深度投研纪要", user))
    message["To"] = args.to
    message["Date"] = formatdate(localtime=True)
    message.set_content(f"{args.subject}\n\n{args.note}\n\n{args.url}\n")
    message.add_alternative(build(args.subject, args.url, args.note, args.as_of), subtype="html")

    try:
        with smtplib.SMTP_SSL(HOST, PORT, context=ssl.create_default_context(), timeout=30) as smtp:
            smtp.login(user, code)
            smtp.send_message(message)
    except smtplib.SMTPAuthenticationError:
        print("SMTP 认证失败：163 需要「客户端授权码」，不是登录密码")
        return 3
    except Exception as exc:  # noqa: BLE001 - 定时任务只需可见的失败原因
        print(f"发送失败：{type(exc).__name__}: {exc}")
        return 1

    print(f"已发送 -> {args.to}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
