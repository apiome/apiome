$version: "2"

/// Shared types in their own namespace.
namespace example.common

structure Money {
    @required
    amount: BigDecimal

    @required
    currency: String
}

map Region {
    key: String
    value: String
}
