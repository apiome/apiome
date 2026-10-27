$version: "2"
namespace example.shelter
service Shelter { version: "1", operations: [GetPet, DeletePet] }
@readonly
operation GetPet { input := { @required id: String, filter: String } output := { name: String, tag: String } }
operation DeletePet { input := { @required id: String } }
enum Status { OPEN CLOSED }
structure Pet { @required id: String, status: Status, size: Integer }
