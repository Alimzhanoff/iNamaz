import requests
from fastapi import FastAPI, HTTPException

app = FastAPI()


def geocode_location(query: str) -> dict:
    """
    Принимает любое название (город, село, район) и возвращает
    координаты через OpenStreetMap Nominatim — бесплатно, без API-ключа.
    """
    url = "https://nominatim.openstreetmap.org/search"
    params = {
        "q": query,
        "format": "json",
        "limit": 5,
        "countrycodes": "kz",   # ищем только в Казахстане
        "addressdetails": 1,
    }
    headers = {
        # Nominatim требует User-Agent
        "User-Agent": "PrayerTimesApp/1.0"
    }
    resp = requests.get(url, params=params, headers=headers, timeout=10)
    results = resp.json()

    if not results:
        # Если в Казахстане не нашли — пробуем без ограничения страны
        params.pop("countrycodes")
        resp = requests.get(url, params=params, headers=headers, timeout=10)
        results = resp.json()

    if not results:
        return None

    best = results[0]
    return {
        "display_name": best["display_name"],
        "lat": float(best["lat"]),
        "lon": float(best["lon"]),
    }


def get_timings_by_coords(lat: float, lon: float) -> dict:
    """
    Получает время намаза по координатам через Aladhan API.
    Метод 99 с настройкой 15° для Казахстана.
    """
    url = "http://api.aladhan.com/v1/timings"
    import datetime
    today = datetime.date.today().strftime("%d-%m-%Y")

    params = {
        "latitude": lat,
        "longitude": lon,
        "method": 99,
        "methodSettings": "15,null,15",
        "date": today,
    }
    resp = requests.get(url, params=params, timeout=10)
    data = resp.json()

    if data.get("code") != 200:
        raise HTTPException(status_code=502, detail="Ошибка при получении времени намаза")

    return data["data"]["timings"]


@app.get("/api/prayer-times")
def get_prayer_times(location: str = "Астана"):
    """
    Принимает любое название места на любом языке (казахский, русский, английский).
    Возвращает время намаза для этого места.

    Примеры:
      /api/prayer-times?location=Алматы
      /api/prayer-times?location=Шымкент
      /api/prayer-times?location=Туркестан
      /api/prayer-times?location=Жанаозен
      /api/prayer-times?location=аул Карабулак
    """
    geo = geocode_location(location)

    if not geo:
        raise HTTPException(
            status_code=404,
            detail=f"Место '{location}' не найдено. Попробуйте написать иначе."
        )

    timings = get_timings_by_coords(geo["lat"], geo["lon"])

    return {
        "searched": location,
        "found": geo["display_name"],
        "coordinates": {
            "lat": geo["lat"],
            "lon": geo["lon"],
        },
        "prayer_times": {
            "Фаджр":   timings["Fajr"],
            "Восход":  timings["Sunrise"],
            "Зухр":    timings["Dhuhr"],
            "Аср":     timings["Asr"],
            "Магриб":  timings["Maghrib"],
            "Иша":     timings["Isha"],
        }
    }


@app.get("/api/search-suggestions")
def search_suggestions(q: str):
    """
    Возвращает список подсказок для строки поиска.
    Используй этот эндпоинт пока пользователь печатает.
    """
    if len(q) < 2:
        return {"suggestions": []}

    url = "https://nominatim.openstreetmap.org/search"
    params = {
        "q": q,
        "format": "json",
        "limit": 7,
        "countrycodes": "kz",
        "addressdetails": 1,
    }
    headers = {"User-Agent": "PrayerTimesApp/1.0"}
    resp = requests.get(url, params=params, headers=headers, timeout=8)
    results = resp.json()

    suggestions = []
    for r in results:
        addr = r.get("address", {})
        # Формируем красивое короткое название
        name = (
            addr.get("city")
            or addr.get("town")
            or addr.get("village")
            or addr.get("hamlet")
            or addr.get("suburb")
            or r["display_name"].split(",")[0]
        )
        region = addr.get("state") or addr.get("county") or ""
        suggestions.append({
            "name": name,
            "region": region,
            "full": r["display_name"],
            "lat": float(r["lat"]),
            "lon": float(r["lon"]),
        })

    return {"suggestions": suggestions}