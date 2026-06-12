"""Seed the database with mock CRM data.

Orders cover every decision path: APPROVE (in-window, sealed or defective, under
the manager-approval threshold), DENY (out-of-window, opened non-defective, final
sale, already refunded), and ESCALATE (over the threshold). Delivery dates are
relative to seed time so the 30-day-window cases stay valid on every reseed.

Run: uv run python -m app.db.seed
"""

import asyncio
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import delete

from app.db.database import Base, SessionFactory, create_all, drop_all
from app.db.models import Customer, CustomerTier, Order, OrderStatus

# id, name, email, phone, tier
_CUSTOMERS = [
    ("cust-1", "Aarav Sharma", "aarav.sharma@example.com", "+91-98200-41001", CustomerTier.VIP),
    ("cust-2", "Vivaan Patel", "vivaan.patel@example.com", "+91-99001-52002", CustomerTier.REGULAR),
    ("cust-3", "Diya Reddy", "diya.reddy@example.com", "+91-97411-63003", CustomerTier.REGULAR),
    ("cust-4", "Aditya Iyer", "aditya.iyer@example.com", "+91-98860-74004", CustomerTier.REGULAR),
    ("cust-5", "Ananya Nair", "ananya.nair@example.com", "+91-99720-85005", CustomerTier.VIP),
    ("cust-6", "Rohan Mehta", "rohan.mehta@example.com", "+91-98330-96006", CustomerTier.REGULAR),
    ("cust-7", "Saanvi Gupta", "saanvi.gupta@example.com", "+91-90080-17007", CustomerTier.REGULAR),
    ("cust-8", "Arjun Singh", "arjun.singh@example.com", "+91-99100-28008", CustomerTier.REGULAR),
    ("cust-9", "Ishaan Verma", "ishaan.verma@example.com", "+91-98450-39009", CustomerTier.VIP),
    ("cust-10", "Kavya Rao", "kavya.rao@example.com", "+91-97390-40010", CustomerTier.REGULAR),
    ("cust-11", "Karthik Menon", "karthik.menon@example.com", None, CustomerTier.REGULAR),
    ("cust-12", "Priya Joshi", "priya.joshi@example.com", None, CustomerTier.REGULAR),
    ("cust-13", "Meera Das", "meera.das@example.com", None, CustomerTier.REGULAR),
    ("cust-14", "Rahul Kapoor", "rahul.kapoor@example.com", "+91-99670-54014", CustomerTier.VIP),
    ("cust-15", "Sneha Pillai", "sneha.pillai@example.com", None, CustomerTier.REGULAR),
]

# id, customer_id, product, category, amount, delivered_days_ago,
# opened, defective, final_sale, refunded_days_ago (None if not refunded)
_ORDERS = [
    ("ORD-1001", "cust-1", "Sony WH-1000XM5 Headphones", "audio", "26990.00", 9, False, False, False, None),
    ("ORD-1002", "cust-1", "MacBook Pro 16-inch", "laptop", "239900.00", 5, False, False, False, None),
    ("ORD-1003", "cust-1", "USB-C Charging Cable", "accessory", "799.00", 40, False, False, False, None),
    ("ORD-1010", "cust-2", "Dell UltraSharp Monitor", "accessory", "38990.00", 12, False, False, False, 5),
    ("ORD-1011", "cust-2", "Logitech MX Keys Keyboard", "accessory", "9995.00", 56, False, False, False, None),
    ("ORD-1020", "cust-3", "AirPods Pro", "audio", "24900.00", 8, True, False, False, None),
    ("ORD-1021", "cust-3", "Anker Power Bank", "accessory", "3499.00", 7, True, True, False, None),
    ("ORD-1030", "cust-4", "Clearance Webcam", "accessory", "4999.00", 6, False, False, True, None),
    ("ORD-1031", "cust-4", "Razer Gaming Mouse", "accessory", "6999.00", 4, True, False, False, None),
    ("ORD-1040", "cust-5", "iPad Air", "laptop", "59900.00", 10, False, False, False, None),
    ("ORD-1041", "cust-5", "Samsung Galaxy Buds", "audio", "11999.00", 3, False, False, False, None),
    ("ORD-1050", "cust-6", "LG OLED TV 55-inch", "accessory", "179990.00", 14, False, False, False, None),
    ("ORD-1051", "cust-6", "HDMI 2.1 Cable", "accessory", "699.00", 20, False, False, False, None),
    ("ORD-1060", "cust-7", "Bose SoundLink Speaker", "audio", "12900.00", 2, False, False, False, None),
    ("ORD-1061", "cust-7", "Keychron Mechanical Keyboard", "accessory", "8999.00", 35, False, False, False, None),
    ("ORD-1070", "cust-8", "Kindle Paperwhite", "accessory", "13999.00", 9, True, True, False, None),
    ("ORD-1071", "cust-8", "Phone Case", "accessory", "1299.00", 1, False, False, True, None),
    ("ORD-1080", "cust-9", "Dell XPS 15 Laptop", "laptop", "149990.00", 6, False, False, False, None),
    ("ORD-1090", "cust-10", "Sony Alpha A7 Camera", "accessory", "219990.00", 18, True, False, False, None),
    ("ORD-1100", "cust-11", "JBL Wireless Earbuds", "audio", "4999.00", 25, False, False, False, None),
    ("ORD-1110", "cust-12", "Gaming Monitor 27-inch", "accessory", "32900.00", 70, False, False, False, None),
    ("ORD-1120", "cust-13", "Garmin Smartwatch", "accessory", "29990.00", 5, True, True, False, None),
    ("ORD-1130", "cust-14", "Surface Laptop 5", "laptop", "129990.00", 11, False, False, False, None),
    ("ORD-1131", "cust-14", "Wireless Charger", "accessory", "2499.00", 3, False, False, False, None),
    ("ORD-1140", "cust-15", "Sennheiser Headphones", "audio", "14990.00", 45, False, False, False, None),
    ("ORD-1141", "cust-15", "1080p Webcam", "accessory", "3999.00", 2, True, False, False, None),
]


def _build_customers() -> list[Customer]:
    return [
        Customer(id=cid, name=name, email=email, phone=phone, tier=tier)
        for cid, name, email, phone, tier in _CUSTOMERS
    ]


def _build_orders(now: datetime) -> list[Order]:
    orders = []
    for oid, cid, product, category, amount, dday, opened, defective, final, refunded in _ORDERS:
        delivered = now - timedelta(days=dday)
        orders.append(
            Order(
                id=oid,
                customer_id=cid,
                product_name=product,
                category=category,
                amount=Decimal(amount),
                currency="INR",
                quantity=1,
                order_date=delivered - timedelta(days=3),
                delivered_at=delivered,
                status=OrderStatus.DELIVERED,
                is_opened=opened,
                is_defective=defective,
                is_final_sale=final,
                refunded_at=now - timedelta(days=refunded) if refunded is not None else None,
            )
        )
    return orders


async def _clear(session) -> None:
    for table in reversed(Base.metadata.sorted_tables):
        await session.execute(delete(table))


async def seed() -> None:
    await drop_all()  # rebuild the schema so model changes (new columns) take effect
    await create_all()
    now = datetime.now(timezone.utc)
    async with SessionFactory() as session:
        await _clear(session)
        session.add_all(_build_customers())
        session.add_all(_build_orders(now))
        await session.commit()
    print(f"Seeded {len(_CUSTOMERS)} customers and {len(_ORDERS)} orders.")


if __name__ == "__main__":
    asyncio.run(seed())
