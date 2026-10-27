$version: "2"

namespace example.shelter

/// A shelter for pets awaiting adoption (MFI-17.3 lint fixture).
service Shelter {
    version: "2024-01-01"
    operations: [ListPets, GetPet]
}

/// Lists every pet; returns a growing list with no pagination.
@readonly
operation ListPets {
    input := {}
    output := {
        pets: PetList
    }
}

/// Fetches one pet.
@readonly
operation GetPet {
    input := {
        @required
        pet_id: String
    }
    output := {
        name: String
        adoptedAt: Long
    }
}

list PetList {
    member: PetSummary
}

/// A pet in a listing.
structure PetSummary {
    petName: String
    URLValue: String
    password: String
}

@deprecated(message: "Use PetSummary.")
structure LegacyPet {
    name: String
}
