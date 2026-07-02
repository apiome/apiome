"""Tests for the compare-any-two canonical model diff (MFI-3.2, #3743).

The acceptance criteria are:

* correct add / remove / modify on cross-format fixtures (REST, event, graph);
* non-adjacent pairs are supported (the diff compares two models *directly*);
* identical models produce an empty diff.

Around those, the tests also pin the properties the diff inherits from the
fingerprint it is taken over (MFI-3.1): documentation-only edits and source
declaration-order differences are invisible, parent/child changes are never
double-counted, output is deterministic, and the per-format label hook dispatches
to a registered labeler. Everything here is pure (no DB/network), mirroring the
diff module itself.
"""

import copy

import pytest

from app.canonical_model import (
    ApiIdentity,
    ApiParadigm,
    CanonicalApi,
    CanonicalField,
    Channel,
    Constraints,
    EnumValue,
    Message,
    MessageRole,
    Operation,
    OperationKind,
    Parameter,
    ParameterLocation,
    Service,
    Type,
    TypeKind,
    TypeRef,
)
from app.diff import (
    ChangeKind,
    DiffLabeler,
    EntityCategory,
    ModelDiff,
    available_diff_formats,
    diff,
    get_diff_labeler,
    register_diff_labeler,
)

# ===========================================================================
# Fixtures
# ===========================================================================


def _rest_api() -> CanonicalApi:
    """A small REST artifact touching services, operations, messages, types, fields."""
    pet_type = Type(
        key="Pet",
        name="Pet",
        kind=TypeKind.RECORD,
        description="A pet.",
        fields=[
            CanonicalField(
                key="Pet.id",
                name="id",
                type=TypeRef(name="integer", nullable=False),
                constraints=Constraints(minimum=1),
                description="The id.",
            ),
            CanonicalField(
                key="Pet.name",
                name="name",
                type=TypeRef(name="string", nullable=False),
                default="unknown",
            ),
        ],
    )
    status_type = Type(
        key="Status",
        name="Status",
        kind=TypeKind.ENUM,
        enum_values=[
            EnumValue(key="Status.ACTIVE", name="ACTIVE", value=0),
            EnumValue(key="Status.RETIRED", name="RETIRED", value=1),
        ],
    )
    get_pet = Operation(
        key="GET /pets/{id}",
        name="getPet",
        kind=OperationKind.REQUEST_RESPONSE,
        http_method="GET",
        http_path="/pets/{id}",
        description="Fetch a pet.",
        parameters=[
            Parameter(
                key="GET /pets/{id}#path.id",
                name="id",
                location=ParameterLocation.PATH,
                type=TypeRef(name="integer", nullable=False),
                required=True,
            )
        ],
        messages=[
            Message(
                key="GET /pets/{id}#response.200",
                role=MessageRole.RESPONSE,
                status_code="200",
                payload=TypeRef(name="Pet"),
                content_types=["application/json"],
                description="OK.",
            )
        ],
    )
    return CanonicalApi(
        paradigm=ApiParadigm.REST,
        format="openapi-3.1",
        protocol="http",
        identity=ApiIdentity(name="Pets", namespace="com.acme.pets"),
        version="1.0.0",
        title="Pets API",
        description="A pets API.",
        services=[Service(key="pets", name="pets", operations=[get_pet])],
        types=[pet_type, status_type],
        raw={"openapi": "3.1.0", "x-comment": "irrelevant to identity"},
    )


def _event_api() -> CanonicalApi:
    """A small event artifact touching a channel and a pub operation."""
    signup_channel = Channel(
        key="user/signedup",
        address="user/signedup",
        protocol="kafka",
        description="User signups.",
        parameters=[
            CanonicalField(key="user/signedup#userId", name="userId", type=TypeRef(name="string")),
        ],
        bindings={"kafka": {"partitions": 3}},
    )
    publish = Operation(
        key="publish user/signedup",
        name="publishSignup",
        kind=OperationKind.PUBLISH,
        channel_ref="user/signedup",
        messages=[
            Message(
                key="publish user/signedup#event",
                role=MessageRole.EVENT,
                payload=TypeRef(name="SignupEvent"),
            )
        ],
    )
    return CanonicalApi(
        paradigm=ApiParadigm.EVENT,
        format="asyncapi-3",
        protocol="kafka",
        identity=ApiIdentity(name="Signups"),
        services=[Service(key="signups", name="signups", operations=[publish])],
        channels=[signup_channel],
    )


