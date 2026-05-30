import requests
from fastapi import FastAPI

# Создаем приложение FastAPI (наш будущий сервер)
app = FastAPI()

# Это наш эндпоинт. Когда мобилка перейдет по адресу /api/prayer-times,
# сработает эта функция.
@app.get("/api/prayer-times")
def get_prayer_times(city: str = "Astana", country: str = "Kazakhstan"):
    url = "http://api.aladhan.com/v1/timingsByCity"
    
    params = {
        "city": city,
        "country": country,
        "method": 99,
        "methodSettings" : "15, null, 15"
    }
   
    response = requests.get(url, params=params)
    data = response.json() 
    
    timings = data['data']['timings']
    
    # Теперь мы не просто печатаем в консоль, а ВОЗВРАЩАЕМ данные 
    # в формате JSON, который легко прочитает любое Android-приложение.
    return {
        "city": city,
        "country": country,
        "prayer_times": {
            "Fajr": timings['Fajr'],
            "Dhuhr": timings['Dhuhr'],
            "Asr": timings['Asr'],
            "Maghrib": timings['Maghrib'],
            "Isha": timings['Isha']
        }
    }