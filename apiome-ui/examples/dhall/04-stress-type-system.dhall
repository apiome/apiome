-- Above the divider: types a JSON Schema projection can carry.
-- Below it: Dhall constructs that exceed it, which FMT-8.5 requires declared as limits.

-- ---------------------------------------------------------------- expressible

let Scalars =
      { text : Text
      , count : Natural
      , signed : Integer
      , ratio : Double
      , flag : Bool
      , nothing : Optional Text
      , when : Text
      }

let Level = < Debug | Info | Warn | Error >

let Shape = < Circle : { radius : Double } | Square : { side : Double } | Point >

let Collections =
      { items : List Text
      , pairs : List { mapKey : Text, mapValue : Natural }
      , nested : List (List Natural)
      , optionalList : Optional (List Text)
      }

let Nested = { inner : { deep : { value : Natural } } }

let WithDefaults =
      { Type = { level : Level, retries : Natural, label : Text }
      , default = { level = Level.Info, retries = 3, label = "unnamed" }
      }

let recordTypeMerge = Scalars //\\ { extra : Bool }

let recordPrefer = { a = 1 } /\ { b = 2 }

-- ---------------------------------------------------------------- declared limits

-- Functions: Dhall types are values, so a schema can be *computed*.
let Page = \(a : Type) -> { items : List a, total : Natural, cursor : Optional Text }

let OrderPage = Page Text

-- Dependent-ish construction: the record's shape depends on a parameter.
let withEnvelope =
      \(payload : Type) ->
      \(withTrace : Bool) ->
        { payload : payload
        , meta : List { mapKey : Text, mapValue : Text }
        }

-- A fold, evaluated during normalization.
let total =
      List/fold
        Natural
        [ 1, 2, 3 ]
        Natural
        (\(x : Natural) -> \(acc : Natural) -> x + acc)
        0

-- Imports as values, including one with an integrity hash (with a fallback, because this
-- file is imported on its own and the pinned file is not beside it).
let remoteType =
        ./shared.dhall
          sha256:0000000000000000000000000000000000000000000000000000000000000000
      ? { line1 : Text }

in  { Scalars
    , Level
    , Shape
    , Collections
    , Nested
    , WithDefaults
    , recordTypeMerge
    , recordPrefer
    , Page
    , OrderPage
    , withEnvelope
    , total
    }
