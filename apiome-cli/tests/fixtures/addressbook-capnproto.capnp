# Cap'n Proto schema for the CLI tests (MFI-19.4): a file id, structs with a union, an enum, and an
# interface whose results are parenthesized types.
@0x9eb32e19f86ee174;

struct Person {
  id @0 :UInt32;
  name @1 :Text;
  email @2 :Text;
  phones @3 :List(PhoneNumber);

  employment :union {
    unemployed @4 :Void;
    employer @5 :Text;
    school @6 :Text;
  }

  struct PhoneNumber {
    number @0 :Text;
    type @1 :Type;

    enum Type {
      mobile @0;
      home @1;
      work @2;
    }
  }
}

struct AddressBook {
  people @0 :List(Person);
}

interface Directory {
  lookup @0 (id :UInt32) -> (person :Person);
  list @1 () -> (people :List(Person));
  add @2 (person :Person) -> (id :UInt32);
}
