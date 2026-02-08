# backend/app.py
import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import uuid
from fastapi import FastAPI, UploadFile, File, HTTPException, BackgroundTasks,Body
from fastapi.responses import JSONResponse
from auth import router as auth_router
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel  # using simple str for email to avoid extra deps
from dotenv import load_dotenv
import certifi
from motor.motor_asyncio import AsyncIOMotorClient
# from utils.inference import run_inference
from fastapi.staticfiles import StaticFiles
from database import bookings_collection
from routes.valuation_routes import router as valuation_router
from routes import listings, payments,orders,marketplace,users
import razorpay
import os

ENV = os.getenv("ENV", "development")

def run_ml_inference(image_bytes: bytes):
    from utils.inference import run_inference  # lazy import
    return run_inference(image_bytes)


load_dotenv()

app = FastAPI()


# ---------- Middleware ----------

app.add_middleware(
    CORSMiddleware,
    allow_origin="https://ewaste-frontend-bice.vercel.app",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router)
app.include_router(valuation_router)
app.include_router(listings.router)
app.include_router(orders.router)
app.include_router(users.router)
app.include_router(marketplace.router)
app.mount("/uploads", StaticFiles(directory="uploads"), name="uploads")


# ---------- check backend is running----------
@app.get("/")
def root():
    return {"status": "ok", "message": "E-waste backend running"}


# ---------- load credentials from .env----------

FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:3000")
SMTP_HOST = os.getenv("SMTP_HOST")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USERNAME = os.getenv("SMTP_USERNAME")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD")
SMTP_FROM = os.getenv("SMTP_FROM", SMTP_USERNAME or "")




# ---------- MODELS ----------

class BookingRequest(BaseModel):
    userId: str
    userEmail: str
    fullName: str
    address: str
    phone: str
    pickupDate: str
    pickupTime: str
    facility: str
    recycleItemPrice: float
    recycleItem: str | None = None  



# ---------- EMAIL CONFIG ----------

SMTP_HOST = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USERNAME = os.getenv("SMTP_USERNAME")  # your email / SMTP username
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD")  # app password or SMTP password
FROM_EMAIL = os.getenv("FROM_EMAIL", SMTP_USERNAME or "no-reply@example.com")


def send_booking_email(booking: BookingRequest):
    """
    Send booking confirmation email to the customer.
    Runs in a background task so it won't block the API response.
    """
    if not (SMTP_USERNAME and SMTP_PASSWORD):
        # For dev, just log instead of breaking the request
        print("⚠ SMTP credentials not configured. Skipping email send.")
        print("Booking details:", booking.model_dump())
        return

    subject = f"E-Waste Pickup Booking Confirmation - {booking.pickupDate} {booking.pickupTime}"

    body = f"""Hi {booking.fullName},

Thank you for booking an e-waste pickup with E-Cycle.

Here are your booking details:

- Item: {booking.recycleItem}
- Estimated price: ₹{booking.recycleItemPrice}
- Pickup slot: {booking.pickupDate} at {booking.pickupTime}
- Pickup address: {booking.address}
- Facility: {booking.facility}
- Contact phone: {booking.phone}
- Booking reference: {booking.userId}

If any of the above details are incorrect, please reply to this email.

Thank you for recycling responsibly 🌱
E-Cycle Team
"""

    msg = MIMEMultipart()
    msg["Subject"] = subject
    msg["From"] = FROM_EMAIL
    msg["To"] = booking.userEmail
    msg.attach(MIMEText(body, "plain"))

    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            server.starttls()
            server.login(SMTP_USERNAME, SMTP_PASSWORD)
            server.sendmail(FROM_EMAIL, [booking.userEmail], msg.as_string())
        print(f" Booking confirmation email sent to {booking.userEmail}")
    except Exception as e:
        # Don't crash the app if email fails
        print(" Error sending booking email:", e)


# ---------- EXISTING ENDPOINTS ----------

@app.get("/health")
def health():
    return {"status": "ok"}


# ----------- classify endpoint ------------

UPLOAD_DIR = "uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)



