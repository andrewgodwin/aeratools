# weather-art

A full-page weather illustration tool that displays a curated photograph matching the current weather conditions at a configured location.

## Features

- Full-page landscape photograph sourced from Unsplash, matching the current weather condition
- Weather condition mapped to a descriptive search query (e.g. "thunderstorm lightning dramatic sky")
- Optional overlay showing temperature range and condition name
- Photo credited to photographer with Unsplash attribution link
- Photos cached for one hour per weather condition to stay within API rate limits
- Auto-refreshes photo every hour

## Preferences

| Setting | Description |
|---------|-------------|
| Location | City name to geocode (e.g. `London`, `New York`) |
| Units | `°C` (Celsius) or `°F` (Fahrenheit) |
| Overlay | Show or hide the weather info pill overlay |
| Unsplash key | Your Unsplash API access key |

All preferences are stored in URL query params, so the URL is shareable and bookmarkable.

## Setup

1. Sign up at [unsplash.com/developers](https://unsplash.com/developers) and create an application.
2. Copy the **Access Key** (not the Secret Key).
3. Open the tool, click the gear icon, and paste the key into the **Unsplash key** field.

## Build & Run

```sh
make        # builds Docker image tagged 'weather-art'
make run    # builds and runs on http://localhost:8000
```

## Data Sources

- Weather: [Open-Meteo](https://open-meteo.com/) (free, no API key required)
- Geocoding: [Open-Meteo Geocoding API](https://open-meteo.com/en/docs/geocoding-api)
- Photos: [Unsplash API](https://unsplash.com/developers) (free tier: 50 requests/hour)