def _graph_api() -> CanonicalApi:
    """A small GraphQL artifact touching a query operation and an object type."""
    user_type = Type(
        key="User",
        name="User",
        kind=TypeKind.RECORD,
        fields=[
            CanonicalField(key="User.id", name="id", type=TypeRef(name="ID", nullable=False)),
            CanonicalField(key="User.email", name="email", type=TypeRef(name="String")),
        ],
    )
    user_query = Operation(
        key="Query.user",
        name="user",
        kind=OperationKind.QUERY,
        messages=[
            Message(
                key="Query.user#response",
                role=MessageRole.RESPONSE,
                payload=TypeRef(name="User"),
            )
        ],
    )
    return CanonicalApi(
        paradigm=ApiParadigm.GRAPH,
        format="graphql",
        protocol="graphql-over-http",
        identity=ApiIdentity(name="Graph"),
        services=[Service(key="Query", name="Query", operations=[user_query])],
        types=[user_type],
    )


# ===========================================================================
# Identical → empty diff
# ===========================================================================


@pytest.mark.parametrize("factory", [_rest_api, _event_api, _graph_api])
def test_identical_models_produce_empty_diff(factory):
    """Identical models → empty diff and equal fingerprints, for every paradigm."""
    result = diff(factory(), factory())
    assert isinstance(result, ModelDiff)
    assert result.is_empty()
    assert result.changes == []
    assert result.identical is True
    assert result.base_fingerprint == result.target_fingerprint
    assert result.counts.total == 0
    assert result.counts_by_category == {}


def test_diff_of_self_is_empty():
    """A model diffed against itself is empty."""
    api = _rest_api()
    assert diff(api, api).is_empty()


def test_artifact_metadata_edit_flips_fingerprint_without_an_entity_change():
    """A version-only edit is outside the six categories: empty changes, not identical.

    Pins the documented boundary between ``is_empty()`` (no entity change) and
    ``identical`` (fingerprint match): a bare ``version`` bump flips the fingerprint
    but itemizes no service/operation/message/channel/type/field change.
    """
    base = _rest_api()
    target = _rest_api()
    target.version = "2.0.0"
    result = diff(base, target)
    assert result.is_empty()
    assert result.identical is False
    assert result.base_fingerprint != result.target_fingerprint


# ===========================================================================
# Doc-only and ordering invariance (inherited from the fingerprint projection)
# ===========================================================================


def test_doc_only_edit_is_not_a_change():
    """Editing only descriptions/titles/raw produces an empty diff."""
    base = _rest_api()
    target = _rest_api()
    target.description = "A completely rewritten prose description."
    target.title = "Renamed title"
    target.services[0].operations[0].description = "New op prose."
    target.types[0].fields[0].description = "New field prose."
    target.raw = {"openapi": "3.1.0", "x-comment": "totally different comment"}
    result = diff(base, target)
    assert result.is_empty()
    assert result.identical is True


def test_declaration_order_is_not_a_change():
    """Reordering identity-keyed collections produces an empty diff."""
    base = _rest_api()
    target = _rest_api()
    target.types.reverse()
    target.types[-1].fields.reverse()  # Pet.id / Pet.name reordered
    result = diff(base, target)
    assert result.is_empty()


# ===========================================================================
# Add / remove / modify — fields
# ===========================================================================


def _changes_for(result: ModelDiff, category: EntityCategory):
    return [c for c in result.changes if c.category == category]


