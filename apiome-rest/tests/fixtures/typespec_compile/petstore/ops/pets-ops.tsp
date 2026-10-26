// Operations in a third file, using the models' namespace.
import "@typespec/http";
import "../models/pets.tsp";

using TypeSpec.Http;
using PetStore.Models;

namespace PetStore;

@route("/pets")
interface Pets {
  /** List pets. */
  @get list(@query limit?: int32): Pet[];

  /** Add a pet. */
  @post create(@body pet: Pet): {
    @statusCode statusCode: 201;
    @body pet: Pet;
  };

  /** Get one pet. */
  @get read(@path petId: int32): Pet | Error;
}
