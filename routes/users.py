# app/routers/users.py (or wherever this file lives)

from fastapi import APIRouter, HTTPException, Query, Body
from pydantic import BaseModel
from database import db
from bson import ObjectId

router = APIRouter(prefix="/users", tags=["users"])

users_collection = db["users"]


class UserProfile(BaseModel):
    email: str
    name: str | None = None
    phone: str | None = None
    address: str | None = None


class UserProfileUpdate(BaseModel):
    # for updates, email is passed as query param, not required in body
    name: str | None = None
    phone: str | None = None
    address: str | None = None


def user_entity(doc):
    return {
        "id": str(doc["_id"]),
        "email": doc.get("email", ""),
        "name": doc.get("name"),
        "phone": doc.get("phone"),
        "address": doc.get("address"),
    }


@router.get("/me", response_model=UserProfile)
async def get_profile(email: str = Query(...)):
    """
    Get profile for given email.
    If not found, create a blank profile document and return it.
    """
    user = await users_collection.find_one({"email": email})
    if user:
        return user_entity(user)

    # Create profile if missing
    new_doc = {"email": email, "name": None, "phone": None, "address": None}
    res = await users_collection.insert_one(new_doc)
    new_doc["_id"] = res.inserted_id
    return user_entity(new_doc)


@router.put("/me", response_model=UserProfile)
async def update_me(
    email: str = Query(...),
    payload: UserProfileUpdate = Body(...)
):
    """
    Update profile fields (name / phone / address) for the given email.
    Email comes in as a query param: /users/me?email=...
    """
    # Only include fields that are not None
    update_data = {k: v for k, v in payload.dict().items() if v is not None}

    # If nothing to update, just return existing profile (or 404 if none)
    if not update_data:
        existing = await users_collection.find_one({"email": email})
        if not existing:
            raise HTTPException(status_code=404, detail="User not found")
        return user_entity(existing)

    res = await users_collection.update_one(
        {"email": email},
        {"$set": update_data}
    )

    # matched_count is more reliable than modified_count (modified_count can be 0 if data is same)
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="User not found")

    updated = await users_collection.find_one({"email": email})
    if not updated:
        raise HTTPException(status_code=404, detail="User not found after update")

    return user_entity(updated)
