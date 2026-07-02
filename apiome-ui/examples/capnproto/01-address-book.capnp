# Cap'n Proto schema example — an address book.
#
# Cap'n Proto (.capnp) is a data-schema + RPC IDL. The leading `@0x...` 64-bit file
# id is mandatory and marks the format. `struct` defines records (Person, Date)
# that become catalog classes; `enum` defines enumerations; `interface` (shown)
# defines a capability/RPC surface. Field numbers (`@0`, `@1`) are explicit for
# wire compatibility.
@0xbf5147cbbecf40c1;

struct Person {
  id @0 :UInt32;
  name @1 :Text;
  email @2 :Text;
  phones @3 :List(PhoneNumber);

  struct PhoneNumber {
    number @0 :Text;
    type @1 :Type;

    enum Type {
      mobile @0;
      home @1;
      work @2;
    }
  }

  birthdate @4 :Date;
}

struct Date {
  year @0 :Int16;
  month @1 :UInt8;
  day @2 :UInt8;
}

struct AddressBook {
  people @0 :List(Person);
}

# A simple capability-based RPC interface.
interface Directory {
  lookup @0 (id :UInt32) -> (person :Person);
  add @1 (person :Person) -> (id :UInt32);
}
