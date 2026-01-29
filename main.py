import os
import uuid
from typing import Any, Dict, List, Optional
import json
import mysql.connector
import stripe
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request, Header, Body
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, EmailStr
from email_service import send_email, render_order_confirmation_email

load_dotenv()

ADMIN_TOKEN = os.getenv("ADMIN_TOKEN")
print("ADMIN_TOKEN loaded?", bool(ADMIN_TOKEN))

# Stripe config
stripe.api_key = os.getenv("STRIPE_SECRET_KEY")
if not stripe.api_key:
    raise RuntimeError("Missing STRIPE_SECRET_KEY. Check your .env and that load_dotenv() runs.")

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://chikondiman.com",
        "https://chikondiman.com",
        "http://discipline.chikondiman.com",
        "https://discipline.chikondiman.com",
        "http://api.chikondiman.com",
        "https://api.chikondiman.com",
        "https://tlc-frontend-959402527512.us-central1.run.app",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health():
    return {"ok": True}


# Google domain verification
from fastapi.responses import PlainTextResponse

@app.get("/googlec8a91cf65f9b8dd7.html", response_class=PlainTextResponse)
def google_verification():
    return "google-site-verification: googlec8a91cf65f9b8dd7.html"

class AnalyticsEventIn(BaseModel):
    event: str
    video_slug: Optional[str] = None
    path: Optional[str] = None
    session_id: str
    user_id: Optional[str] = None
    context: Optional[Dict[str, Any]] = None

class AnalyticsBatchIn(BaseModel):
    events: List[AnalyticsEventIn]

def get_client_ip(request: Request) -> str | None:

    xff = request.headers.get("x-forwarded-for")
    if xff:
        return xff.split(",")[0].strip()[:45] 

    xri = request.headers.get("x-real-ip")
    if xri:
        return xri.strip()[:45]

    if request.client:
        return (request.client.host or "")[:45]

    return None

@app.post("/api/analytics/events")
async def ingest_analytics(
    payload: Dict[str, Any] | List[Dict[str, Any]] = Body(...),
    request: Request = None,
):
    # Accept BOTH shapes:
    # 1) { events: [...] }
    # 2) [ ... ]
    if isinstance(payload, dict):
        events = payload.get("events") or []
    else:
        events = payload or []

    ua = request.headers.get("user-agent", "")[:255]
    ip = get_client_ip(request)

    print("✅ analytics hit count:", len(events))

    if not events:
        return {"ok": True, "inserted": 0}

    ua = (request.headers.get("user-agent", "") if request else "")[:255]

    db = get_db()
    try:
        cur = db.cursor()

        rows = []
        for ev in events:
            rows.append((
                str(uuid.uuid4()),
                ev.get("event"),
                ev.get("video_slug"),
                ev.get("path"),
                ev.get("session_id"),
                ev.get("user_id"),
                json.dumps(ev.get("context")) if ev.get("context") else None,
                ip,
                ua,
            ))

        cur.executemany(
            """
            INSERT INTO analytics_events
            (id, event, video_slug, path, session_id, user_id, context, ip, user_agent)
            VALUES
            (%s, %s, %s, %s, %s, %s, CAST(%s AS JSON), %s, %s)
            """,
            rows,
        )

        db.commit()
        return {"ok": True, "inserted": len(rows)}
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        db.close()



@app.post("/api/views/{slug}")
def increment_views(slug: str):
    db = get_db()
    try:
        cur = db.cursor(dictionary=True)

        # Upsert-style increment (MySQL)
        cur.execute("SELECT id, views FROM video_views WHERE slug=%s", (slug,))
        row = cur.fetchone()

        if row:
            cur.execute("UPDATE video_views SET views = views + 1 WHERE slug=%s", (slug,))
        else:
            cur.execute(
                "INSERT INTO video_views (id, slug, views) VALUES (%s, %s, %s)",
                (str(uuid.uuid4()), slug, 1),
            )

        db.commit()

        cur.execute("SELECT views FROM video_views WHERE slug=%s", (slug,))
        out = cur.fetchone()
        return {"ok": True, "slug": slug, "views": out["views"] if out else None}

    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        db.close()


