import asyncio
import html
import logging
import os
import smtplib
from email.utils import formataddr
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

logger = logging.getLogger("mailer")


def _smtp_configured():
    return all(os.environ.get(key) for key in ("SMTP_HOST", "SMTP_PORT", "SMTP_USER", "SMTP_PASS", "SMTP_FROM"))


def frontend_url():
    return os.environ.get("FRONTEND_URL", "http://localhost:3000").rstrip("/")


def admin_notify_email():
    return os.environ.get("ADMIN_NOTIFY_EMAIL", "rishabh@arevei.com")


def from_header():
    name = os.environ.get("SMTP_FROM_NAME", "AI Manager")
    email_address = os.environ.get("SMTP_FROM", "")
    return formataddr((name, email_address)) if name else email_address


def _base_email(title, eyebrow, body_html, cta_label=None, cta_url=None):
    cta = ""
    fallback = ""
    if cta_label and cta_url:
        safe_url = html.escape(cta_url, quote=True)
        cta = f"""
          <tr>
            <td style="padding:24px 0 8px">
              <a href="{safe_url}" style="display:inline-block;background:#075cff;color:#ffffff;text-decoration:none;font-weight:700;border-radius:999px;padding:13px 22px;font-family:Inter,Arial,sans-serif">{html.escape(cta_label)}</a>
            </td>
          </tr>
        """
        fallback = f"""
          <p style="margin:22px 0 0;color:#64748b;font-size:13px;line-height:20px">If the button does not work, paste this link into your browser:<br>
            <a href="{safe_url}" style="color:#075cff;word-break:break-all">{safe_url}</a>
          </p>
        """
    return f"""<!doctype html>
<html>
  <body style="margin:0;background:#f4f7fb;padding:32px 16px;font-family:Inter,Arial,sans-serif;color:#0f172a">
    <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="max-width:640px;margin:0 auto">
      <tr>
        <td style="padding:0 0 18px">
          <div style="font-size:22px;font-weight:900;letter-spacing:-0.03em;color:#075cff">Arevei</div>
        </td>
      </tr>
      <tr>
        <td style="background:#ffffff;border:1px solid #e2e8f0;border-radius:18px;box-shadow:0 20px 50px rgba(15,23,42,.08);overflow:hidden">
          <div style="height:6px;background:linear-gradient(90deg,#075cff,#14b8a6,#f59e0b)"></div>
          <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="padding:34px">
            <tr><td style="color:#075cff;font-size:12px;font-weight:800;letter-spacing:.18em;text-transform:uppercase">{html.escape(eyebrow)}</td></tr>
            <tr><td><h1 style="margin:10px 0 16px;font-size:30px;line-height:36px;letter-spacing:-0.04em">{html.escape(title)}</h1></td></tr>
            <tr><td style="color:#334155;font-size:16px;line-height:26px">{body_html}</td></tr>
            {cta}
            <tr><td>{fallback}</td></tr>
          </table>
        </td>
      </tr>
      <tr>
        <td style="padding:18px 4px 0;color:#64748b;font-size:12px;line-height:18px">
          This email was sent by Arevei. If you did not request it, you can safely ignore it.
        </td>
      </tr>
    </table>
  </body>
</html>"""


def reset_password_email(name, reset_url):
    safe_name = html.escape(name or "there")
    body = f"""
      <p style="margin:0 0 14px">Hi {safe_name},</p>
      <p style="margin:0 0 14px">We received a request to reset your Arevei password. This secure link expires in 30 minutes and can be used once.</p>
      <p style="margin:0">If this was not you, no action is needed and your current password will keep working.</p>
    """
    return _base_email("Reset your password", "Account Security", body, "Reset password", reset_url)


def welcome_email(name):
    safe_name = html.escape(name or "there")
    body = f"""
      <p style="margin:0 0 14px">Hi {safe_name},</p>
      <p style="margin:0 0 14px">Welcome to Arevei. Your AI website manager is ready to help you build a business brain, plan growth, publish content, and manage customer workflows.</p>
      <p style="margin:0">Open your dashboard to start setting up your workspace.</p>
    """
    return _base_email("Welcome to Arevei", "You're In", body, "Open dashboard", f"{frontend_url()}/app")


def admin_new_user_email(user):
    created_at = html.escape(str(user.get("created_at", "")))
    name = html.escape(user.get("name") or "Unknown")
    email = html.escape(user.get("email") or "")
    body = f"""
      <p style="margin:0 0 14px">A new user created an Arevei account.</p>
      <table role="presentation" cellspacing="0" cellpadding="0" style="width:100%;border-collapse:collapse;font-size:14px">
        <tr><td style="padding:10px;border-bottom:1px solid #e2e8f0;color:#64748b">Name</td><td style="padding:10px;border-bottom:1px solid #e2e8f0;font-weight:700">{name}</td></tr>
        <tr><td style="padding:10px;border-bottom:1px solid #e2e8f0;color:#64748b">Email</td><td style="padding:10px;border-bottom:1px solid #e2e8f0;font-weight:700">{email}</td></tr>
        <tr><td style="padding:10px;color:#64748b">Created</td><td style="padding:10px;font-weight:700">{created_at}</td></tr>
      </table>
    """
    return _base_email("New account created", "Admin Notification", body)


def _send_email_sync(to_email, subject, html_body):
    if not _smtp_configured():
        logger.warning("SMTP is not configured; skipped email to %s", to_email)
        return
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = from_header()
    msg["To"] = to_email
    msg.attach(MIMEText("Please view this email in an HTML-capable email client.", "plain"))
    msg.attach(MIMEText(html_body, "html"))
    port = int(os.environ.get("SMTP_PORT", "465"))
    with smtplib.SMTP_SSL(os.environ["SMTP_HOST"], port, timeout=15) as server:
        server.login(os.environ["SMTP_USER"], os.environ["SMTP_PASS"])
        server.sendmail(os.environ["SMTP_FROM"], [to_email], msg.as_string())


async def send_email(to_email, subject, html_body):
    await asyncio.to_thread(_send_email_sync, to_email, subject, html_body)


def send_email_background(to_email, subject, html_body):
    async def runner():
        try:
            await send_email(to_email, subject, html_body)
        except Exception:
            logger.exception("Failed to send email to %s", to_email)

    asyncio.create_task(runner())
