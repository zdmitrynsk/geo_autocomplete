from fastapi import HTTPException, Query
from typing import List, Dict, Any
import httpx
import os

GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY", "YOUR_GOOGLE_API_KEY")

AUTOCOMPLETE_URL = "https://places.googleapis.com/v1/places:autocomplete"

async def autocomplete_cities(
    q: str = Query(..., min_length=1, description="Part of city name to autocomplete"),
    session_token: str = Query(..., description="Session token for grouping user requests"),
    language_code: str = Query("en", description="Language code for the results")
) -> List[Dict[str, Any]]:
    async with httpx.AsyncClient() as client:
        limit = 10
        payload = {
            "input": q,
            "includedPrimaryTypes": ["locality"],
            "sessionToken": session_token,
            "languageCode": language_code
        }
        headers = {
            "Content-Type": "application/json",
            "X-Goog-FieldMask": "suggestions.placePrediction.text.text,suggestions.placePrediction.placeId,suggestions.placePrediction.structuredFormat.mainText.text",
            "X-Goog-Api-Key": GOOGLE_API_KEY
        }

        resp = await client.post(AUTOCOMPLETE_URL, headers=headers, json=payload)

        if resp.status_code != 200:
            raise HTTPException(status_code=resp.status_code, detail=f"Google Places API error: {resp.text}")

        data = resp.json()
        if "suggestions" not in data:
            raise HTTPException(status_code=400, detail=f"Google API error: {data}")

        results = []
        for suggestion in data["suggestions"][:limit]:
            pred = suggestion.get("placePrediction", {})
            results.append({
                "place_id": pred.get("placeId"),
                "name": pred.get("text", {}).get("text"),
                "main_text": pred.get("structuredFormat", {}).get("mainText", {}).get("text")
            })

    return results