@app.get("/api/views/{slug}")
def get_views(slug: str):
    db = get_db()
    try:
        cur = db.cursor(dictionary=True)
        cur.execute("SELECT slug, views FROM video_views WHERE slug=%s", (slug,))
        row = cur.fetchone()
        return {"ok": True, "slug": slug, "views": row["views"] if row else 0}
    finally:
        db.close()


# --- Admin: test email ---
@app.get("/api/admin/test-email")
def test_email(x_admin_token: str | None = Header(default=None)):
    if not ADMIN_TOKEN or x_admin_token != ADMIN_TOKEN:
        raise HTTPException(status_code=401, detail="Unauthorized")

    html = "<h1>Test</h1><p>This is a test email.</p>"
    send_email("chikondiman@gmail.com", "SendGrid test", html)
    return {"ok": True}


# ----------------------------
# Models
# ----------------------------
class Customer(BaseModel):
    name: str
    email: EmailStr
    address: str


class CartItem(BaseModel):
    id: str
    productId: str
    name: str
    price: float
    quantity: int
    category: str
    image: str
    size: Optional[str] = None
    dealId: Optional[str] = None
    isDealHeader: Optional[bool] = False


class CreateOrderPayload(BaseModel):
    customer: Customer
    items: List[CartItem]
    total: float


class CreateCheckoutRequest(BaseModel):
    customer: Customer
    items: List[CartItem]
    total: float
    currency: str = "usd"


class UpdateOrderStatusBody(BaseModel):
    status: str
    tracking_number: str | None = None
    carrier: str | None = None
    note: str | None = None


def render_status_email(display_order: str, status: str, tracking: str | None, carrier: str | None):
    tracking_html = ""
    if tracking:
        tracking_html = f"<p><b>Tracking:</b> {carrier or ''} {tracking}</p>"

    return f"""
    <div style="font-family: Arial, sans-serif; line-height:1.5">
      <h2>Order update: {status}</h2>
      <p>Your order <b>{display_order}</b> is now <b>{status}</b>.</p>
      {tracking_html}
      <p>Thank you for supporting Discipline.</p>
    </div>
    """

# ----------------------------
# Admin: update order status + notify customer
# ----------------------------
@app.post("/api/admin/orders/{order_id}/status")
def update_order_status(
    order_id: str,
    body: UpdateOrderStatusBody,
    x_admin_token: str | None = Header(default=None),
):
    if not ADMIN_TOKEN or x_admin_token != ADMIN_TOKEN:
        raise HTTPException(status_code=401, detail="Unauthorized")

    db = get_db()
    try:
        cur = db.cursor(dictionary=True)

        # ✅ Allow either UUID or numeric order_number in the URL
        if order_id.isdigit():
            cur.execute(
                "SELECT id, order_number, customer_email, status FROM orders WHERE order_number=%s",
                (int(order_id),),
            )
        else:
            cur.execute(
                "SELECT id, order_number, customer_email, status FROM orders WHERE id=%s",
                (order_id,),
            )

        order = cur.fetchone()
        if not order:
            raise HTTPException(status_code=404, detail="Order not found")

        real_id = order["id"]  # internal UUID
        old_status = order["status"]
        new_status = body.status

        cur.execute(
            """
            UPDATE orders
            SET status=%s, tracking_number=%s, carrier=%s
            WHERE id=%s
            """,
            (new_status, body.tracking_number, body.carrier, real_id),
        )
        db.commit()

        # ✅ Customer-facing order label
        display_order = f"D-{int(order['order_number'])}" if order.get("order_number") else real_id

        # Send email for meaningful statuses (admin-controlled)
        if new_status in {"Processing", "Shipped", "Delivered"}:
            html = render_status_email(display_order, new_status, body.tracking_number, body.carrier)
            send_email(order["customer_email"], f"Order update: {new_status}", html)

        return {
            "ok": True,
            "orderId": real_id,  # internal
            "orderNumber": order.get("order_number"),  # numeric public
            "displayOrder": display_order,  # "D-143"
            "old": old_status,
            "new": new_status,
        }

    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