def test_added_field_is_reported_as_added_not_type_modified():
    """A new field on a record type is an added FIELD, and the type is not 'modified'."""
    base = _rest_api()
    target = _rest_api()
    target.types[0].fields.append(
        CanonicalField(key="Pet.tag", name="tag", type=TypeRef(name="string"))
    )
    result = diff(base, target)

    field_changes = _changes_for(result, EntityCategory.FIELD)
    assert len(field_changes) == 1
    added = field_changes[0]
    assert added.kind is ChangeKind.ADDED
    assert added.key == "Pet.tag"
    assert added.before is None
    assert added.after is not None and added.after["name"] == "tag"

    # The owning type is unchanged in its own attributes → no TYPE change.
    assert _changes_for(result, EntityCategory.TYPE) == []
    assert result.counts.added == 1
    assert result.counts.total == 1


def test_removed_field_is_reported():
    """Dropping a field surfaces a single removed FIELD with a before projection."""
    base = _rest_api()
    target = _rest_api()
    target.types[0].fields.pop()  # drop Pet.name
    result = diff(base, target)

    field_changes = _changes_for(result, EntityCategory.FIELD)
    assert len(field_changes) == 1
    removed = field_changes[0]
    assert removed.kind is ChangeKind.REMOVED
    assert removed.key == "Pet.name"
    assert removed.after is None
    assert removed.before["name"] == "name"
    assert result.counts.removed == 1


def test_modified_field_carries_before_after_and_field_breakdown():
    """Retyping a field is a modify with a per-attribute breakdown of just 'type'."""
    base = _rest_api()
    target = _rest_api()
    target.types[0].fields[0].type = TypeRef(name="string", nullable=False)  # Pet.id int→string
    result = diff(base, target)

    field_changes = _changes_for(result, EntityCategory.FIELD)
    assert len(field_changes) == 1
    modified = field_changes[0]
    assert modified.kind is ChangeKind.MODIFIED
    assert modified.key == "Pet.id"
    assert modified.before is not None and modified.after is not None
    changed_attrs = {fc.field for fc in modified.fields}
    assert changed_attrs == {"type"}
    type_fc = modified.fields[0]
    assert type_fc.before["name"] == "integer"
    assert type_fc.after["name"] == "string"
    assert result.counts.modified == 1


def test_field_default_change_is_detected():
    """A changed default (a literal kept verbatim by the projection) is a modify."""
    base = _rest_api()
    target = _rest_api()
    target.types[0].fields[1].default = "anonymous"  # Pet.name default
    result = diff(base, target)
    field_changes = _changes_for(result, EntityCategory.FIELD)
    assert len(field_changes) == 1
    assert {fc.field for fc in field_changes[0].fields} == {"default"}


def test_field_constraint_change_is_detected():
    """A tightened constraint is a modify on the field's 'constraints' attribute."""
    base = _rest_api()
    target = _rest_api()
    target.types[0].fields[0].constraints = Constraints(minimum=10)
    result = diff(base, target)
    field_changes = _changes_for(result, EntityCategory.FIELD)
    assert {fc.field for fc in field_changes[0].fields} == {"constraints"}


# ===========================================================================
# Add / remove / modify — types, operations, messages, services
# ===========================================================================


def test_added_type_is_reported_with_its_fields():
    """Adding a record type surfaces the type plus each of its fields."""
    base = _rest_api()
    target = _rest_api()
    target.types.append(
        Type(
            key="Owner",
            name="Owner",
            kind=TypeKind.RECORD,
            fields=[CanonicalField(key="Owner.name", name="name", type=TypeRef(name="string"))],
        )
    )
    result = diff(base, target)
    type_changes = _changes_for(result, EntityCategory.TYPE)
    field_changes = _changes_for(result, EntityCategory.FIELD)
    assert [c.key for c in type_changes] == ["Owner"]
    assert type_changes[0].kind is ChangeKind.ADDED
    # The added type's self-projection excludes its separately-reported fields.
    assert "fields" not in type_changes[0].after
    assert [c.key for c in field_changes] == ["Owner.name"]
    assert field_changes[0].kind is ChangeKind.ADDED


