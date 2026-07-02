// Apache Thrift IDL example — a user service.
//
// Maps to the catalog's `thrift` RPC format. Each `struct` becomes a catalog
// class and each field a property; the `service` block declares the RPC methods.
namespace java com.example.user
namespace py example.user

// Lifecycle status of an account.
enum Status {
  ACTIVE = 1,
  SUSPENDED = 2,
  DELETED = 3,
}

// A registered user.
struct User {
  1: required string id,          // Unique user identifier.
  2: required string email,       // The user's email address.
  3: optional string displayName, // Optional human-readable name.
  4: Status status = Status.ACTIVE,
  5: list<string> roles,          // Roles assigned to the user.
  6: i64 createdAt,               // Creation time (epoch millis).
}

struct CreateUserRequest {
  1: required string email,
  2: optional string displayName,
}

exception NotFound {
  1: string message,
}

// Operations on users.
service UserService {
  // Fetch a user by id.
  User getUser(1: string id) throws (1: NotFound nf),

  // Create a new user.
  User createUser(1: CreateUserRequest request),

  // Delete a user by id.
  void deleteUser(1: string id) throws (1: NotFound nf),
}
