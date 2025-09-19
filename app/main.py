from fastapi import FastAPI, HTTPException, Query
from typing import List, Dict, Any, Optional
import httpx
import os
from datetime import datetime
from motor.motor_asyncio import AsyncIOMotorClient

app = FastAPI()

# ==============================
# Конфигурация
# ==============================
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY", "YOUR_GOOGLE_API_KEY")
MONGODB_URI = os.getenv("MONGODB_URI", "mongodb://localhost:27017")

if GOOGLE_API_KEY == "YOUR_GOOGLE_API_KEY":
    raise RuntimeError("You must set GOOGLE_API_KEY environment variable")

client = AsyncIOMotorClient(MONGODB_URI)
db = client['cache_db']
autocomplete_collection = db['autocomplete_cache']
coords_collection = db['coordinates_cache']

# TTL индексы на 6 месяцев
autocomplete_collection.create_index("created_at", expireAfterSeconds=15552000)
coords_collection.create_index("created_at", expireAfterSeconds=15552000)

AUTOCOMPLETE_URL = "https://places.googleapis.com/v1/places:autocomplete"
DETAILS_URL = "https://places.googleapis.com/v1/places/"


# ==============================
# Утилиты работы с кешем
# ==============================
async def get_from_cache(collection, cache_key: str) -> Optional[Dict[str, Any]]:
    return await collection.find_one({"_id": cache_key})


async def update_cache(collection, cache_key: str, data: Dict[str, Any]):
    await collection.update_one(
        {"_id": cache_key},
        {
            "$set": {**data, "created_at": datetime.utcnow()},
            "$setOnInsert": {"usage_count": 0}
        },
        upsert=True
    )


async def increment_usage(collection, cache_key: str):
    await collection.update_one({"_id": cache_key}, {"$inc": {"usage_count": 1}})


# ==============================
# Google API helpers
# ==============================
async def fetch_autocomplete(q: str, session_token: str, language_code: str) -> List[Dict[str, Any]]:
    payload = {
        "input": q,
        "includedPrimaryTypes": "(cities)",  # всегда города
        "sessionToken": session_token,
        "languageCode": language_code,
    }
    headers = {
        "Content-Type": "application/json",
        "X-Goog-FieldMask": (
            "suggestions.placePrediction.text.text,"
            "suggestions.placePrediction.placeId,"
            "suggestions.placePrediction.structuredFormat.mainText.text"
        ),
        "X-Goog-Api-Key": GOOGLE_API_KEY,
    }

    async with httpx.AsyncClient() as client_http:
        resp = await client_http.post(AUTOCOMPLETE_URL, headers=headers, json=payload)

    if resp.status_code != 200:
        raise HTTPException(status_code=resp.status_code, detail=f"Google Places API error: {resp.text}")

    data = resp.json()
    if "suggestions" not in data:
        raise HTTPException(status_code=400, detail=f"Google API error: {data}")

    results = []
    for suggestion in data["suggestions"][:10]:
        pred = suggestion.get("placePrediction", {})
        results.append({
            "place_id": pred.get("placeId"),
            "name": pred.get("text", {}).get("text"),
            "main_text": pred.get("structuredFormat", {}).get("mainText", {}).get("text"),
        })

    return results


async def fetch_coordinates(place_id: str, session_token: str) -> Dict[str, Any]:
    headers = {
        "Content-Type": "application/json",
        "X-Goog-FieldMask": "location",
        "X-Goog-Api-Key": GOOGLE_API_KEY,
    }
    url = f"{DETAILS_URL}{place_id}?sessionToken={session_token}"

    async with httpx.AsyncClient() as client_http:
        resp = await client_http.get(url, headers=headers)

    if resp.status_code != 200:
        raise HTTPException(status_code=resp.status_code, detail=f"Google Places API error: {resp.text}")

    data = resp.json()
    if "location" not in data:
        raise HTTPException(status_code=400, detail=f"Google API error: {data}")

    return {
        "lat": data["location"].get("latitude"),
        "lng": data["location"].get("longitude"),
    }


# ==============================
# Эндпоинты
# ==============================
@app.get("/autocomplete_cities", response_model=List[Dict[str, Any]])
async def autocomplete_cities(
    q: str = Query(..., min_length=1, description="Part of city name to autocomplete"),
    session_token: str = Query(..., description="Session token for grouping user requests"),
    language_code: str = Query("en", description="Language code for the results"),
):
    cache_key = f"{q}:{language_code}"
    cached = await get_from_cache(autocomplete_collection, cache_key)

    #if cached:
    #    await increment_usage(autocomplete_collection, cache_key)
    #    return cached["results"]

    results = await fetch_autocomplete(q, session_token, language_code)
    await update_cache(autocomplete_collection, cache_key, {"results": results})

    return results


@app.get("/get_coordinates", response_model=Dict[str, Any])
async def get_coordinates(
    place_id: str = Query(..., description="Google Place ID"),
    session_token: str = Query(..., description="Session token for grouping user requests"),
):
    cache_key = place_id
    cached = await get_from_cache(coords_collection, cache_key)

    if cached:
        await increment_usage(coords_collection, cache_key)
        return cached["coordinates"]

    coordinates = await fetch_coordinates(place_id, session_token)
    await update_cache(coords_collection, cache_key, {"coordinates": coordinates})

    return coordinates