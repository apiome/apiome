# Property Deduplication Test Suite

## Overview
This test suite verifies the property library deduplication logic in the OpenAPI importer. It includes four comprehensive test files covering different scenarios.

## Test Files

### 1. test-property-reuse-same.yaml
**Purpose:** Verify that properties with identical definitions are correctly reused across multiple schemas.

**Schemas:** User, Product, Order, Invoice (4 schemas)

**Key Properties to Test:**
- `id` (uuid) - Should appear 4 times, but ONE library property
- `name` (string) - Should appear 2 times, but ONE library property
- `email` (email) - Should appear 3 times, but ONE library property
- `status` (enum with same values) - Should appear 4 times, but ONE library property
- `createdAt` (date-time) - Should appear 4 times, but ONE library property

**Expected Result:**
- 9 properties in library total
- Import log should show: "Creating property: id (used as: id, id, id, id)"
- Each class should link to the same property IDs

**Success Criteria:**
✅ Property library has 9 entries (not 20+)
✅ Each property shows multiple uses in debug log
✅ Database query shows property_id reused across class_properties

### 2. test-property-conflict-diff.yaml
**Purpose:** Verify that properties with the same name but different definitions create separate library entries.

**Schemas:** Customer, Transaction, Shipment, Document (4 schemas)

**Key Conflicts to Test:**
- `id`: 3 different types (uuid, int64, pattern string)
- `name`: 3 different constraints (max 100, min 1, no constraints)
- `status`: 4 different enum sets
- `metadata`: 4 different types (object, string, array, object with different props)

**Expected Result:**
- 14 unique properties in library
- Each conflicting property should have separate library entry
- Import log should show separate creation for each variant

**Success Criteria:**
✅ Property library has exactly 14 entries
✅ No property reuse across conflicting definitions
✅ Each property has unique signature in database

### 3. test-property-mixed.yaml
**Purpose:** Realistic scenario combining both reuse and conflicts.

**Schemas:** Person, Employee, Contract, Vendor (4 schemas)

**Reused Properties (should be shared):**
- `id` (uuid) - Person, Employee, Vendor (3 uses, 1 library entry)
- `firstName` (string, min 1, max 50) - Person, Employee (2 uses, 1 library entry)
- `lastName` (string, min 1, max 50) - Person, Employee (2 uses, 1 library entry)
- `email` (email format) - Person, Employee, Vendor (3 uses, 1 library entry)
- `tags` (array of strings) - Person, Employee, Vendor (3 uses, 1 library entry)

**Conflicting Properties (should be separate):**
- `id` (int64) - Contract (different from uuid)
- `firstName` (no constraints) - Contract (different from Person/Employee)
- `age` (0-150) vs (18-70) - Person vs Employee (2 separate entries)
- `tags` (object) - Contract (different from array)
- Plus unique properties: employeeId, duration, companyName, rating

**Expected Result:**
- 16 properties in library (5 reused + 11 unique)
- Clear distinction between reused and separate properties

**Success Criteria:**
✅ Property library has 16 entries
✅ UUID id is reused 3 times
✅ Int64 id is separate
✅ firstName/lastName with constraints reused
✅ firstName/lastName without constraints separate

### 4. test-property-edge-cases.yaml
**Purpose:** Test subtle differences that should or shouldn't trigger separate properties.

**Schemas:** Article, NewsPost, VideoPost (3 schemas)

**Edge Cases to Test:**

1. **Description differences (should NOT create separate properties):**
   - `content` with different description text
   - Should be REUSED (description is metadata, not part of signature)

2. **Constraint differences (should create separate properties):**
   - `title` with maxLength: 200 vs maxLength: 150
   - Should be SEPARATE

3. **Nested structure differences (should create separate properties):**
   - `author` with {name, email} vs {name, bio}
   - Should be SEPARATE

4. **Array item type differences (should create separate properties):**
   - `comments` as array of different object structures
   - Should be SEPARATE

**Expected Result:**
- 9 unique properties in library
- Content property reused despite description differences
- Structural differences create separate properties

**Success Criteria:**
✅ Property library has 9 entries
✅ Content property is reused 3 times (same signature)
✅ Title variants are separate (different constraints)
✅ Author variants are separate (different nested structure)
✅ Comments variants are separate (different array items)

## Testing Procedure

### Step 1: Import Each Test File

```bash
# Start the application
yarn --cwd apiome/apiome-ui dev

# Navigate to: ADE → Dashboard → Projects → Import
# For each test file:
1. Upload the YAML file
2. Review analysis (should show valid OpenAPI 3.1.0)
3. Preview schemas (all should be selected)
4. Click "Import →"
5. Monitor Live Progress and Import Log
```

### Step 2: Review Import Logs

Look for these debug events in the Import Log:

```
DEBUG_PROPERTY: Creating property: <name> (used as: <name1>, <name2>, ...)
```

