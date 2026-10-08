import httpx
from typing import Any
import asyncio


MET_SEARCH_URL = (
    "https://collectionapi.metmuseum.org/public/collection/v1.1/search"
)

MET_OBJECT_URL = (
    "https://collectionapi.metmuseum.org/public/collection/v1/objects"
)

CLEVELAND_SEARCH_URL = (
    "https://openaccess-api.clevelandart.org/api/artworks"
)

AIC_SEARCH_URL = (
    "https://api.artic.edu/api/v1/artworks/search"
)


# Keep this conservative for a public showcase.
# Metadata containing these terms will cause the result to be hidden.
UNSAFE_TERMS = {
    "pornographic",
    "pornography",
    "erotic",
    "explicit sexual",
    "sexual content",
    "genital",
    "genitals",
    "nude",
    "nudity",
    "nsfw",
}


def is_safe_artwork(artwork: dict[str, Any]) -> bool:
    """
    Conservative metadata-based safety check.

    This is intentionally not an image classifier. If the museum metadata
    explicitly indicates sexual/explicit content, don't expose the artwork
    through the assistant.
    """

    searchable_values = [
        artwork.get("title"),
        artwork.get("artist"),
        artwork.get("description"),
        artwork.get("classification"),
        artwork.get("medium"),
        artwork.get("subject"),
        artwork.get("tags"),
    ]

    text = " ".join(
        str(value).lower()
        for value in searchable_values
        if value
    )

    return not any(term in text for term in UNSAFE_TERMS)


def normalize_result(
    *,
    source: str,
    artwork: dict[str, Any],
) -> dict[str, Any]:

    return {
        "source": source,
        "id": artwork.get("id"),
        "title": artwork.get("title"),
        "artist": artwork.get("artist"),
        "date": artwork.get("date"),
        "medium": artwork.get("medium"),
        "classification": artwork.get("classification"),
        "description": artwork.get("description"),
        "image_url": artwork.get("image_url"),
        "object_url": artwork.get("object_url"),
    }

async def search_met(
    query: str,
    *,
    limit: int = 5,
) -> list[dict[str, Any]]:

    params = {
        "q": query,
        "hasImages": "true",
        "limit": limit,
        "offset": 0,
    }

    headers = {
        "User-Agent": (
            "Sarjy-Artwork-Assistant/1.0 "
            "(educational demonstration)"
        ),
        "Accept": "application/json",
    }

    async with httpx.AsyncClient(
        timeout=10.0,
        headers=headers,
        follow_redirects=True,
    ) as client:

        response = await client.get(
            MET_SEARCH_URL,
            params=params,
        )

        response.raise_for_status()

        search_data = response.json()

        object_ids = search_data.get("objectIDs", [])

        if not object_ids:
            return []

        object_ids = object_ids[:limit]

        async def fetch_object(object_id: int) -> dict[str, Any]:
            response = await client.get(
                f"{MET_OBJECT_URL}/{object_id}"
            )

            response.raise_for_status()

            return response.json()

        artworks = await asyncio.gather(
            *(fetch_object(object_id) for object_id in object_ids)
        )

        results = []

        for artwork in artworks:
            results.append(
                normalize_result(
                    source="The Metropolitan Museum of Art",
                    artwork={
                        "id": artwork.get("objectID"),
                        "title": artwork.get("title"),
                        "artist": artwork.get("artistDisplayName"),
                        "date": artwork.get("objectDate"),
                        "medium": artwork.get("medium"),
                        "classification": artwork.get("classification"),
                        "description": artwork.get("creditLine"),
                        "image_url": artwork.get("primaryImageSmall"),
                        "object_url": artwork.get("objectURL"),
                    },
                )
            )

        return results

async def search_cleveland(
    query: str,
    *,
    limit: int = 8,
) -> list[dict[str, Any]]:

    params = {
        "q": query,
        "has_image": 1,
        "limit": limit,
        "skip": 0,
    }

    async with httpx.AsyncClient(timeout=10.0) as client:

        response = await client.get(
            CLEVELAND_SEARCH_URL,
            params=params,
        )

        response.raise_for_status()

        data = response.json()

    results = []

    for artwork in data.get("data", []):

        images = artwork.get("images") or {}
        web_image = images.get("web") or {}

        results.append(
            normalize_result(
                source="Cleveland Museum of Art",
                artwork={
                    "id": artwork.get("id"),
                    "title": artwork.get("title"),
                    "artist": artwork.get("creators"),
                    "date": artwork.get("creation_date"),
                    "medium": artwork.get("medium"),
                    "classification": artwork.get("type"),
                    "description": artwork.get("tombstone"),
                    "image_url": web_image.get("url"),
                    "object_url": artwork.get("url"),
                },
            )
        )

    return results


