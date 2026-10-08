# Tuple Mode Testing Guide

## Test Suite for OpenAPI 3.1 prefixItems Feature

### Test 1: Create New Tuple Property

**Steps:**
1. Click "Add Property"
2. Name: `coordinateTuple`
3. Set type to "Array"
4. Check "Tuple Mode (prefixItems)" checkbox
5. Click "Add Position"
6. Set Position 0 type to "number"
7. Edit JSON: `{"type": "number", "minimum": -90, "maximum": 90}`
8. Click "Add Position" again
9. Set Position 1 type to "number"
10. Edit JSON: `{"type": "number", "minimum": -180, "maximum": 180}`
11. Set Items Schema to: `false`
12. Click Save

**Expected Result:**
✅ Property created with prefixItems array containing 2 schemas
✅ Items set to false (strict tuple)
✅ Property appears in property list

**Verify in JSON view:**
```json
{
  "type": "array",
  "prefixItems": [
    {"type": "number", "minimum": -90, "maximum": 90},
    {"type": "number", "minimum": -180, "maximum": 180}
  ],
  "items": false
}
```

---

### Test 2: Edit Existing Tuple Property

**Steps:**
1. From Test 1, click edit on `coordinateTuple`
2. Verify Tuple Mode checkbox is checked
3. Verify 2 prefix items are shown
4. Verify Items Schema shows "false"
5. Add a third position
6. Set Position 2 type to "string"
7. Edit JSON: `{"type": "string", "enum": ["N", "S", "E", "W"]}`
8. Click Save

**Expected Result:**
✅ Property updated with 3 prefix items
✅ All previous data preserved
✅ New position added correctly

**Verify in JSON view:**
```json
{
  "type": "array",
  "prefixItems": [
    {"type": "number", "minimum": -90, "maximum": 90},
    {"type": "number", "minimum": -180, "maximum": 180},
    {"type": "string", "enum": ["N", "S", "E", "W"]}
  ],
  "items": false
}
```

---

### Test 3: Drag Tuple Property to Class

**Steps:**
1. From Test 2, drag `coordinateTuple` to a class
2. Drop on class node
3. Verify property added to class
4. Click edit on the class property (in the class node)

**Expected Result:**
✅ Tuple mode checkbox is checked
✅ All 3 prefix items are present with correct schemas
✅ Items schema shows "false"
✅ No data loss during drag-and-drop

---

### Test 4: Reorder Prefix Items

**Steps:**
1. Edit `coordinateTuple` property
2. Drag Position 2 (string with enum) to Position 0
3. Observe positions renumbered
4. Click Save

**Expected Result:**
✅ Position order changed in prefixItems array
✅ Schemas remain intact
✅ New order: string, number, number

---

### Test 5: Tuple Mode with Flexible Items

**Steps:**
1. Create new array property: `csvRow`
2. Enable Tuple Mode
3. Add Position 0: `{"type": "integer", "description": "ID"}`
4. Add Position 1: `{"type": "string", "description": "Name"}`
5. Set Items Schema to: `{"type": "string", "description": "Tags"}`
6. Click Save

**Expected Result:**
✅ First 2 positions are fixed (integer, string)
✅ Additional items allowed (must be strings)
✅ Items is an object schema, not false

**Verify in JSON view:**
```json
{
  "type": "array",
  "prefixItems": [
    {"type": "integer", "description": "ID"},
    {"type": "string", "description": "Name"}
  ],
  "items": {"type": "string", "description": "Tags"}
}
```

---

### Test 6: Disable Tuple Mode

**Steps:**
1. Edit `coordinateTuple` property
2. Uncheck "Tuple Mode" checkbox
3. Note: prefixItems editor should disappear
4. Click Save

**Expected Result:**
✅ prefixItems removed from property data
✅ Property reverts to regular array with items schema
✅ Can set regular array item type

---

### Test 7: Tuple Mode + Contains

**Steps:**
1. Create new array property: `mixedTuple`
2. Enable Tuple Mode
3. Add 2 prefix items with different types
4. Set Items Schema to: `true`
5. Add Contains schema: `{"type": "string", "minLength": 5}`
6. Set minContains: `1`
7. Click Save

**Expected Result:**
✅ Tuple mode and contains work together
✅ At least 1 item must match contains schema
✅ Both features persist when editing

---

### Test 8: Complex Nested Schemas

**Steps:**
1. Create array property: `complexTuple`
2. Enable Tuple Mode
3. Add Position 0 with nested object:
```json
{
  "type": "object",
  "properties": {
    "name": {"type": "string"},
    "age": {"type": "integer"}
  },
  "required": ["name"]
}
```
4. Add Position 1 with nested array:
```json
{
  "type": "array",
  "items": {"type": "number"}
}
```
5. Click Save