@app.post("/classify")
async def classify(file: UploadFile = File(...)):
    #  Production-safe mock
    if ENV == "production":
        return {
            "predictions": [],
            "category": "recyclable",
            "confidence": 0.87,
            "note": "ML inference disabled in production"
        }

    # ⬇ Everything below runs ONLY in development
    if not file.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="File must be an image.")

    ext = os.path.splitext(file.filename)[1] or ".jpg"
    unique_name = f"{uuid.uuid4().hex}{ext}"
    file_path = os.path.join(UPLOAD_DIR, unique_name)

    with open(file_path, "wb") as f:
        f.write(await file.read())

    try:
        with open(file_path, "rb") as img_file:
            result = await run_ml_inference(img_file.read())

        return {
            "predictions": result.get("predictions", []),
            "category": result.get("category"),
            "speed": f"{result.get('speed_ms', 0)}ms",
            "image_url": f"/{file_path}",
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))




# @app.post("/classify")

# async def classify(file: UploadFile = File(...)):
#     if not file.content_type.startswith("image/"):
#         raise HTTPException(status_code=400, detail="File must be an image.")
    
#     # Create unique filename
#     ext = os.path.splitext(file.filename)[1] or ".jpg"
#     unique_name = f"{uuid.uuid4().hex}{ext}"
#     file_path = os.path.join(UPLOAD_DIR, unique_name)

#     # Save uploaded image
#     with open(file_path, "wb") as f:
#         f.write(await file.read())

#     # Run classifier on saved image
#     try:
#         with open(file_path, "rb") as img_file:
#             result = await run_inference( img_file.read())

#         return JSONResponse({
#             "predictions": result.get("predictions", []),
#             "category": result.get("category"),       # reusable|recyclable|hazardous
#             "speed": f"{result.get('speed_ms', 0)}ms",
#             "image_url": f"/{file_path}"  # <-- VERY IMPORTANT
#         })

#     except Exception as e:
#         raise HTTPException(status_code=500, detail=str(e)) 


# ---------- NEW BOOKING ENDPOINT ----------

@app.post("/api/v1/booking")
async def create_booking(booking: BookingRequest, background_tasks: BackgroundTasks):
    """
    Create a booking from the frontend, save it in MongoDB,
    and send a confirmation email.
    """

    # Turn Pydantic model into a plain dict
    booking_doc = booking.model_dump()

   
    result = await bookings_collection.insert_one(booking_doc)
    booking_id = str(result.inserted_id)

    # Motor  added `_id: ObjectId(...)` into booking_doc
   
    booking_doc.pop("_id", None)

   

    print(" New booking stored in Mongo:", booking_doc, " -> _id:", booking_id)

    # Send email in background
    background_tasks.add_task(send_booking_email, booking)

    return {
        "message": "Booking created successfully",
        "bookingId": booking_id,
        "booking": booking_doc,
    }




# ... Payment gateway  ...


RAZORPAY_KEY_ID = os.getenv("RAZORPAY_KEY_ID")
RAZORPAY_KEY_SECRET = os.getenv("RAZORPAY_KEY_SECRET")

razorpay_client = None
if RAZORPAY_KEY_ID and RAZORPAY_KEY_SECRET:
    razorpay_client = razorpay.Client(auth=(RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET))


@app.post("/payments/create-order")
async def create_payment_order(body: dict = Body(...)):
    """
    body is expected like:
    {
      "amount": 2500,          # rupees
      "currency": "INR",
      "receipt": "order_rcpt_...",
      "notes": { "email": "..." }
    }
    """
    if razorpay_client is None:
        raise HTTPException(status_code=500, detail="Razorpay client not configured")

    try:
        # Safely read amount (default 0)
        amount_rupees = int(body.get("amount", 0) or 0)
        if amount_rupees <= 0:
            raise HTTPException(status_code=400, detail="Invalid amount")

        currency = body.get("currency", "INR")
        receipt = body.get("receipt")
        notes = body.get("notes") or {}

        order_data = {
            "amount": amount_rupees * 100,  # Razorpay needs paise
            "currency": currency,
            "payment_capture": 1,
            "notes": notes,
        }
        if receipt:
            order_data["receipt"] = receipt

        order = razorpay_client.order.create(order_data)

        return {
            "id": order["id"],
            "amount": order["amount"],
            "currency": order["currency"],
            "status": order["status"],
            "razorpay_key_id": RAZORPAY_KEY_ID,
        }
    except HTTPException:
        raise
    except Exception as e:
        print("Razorpay error:", e)
        raise HTTPException(status_code=500, detail="Failed to create Razorpay order")
