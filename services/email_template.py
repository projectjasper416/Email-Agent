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
<body style="margin:0;padding:0;background-color:#ffffff;font-family:Arial,sans-serif;">
  <div style="display:none;max-height:0px;overflow:hidden;">A message from ResumeSetGo.</div>
  <table width="100%" cellpadding="0" cellspacing="0" border="0" style="background-color:#ffffff;">
    <tr>
      <td align="center" style="padding:40px 16px 24px;">
        <table width="560" cellpadding="0" cellspacing="0" border="0" style="max-width:560px;width:100%;">

          <!-- Logo -->
          <tr>
            <td align="center" style="padding-bottom:36px;">
              <a href="https://resumesetgo.in" target="_blank" style="text-decoration:none;">
                <img src="https://resumesetgo.in/images/RSGLogoHorizontalRedBlack.png"
                     alt="ResumeSetGo" width="180"
                     style="display:block;width:180px;height:auto;border:0;">
              </a>
            </td>
          </tr>

          <!-- Card -->
          <tr>
            <td style="background-color:#fafafa;border-radius:12px;border:1px solid #f0f0f0;padding:44px 40px 40px;">

              <!-- Body -->
              <div style="font-size:15px;line-height:1.7;color:#444444;">
                {body_html}
              </div>

              <!-- CTA -->
              <table width="100%" cellpadding="0" cellspacing="0" border="0">
                <tr>
                  <td align="center" style="padding:32px 0 8px;">
                    <a href="{cta_url}" target="_blank"
                       style="display:inline-block;background-color:#ef2020;color:#ffffff;font-size:15px;font-weight:600;text-decoration:none;padding:13px 30px;border-radius:6px;letter-spacing:0.1px;">
                      {_escape_html(cta_text)}
                    </a>
                  </td>
                </tr>
              </table>

              <hr style="border:none;border-top:1px solid #ebebeb;margin:28px 0 20px 0;">

              <p style="margin:0;font-size:13px;line-height:20px;color:#aaaaaa;">
                Still having trouble? Reply to this email or reach out through our
                <a href="https://resumesetgo.in/support" target="_blank" style="color:#ef2020;text-decoration:underline;">support page</a>
                — we're happy to help you get up and running.
              </p>
            </td>
          </tr>

          <!-- Footer -->
          <tr>
            <td align="center" style="padding:28px 0 16px;font-family:Arial,sans-serif;">
              <p style="margin:0 0 6px;line-height:18px;font-size:12px;color:#bbbbbb;">
                Jasper Technologies Pvt. Ltd. · Hyderabad, India
              </p>
              <p style="margin:0;font-size:12px;color:#bbbbbb;">
                <a href="https://resumesetgo.in/privacy" target="_blank" style="color:#bbbbbb;text-decoration:underline;">Privacy Policy</a>
                &nbsp;·&nbsp;
                <a href="https://resumesetgo.in/terms" target="_blank" style="color:#bbbbbb;text-decoration:underline;">Terms of Service</a>
                &nbsp;·&nbsp;
                <a href="https://resumesetgo.in" target="_blank" style="color:#bbbbbb;text-decoration:underline;">resumesetgo.in</a>
              </p>
              <p style="margin:12px 0 0;font-size:12px;color:#bbbbbb;">
                <a href="{unsubscribe_url}" target="_blank" style="color:#bbbbbb;text-decoration:underline;">Unsubscribe</a>
              </p>
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