**For test-property-reuse-same.yaml:**
```
Creating property: id (used as: id)
Creating property: name (used as: name)
Creating property: email (used as: email)
Creating property: status (used as: status)
Creating property: createdAt (used as: createdAt)
Creating property: description (used as: description)
Creating property: price (used as: price)
Creating property: total (used as: total)
Creating property: amount (used as: amount)
```
✅ Only 9 CREATE events (not 20+)

**For test-property-conflict-diff.yaml:**
```
Creating property: id (used as: id)
Creating property: name (used as: name)
Creating property: status (used as: status)
Creating property: metadata (used as: metadata)
... (14 total CREATE events)
```
✅ 14 CREATE events (one for each unique signature)

### Step 3: Verify in Database

```sql
-- Check property library for the imported project
SELECT 
  p.id,
  p.name,
  p.description,
  COUNT(cp.id) as usage_count
FROM apiome.properties p
LEFT JOIN apiome.class_properties cp ON cp.property_id = p.id
LEFT JOIN apiome.classes c ON c.id = cp.class_id
LEFT JOIN apiome.versions v ON v.id = c.version_id
WHERE p.project_id = '<imported-project-id>'
GROUP BY p.id, p.name, p.description
ORDER BY usage_count DESC, p.name;
```

**Expected for test-property-reuse-same.yaml:**
```
name          | usage_count
--------------+------------
id            | 4          ← REUSED across 4 schemas
status        | 4          ← REUSED across 4 schemas
createdAt     | 4          ← REUSED across 4 schemas
email         | 3          ← REUSED across 3 schemas
name          | 2          ← REUSED across 2 schemas
description   | 1
price         | 1
total         | 1
amount        | 1
```

**Expected for test-property-conflict-diff.yaml:**
```
name          | usage_count
--------------+------------
id            | 1          ← Each conflict creates separate entry
id#2          | 1
id#3          | 1
name          | 1
name#2        | 1
name#3        | 1
(14 rows total, each with count 1)
```

### Step 4: Verify in Studio Code View

1. Open imported project in Studio
2. Switch to "Code" view
3. Select "OpenAPI Specification"
4. Check generated YAML:

**For reused properties:**
```yaml
User:
  properties:
    id:
      type: string
      format: uuid
      description: Unique identifier  # ✅ Description preserved
```

**For all schemas:**
```yaml
# Verify that properties with same definition appear identical
# across all schemas (proving they're from the same library property)
```

### Step 5: Export and Re-import Test

1. Export the project as OpenAPI spec
2. Import the exported spec
3. Verify property deduplication still works
4. Compare property counts before/after

This verifies that the round-trip (import → export → import) maintains property integrity.

## Troubleshooting

### Problem: All properties are reused (even conflicts)
**Symptom:** test-property-conflict-diff.yaml shows 4 properties instead of 14

**Cause:** Signature matching is too loose (ignoring important differences)

**Fix Needed:** Update signature generation in import-helper.ts to include all relevant fields

### Problem: No properties are reused (even identical ones)
**Symptom:** test-property-reuse-same.yaml shows 20+ properties instead of 9

**Cause:** Signature matching is too strict (including metadata like descriptions)

**Fix Needed:** Update signature generation to exclude description field

### Problem: Inconsistent reuse behavior
**Symptom:** Some identical properties reuse, others don't

**Cause:** Property order or normalization differences

**Fix Needed:** Ensure JSON.stringify produces consistent signatures (sort keys)

## Success Metrics

### All Tests Pass When:

1. **test-property-reuse-same.yaml:**
   - ✅ 9 properties in library
   - ✅ High usage_count for common properties
   - ✅ Import log shows reuse patterns

2. **test-property-conflict-diff.yaml:**
   - ✅ 14 properties in library
   - ✅ All usage_count = 1 (no reuse)
   - ✅ Each variant creates separate entry

3. **test-property-mixed.yaml:**
   - ✅ 16 properties in library
   - ✅ 5 properties show usage_count > 1
   - ✅ 11 properties show usage_count = 1

4. **test-property-edge-cases.yaml:**
   - ✅ 9 properties in library
   - ✅ Content property usage_count = 3
   - ✅ Title shows 2 variants
   - ✅ Author shows 2 variants

## Current Implementation Status

Based on the fixes applied:

✅ Properties use original names from schema
✅ Deduplication by JSON signature (JSON.stringify(data))
✅ Descriptions tracked but not in signature
✅ Property library creation working
✅ Property linking to classes working

**Potential Issues to Watch:**
⚠️ JSON.stringify key order consistency
⚠️ Description field handling (should NOT affect signature)
⚠️ Nested property signature generation
⚠️ Array items signature generation

## Next Steps After Testing

1. Run all 4 test imports
2. Document actual vs expected results
3. Fix any discrepancies in signature generation
4. Add unit tests for signature matching
5. Consider adding deduplication statistics to import summary

