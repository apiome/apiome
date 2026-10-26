// Models in their own namespace, in a second file.
namespace PetStore.Models;

/** A pet in the store. */
model Pet {
  id: int32;
  name: string;
  tag?: string;
  status: PetStatus;
}

enum PetStatus {
  available,
  pending,
  sold,
}

@error
model Error {
  code: int32;
  message: string;
}
