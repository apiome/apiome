/**
 * The Catalog → Project journey's `.proto` check (#6278).
 *
 * The journey exports an OpenAPI project to Protobuf and runs `checkProto` on the file it
 * downloads. These tests pin what the check accepts and what it rejects — above all the bug that
 * motivated it: JSON Schema scalar names written as type references (`.integer id = 1;`).
 */

import { checkProto } from '../e2e/journey/support/proto-check';

/** What the fixed exporter writes for an OpenAPI schema with every scalar kind. */
const GOOD = `syntax = "proto3";

package acme.pets.v1;

import "google/protobuf/timestamp.proto";

// A pet.
message Pet {
  int64 id = 1;
  string name = 2; // the name
  optional bool vaccinated = 3;
  double weight = 4;
  repeated string tags = 5;
  map<string, int32> counts = 6;
  .acme.pets.v1.Status status = 7;
  .google.protobuf.Timestamp born = 8;
  oneof contact {
    string email = 9;
    string phone = 10;
  }
  reserved 11;
  option deprecated = true;
}

enum Status {
  STATUS_UNSPECIFIED = 0;
  AVAILABLE = 1;
}

service PetService {
  rpc GetPet(.acme.pets.v1.Pet) returns (.acme.pets.v1.Pet);
  rpc Watch(stream Pet) returns (stream Pet) {
    option idempotency_level = NO_SIDE_EFFECTS;
  }
}
`;

describe('checkProto', () => {
  it('accepts a well-formed file: scalars, maps, oneofs, enums, imports and rpcs', () => {
    expect(checkProto(GOOD)).toEqual([]);
  });

  it('rejects JSON Schema scalar names written as type references (the #6278 bug)', () => {
    const bad = `syntax = "proto3";

message W {
  .boolean b = 1;
  .integer i = 2;
  .number n = 3;
  string s = 4;
}
`;
    expect(checkProto(bad)).toEqual([
      'line 4: unknown type `.boolean`',
      'line 5: unknown type `.integer`',
      'line 6: unknown type `.number`',
    ]);
  });

  it('rejects a repeated field number, counting oneof members with their message', () => {
    const bad = `syntax = "proto3";
message W {
  string a = 1;
  oneof pick {
    string b = 1;
  }
}
`;
    expect(checkProto(bad)).toEqual(['line 5: field number 1 repeats in `W`']);
  });

  it('allows the same number in two different messages', () => {
    const ok = `syntax = "proto3";
message A {
  string a = 1;
}
message B {
  string b = 1;
}
`;
    expect(checkProto(ok)).toEqual([]);
  });

  it('rejects an unknown map value, an unknown rpc type and an un-imported well-known type', () => {
    const bad = `syntax = "proto3";
message W {
  map<string, .number> m = 1;
  .google.protobuf.Timestamp t = 2;
}
service S {
  rpc Call(W) returns (.Missing);
}
`;
    expect(checkProto(bad)).toEqual([
      'line 3: unknown type `.number`',
      'line 4: unknown type `.google.protobuf.Timestamp`',
      'line 7: unknown type `.Missing`',
    ]);
  });

  it('needs a syntax line and balanced braces', () => {
    expect(checkProto('message W {\n  string a = 1;\n')).toEqual([
      'missing `syntax = "proto3";`',
      'unclosed `{` in `W`',
    ]);
    expect(checkProto('syntax = "proto3";\n}\n')).toEqual(['line 2: unbalanced `}`']);
  });

  it('ignores what comments and strings say', () => {
    const ok = `syntax = "proto3";
/* message Fake {
  .integer x = 1;
} */
message W {
  // .integer y = 2;
  string a = 1 [json_name = "z = 3"];
}
`;
    expect(checkProto(ok)).toEqual([]);
  });
});
