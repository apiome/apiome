import "@typespec/versioning";

using TypeSpec.Versioning;

namespace PetStore;

model Pet {
  id: string;
  name: string;

  @added(Versions.v2)
  tag?: string;

  @removed(Versions.v3)
  legacyCode?: string;
}