**Expected Result:**
✅ Complex nested schemas saved correctly
✅ Position 0 is an object with properties
✅ Position 1 is an array of numbers
✅ Can edit and preserve structure

---

### Test 9: Item Constraints Hidden in Tuple Mode

**Steps:**
1. Create array property with tuple mode enabled
2. Observe the Constraints section
3. Verify message: "Tuple Mode Active"
4. Verify no item-level constraint fields visible

**Expected Result:**
✅ String constraints NOT shown (minLength, maxLength, pattern)
✅ Numeric constraints NOT shown (min, max, multipleOf)
✅ Blue info box explains constraints are per-position
✅ Array constraints still visible (minItems, maxItems, uniqueItems)

---

### Test 10: Empty Tuple (No Positions)

**Steps:**
1. Create array property
2. Enable Tuple Mode
3. Don't add any positions
4. Set Items Schema to: `{"type": "string"}`
5. Click Save

**Expected Result:**
✅ Property saved with empty prefixItems array
✅ Items schema applied to all array elements
✅ Effectively same as regular array with items

---

### Test 11: Delete Prefix Items

**Steps:**
1. Edit property with 3 prefix items
2. Click delete button on Position 1
3. Observe remaining positions renumbered
4. Click Save

**Expected Result:**
✅ Position deleted
✅ Positions 0 and 2 renumbered to 0 and 1
✅ Schemas preserved for remaining positions

---

### Test 12: JSON Validation in Prefix Items

**Steps:**
1. Edit tuple property
2. In a position's JSON editor, enter invalid JSON: `{"type": "string"`
3. Observe error message
4. Try to save

**Expected Result:**
✅ Red border around textarea
✅ Error message: "Invalid JSON"
✅ Can still save (other positions unaffected)
⚠️ Invalid position saved as-is (user's responsibility)

---

### Test 13: Type Dropdown Sync

**Steps:**
1. Edit tuple property
2. Change Position 0 type dropdown to "integer"
3. Observe JSON editor updates
4. Manually change JSON type to "boolean"
5. Observe type dropdown updates

**Expected Result:**
✅ Type dropdown and JSON stay in sync
✅ Changing dropdown updates JSON
✅ Changing JSON updates dropdown (if type field present)

---

### Test 14: Items Schema Boolean Values

**Steps:**
1. Create tuple property
2. Add 2 prefix items
3. Set Items Schema to: `true`
4. Save and re-edit
5. Verify Items Schema shows "true"
6. Change to: `false`
7. Save and re-edit
8. Verify Items Schema shows "false"

**Expected Result:**
✅ Boolean `true` loads correctly
✅ Boolean `false` loads correctly
✅ Both values persist through save/edit cycles

---

### Test 15: Nested Property Drop with Tuple Mode

**Steps:**
1. Create object class with nested properties enabled
2. Create tuple array property
3. Drag tuple property into object property
4. Edit the nested property

**Expected Result:**
✅ Tuple mode preserved in nested context
✅ All prefix items intact
✅ Items schema preserved

---

## Regression Tests

### R1: Regular Arrays Still Work
**Verify:** Non-tuple array properties work as before
- Items schema editable
- Item constraints visible and functional
- No tuple mode UI shown

### R2: Other Property Types Unaffected
**Verify:** String, number, object, boolean properties unchanged
- All constraints work
- No tuple mode UI shown

### R3: Backward Compatibility
**Verify:** Existing properties before tuple feature
- Load correctly
- Edit without issues
- No migration needed

---

## Performance Tests

### P1: Large Tuple (10+ Positions)
- Add 15 prefix items
- Verify drag-and-drop performance
- Verify save/load time acceptable

### P2: Complex Schemas per Position
- Add positions with deeply nested schemas
- Verify editor remains responsive
- Verify no lag when editing JSON

---

## Edge Cases

### E1: Empty Items Schema
- Leave items schema blank
- Expected: Defaults to `true` (any items allowed)

### E2: Malformed Items Schema
- Enter invalid JSON in items schema
- Expected: Validation error or saved as-is

### E3: Mixed minItems/maxItems with Tuple
- Set minItems: 2, maxItems: 2
- Set 3 prefix items with items: false
- Expected: Validation conflict (warn user?)

### E4: Tuple Mode on Non-Array Property
- Try to enable tuple mode on string property
- Expected: Checkbox hidden (only for arrays)

---

## Browser Compatibility

Test on:
- ✅ Chrome/Edge (latest)
- ✅ Firefox (latest)
- ✅ Safari (latest)
- ✅ Mobile Safari (iOS)
- ✅ Mobile Chrome (Android)

---

## Checklist

- [ ] All 15 main tests pass
- [ ] All 3 regression tests pass
- [ ] All 2 performance tests acceptable
- [ ] All 4 edge cases handled
- [ ] Browser compatibility verified
- [ ] No console errors
- [ ] UI is intuitive and responsive
- [ ] Documentation is clear

