"""Consulta previsão do tempo real via Open-Meteo (grátis, sem API key)."""
import logging
from datetime import datetime

import requests

log = logging.getLogger("hermes-bot.weather")

GEO_URL = "https://geocoding-api.open-meteo.com/v1/search"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"

_DIAS = ["segunda-feira", "terça-feira", "quarta-feira", "quinta-feira",
         "sexta-feira", "sábado", "domingo"]

# Códigos WMO -> descrição em PT-BR
_WMO = {
    0: "céu limpo", 1: "predominantemente limpo", 2: "parcialmente nublado", 3: "nublado",
    45: "nevoeiro", 48: "nevoeiro com geada",
    51: "garoa fraca", 53: "garoa moderada", 55: "garoa forte",
    56: "garoa congelante fraca", 57: "garoa congelante forte",
    61: "chuva fraca", 63: "chuva moderada", 65: "chuva forte",
    66: "chuva congelante fraca", 67: "chuva congelante forte",
    71: "neve fraca", 73: "neve moderada", 75: "neve forte", 77: "grãos de neve",
    80: "pancadas de chuva fracas", 81: "pancadas de chuva moderadas", 82: "pancadas de chuva fortes",
    85: "pancadas de neve fracas", 86: "pancadas de neve fortes",
    95: "trovoada", 96: "trovoada com granizo leve", 99: "trovoada com granizo forte",
}


def _desc(code):
    return _WMO.get(code, f"condição desconhecida (código {code})")


def geocode(city):
    """Nome da cidade -> dados de localização. Retorna dict ou None se não achar."""
    r = requests.get(
        GEO_URL,
        params={"name": city, "count": 1, "language": "pt", "format": "json"},
        timeout=10,
    )
    r.raise_for_status()
    results = r.json().get("results") or []
    return results[0] if results else None


def forecast_text(city, days=7):
    """Retorna (texto_formatado, erro). Um dos dois é None."""
    try:
        g = geocode(city)
    except Exception as e:
        log.warning("Geocode falhou p/ '%s': %s", city, e)
        return None, "erro ao consultar o serviço de localização"
    if not g:
        return None, f"cidade '{city}' não encontrada"

    lat, lon = g["latitude"], g["longitude"]
    nome = g.get("name", city)
    regiao = g.get("admin1", "")
    pais = g.get("country_code", "")
    local = nome + (f", {regiao}" if regiao else "") + (f" ({pais})" if pais else "")

    try:
        r = requests.get(
            FORECAST_URL,
            params={
                "latitude": lat,
                "longitude": lon,
                "current": "temperature_2m,weather_code,relative_humidity_2m,wind_speed_10m",
                "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max",
                "timezone": "auto",
                "forecast_days": days,
            },
            timeout=10,
        )
        r.raise_for_status()
        d = r.json()
    except Exception as e:
        log.warning("Forecast falhou p/ '%s': %s", city, e)
        return None, "erro ao consultar o serviço de previsão"

    lines = [f"Local: {local}."]
    cur = d.get("current") or {}
    if cur:
        lines.append(
            f"Agora: {cur.get('temperature_2m')}°C, {_desc(cur.get('weather_code'))}, "
            f"umidade {cur.get('relative_humidity_2m')}%, vento {cur.get('wind_speed_10m')} km/h."
        )

    daily = d.get("daily") or {}
    dates = daily.get("time", [])
    for i, ds in enumerate(dates):
        try:
            dt = datetime.fromisoformat(ds)
            dia = _DIAS[dt.weekday()]
            lines.append(
                f"{dia} {dt.strftime('%d/%m')}: {_desc(daily['weather_code'][i])}, "
                f"mín {daily['temperature_2m_min'][i]}°C / máx {daily['temperature_2m_max'][i]}°C, "
                f"chance de chuva {daily['precipitation_probability_max'][i]}%."
            )
        except (KeyError, IndexError, ValueError):
            continue

    return "\n".join(lines), None
