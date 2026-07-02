// TypeSpec example — a small pets REST API.
//
// Recognized by the format-detection sniffer via the `import "@typespec/..."`
// statement (routes to the `typespec` format). The `model` declarations become
// catalog classes; the namespace + operations describe the REST surface.
import "@typespec/http";
import "@typespec/rest";

using TypeSpec.Http;
using TypeSpec.Rest;

@service(#{ title: "Pets API" })
namespace PetStore;

/// Lifecycle status of a pet listing.
enum PetStatus {
  available,
  pending,
  sold,
}

/// A pet available for adoption.
model Pet {
  /// Unique pet identifier.
  @key id: string;

  /// The pet's name.
  name: string;

  /// Species, e.g. "dog" or "cat".
  species: string;

  /// Age in years.
  age?: int32;

  /// Current listing status.
  status: PetStatus;
}

/// Payload to create a pet (id is server-assigned).
model NewPet {
  name: string;
  species: string;
  age?: int32;
}

@route("/pets")
interface Pets {
  /// List all pets.
  @get list(): Pet[];

  /// Fetch a pet by id.
  @get read(@path id: string): Pet;

  /// Create a new pet.
  @post create(@body pet: NewPet): Pet;
}
