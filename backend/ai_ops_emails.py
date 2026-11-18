"""HTML emails for the daily AI run: the owner's strategy brief and messages to leads."""
import html
from datetime import datetime
from zoneinfo import ZoneInfo

from mailer import _base_email, frontend_url


def esc(value):
    return html.escape(str(value if value is not None else ""))


def paragraphs(text):
    """Plain text (blank-line separated) to safe HTML paragraphs."""
    blocks = [block.strip() for block in str(text or "").replace("\r\n", "\n").split("\n\n") if block.strip()]
    return "".join(f'<p style="margin:0 0 14px">{esc(block).replace(chr(10), "<br>")}</p>' for block in blocks)


def simple_email(title, eyebrow, lines, cta_label=None, cta_url=None):
    return _base_email(title, eyebrow, "".join(f'<p style="margin:0 0 14px">{esc(line)}</p>' for line in lines), cta_label, cta_url)


def when_text(value, zone_name):
    """'Tue 18 Nov, 3:30 PM (Asia/Kolkata)' for an ISO instant in the workspace timezone."""
    try:
        moment = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        local = moment.astimezone(ZoneInfo(zone_name))
    except Exception:
        return str(value or "")
    hour = local.hour % 12 or 12
    return f"{local:%a} {local.day} {local:%b}, {hour}:{local:%M} {'AM' if local.hour < 12 else 'PM'} ({zone_name})"


def time_text(value, zone_name):
    try:
        local = datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone(ZoneInfo(zone_name))
    except Exception:
        return ""
    hour = local.hour % 12 or 12
    return f"{hour}:{local:%M} {'AM' if local.hour < 12 else 'PM'}"


def plan_url(ws_id, query=""):
    return f"{frontend_url()}/app/w/{ws_id}/daily-plan{query}"


def lead_email(business_name, body_text, footer_note=""):
    """A plain, personal-looking message to a lead, without platform call-to-action chrome."""
    footer = esc(footer_note or f"Sent on behalf of {business_name}. Reply to this email to reach the team.")
    return f"""<!doctype html>
<html><body style="margin:0;background:#ffffff;padding:24px 16px;font-family:Arial,Helvetica,sans-serif;color:#0f172a">
<table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="max-width:600px;margin:0 auto">
<tr><td style="font-size:15px;line-height:24px;color:#1e293b">{paragraphs(body_text)}</td></tr>
<tr><td style="padding-top:18px;border-top:1px solid #e2e8f0;color:#64748b;font-size:12px;line-height:18px">{footer}</td></tr>
</table></body></html>"""


def _rows(items, columns):
    if not items:
        return ""
    head = "".join(f'<th align="left" style="padding:8px 10px;border-bottom:2px solid #e2e8f0;color:#64748b;font-size:12px;text-transform:uppercase;letter-spacing:.06em">{esc(label)}</th>' for label, _ in columns)
    body = "".join("<tr>" + "".join(f'<td style="padding:9px 10px;border-bottom:1px solid #eef2f7;font-size:14px;vertical-align:top">{esc(getter(item))}</td>' for _, getter in columns) + "</tr>" for item in items)
    return f'<table role="presentation" cellspacing="0" cellpadding="0" style="width:100%;border-collapse:collapse;margin:0 0 18px"><tr>{head}</tr>{body}</table>'


def _heading(text):
    return f'<h2 style="margin:22px 0 10px;font-size:17px;line-height:24px;color:#0f172a">{esc(text)}</h2>'


ACTION_LABELS = {"call": "AI call", "email": "Email", "task": "For you", "lead_request": "Lead request"}