def test_enum_value_change_is_a_type_modification():
    """Enum values are part of the type's self-projection (not a FIELD category)."""
    base = _rest_api()
    target = _rest_api()
    target.types[1].enum_values.append(
        EnumValue(key="Status.LOST", name="LOST", value=2)
    )
    result = diff(base, target)
    type_changes = _changes_for(result, EntityCategory.TYPE)
    assert len(type_changes) == 1
    assert type_changes[0].key == "Status"
    assert type_changes[0].kind is ChangeKind.MODIFIED
    assert {fc.field for fc in type_changes[0].fields} == {"enum_values"}
    assert _changes_for(result, EntityCategory.FIELD) == []


def test_operation_attribute_change_is_a_modify_not_message_change():
    """Changing an operation's verb modifies the operation only, not its messages."""
    base = _rest_api()
    target = _rest_api()
    target.services[0].operations[0].http_method = "HEAD"
    result = diff(base, target)
    op_changes = _changes_for(result, EntityCategory.OPERATION)
    assert len(op_changes) == 1
    assert op_changes[0].key == "GET /pets/{id}"
    assert {fc.field for fc in op_changes[0].fields} == {"http_method"}
    assert _changes_for(result, EntityCategory.MESSAGE) == []


def test_operation_parameter_change_is_an_operation_modification():
    """Parameters fold into the operation's self-projection (not their own category)."""
    base = _rest_api()
    target = _rest_api()
    target.services[0].operations[0].parameters[0].required = False
    result = diff(base, target)
    op_changes = _changes_for(result, EntityCategory.OPERATION)
    assert len(op_changes) == 1
    assert {fc.field for fc in op_changes[0].fields} == {"parameters"}


def test_message_change_is_reported():
    """Changing a message's status code is a MESSAGE modification."""
    base = _rest_api()
    target = _rest_api()
    target.services[0].operations[0].messages[0].status_code = "201"
    result = diff(base, target)
    msg_changes = _changes_for(result, EntityCategory.MESSAGE)
    assert len(msg_changes) == 1
    assert msg_changes[0].key == "GET /pets/{id}#response.200"
    assert {fc.field for fc in msg_changes[0].fields} == {"status_code"}


def test_removing_a_service_reports_service_operations_and_messages():
    """A whole-service removal flattens to the service + each child entity removed."""
    base = _rest_api()
    target = _rest_api()
    target.services = []
    result = diff(base, target)
    assert {c.category for c in result.changes} == {
        EntityCategory.SERVICE,
        EntityCategory.OPERATION,
        EntityCategory.MESSAGE,
    }
    assert all(c.kind is ChangeKind.REMOVED for c in result.changes)
    assert _changes_for(result, EntityCategory.SERVICE)[0].key == "pets"
    assert _changes_for(result, EntityCategory.OPERATION)[0].key == "GET /pets/{id}"
    assert _changes_for(result, EntityCategory.MESSAGE)[0].key == "GET /pets/{id}#response.200"


# ===========================================================================
# Channels (event paradigm)
# ===========================================================================


def test_channel_binding_change_is_a_channel_modification():
    """A changed protocol binding (opaque bag, kept verbatim) modifies the channel."""
    base = _event_api()
    target = _event_api()
    target.channels[0].bindings = {"kafka": {"partitions": 6}}
    result = diff(base, target)
    channel_changes = _changes_for(result, EntityCategory.CHANNEL)
    assert len(channel_changes) == 1
    assert channel_changes[0].key == "user/signedup"
    assert {fc.field for fc in channel_changes[0].fields} == {"bindings"}


def test_added_channel_is_reported():
    """A new channel surfaces as an added CHANNEL."""
    base = _event_api()
    target = _event_api()
    target.channels.append(Channel(key="user/deleted", address="user/deleted", protocol="kafka"))
    result = diff(base, target)
    channel_changes = _changes_for(result, EntityCategory.CHANNEL)
    assert [c.key for c in channel_changes] == ["user/deleted"]
    assert channel_changes[0].kind is ChangeKind.ADDED


# ===========================================================================
# Compare-any-two (non-adjacent) and cross-format
# ===========================================================================


