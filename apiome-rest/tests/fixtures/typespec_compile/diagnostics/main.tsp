import "@typespec/http";
import "./ops/legacy.tsp";

using TypeSpec.Http;

/** A small service whose compile reports warnings (MFI-14.3 fixture). */
@service({ title: "Pet Shelter" })
namespace PetShelter;

model Pet {
  @key id: string;
  name: string;
}

@route("/pets")
interface Pets {
  @get list(): Pet[];
}

/** Re-uses `Pets.list` but drops the interface's `/pets` prefix: the built-in http linter warns. */
@route("/adoptable")
op adoptable is Pets.list;
