from fastapi import APIRouter, HTTPException, Query
from bson import ObjectId, errors
from typing import Optional, List
from pydantic import BaseModel
from database import db

router = APIRouter(prefix="/marketplace", tags=["Marketplace"])
listings_collection = db["listings"]

class ListingSchema(BaseModel):
    title: str
    price: int
    condition: str = "Good"
    stock: int = 1
    category: str = "reusable"
    image_url: str
    tags: list[str] = []
    owner_email: Optional[str] = None

def listing_entity(doc):
    return {
        "id": str(doc["_id"]),
        "title": doc.get("title"),
        "price": doc.get("price"),
        "condition": doc.get("condition"),
        "stock": doc.get("stock"),
        "category": doc.get("category"),
        "image_url": doc.get("image_url"),
        "tags": doc.get("tags", []),
        "owner_email": doc.get("owner_email"),
    }

# ---------- Listings on marketplace ----------

@router.post("/listings")
async def create_listing(listing: ListingSchema):
    res = await listings_collection.insert_one(listing.dict())
    return {"id": str(res.inserted_id)}

# ----------  My Listings in profile ----------

@router.get("/my-listings")
async def get_my_listings(owner_email: str = Query(...)):
    cursor = listings_collection.find({"owner_email": owner_email}).sort("_id", -1)
    docs = await cursor.to_list(length=100)
    if not docs:
        return []  # return empty list, not 404
    return [listing_entity(doc) for doc in docs]

# ---------- For deleting  listing (only if owned by the user) ----------

@router.delete("/listings/{listing_id}")
async def delete_listing(listing_id: str, owner_email: str = Query(...)):
    try:
        oid = ObjectId(listing_id)
    except errors.InvalidId:
        raise HTTPException(status_code=400, detail="Invalid listing id")

    result = await listings_collection.delete_one(
        {"_id": oid, "owner_email": owner_email}
    )

    if result.deleted_count == 0:
        raise HTTPException(
            status_code=404,
            detail="Listing not found or you are not allowed to delete it",
        )

    return {"success": True}