async def search_art_institute(
    query: str,
    *,
    limit: int = 8,
) -> list[dict[str, Any]]:

    payload = {
        "query": {
            "multi_match": {
                "query": query,
                "fields": [
                    "title^5",
                    "artist_title^4",
                    "artist_titles^3",
                    "subject_titles^4",
                    "style_titles^2",
                    "material_titles^2",
                    "technique_titles^2",
                    "classification_titles",
                ],
                "type": "best_fields",
            }
        },
        "size": limit,
        "fields": (
            "id,"
            "title,"
            "artist_display,"
            "artist_title,"
            "artist_titles,"
            "date_display,"
            "image_id,"
            "main_reference_number,"
            "classification_title,"
            "classification_titles,"
            "style_title,"
            "style_titles,"
            "subject_titles,"
            "material_titles,"
            "technique_titles"
        ),
    }

    async with httpx.AsyncClient(timeout=10.0) as client:

        response = await client.post(
            AIC_SEARCH_URL,
            json=payload,
        )

        response.raise_for_status()

        data = response.json()

    results = []

    for artwork in data.get("data", []):

        image_url = None

        if artwork.get("image_id"):
            image_url = (
                "https://www.artic.edu/iiif/2/"
                f"{artwork['image_id']}/full/843,/0/default.jpg"
            )

        results.append(
            normalize_result(
                source="Art Institute of Chicago",
                artwork={
                    "id": artwork.get("id"),
                    "title": artwork.get("title"),
                    "artist": artwork.get("artist_display"),
                    "date": artwork.get("date_display"),
                    "medium": ", ".join(
                        artwork.get("material_titles") or []
                    ),
                    "classification": artwork.get(
                        "classification_title"
                    ),
                    "description": ", ".join(
                        artwork.get("subject_titles") or []
                    ),
                    "image_url": image_url,
                    "object_url": (
                        f"https://www.artic.edu/artworks/"
                        f"{artwork.get('id')}"
                        if artwork.get("id")
                        else None
                    ),
                },
            )
        )

    return results


def deduplicate_results(
    results: list[dict[str, Any]],
) -> list[dict[str, Any]]:

    seen: set[str] = set()
    unique_results = []

    for result in results:

        key = (
            f"{result.get('title', '')}|"
            f"{result.get('artist', '')}"
        ).lower()

        if key in seen:
            continue

        seen.add(key)
        unique_results.append(result)

    return unique_results


async def search_artworks(
    query: str,
    *,
    limit: int = 8,
) -> dict[str, Any]:

    """
    Search museum collections progressively.

    Strategy:

    1. Search The Met.
    2. If no usable results, search Cleveland.
    3. If still no usable results, search Art Institute of Chicago.

    Results are normalized into one common structure.
    """

    errors = []

    # ---------------------------------------------------------
    # 1. The Met
    # ---------------------------------------------------------

    try:

        results = await search_met(
            query,
            limit=limit,
        )

        safe_results = [
            result
            for result in results
            if is_safe_artwork(result)
        ]

        if safe_results:
            return {
                "query": query,
                "source": "The Metropolitan Museum of Art",
                "count": len(safe_results),
                "results": safe_results,
                "fallback_used": False,
                "errors": errors,
            }

    except httpx.HTTPError as exc:

        errors.append({
            "source": "The Metropolitan Museum of Art",
            "error": str(exc),
        })


    # ---------------------------------------------------------
    # 2. Cleveland Museum of Art
    # ---------------------------------------------------------

    try:

        results = await search_cleveland(
            query,
            limit=limit,
        )

        safe_results = [
            result
            for result in results
            if is_safe_artwork(result)
        ]

        if safe_results:
            return {
                "query": query,
                "source": "Cleveland Museum of Art",
                "count": len(safe_results),
                "results": safe_results,
                "fallback_used": True,
                "errors": errors,
            }

    except httpx.HTTPError as exc:

        errors.append({
            "source": "Cleveland Museum of Art",
            "error": str(exc),
        })


    # ---------------------------------------------------------
    # 3. Art Institute of Chicago
    # ---------------------------------------------------------

    try:

        results = await search_art_institute(
            query,
            limit=limit,
        )

        safe_results = [
            result
            for result in results
            if is_safe_artwork(result)
        ]

        if safe_results:
            return {
                "query": query,
                "source": "Art Institute of Chicago",
                "count": len(safe_results),
                "results": safe_results,
                "fallback_used": True,
                "errors": errors,
            }

    except httpx.HTTPError as exc:

        errors.append({
            "source": "Art Institute of Chicago",
            "error": str(exc),
        })


    return {
        "query": query,
        "source": None,
        "count": 0,
        "results": [],
        "fallback_used": True,
        "errors": errors,
    }