def daily_brief_email(ws, run, actions, meetings, zone_name, approve_link=""):
    strategy = run.get("strategy") or {}
    stats = run.get("stats") or {}
    parts = [f'<p style="margin:0 0 14px">{esc(strategy.get("summary"))}</p>']
    focus = [item for item in strategy.get("focus") or [] if item]
    if focus:
        parts.append(_heading("Today's focus"))
        parts.append('<ul style="margin:0 0 14px;padding-left:20px">' + "".join(f'<li style="margin:0 0 6px">{esc(item)}</li>' for item in focus) + "</ul>")
    stage_rows = [{"stage": label, "count": count} for label, count in (stats.get("stage_counts") or {}).items()]
    if stage_rows:
        parts.append(_heading("Where your leads stand"))
        parts.append(_rows(stage_rows, [("Stage", lambda r: r["stage"]), ("Leads", lambda r: r["count"])]))
    if strategy.get("pipeline_strategy"):
        parts.append(_heading("Sales pipeline"))
        parts.append(f'<p style="margin:0 0 14px">{esc(strategy["pipeline_strategy"])}</p>')
    if strategy.get("customer_strategy"):
        parts.append(_heading("Existing customers"))
        parts.append(f'<p style="margin:0 0 14px">{esc(strategy["customer_strategy"])}</p>')
    planned = [a for a in actions if a["status"] in {"scheduled", "awaiting_approval"}]
    manual = [a for a in actions if a["status"] == "suggested"]
    waiting = any(a["status"] == "awaiting_approval" for a in planned)
    columns = [("Time", lambda a: time_text(a.get("scheduled_for"), zone_name)),
               ("Lead", lambda a: f"{a.get('lead_name')} · {a.get('stage_label')}" if a.get("stage_label") else a.get("lead_name")),
               ("Action", lambda a: a.get("purpose_label") or ACTION_LABELS.get(a["kind"], a["kind"])), ("Why", lambda a: a.get("reason"))]
    if planned:
        parts.append(_heading(f"Today's plan ({len(planned)} actions)"))
        if waiting:
            parts.append('<p style="margin:0 0 14px">Nothing below runs until you approve the plan. You can remove or change any action first.</p>')
        teams = {}
        for action in planned:  # one block per agent, in the order the plan runs
            teams.setdefault(action.get("agent_name") or "AI Manager", []).append(action)
        for name, items in teams.items():
            parts.append(f'<p style="margin:16px 0 6px;font-weight:700;color:#0f172a">{esc(name)} <span style="font-weight:400;color:#64748b">· {len(items)} action{"s" if len(items) != 1 else ""}</span></p>')
            parts.append(_rows(items[:25], columns))
    if manual:
        parts.append(_heading(f"For you and your team ({len(manual)})"))
        parts.append(_rows(manual[:40], columns[1:]))
    if not (planned or manual):
        parts.append('<p style="margin:0 0 14px">No lead needs action today. I will check again tomorrow.</p>')
    if stats.get("resting"):
        parts.append(f'<p style="margin:0 0 14px;color:#64748b;font-size:13px">{esc(stats["resting"])} leads are left alone today because they have no current requirement or were already followed up enough.</p>')
    if meetings:
        parts.append(_heading("Upcoming meetings"))
        parts.append(_rows(meetings[:20], [("When", lambda m: when_text(m.get("start"), zone_name)), ("Lead", lambda m: m.get("lead_name")),
                                           ("Status", lambda m: str(m.get("status", "")).replace("_", " ").title())]))
    previous = run.get("previous_results") or {}
    if any(previous.values()):
        parts.append(_heading("Since the last run"))
        parts.append(f'<p style="margin:0 0 14px">{previous.get("calls", 0)} AI calls, {previous.get("emails", 0)} emails sent, '
                     f'{previous.get("meetings", 0)} meetings arranged, {previous.get("failed", 0)} actions that could not be completed.</p>')
    risks = [item for item in strategy.get("risks") or [] if item]
    if risks:
        parts.append(_heading("Watch out for"))
        parts.append('<ul style="margin:0 0 14px;padding-left:20px">' + "".join(f'<li style="margin:0 0 6px">{esc(item)}</li>' for item in risks) + "</ul>")
    if run.get("strategy_source") != "ai":
        parts.append('<p style="margin:14px 0 0;color:#64748b;font-size:13px">The AI model was unavailable for this run, so this plan was built from your CRM rules only.</p>')
    title = strategy.get("headline") or f"Daily plan for {ws.get('name') or 'your business'}"
    app_link = plan_url(str(ws["_id"]))
    if waiting:
        parts.append(f'<p style="margin:14px 0 0;font-size:14px">To change an action, a lead or an email before approving, <a href="{esc(app_link)}" style="color:#075cff">edit the plan in the app</a>.</p>')
        return _base_email(title[:120], f"Daily AI plan · {run.get('day', '')}", "".join(parts), "Review and approve the plan", approve_link or app_link)
    return _base_email(title[:120], f"Daily AI plan · {run.get('day', '')}", "".join(parts), "Open today's plan", app_link)


def meeting_admin_email(ws, meeting, zone_name, calendar_connected):
    confirmed = meeting["status"] == "confirmed"
    lines = [f"{meeting['lead_name']} asked for a meeting during a call." + (f" They said: “{meeting['requested_text']}”" if meeting.get("requested_text") else "")]
    lines.append(("I booked it for " if confirmed else "Proposed time: ") + when_text(meeting["start"], zone_name) + f" ({meeting['duration_minutes']} minutes).")
    if meeting.get("slot_note"):
        lines.append(meeting["slot_note"])
    if not calendar_connected:
        lines.append("No calendar is connected, so I could not check your availability. Connect Google Calendar in Settings to avoid clashes.")
    if confirmed:
        lines.append("The lead has been emailed this time." if meeting.get("lead_notified") else "The lead has no email on file, so please confirm the time with them by phone.")
        lines.append("If this time does not suit you, choose another and I will email the lead the new time.")
    else:
        lines.append("Confirm this time or choose another. The lead is emailed only after you decide.")
    return simple_email("Meeting booked" if confirmed else "Meeting request needs your decision", "Meeting", lines,
                        "Change the time" if confirmed else "Confirm or change", plan_url(str(ws["_id"]), f"?meeting={meeting['_id']}"))


def meeting_lead_text(business_name, lead_name, meeting, zone_name, change):
    first = (lead_name or "").split(" ")[0] or "there"
    when = when_text(meeting["start"], zone_name)
    if change == "cancelled":
        body = f"Hi {first},\n\nOur meeting planned for {when} has been cancelled. We will be in touch to arrange a new time.\n\nReply to this email if you have any questions."
    elif change == "rescheduled":
        body = f"Hi {first},\n\nWe need to move our meeting. The new time is {when} ({meeting['duration_minutes']} minutes).\n\nIf this does not work for you, reply to this email with a time that suits you."
    else:
        body = f"Hi {first},\n\nThank you for speaking with us. Your meeting is confirmed for {when} ({meeting['duration_minutes']} minutes).\n\nIf you need a different time, reply to this email and we will rearrange it."
    if meeting.get("admin_note"):
        body += f"\n\n{meeting['admin_note']}"
    return body + f"\n\n{business_name}"


def lead_request_admin_email(ws, action):
    lines = [f"{action['lead_name']} raised something on a call that needs your answer:"]
    lines.extend(f"• {item}" for item in (action.get("payload") or {}).get("requests", [])[:8])
    lines.append("Write your answer on the daily plan page and I will email it to the lead.")
    return simple_email("A lead needs your answer", "Lead request", lines, "Reply to the lead", plan_url(str(ws["_id"]), f"?request={action['_id']}"))
