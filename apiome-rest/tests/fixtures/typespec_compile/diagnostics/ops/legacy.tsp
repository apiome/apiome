import "@typespec/http";

using TypeSpec.Http;

namespace PetShelter;

#deprecated "Use Pet instead."
model LegacyPet {
  id: string;
}

/** Still returns the deprecated model: the compiler warns `deprecated`. */
@get
@route("/legacy-pets")
op legacyPets(): LegacyPet[];
