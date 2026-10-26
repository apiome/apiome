// MFI-14.1 (#3794) fixture: a TypeSpec service split across three files.
import "@typespec/http";
import "./models/pets.tsp";
import "./ops/pets-ops.tsp";

using TypeSpec.Http;

/** The Pet Store service. */
@service({ title: "Pet Store" })
@server("https://api.example.com", "Production")
namespace PetStore;