def test_non_adjacent_pair_is_compared_directly():
    """v1 → v3 equals the net of v1→v2 and v2→v3 (no step-chaining drift)."""
    v1 = _rest_api()
    v2 = _rest_api()
    v2.types[0].fields.append(
        CanonicalField(key="Pet.tag", name="tag", type=TypeRef(name="string"))
    )
    v3 = _rest_api()
    # v3 keeps the v2 addition and also drops Pet.name and adds a type.
    v3.types[0].fields.append(
        CanonicalField(key="Pet.tag", name="tag", type=TypeRef(name="string"))
    )
    v3.types[0].fields = [f for f in v3.types[0].fields if f.key != "Pet.name"]
    v3.types.append(Type(key="Owner", name="Owner", kind=TypeKind.SCALAR))

    direct = diff(v1, v3)
    field_keys = {c.key: c.kind for c in _changes_for(direct, EntityCategory.FIELD)}
    assert field_keys == {"Pet.tag": ChangeKind.ADDED, "Pet.name": ChangeKind.REMOVED}
    assert [c.key for c in _changes_for(direct, EntityCategory.TYPE)] == ["Owner"]


def test_cross_format_diff_pairs_by_key():
    """Diffing two different-format models reports everything added/removed by key."""
    result = diff(_rest_api(), _graph_api())
    # No keys overlap, so every base entity is removed and every target entity added.
    assert result.counts.modified == 0
    assert result.counts.added > 0 and result.counts.removed > 0
    kinds = {c.kind for c in result.changes}
    assert kinds == {ChangeKind.ADDED, ChangeKind.REMOVED}
    # Fingerprints differ for different artifacts.
    assert result.base_fingerprint != result.target_fingerprint


# ===========================================================================
# Counts and determinism
# ===========================================================================


def test_counts_overall_and_per_category():
    """Counts aggregate correctly and break down per category."""
    base = _rest_api()
    target = _rest_api()
    target.types[0].fields.append(
        CanonicalField(key="Pet.tag", name="tag", type=TypeRef(name="string"))
    )  # +1 field
    target.types[0].fields[0].constraints = Constraints(minimum=5)  # modify Pet.id
    target.types.append(Type(key="Owner", name="Owner", kind=TypeKind.SCALAR))  # +1 type
    result = diff(base, target)

    assert result.counts.added == 2  # Pet.tag field + Owner type
    assert result.counts.modified == 1  # Pet.id
    assert result.counts.removed == 0
    assert result.counts.total == 3
    assert result.counts_by_category["field"].added == 1
    assert result.counts_by_category["field"].modified == 1
    assert result.counts_by_category["type"].added == 1
    assert "service" not in result.counts_by_category


def test_changes_are_deterministically_ordered():
    """Changes sort by (category spine, key) regardless of source mutation order."""
    base = _rest_api()
    target = _rest_api()
    target.types.append(Type(key="Owner", name="Owner", kind=TypeKind.SCALAR))
    target.types[0].fields.append(
        CanonicalField(key="Pet.zzz", name="zzz", type=TypeRef(name="string"))
    )
    target.services[0].operations[0].http_method = "HEAD"

    first = diff(base, target)
    second = diff(base, target)
    order_first = [(c.category.value, c.key) for c in first.changes]
    order_second = [(c.category.value, c.key) for c in second.changes]
    assert order_first == order_second
    # Category spine order: operation (1) before type (4) before field (5).
    categories_in_order = [c.category for c in first.changes]
    assert categories_in_order == sorted(
        categories_in_order, key=lambda c: {
            EntityCategory.OPERATION: 1,
            EntityCategory.TYPE: 4,
            EntityCategory.FIELD: 5,
        }[c]
    )


def test_diff_does_not_mutate_inputs():
    """diff() leaves both input models untouched."""
    base = _rest_api()
    target = _rest_api()
    target.types[0].fields[0].constraints = Constraints(minimum=99)
    base_snapshot = copy.deepcopy(base.model_dump())
    target_snapshot = copy.deepcopy(target.model_dump())
    diff(base, target)
    assert base.model_dump() == base_snapshot
    assert target.model_dump() == target_snapshot


