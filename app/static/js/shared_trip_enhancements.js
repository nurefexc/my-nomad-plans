(function () {
    function weatherIconByCode(code) {
        if (code === null || code === undefined) {
            return "⛅";
        }
        const normalized = Number(code);
        if (normalized === 0) return "☀";
        if ([1, 2, 3].includes(normalized)) return "⛅";
        if ([45, 48].includes(normalized)) return "🌫";
        if ([51, 53, 55, 56, 57].includes(normalized)) return "🌦";
        if ([61, 63, 65, 66, 67, 80, 81, 82].includes(normalized)) return "🌧";
        if ([71, 73, 75, 77, 85, 86].includes(normalized)) return "🌨";
        if ([95, 96, 99].includes(normalized)) return "⛈";
        return "⛅";
    }

    function formatWeatherText(label, weatherData) {
        const temp = weatherData && typeof weatherData.temperature === "number"
            ? `${Math.round(weatherData.temperature)}°C`
            : null;
        const wind = weatherData && typeof weatherData.windspeed === "number"
            ? `${Math.round(weatherData.windspeed)} km/h`
            : null;

        if (temp && wind) {
            return `${label}: ${temp} • ${wind}`;
        }
        if (temp) {
            return `${label}: ${temp}`;
        }
        return null;
    }

    async function hydrateWeatherChips() {
        const chips = document.querySelectorAll(".shared-weather-chip[data-weather-endpoint]");
        for (const chip of chips) {
            const endpoint = chip.getAttribute("data-weather-endpoint");
            const loading = chip.getAttribute("data-weather-loading") || "Loading weather...";
            const unavailable = chip.getAttribute("data-weather-unavailable") || "Weather unavailable";
            const missingCoordinates = chip.getAttribute("data-weather-missing-coordinates") || "No coordinates";
            const label = chip.getAttribute("data-weather-label") || "Weather";

            const textNode = chip.querySelector(".shared-weather-text");
            const iconNode = chip.querySelector(".ui-icon");
            if (textNode) {
                textNode.textContent = loading;
            }

            try {
                const response = await fetch(endpoint, { credentials: "same-origin" });
                if (!response.ok) {
                    throw new Error(`HTTP ${response.status}`);
                }
                const payload = await response.json();
                const weather = payload && payload.current_weather ? payload.current_weather : null;

                if (!weather) {
                    if (textNode) {
                        textNode.textContent = missingCoordinates;
                    }
                    continue;
                }

                const message = formatWeatherText(label, weather);
                if (textNode) {
                    textNode.textContent = message || unavailable;
                }
                if (iconNode) {
                    iconNode.textContent = weatherIconByCode(weather.weathercode);
                }
            } catch (error) {
                if (textNode) {
                    textNode.textContent = unavailable;
                }
            }
        }
    }

    document.addEventListener("DOMContentLoaded", hydrateWeatherChips);
})();

