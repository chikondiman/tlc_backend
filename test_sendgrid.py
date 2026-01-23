import os
from dotenv import load_dotenv
from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail

load_dotenv()

sg_key = os.getenv("SENDGRID_API_KEY")
from_email = os.getenv("FROM_EMAIL")

if not sg_key or not from_email:
    raise RuntimeError("Missing SENDGRID_API_KEY or FROM_EMAIL in .env")

msg = Mail(
    from_email=from_email,
    to_emails="youremail@example.com",
    subject="Test email from TLC backend",
    html_content="<strong>If you see this, SendGrid works.</strong>",
)

resp = SendGridAPIClient(sg_key).send(msg)
print("Status:", resp.status_code)
