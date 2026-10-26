$version: "2"

namespace example.weather

use example.common#Money
use example.common#Region

/// Provides weather forecasts.
service Weather {
    version: "2006-03-01"
    resources: [City]
    operations: [GetCurrentTime]
}

resource City {
    identifiers: { cityId: CityId }
    read: GetCity
    operations: [GetForecast]
}

operation GetCity {
    input := {
        @required
        cityId: CityId
    }
    output := {
        @required
        name: String
        region: Region
    }
    errors: [NoSuchResource]
}

operation GetForecast {
    input := {
        @required
        cityId: CityId
    }
    output := {
        chanceOfRain: Float
        conditions: ConditionList
        priceOfUmbrella: Money
    }
}

operation GetCurrentTime {
    output := {
        @required
        time: Timestamp
    }
}
