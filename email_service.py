import os
from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail

from urllib.error import URLError
import socket

def send_email(to_email: str, subject: str, html: str):
    api_key = os.getenv("SENDGRID_API_KEY")
    from_email = os.getenv("FROM_EMAIL")
    if not api_key or not from_email:
        raise RuntimeError("Missing SENDGRID_API_KEY or FROM_EMAIL")

    try:
        # quick DNS check
        socket.gethostbyname("api.sendgrid.com")
        msg = Mail(from_email=from_email, to_emails=to_email, subject=subject, html_content=html)
        resp = SendGridAPIClient(api_key).send(msg)
        print("✅ SendGrid status:", resp.status_code)
        return resp.status_code
    except URLError as e:
        print("❌ Network error reaching SendGrid:", e)
        raise
    except Exception as e:
        print("❌ SendGrid send failed:", e)
        raise


def render_order_confirmation_email(order: dict) -> str:
    display_order = f"D-{int(order['order_number'])}" if order.get("order_number") else order["id"]

    rows_html = ""
    for it in order.get("items", []):
        rows_html += f"""
          <tr style="border-bottom:1px solid #eee">
            <td>{it['name']}</td>
            <td align="center">{it['quantity']}</td>
            <td align="right">${float(it['price']):.2f}</td>
          </tr>
        """

    return f"""
    <div style="font-family: Arial, sans-serif; max-width:600px">
      <h2>Order confirmed</h2>
      <p>Thanks for your order, {order['customer_name']}.</p>

      <p><b>Order Number:</b> {display_order}</p>

      <table width="100%" cellpadding="8" cellspacing="0" style="border-collapse: collapse;">
        <thead>
          <tr style="border-bottom:1px solid #ddd">
            <th align="left">Item</th>
            <th align="center">Qty</th>
            <th align="right">Price</th>
          </tr>
        </thead>
        <tbody>
          {rows_html}
        </tbody>
      </table>

      <p style="text-align:right; font-size:16px;"><b>Total:</b> ${float(order['total']):.2f}</p>

      <p>We'll notify you when your order ships.</p>
      <p>Thank you for supporting <b>Discipline</b>.</p>
    </div>
    """