# ----------------------------
# DB helpers
# ----------------------------
def get_db():
    # Cloud Run uses Unix socket via Cloud SQL connector
    instance_connection = os.getenv("INSTANCE_CONNECTION_NAME")
    if instance_connection:
        return mysql.connector.connect(
            unix_socket=f"/cloudsql/{instance_connection}",
            user=os.getenv("MYSQL_USER"),
            password=os.getenv("MYSQL_PASSWORD"),
            database=os.getenv("MYSQL_DATABASE"),
        )
    # Local/direct connection via host/port
    return mysql.connector.connect(
        host=os.getenv("MYSQL_HOST"),
        user=os.getenv("MYSQL_USER"),
        password=os.getenv("MYSQL_PASSWORD"),
        database=os.getenv("MYSQL_DATABASE"),
        port=int(os.getenv("MYSQL_PORT", "3306")),
    )


def compute_total(items: List[CartItem]) -> float:
    return round(sum(float(i.price) * int(i.quantity) for i in items), 2)


def create_order_record(customer: Customer, items: List[CartItem], client_total: float) -> str:
    server_total = compute_total(items)
    if round(server_total, 2) != round(client_total, 2):
        raise HTTPException(
            status_code=400,
            detail=f"Total mismatch client={client_total} server={server_total}",
        )

    order_id = str(uuid.uuid4())

    db = get_db()
    try:
        cur = db.cursor()

        cur.execute(
            """
            INSERT INTO orders (id, customer_name, customer_email, customer_address, total, status)
            VALUES (%s, %s, %s, %s, %s, %s)
            """,
            (order_id, customer.name, customer.email, customer.address, server_total, "Pending Payment"),
        )

        item_sql = """
            INSERT INTO order_items
              (id, order_id, product_id, name, category, image, price, quantity, size, deal_id, is_deal_header)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """

        rows = []
        for item in items:
            rows.append(
                (
                    str(uuid.uuid4()),
                    order_id,
                    item.productId,
                    item.name,
                    item.category,
                    item.image or "",
                    float(item.price),
                    int(item.quantity),
                    item.size,
                    item.dealId,
                    1 if item.isDealHeader else 0,
                )
            )

        if rows:
            cur.executemany(item_sql, rows)

        db.commit()
        return order_id
    except mysql.connector.Error as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"MySQL error: {e}")
    finally:
        db.close()


def attach_payment_intent(order_id: str, payment_intent_id: str):
    db = get_db()
    try:
        cur = db.cursor()
        cur.execute(
            """
            UPDATE orders
            SET payment_intent_id = %s
            WHERE id = %s
            """,
            (payment_intent_id, order_id),
        )
        db.commit()
    except mysql.connector.Error as e:
        db.rollback()
        print("⚠️ attach_payment_intent failed:", e)
    finally:
        db.close()


def get_order_email_and_flags(order_id: str):
    db = get_db()
    try:
        cur = db.cursor(dictionary=True)
        # Try with flag column first
        try:
            cur.execute(
                "SELECT customer_email, confirmation_email_sent FROM orders WHERE id=%s",
                (order_id,),
            )
            row = cur.fetchone()
            if not row:
                return None, True
            return row.get("customer_email"), bool(row.get("confirmation_email_sent"))
        except mysql.connector.Error:
            # Fallback if the column doesn't exist yet
            cur.execute("SELECT customer_email FROM orders WHERE id=%s", (order_id,))
            row = cur.fetchone()
            if not row:
                return None, True
            return row.get("customer_email"), False
    finally:
        db.close()


def get_order_with_items(order_id: str):
    db = get_db()
    try:
        cur = db.cursor(dictionary=True)

        # Order
        cur.execute(
            """
            SELECT id, order_number, customer_name, customer_email, total
            FROM orders
            WHERE id = %s
            """,
            (order_id,),
        )
        order = cur.fetchone()
        if not order:
            return None

        # Items
        cur.execute(
            """
            SELECT name, price, quantity, size
            FROM order_items
            WHERE order_id = %s
            """,
            (order_id,),
        )
        order["items"] = cur.fetchall() or []
        return order
    finally:
        db.close()


def mark_confirmation_email_sent(order_id: str):
    db = get_db()
    try:
        cur = db.cursor()
        try:
            cur.execute("UPDATE orders SET confirmation_email_sent=1 WHERE id=%s", (order_id,))
            db.commit()
        except mysql.connector.Error as e:
            db.rollback()
            print("⚠️ mark_confirmation_email_sent failed:", e)
    finally:
        db.close()


