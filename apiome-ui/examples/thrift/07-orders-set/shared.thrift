// Shared definitions for the orders set: money and the base every service extends.
namespace java com.example.shared.v1
namespace py example.shared.v1

typedef i64 Amount

enum Currency {
  USD = 1,
  EUR = 2,
  JPY = 3,
}

struct Money {
  1: required Amount amount,
  2: required Currency currency,
}

service BaseService {
  string ping(),
}
