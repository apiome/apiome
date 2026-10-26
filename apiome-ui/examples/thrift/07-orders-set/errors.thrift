// Exceptions shared by the orders set.
namespace java com.example.errors.v1
namespace py example.errors.v1

exception NotFound {
  1: required string message,
  2: optional string resource,
}

exception InvalidRequest {
  1: required string message,
  2: optional list<string> fields,
}
