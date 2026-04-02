# weather-header

A compact header widget showing the current date on the left and today's weather forecast on the right. Designed to be embedded as a dashboard header iframe.

## Features

- Current date (weekday + full date)
- Today's weather: icon, description, min/max temperature
- Tomorrow's weather: icon and min/max temperature
- Weather icons from WMO weather codes via emoji
- Auto-refreshes weather every 30 minutes

## Preferences

| Setting | Description |
|---------|-------------|
| Location | City name to geocode (e.g. `London`, `New York`) |
| Units | `°C` (Celsius) or `°F` (Fahrenheit) |

Preferences are stored in URL query params (`?location=London&units=c`), so the URL is shareable and bookmarkable.

## Build & Run

```sh
make        # builds Docker image tagged 'weather-header'
make run    # builds and runs on http://localhost:8000
```

## Data Sources

- Weather: [Open-Meteo](https://open-meteo.com/) (free, no API key required)
- Geocoding: [Open-Meteo Geocoding API](https://open-meteo.com/en/docs/geocoding-api)