def test_model_diff_is_json_serializable():
    """ModelDiff round-trips through JSON (it is persisted as JSONB by MFI-3.4)."""
    base = _rest_api()
    target = _rest_api()
    target.types[0].fields[0].type = TypeRef(name="string")
    result = diff(base, target)
    dumped = result.model_dump_json()
    reloaded = ModelDiff.model_validate_json(dumped)
    assert reloaded.counts.total == result.counts.total
    assert [c.key for c in reloaded.changes] == [c.key for c in result.changes]


# ===========================================================================
# Per-format label enrichment SPI
# ===========================================================================


def test_no_labeler_leaves_labels_unset():
    """With no labeler registered for the format, every change label is None."""
    base = _rest_api()
    target = _rest_api()
    target.types[0].fields[0].type = TypeRef(name="string")
    result = diff(base, target)
    assert all(c.label is None for c in result.changes)


def test_registered_labeler_enriches_change_labels():
    """A registered labeler annotates each change; dispatch is by target.format."""

    class _StubLabeler(DiffLabeler):
        format = "stub-format"

        def label(self, change, base, target):
            return f"{change.category.value}:{change.kind.value}"

    register_diff_labeler(_StubLabeler)
    try:
        assert get_diff_labeler("stub-format") is _StubLabeler
        assert "stub-format" in available_diff_formats()

        base = _rest_api()
        base.format = "stub-format"
        target = _rest_api()
        target.format = "stub-format"
        target.types[0].fields.append(
            CanonicalField(key="Pet.tag", name="tag", type=TypeRef(name="string"))
        )
        result = diff(base, target)
        assert result.changes[0].label == "field:added"
    finally:
        # Keep the global registry clean for other tests.
        from app.diff import _LABELER_REGISTRY

        _LABELER_REGISTRY.pop("stub-format", None)


def test_labeler_returning_none_leaves_label_unset():
    """A labeler may return None for a change to leave it bare."""

    class _NoneLabeler(DiffLabeler):
        format = "none-format"

        def label(self, change, base, target):
            return None

    register_diff_labeler(_NoneLabeler)
    try:
        base = _rest_api()
        base.format = "none-format"
        target = _rest_api()
        target.format = "none-format"
        target.types.append(Type(key="Owner", name="Owner", kind=TypeKind.SCALAR))
        result = diff(base, target)
        assert result.changes and all(c.label is None for c in result.changes)
    finally:
        from app.diff import _LABELER_REGISTRY

        _LABELER_REGISTRY.pop("none-format", None)


def test_self_registration_via_subclass_flag():
    """A subclass with register=True self-registers in the labeler registry."""

    class _AutoLabeler(DiffLabeler, register=True):
        format = "auto-format"

        def label(self, change, base, target):
            return "x"

    try:
        assert get_diff_labeler("auto-format") is _AutoLabeler
    finally:
        from app.diff import _LABELER_REGISTRY

        _LABELER_REGISTRY.pop("auto-format", None)


def test_register_requires_nonempty_format():
    """Registering a labeler with an empty format key raises."""

    class _BlankLabeler(DiffLabeler):
        def label(self, change, base, target):
            return None

    with pytest.raises(ValueError, match="non-empty `format`"):
        register_diff_labeler(_BlankLabeler)


def test_register_conflicting_format_raises():
    """Two different classes cannot register under the same format key."""

    class _First(DiffLabeler):
        format = "dup-format"

        def label(self, change, base, target):
            return None

    class _Second(DiffLabeler):
        format = "dup-format"

        def label(self, change, base, target):
            return None

    register_diff_labeler(_First)
    try:
        with pytest.raises(ValueError, match="already registered"):
            register_diff_labeler(_Second)
        # Re-registering the same class is a no-op (module re-import safety).
        assert register_diff_labeler(_First) is _First
    finally:
        from app.diff import _LABELER_REGISTRY

        _LABELER_REGISTRY.pop("dup-format", None)
