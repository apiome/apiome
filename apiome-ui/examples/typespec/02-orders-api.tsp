// TypeSpec example — a small orders REST API with update and delete operations.
import "@typespec/http";
import "@typespec/rest";

using TypeSpec.Http;
using TypeSpec.Rest;

@service(#{ title: "Orders API" })
namespace OrderStore;

enum OrderStatus {
  pending,
  shipped,
  cancelled,
}

model Order {
  @key id: string;
  customerId: string;
  total: float64;
  status: OrderStatus;
}

model OrderUpdate {
  status: OrderStatus;
}

@route("/orders")
interface Orders {
  @get list(): Order[];

  @get read(@path id: string): Order;

  @put update(@path id: string, @body update: OrderUpdate): Order;

  @delete remove(@path id: string): void;
}
