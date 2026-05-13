"""Email stage: send a styled HTML QA report with PNG screenshots via SendGrid."""
from __future__ import annotations

import base64
import html
import logging
import mimetypes
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Optional

import markdown as md
from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import (
    Attachment, ContentId, Disposition, FileContent, FileName, FileType, Mail,
)

log = logging.getLogger(__name__)


class EmailError(RuntimeError):
    pass


def _cfg() -> tuple[str, str]:
    api_key = os.environ.get("SENDGRID_API_KEY", "").strip()
    to_addr = os.environ.get("EMAIL_TO", "").strip()
    if not api_key:
        raise EmailError("SENDGRID_API_KEY missing")
    if not to_addr:
        raise EmailError("EMAIL_TO missing")
    return api_key, to_addr


def _strip_overall_line(text: str) -> str:
    """Remove the explicit OVERALL: PASS/FAIL line so it doesn't render as raw text."""
    return re.sub(r"(?im)^\s*OVERALL\s*:\s*(PASS|FAIL)\s*$", "", text).strip()


def _render_report_html(report_md: str) -> str:
    """Render bug-report.md to HTML, with sensible table + heading styling."""
    body = _strip_overall_line(report_md)
    return md.markdown(body, extensions=["tables", "fenced_code"])


def _build_html(
    *,
    jira_key: str,
    summary: str,
    passed: bool,
    deployment_url: Optional[str],
    pr_url: Optional[str],
    report_md: str,
    screenshot_cids: list[tuple[str, str]],  # [(filename, cid)]
) -> str:
    verdict = "PASS" if passed else "FAIL"
    accent = "#16a34a" if passed else "#dc2626"
    accent_soft = "#dcfce7" if passed else "#fee2e2"
    icon = "✓" if passed else "✕"
    when = datetime.now().strftime("%Y-%m-%d %H:%M UTC%z").strip() or datetime.now().strftime("%Y-%m-%d %H:%M")

    deployment_block = (
        f'<a href="{html.escape(deployment_url)}" '
        f'style="color:#2563eb;text-decoration:none;font-weight:600;">'
        f'{html.escape(deployment_url)}</a>'
        if deployment_url else '<span style="color:#6b7280;">n/a</span>'
    )
    pr_block = (
        f'<a href="{html.escape(pr_url)}" '
        f'style="color:#2563eb;text-decoration:none;font-weight:600;">'
        f'View pull request</a>'
        if pr_url else '<span style="color:#6b7280;">n/a</span>'
    )

    report_html = _render_report_html(report_md)

    gallery_html = ""
    if screenshot_cids:
        items = []
        for fname, cid in screenshot_cids:
            caption = html.escape(Path(fname).stem.replace("-", " ").replace("_", " ").title())
            items.append(
                f'<figure style="margin:0;padding:0;">'
                f'  <img src="cid:{html.escape(cid)}" alt="{caption}" '
                f'       style="width:100%;border:1px solid #e5e7eb;border-radius:8px;display:block;">'
                f'  <figcaption style="font-size:12px;color:#6b7280;padding:6px 4px 0;">{caption}</figcaption>'
                f'</figure>'
            )
        gallery_html = (
            '<h2 style="font-size:16px;margin:24px 0 12px;color:#111827;">Screenshots</h2>'
            '<div style="display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px;">'
            + "".join(items)
            + '</div>'
        )

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>QA Report — {html.escape(jira_key)}</title>
</head>
<body style="margin:0;padding:0;background:#f3f4f6;font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;color:#111827;">
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#f3f4f6;padding:24px 0;">
    <tr><td align="center">
      <table role="presentation" width="640" cellpadding="0" cellspacing="0"
             style="background:#ffffff;border-radius:12px;box-shadow:0 1px 3px rgba(0,0,0,0.08);overflow:hidden;">
        <tr>
          <td style="background:{accent};padding:24px;color:#ffffff;">
            <div style="font-size:12px;letter-spacing:0.12em;opacity:0.85;text-transform:uppercase;">QA Report</div>
            <div style="display:flex;align-items:baseline;gap:12px;margin-top:6px;">
              <span style="font-size:36px;line-height:1;font-weight:700;">{icon} {verdict}</span>
              <span style="font-size:14px;opacity:0.9;">{html.escape(jira_key)}</span>
            </div>
            <div style="font-size:14px;margin-top:8px;opacity:0.95;">{html.escape(summary)}</div>
          </td>
        </tr>
        <tr>
          <td style="padding:20px 24px;background:{accent_soft};border-bottom:1px solid #e5e7eb;">
            <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="font-size:14px;">
              <tr>
                <td style="padding:4px 0;color:#374151;width:120px;">Deployment</td>
                <td style="padding:4px 0;">{deployment_block}</td>
              </tr>
              <tr>
                <td style="padding:4px 0;color:#374151;">Pull request</td>
                <td style="padding:4px 0;">{pr_block}</td>
              </tr>
              <tr>
                <td style="padding:4px 0;color:#374151;">Generated</td>
                <td style="padding:4px 0;color:#374151;">{html.escape(when)}</td>
              </tr>
            </table>
          </td>
        </tr>
        <tr>
          <td style="padding:24px;">
            <div class="report" style="font-size:14px;line-height:1.55;color:#111827;">
              <style>
                .report h1 {{ font-size:20px; margin:0 0 12px; color:#111827; }}
                .report h2 {{ font-size:16px; margin:20px 0 10px; color:#111827; }}
                .report h3 {{ font-size:14px; margin:16px 0 8px; color:#111827; }}
                .report table {{ border-collapse:collapse; width:100%; margin:8px 0 16px; }}
                .report th, .report td {{ border:1px solid #e5e7eb; padding:8px 10px; text-align:left; vertical-align:top; }}
                .report th {{ background:#f9fafb; font-weight:600; }}
                .report code {{ background:#f3f4f6; padding:1px 5px; border-radius:4px; font-family:ui-monospace,SFMono-Regular,Menlo,monospace; font-size:13px; }}
                .report ul, .report ol {{ margin:8px 0 12px 20px; }}
                .report li {{ margin:2px 0; }}
                .report p {{ margin:8px 0; }}
              </style>
              {report_html}
            </div>
            {gallery_html}
          </td>
        </tr>
        <tr>
          <td style="padding:16px 24px;background:#f9fafb;border-top:1px solid #e5e7eb;color:#6b7280;font-size:12px;">
            Auto-generated by the Zero Human Touch Pipeline. Original PNG screenshots
            are attached for download.
          </td>
        </tr>
      </table>
    </td></tr>
  </table>
</body>
</html>"""


def send_qa_report(
    jira_key: str,
    passed: bool,
    report_text: str,
    screenshots: list[str],
    deployment_url: Optional[str] = None,
    pr_url: Optional[str] = None,
    summary: Optional[str] = None,
) -> None:
    api_key, to_addr = _cfg()
    from_addr = os.environ.get("EMAIL_FROM", "").strip() or to_addr
    verdict = "PASS" if passed else "FAIL"
    subject = f"QA Report — {jira_key} — {verdict}"

    # Pre-resolve attachment cids so the same images can be inlined AND attached.
    screenshot_cids: list[tuple[str, str]] = []
    attachments: list[Attachment] = []
    for idx, path_str in enumerate(screenshots, start=1):
        path = Path(path_str)
        if not path.exists() or not path.is_file():
            continue
        mime, _ = mimetypes.guess_type(str(path))
        mime = mime or "application/octet-stream"
        encoded = base64.b64encode(path.read_bytes()).decode("ascii")
        cid = f"qa-img-{idx}"
        att = Attachment(
            FileContent(encoded),
            FileName(path.name),
            FileType(mime),
            Disposition("inline"),
            ContentId(cid),
        )
        attachments.append(att)
        screenshot_cids.append((path.name, cid))

    html_body = _build_html(
        jira_key=jira_key,
        summary=summary or jira_key,
        passed=passed,
        deployment_url=deployment_url,
        pr_url=pr_url,
        report_md=report_text,
        screenshot_cids=screenshot_cids,
    )

    # Plain-text fallback for clients that don't render HTML.
    plain_lines = [
        f"QA Report — {jira_key} — {verdict}",
        "",
    ]
    if summary:
        plain_lines.append(f"Story  : {summary}")
    if deployment_url:
        plain_lines.append(f"Deploy : {deployment_url}")
    if pr_url:
        plain_lines.append(f"PR     : {pr_url}")
    plain_lines.append("")
    plain_lines.append(_strip_overall_line(report_text))
    plain_text = "\n".join(plain_lines)

    message = Mail(
        from_email=from_addr,
        to_emails=to_addr,
        subject=subject,
        plain_text_content=plain_text,
        html_content=html_body,
    )
    for att in attachments:
        message.add_attachment(att)

    log.info(
        "Email: sending QA report (%s) to %s with %d attachment(s)",
        verdict, to_addr, len(attachments),
    )
    client = SendGridAPIClient(api_key)
    try:
        resp = client.send(message)
    except Exception as e:  # noqa: BLE001 — wrap SDK HTTP errors uniformly
        body = getattr(e, "body", b"") or b""
        try:
            body_text = body.decode("utf-8", errors="replace") if isinstance(body, (bytes, bytearray)) else str(body)
        except Exception:  # noqa: BLE001
            body_text = repr(body)
        raise EmailError(
            f"SendGrid send failed: {e.__class__.__name__}: {e}. Body: {body_text[:1000]}"
        ) from e
    if resp.status_code >= 300:
        raise EmailError(f"SendGrid send failed [{resp.status_code}]: {resp.body!r}")
    log.info("Email: sent (status=%d)", resp.status_code)
