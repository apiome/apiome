// Apache Thrift multi-file set — the root of an orders API split across three files.
//
// `include` pulls in `shared.thrift` (money, a base service) and `errors.thrift`
// (exceptions); their definitions are referenced with the file name as a prefix.
// OrderService extends shared.BaseService, so it also answers `ping`.
include "shared.thrift"
include "errors.thrift"

namespace java com.example.orders.v1
namespace py example.orders.v1

typedef string OrderId

enum OrderStatus {
  PENDING = 1,
  PAID = 2,
  SHIPPED = 3,
  CANCELLED = 4,
}

struct OrderLine {
  1: required string sku,
  2: required i32 quantity,
  3: optional shared.Money unitPrice,
}

struct Order {
  1: required OrderId id,
  2: required list<OrderLine> lines,
  3: optional shared.Amount total,
  4: optional OrderStatus status = OrderStatus.PENDING,
}

service OrderService extends shared.BaseService {
  Order getOrder(1: OrderId id) throws (1: errors.NotFound notFound),
  Order placeOrder(1: list<OrderLine> lines, 2: shared.Currency currency)
    throws (1: errors.InvalidRequest invalid),
  void cancelOrder(1: OrderId id) throws (1: errors.NotFound notFound),
}

service InventoryService {
  i32 available(1: string sku),
  oneway void reserve(1: string sku, 2: i32 quantity),
}
