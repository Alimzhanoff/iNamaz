from datetime import datetime, timedelta, timezone
from typing import Annotated, Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import httpx
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

try:
    from timezonefinder import TimezoneFinder
except ImportError:
    TimezoneFinder = None


app = FastAPI(title="iNamaz API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
ALADHAN_URL = "https://api.aladhan.com/v1/timings"
HEADERS = {
    "User-Agent": "iNamaz/1.0 (prayer-times-backend)",
    "Cache-Control": "no-cache, no-store, must-revalidate",
    "Pragma": "no-cache",
}

PRAYER_NAME_MAP = {
    "Fajr": "Фаджр",
    "Sunrise": "Восход",
    "Dhuhr": "Зухр",
    "Asr": "Аср",
    "Maghrib": "Магриб",
    "Isha": "Иша",
}


async def fetch_json(url: str, params: dict[str, Any], timeout: int = 10) -> Any:
    try:
        async with httpx.AsyncClient(
            headers=HEADERS,
            timeout=timeout,
            follow_redirects=True,
        ) as client:
            response = await client.get(url, params=params)
        response.raise_for_status()
        return response.json()
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Не удалось получить данные от внешнего сервиса: {exc}",
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=502,
            detail="Внешний сервис вернул некорректный JSON.",
        ) from exc


async def geocode_location(query: str) -> dict[str, Any] | None:
    city = query.strip()
    if not city:
        return None

    params = {
        "q": city,
        "format": "json",
        "limit": 5,
        "countrycodes": "kz",
        "addressdetails": 1,
    }

    results = await fetch_json(NOMINATIM_URL, params)

    if not results:
        params.pop("countrycodes")
        results = await fetch_json(NOMINATIM_URL, params)

    if not results:
        return None

    best = results[0]
    lat = float(best["lat"])
    lon = float(best["lon"])
    print(f"geocode_location: query={city!r}, lat={lat}, lon={lon}")

    return {
        "display_name": best["display_name"],
        "lat": lat,
        "lon": lon,
        "address": best.get("address", {}),
    }


async def get_timezone_name(lat: float, lon: float) -> str:
    if TimezoneFinder:
        tf = TimezoneFinder()
        return tf.timezone_at(lat=lat, lng=lon) or "Asia/Almaty"
    return "Asia/Almaty"


async def get_tzinfo(tz_name: str) -> timezone | ZoneInfo:
    try:
        return ZoneInfo(tz_name)
    except ZoneInfoNotFoundError:
        # Kazakhstan has used UTC+5 nationwide since 2024. This keeps Windows
        # environments without the tzdata package working for the app's main market.
        if tz_name.startswith("Asia/"):
            return timezone(timedelta(hours=5), name=tz_name)
        return timezone.utc


async def get_timezone_info(lat: float, lon: float) -> dict[str, str]:
    tz_name = await get_timezone_name(lat, lon)
    tz = await get_tzinfo(tz_name)
    current_time = datetime.now(tz)

    return {
        "timezone": tz_name,
        "current_time": current_time.strftime("%H:%M:%S"),
        "current_date": current_time.strftime("%d-%m-%Y"),
        "utc_offset": current_time.strftime("%z"),
    }


async def get_local_date(lat: float, lon: float) -> str:
    tz = await get_tzinfo(await get_timezone_name(lat, lon))
    return datetime.now(tz).strftime("%d-%m-%Y")


async def get_timings_by_coords(lat: float, lon: float) -> dict[str, str]:
    params = {
        "latitude": lat,
        "longitude": lon,
        "method": 99,
        "methodSettings": "15,null,15",
        "date": await get_local_date(lat, lon),
    }

    data = await fetch_json(ALADHAN_URL, params)

    if data.get("code") != 200:
        raise HTTPException(
            status_code=502,
            detail="Ошибка при получении времени намаза.",
        )

    timings = data["data"]["timings"]
    return {ru_name: timings[api_name] for api_name, ru_name in PRAYER_NAME_MAP.items()}


async def get_place_name(result: dict[str, Any]) -> str:
    address = result.get("address", {})
    return (
        address.get("city")
        or address.get("town")
        or address.get("village")
        or address.get("hamlet")
        or address.get("suburb")
        or result["display_name"].split(",")[0]
    )


@app.get("/")
async def root() -> dict[str, str]:
    return {
        "message": "iNamaz API работает.",
        "example": "/api/prayer-times?location=Almaty",
    }


@app.get("/api/prayer-times")
async def get_prayer_times(
    location: Annotated[str | None, Query(description="Город, например Almaty")] = None,
) -> dict[str, Any]:
    city = (location or "").strip() or "Astana"

    geo = await geocode_location(city)
    if not geo:
        raise HTTPException(
            status_code=404,
            detail=f"Место '{city}' не найдено. Попробуйте написать город иначе.",
        )

    timezone = await get_timezone_info(geo["lat"], geo["lon"])
    prayer_times = await get_timings_by_coords(geo["lat"], geo["lon"])

    return {
        "city": city,
        "searched": city,
        "found": geo["display_name"],
        "coordinates": {
            "lat": geo["lat"],
            "lon": geo["lon"],
        },
        "timezone": timezone,
        "prayer_times": prayer_times,
    }


@app.get("/api/search-suggestions")
async def search_suggestions(q: str = Query(min_length=1)) -> dict[str, list[dict[str, Any]]]:
    query = q.strip()
    if len(query) < 2:
        return {"suggestions": []}

    params = {
        "q": query,
        "format": "json",
        "limit": 7,
        "countrycodes": "kz",
        "addressdetails": 1,
    }

    results = await fetch_json(NOMINATIM_URL, params, timeout=8)
    suggestions = []

    for result in results:
        lat = float(result["lat"])
        lon = float(result["lon"])
        address = result.get("address", {})

        suggestions.append(
            {
                "name": await get_place_name(result),
                "region": address.get("state") or address.get("county") or "",
                "full": result["display_name"],
                "lat": lat,
                "lon": lon,
                "timezone": await get_timezone_info(lat, lon),
            }
        )

    return {"suggestions": suggestions}
