"""
HTML email template builder.
All CSS is inline; no external stylesheets or templating engine.
"""


def build_email_html(
    body: str,
    cta_text: str,
    cta_url: str,
    unsubscribe_url: str,
) -> str:
    """
    Build a complete HTML email given Claude's copy and the pre-signed unsubscribe URL.
    The body text may contain newlines; they are converted to <br> tags.
    """
    body_html = _escape_and_br(body)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>ResumeSetGo</title>
</head>
<body style="margin:0;padding:0;background-color:#f4f4f5;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;">
  <table width="100%" cellpadding="0" cellspacing="0" style="background-color:#f4f4f5;padding:32px 0;">
    <tr>
      <td align="center">
        <table width="580" cellpadding="0" cellspacing="0" style="max-width:580px;width:100%;background-color:#ffffff;border-radius:8px;overflow:hidden;box-shadow:0 1px 3px rgba(0,0,0,0.08);">

          <!-- Header -->
          <tr>
            <td style="padding:28px 40px 20px;border-bottom:1px solid #e5e7eb;">
              <span style="font-size:20px;font-weight:700;color:#4f46e5;letter-spacing:-0.3px;">ResumeSetGo</span>
            </td>
          </tr>

          <!-- Body -->
          <tr>
            <td style="padding:32px 40px 24px;font-size:15px;line-height:1.7;color:#374151;">
              {body_html}
            </td>
          </tr>

          <!-- CTA -->
          <tr>
            <td align="center" style="padding:0 40px 36px;">
              <a href="{cta_url}"
                 style="display:inline-block;background-color:#4f46e5;color:#ffffff;font-size:15px;font-weight:600;text-decoration:none;padding:12px 28px;border-radius:6px;letter-spacing:0.1px;">
                {_escape_html(cta_text)}
              </a>
            </td>
          </tr>

          <!-- Footer -->
          <tr>
            <td style="padding:20px 40px 28px;border-top:1px solid #e5e7eb;font-size:12px;color:#9ca3af;text-align:center;">
              You're receiving this because you have a free ResumeSetGo account.
              <br>
              <a href="{unsubscribe_url}"
                 style="color:#9ca3af;text-decoration:underline;">
                Unsubscribe
              </a>
            </td>
          </tr>

        </table>
      </td>
    </tr>
  </table>
</body>
</html>"""


def _escape_html(text: str) -> str:
    return (
        text
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _escape_and_br(text: str) -> str:
    escaped = _escape_html(text)
    return escaped.replace("\n", "<br>")
