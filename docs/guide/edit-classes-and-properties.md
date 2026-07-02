# How do I… edit classes & properties?

A **class** is a schema object (it becomes an OpenAPI component schema); its **properties** are the
fields. Editing classes and properties is how you shape the data model that your published spec
exposes. Every class must carry a description before a version can be published (see the publish
gates in [publish-a-version.md](publish-a-version.md)).

---

## In the UI

1. Open the **Designer** at `/ade/studio`.
2. Select a class on the canvas (or **Add a class → Browse templates** to start from one of the
   built-in starter templates).
3. Edit the class name and description, then add or edit properties — type, description, required.
4. Changes are saved through the same REST endpoints listed below.

## With the REST API

Update a class (name, description, metadata):

```http
PUT /v1/classes/{tenant_slug}/{class_id}
X-API-Key: <your-api-key>

{ "description": "A pet available in the store." }
```

Update a single property on a class:

```http
PUT /v1/classes/{tenant_slug}/{class_id}/properties/{class_property_id}
X-API-Key: <your-api-key>

{ "description": "Unique identifier for the pet.", "required": true }
```

## With the CLI

The CLI is **read-only** for classes and properties (authoring happens in the UI/REST). Inspect them
with:

```bash
apiome schemas list                       # all classes in the tenant
apiome schemas get <class_id>             # one class
apiome properties list --project-id <id>  # properties in a project
```

## Verify

- **UI:** the class shows its new description; properties reflect their edits.
- **Lint:** run [lint-and-quality.md](lint-and-quality.md) — documented classes raise the score and
  clear the "missing description" findings that block publishing.

## Related

- [edit-paths.md](edit-paths.md) — paths reference these classes in request/response bodies
- [lint-and-quality.md](lint-and-quality.md) — see what still needs documenting
