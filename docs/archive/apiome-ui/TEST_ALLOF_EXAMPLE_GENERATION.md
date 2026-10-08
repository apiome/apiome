# Test Scenario: allOf Example Generation

## Setup

### Step 1: Create Base Class "Animal"
1. Create a new class named "Animal"
2. Add the following properties:
   - `name` (type: string, required: true)
   - `age` (type: integer, required: true)
   - `species` (type: string, required: false)

### Step 2: Create Derived Class "Dog"
1. Create a new class named "Dog"
2. Add the following properties:
   - `breed` (type: string, required: true)
   - `barkVolume` (type: number, required: false)
   - `isTrained` (type: boolean, required: false)

### Step 3: Configure Inheritance
1. Edit the "Dog" class
2. In the composition section, add an `allOf` reference to "Animal"
3. Save the class

## Expected Schema Structure

The Dog class schema should look like:

```json
{
  "allOf": [
    {
      "$ref": "#/components/schemas/Animal"
    }
  ],
  "properties": {
    "breed": {
      "type": "string"
    },
    "barkVolume": {
      "type": "number"
    },
    "isTrained": {
      "type": "boolean"
    }
  },
  "required": ["breed"]
}
```

## Testing Example Generation

### Test 1: View Example in Dialog
1. Click on the "Dog" class to open the Class Edit Dialog
2. Switch to the "EXAMPLE" tab
3. **Expected Result**: The generated example should include ALL properties:
   ```json
   {
     "name": "some-string",
     "age": 42,
     "species": "some-string",
     "breed": "some-string",
     "barkVolume": 3.14,
     "isTrained": true
   }
   ```

### Test 2: Copy Example
1. In the Class Edit Dialog with "Dog" selected
2. Switch to "EXAMPLE" tab
3. Click "Copy" button
4. Paste the clipboard content
5. **Expected Result**: Should contain all properties from both Animal and Dog

### Test 3: Export Example
1. In the Class Edit Dialog with "Dog" selected
2. Switch to "EXAMPLE" tab
3. Click "Export" button
4. Open the downloaded file
5. **Expected Result**: Should contain all properties from both Animal and Dog

### Test 4: Refresh Example
1. In the Class Edit Dialog with "Dog" selected
2. Switch to "EXAMPLE" tab
3. Click "Refresh" button multiple times
4. **Expected Result**: Each refresh should generate different random values but always include all properties

## Console Verification

When viewing the example, check the browser console for debug output:

```
Original schema: { allOf: [...], properties: {...}, required: [...] }
Resolved schema for example generation: { type: 'object', properties: {...}, required: [...] }
Resolved schema properties: { name: {...}, age: {...}, species: {...}, breed: {...}, barkVolume: {...}, isTrained: {...} }
```

The "Resolved schema properties" should show all 6 properties (3 from Animal + 3 from Dog).

## Known Issues Fixed

### Before Fix
- Only Dog's properties (breed, barkVolume, isTrained) appeared in examples
- Animal's properties (name, age, species) were missing

### After Fix
- All properties from both Animal and Dog appear in examples
- Required fields are correctly merged from both classes
- The schema is fully resolved before being passed to json-schema-faker

## Additional Test Cases

### Multi-level Inheritance
1. Create "Mammal" with properties `bloodType`, `furColor`
2. Make "Animal" extend from "Mammal" using `allOf`
3. Verify "Dog" example includes properties from all three classes

### Multiple Parents (anyOf/oneOf)
1. Create "Pet" class with properties `ownerName`, `licenseNumber`
2. Modify "Dog" to use `anyOf` with both "Animal" and "Pet"
3. Verify example generation handles anyOf correctly

