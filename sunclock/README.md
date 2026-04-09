# sunclock

Embeddable widget showing sunrise time, current time, and sunset time in a three-column layout. Also displays total daylight duration for the day.

## Features

- Live current time (updates every second)
- Today's sunrise and sunset times from Open-Meteo
- Day length calculation
- 12/24-hour format toggle
- Location configured via preferences (geocoded by name)
- Designed for embedding in dashboards at small sizes

## Configuration

Set your location in the preferences panel (gear icon). The tool geocodes the city name using Open-Meteo's free geocoding API — no API key required.

## Preferences (URL params)

- `location` — city name (e.g. `London`)
- `format` — `12` or `24` (default `24`)