# ----------------------------
# Routes
# ----------------------------
@app.post("/api/orders")
def create_order_in_db(body: CreateOrderPayload):
    order_id = create_order_record(body.customer, body.items, body.total)
    return {"ok": True, "orderId": order_id}


@app.post("/api/checkout/create")
def create_checkout(req: CreateCheckoutRequest):
    if req.total <= 0:
        raise HTTPException(status_code=400, detail="Total must be > 0")

    # 1) Create order in DB (Pending Payment)
    order_id = create_order_record(req.customer, req.items, req.total)

    # ✅ No email here. Email ONLY after payment success (webhook).

    # 2) Create PaymentIntent
    amount_cents = int(round(req.total * 100))

    intent = stripe.PaymentIntent.create(
        amount=amount_cents,
        currency=req.currency,
        automatic_payment_methods={"enabled": True},
        receipt_email=req.customer.email,
        metadata={"order_id": order_id},
    )

    # store payment_intent_id on the order
    attach_payment_intent(order_id, intent["id"])

    return {
        "orderId": order_id,
        "clientSecret": intent["client_secret"],
        "paymentIntentId": intent["id"],
    }


# ----------------------------
# Stripe webhook (send confirmation AFTER success)
# ----------------------------
@app.post("/api/stripe/webhook")
async def stripe_webhook(request: Request):
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature", "")

    endpoint_secret = os.getenv("STRIPE_WEBHOOK_SECRET")
    if not endpoint_secret:
        print("❌ Missing STRIPE_WEBHOOK_SECRET")
        # Return 200 so Stripe doesn't keep retrying locally
        return {"received": True}

    try:
        event = stripe.Webhook.construct_event(payload, sig_header, endpoint_secret)
    except Exception as e:
        print("❌ Webhook signature verification failed:", str(e))
        return {"received": True}

    event_type = event.get("type")
    obj = event.get("data", {}).get("object", {}) or {}

    # (Optional) log all webhook events while testing
    print("✅ webhook event:", event_type)

    if event_type == "payment_intent.succeeded":
        try:
            order_id = (obj.get("metadata") or {}).get("order_id")
            payment_intent_id = obj.get("id")

            print("✅ PI succeeded:", payment_intent_id)
            print("✅ order_id:", order_id)

            if not order_id:
                print("⚠️ No order_id in metadata. Skipping.")
                return {"received": True}

            # 1) Mark paid
            mark_order_paid(order_id, payment_intent_id)

            # 2) Send confirmation email once (with summary)
            customer_email, already_sent = get_order_email_and_flags(order_id)
            print("✅ customer_email:", customer_email, "already_sent:", already_sent)

            if customer_email and not already_sent:
                order = get_order_with_items(order_id)
                if not order:
                    print("⚠️ Order not found in DB for email:", order_id)
                    return {"received": True}

                # ✅ includes items + total
                html = render_order_confirmation_email(order)
                send_email(customer_email, "Order confirmed", html)
                mark_confirmation_email_sent(order_id)
                print("✅ confirmation email sent (with summary)")
            else:
                print("ℹ️ email skipped (missing email or already sent)")

        except Exception as e:
            # Do NOT 500 the webhook. Log the error and return 200.
            print("❌ Error handling payment_intent.succeeded:", repr(e))

    elif event_type == "payment_intent.payment_failed":
        try:
            order_id = (obj.get("metadata") or {}).get("order_id")
            if order_id:
                mark_order_failed(order_id)
        except Exception as e:
            print("❌ Error handling payment_intent.payment_failed:", repr(e))

    return {"received": True}


def mark_order_paid(order_id: str, payment_intent_id: str):
    db = get_db()
    try:
        cur = db.cursor()
        cur.execute(
            """
            UPDATE orders
            SET status = %s, payment_intent_id = %s
            WHERE id = %s
            """,
            ("Paid", payment_intent_id, order_id),
        )
        db.commit()
    except mysql.connector.Error as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"MySQL error: {e}")
    finally:
        db.close()


def mark_order_failed(order_id: str):
    db = get_db()
    try:
        cur = db.cursor()
        cur.execute(
            """
            UPDATE orders
            SET status = %s
            WHERE id = %s
            """,
            ("Payment Failed", order_id),
        )
        db.commit()
    except mysql.connector.Error as e:
        db.rollback()
        print("⚠️ mark_order_failed failed:", e)
    finally:
        db.close()
