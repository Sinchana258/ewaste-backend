# backend/app.py
import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import uuid
from fastapi import FastAPI, UploadFile, File, HTTPException, BackgroundTasks
from fastapi.responses import JSONResponse
from auth import router as auth_router
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel  # using simple str for email to avoid extra deps
from dotenv import load_dotenv
import certifi
from motor.motor_asyncio import AsyncIOMotorClient
from utils.inference import run_inference
from fastapi.staticfiles import StaticFiles
from database import bookings_collection
from routes.valuation_routes import router as valuation_router
from routes import listings, payments,orders,marketplace,users

IN_SERVER = True  # Set True when running on Render

if IN_SERVER:
    run_inference = None
else:
    from utils.inference import run_inference


load_dotenv()

app = FastAPI()
app.include_router(auth_router)
app.include_router(valuation_router)
app.include_router(listings.router)
app.include_router(payments.router)
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


MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017")
MONGO_DB_NAME = os.getenv("MONGO_DB_NAME", "ewaste_db")
MONGO_BOOKINGS_COLLECTION = os.getenv("MONGO_BOOKINGS_COLLECTION", "bookings")



# ---------- Mongodb connection (local dev)----------
uri_lower = MONGO_URI.lower()

if "+srv" in uri_lower or "mongodb.net" in uri_lower:
    mongo_client = AsyncIOMotorClient(
        MONGO_URI,
        tls=True,
        tlsCAFile=certifi.where(),
        serverSelectionTimeoutMS=10000
    )
else:
    mongo_client = AsyncIOMotorClient(
        MONGO_URI,
        serverSelectionTimeoutMS=10000
    )

mongo_db = mongo_client[MONGO_DB_NAME]
bookings_collection = mongo_db[MONGO_BOOKINGS_COLLECTION]


# ---------- Middleware ----------

app.add_middleware(
    CORSMiddleware,
      allow_origins=["http://localhost:5173", "http://localhost:3000", "*"],  # later you can change to [FRONTEND_URL]
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------- MODELS ----------

class BookingRequest(BaseModel):
    userId: str
    userEmail: str          
    recycleItemPrice: float
    pickupDate: str         
    pickupTime: str        
    facility: str          
    fullName: str
    address: str
    phone: int


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
        print(f"✅ Booking confirmation email sent to {booking.userEmail}")
    except Exception as e:
        # Don't crash the app if email fails
        print("❌ Error sending booking email:", e)


# ---------- EXISTING ENDPOINTS ----------

@app.get("/health")
def health():
    return {"status": "ok"}


# ----------- classify endpoint ------------

UPLOAD_DIR = "uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)


@app.post("/classify")
async def classify(file: UploadFile = File(...)):
    if IN_SERVER:
        raise HTTPException(status_code=503, detail="AI model disabled in server deployment.")

    contents = await file.read()
    try:
        result = await run_inference(contents)
        return {
            "predictions": result.get("predictions", []),
            "category": result.get("category"),
            "speed": f"{result.get('speed_ms', 0)}ms",
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

"""------- @app.post("/classify")
async def classify(file: UploadFile = File(...)):
    if not file.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="File must be an image.")
    
    # Create unique filename
    ext = os.path.splitext(file.filename)[1] or ".jpg"
    unique_name = f"{uuid.uuid4().hex}{ext}"
    file_path = os.path.join(UPLOAD_DIR, unique_name)

    # Save uploaded image
    with open(file_path, "wb") as f:
        f.write(await file.read())

    # Run classifier on saved image
    try:
        with open(file_path, "rb") as img_file:
            result = await run_inference( img_file.read())

        return JSONResponse({
            "predictions": result.get("predictions", []),
            "category": result.get("category"),       # reusable|recyclable|hazardous
            "speed": f"{result.get('speed_ms', 0)}ms",
            "image_url": f"/{file_path}"  # <-- VERY IMPORTANT
        })

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) 
"""


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

    # Motor has now added `_id: ObjectId(...)` into booking_doc
    # We don't want to return raw ObjectId to the client
    # Option 1: remove it entirely
    booking_doc.pop("_id", None)

    # (Optional) you can expose it as a normal string id if you want:
    # booking_doc["id"] = booking_id

    print(" New booking stored in Mongo:", booking_doc, " -> _id:", booking_id)

    # Send email in background
    background_tasks.add_task(send_booking_email, booking)

    # Now everything in this object is JSON serializable
    return {
        "message": "Booking created successfully",
        "bookingId": booking_id,
        "booking": booking_doc,
    }
