$version: "2"

// The same namespace as main.smithy, split into a second file.
namespace example.weather

@pattern("^[A-Za-z0-9 ]+$")
string CityId

list ConditionList {
    member: Condition
}

enum Condition {
    SUNNY
    CLOUDY
    RAIN
}

@error("client")
structure NoSuchResource {
    @required
    resourceType: String
}
