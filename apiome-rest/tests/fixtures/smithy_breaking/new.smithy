$version: "2"
namespace example.shelter
service Shelter { version: "2", operations: [GetPet] }
@readonly
operation GetPet { input := { @required id: String, @required region: String } output := { name: String, extra: String } }
enum Status { OPEN HELD }
structure Pet { @required id: String, status: Status, size: Long }
