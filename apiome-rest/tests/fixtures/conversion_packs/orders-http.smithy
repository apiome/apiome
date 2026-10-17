// MFI-22.8 golden fixture: a Smithy service whose operations declare their
// HTTP bindings with @http, plus the @endpoint/@hostLabel traits that
// smithy-openapi documents as unconverted.
$version: "2"

namespace shop.orders

service OrderService {
    version: "2026-10-16"
    operations: [GetOrder, ListOrders, CreateOrder, DeleteOrder]
}

/// Fetch one order by id.
@readonly
@http(method: "GET", uri: "/orders/{id}", code: 200)
operation GetOrder {
    input: GetOrderInput
    output: Order
}

/// List orders.
@readonly
@http(method: "GET", uri: "/orders")
operation ListOrders {
    input: ListOrdersInput
    output: ListOrdersOutput
}

/// Place an order, on a per-region host.
@endpoint(hostPrefix: "{region}.")
@http(method: "POST", uri: "/orders", code: 201)
operation CreateOrder {
    input: CreateOrderInput
    output: Order
}

/// Remove an order.
@idempotent
@http(method: "DELETE", uri: "/orders/{id}", code: 204)
operation DeleteOrder {
    input: DeleteOrderInput
}

structure GetOrderInput {
    @required
    @httpLabel
    id: String
}

structure ListOrdersInput {
    @httpQuery("customer")
    customerId: String
}

structure ListOrdersOutput {
    orders: OrderList
}

structure CreateOrderInput {
    @required
    @hostLabel
    region: String

    @required
    customerId: String

    items: LineItemList
}

structure DeleteOrderInput {
    @required
    @httpLabel
    id: String
}

structure Order {
    @required
    id: String

    customerId: String

    items: LineItemList
}

structure LineItem {
    @required
    sku: String

    quantity: Integer
}

list OrderList {
    member: Order
}

list LineItemList {
    member: LineItem
}
