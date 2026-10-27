import "@typespec/http";
import "@typespec/versioning";
import "./models/pet.tsp";

using TypeSpec.Http;
using TypeSpec.Versioning;

/** A pet store whose API evolves across three versions (MFI-14.4 fixture). */
@service({ title: "Versioned Pet Store" })
@versioned(Versions)
namespace PetStore;

/** The API versions, oldest first. */
enum Versions {
  /** First release. */
  v1: "2023-01-01",
  /** Adds tags and single-pet reads. */
  v2: "2023-06-01",
  /** Drops the legacy code. */
  v3: "2024-01-01",
}

@route("/pets")
interface Pets {
  @get list(): Pet[];

  @added(Versions.v2)
  @get read(@path id: string): Pet;
}
