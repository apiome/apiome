// MFI-14.5 (#3798) fixture: a one-file TypeSpec project (main.tsp + tspconfig.yaml).
import "@typespec/http";

using TypeSpec.Http;

@service({ title: "Greeter" })
namespace Greeter;

model Greeting {
  message: string;
  count: safeint;
}

model Unused {
  note: string;
}

@route("/greetings")
@get op list(): Greeting[];
