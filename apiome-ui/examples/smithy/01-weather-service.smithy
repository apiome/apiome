$version: "2.0"

// Smithy 2.0 example — a small weather service.
//
// Recognized by the format-detection sniffer via the `$version: "2.0"` control
// statement plus Smithy shapes (`service`/`operation`/`structure`), routing to the
// `smithy` RPC format. Each `structure` becomes a catalog class; the `service` and
// `operation` shapes describe the RPC surface.

namespace example.weather

service WeatherService {
    version: "2026-01-01"
    operations: [GetForecast, GetCurrentConditions]
}

/// Returns the multi-day forecast for a city.
operation GetForecast {
    input: GetForecastInput
    output: Forecast
}

/// Returns the current conditions for a city.
operation GetCurrentConditions {
    input: GetForecastInput
    output: CurrentConditions
}

structure GetForecastInput {
    @required
    city: String

    /// Number of days to forecast (1-10).
    days: Integer
}

structure Forecast {
    @required
    city: String

    @required
    days: DayForecastList
}

list DayForecastList {
    member: DayForecast
}

structure DayForecast {
    @required
    date: String

    /// High temperature in Celsius.
    high: Float

    /// Low temperature in Celsius.
    low: Float

    condition: Condition
}

structure CurrentConditions {
    @required
    city: String

    /// Temperature in Celsius.
    temperature: Float

    condition: Condition
}

enum Condition {
    SUNNY
    CLOUDY
    RAIN
    SNOW
}
