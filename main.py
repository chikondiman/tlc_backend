import os
import uuid
from typing import List, Optional

import mysql.connector
import stripe
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, EmailStr

load_dotenv()

# Stripe config (don't crash at import)
stripe.api_key = os.getenv("STRIPE_SECRET_KEY")
if not stripe.api_key:
    raise RuntimeError("Missing STRIPE_SECRET_KEY. Check your .env and that load_dotenv() runs.")

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",  # Vite
        "http://localhost:3000",  # CRA (optional)
        "http://chikondiman.com",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/health")
def health():
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


# ----------------------------
# DB helpers
# ----------------------------
def get_db():
    return mysql.connector.connect(
        host=os.getenv("MYSQL_HOST"),
        user=os.getenv("MYSQL_USER"),
        password=os.getenv("MYSQL_PASSWORD"),
        database=os.getenv("MYSQL_DATABASE"),
        port=int(os.getenv("MYSQL_PORT", "3306")),
    )

def compute_total(items: List[CartItem]) -> float:
    # IMPORTANT: deal children should have price 0 in your cart design
    return round(sum(float(i.price) * int(i.quantity) for i in items), 2)

def create_order_record(customer: Customer, items: List[CartItem], client_total: float) -> str:
    """
    Inserts into orders + order_items and returns order_id.
    Uses UUIDs for orders.id and order_items.id.
    """
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

        # Insert order
        cur.execute(
            """
            INSERT INTO orders (id, customer_name, customer_email, customer_address, total, status)
            VALUES (%s, %s, %s, %s, %s, %s)
            """,
            (
                order_id,
                customer.name,
                customer.email,
                customer.address,
                server_total,
                "Pending Payment",
            ),
        )

        # Insert items (generate a new UUID per row)
        item_sql = """
            INSERT INTO order_items
              (id, order_id, product_id, name, category, image, price, quantity, size, deal_id, is_deal_header)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """

        rows = []
        for item in items:
            rows.append(
                (
                    str(uuid.uuid4()),                     # ✅ unique per order item row
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

    # 2) Create PaymentIntent
    amount_cents = int(round(req.total * 100))

    intent = stripe.PaymentIntent.create(
        amount=amount_cents,
        currency=req.currency,
        automatic_payment_methods={"enabled": True},
        receipt_email=req.customer.email,
        metadata={"order_id": order_id},
    )

    # Optional: store payment_intent_id on the order
    attach_payment_intent(order_id, intent["id"])

    return {"orderId": order_id, "clientSecret": intent["client_secret"]}


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
    except mysql.connector.Error:
        db.rollback()
    finally:
        db.close()


# ----------------------------
# Stripe webhook
# ----------------------------
@app.post("/api/stripe/webhook")
async def stripe_webhook(request: Request):
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature", "")

    endpoint_secret = os.getenv("STRIPE_WEBHOOK_SECRET")
    if not endpoint_secret:
        raise HTTPException(status_code=500, detail="Missing STRIPE_WEBHOOK_SECRET")

    try:
        event = stripe.Webhook.construct_event(payload, sig_header, endpoint_secret)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

    if event["type"] == "payment_intent.succeeded":
        intent = event["data"]["object"]
        order_id = intent.get("metadata", {}).get("order_id")
        if order_id:
            mark_order_paid(order_id, intent["id"])

    elif event["type"] == "payment_intent.payment_failed":
        intent = event["data"]["object"]
        order_id = intent.get("metadata", {}).get("order_id")
        if order_id:
            mark_order_failed(order_id)

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
    except mysql.connector.Error:
        db.rollback()
    finally:
        db.close()
