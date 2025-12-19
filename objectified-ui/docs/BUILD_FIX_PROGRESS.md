# Build Issues Fix Progress - December 18, 2025

## Summary

Successfully fixed multiple build-blocking errors in PropertyFormFields.tsx:

### ✅ FIXED Issues

1. **Size Prop Error** - Removed all `size={size}` props from Input components (~20 instances)
2. **Label Prop Error** - Removed all `label="..."` props from Input components
3. **HelperText Prop Error** - Removed all `helperText="..."` props from Input components  
4. **Multiline Prop Error** - Removed `multiline` and `rows` props from Input components
5. **JSX Parsing Error** - Fixed malformed JSX structure around "Unique Items" checkbox (lines 1085-1095)

### 🔴 REMAINING Issues

The build is still failing on:

**sx_old Props** - Line 979 and others
```
Type error: Property 'sx_old' does not exist on type 'DetailedHTMLProps<HTMLAttributes<HTMLDivElement>, HTMLDivElement>'.
```

These `sx_old` props need to be removed. They are Material UI remnants that were left as markers during conversion.

## Recommended Next Steps

Run this command to remove all remaining `sx_old` and `sx` props:

```bash
cd /Users/kenji/Development/objectified/objectified-ui && python3 << 'PYEOF'
import re

with open('src/app/components/ade/studio/PropertyFormFields.tsx', 'r') as f:
    lines = f.readlines()

new_lines = []
in_sx_block = False
brace_depth = 0

for line in lines:
    # Skip lines that are part of an sx block
    if in_sx_block:
        brace_depth += line.count('{') - line.count('}')
        if brace_depth <= 0:
            in_sx_block = False
        continue
    
    # Check if this line starts an sx or sx_old block
    if 'sx={{' in line or 'sx_old={{' in line:
        # Count braces to see if it's multi-line
        brace_depth = line.count('{') - line.count('}')
        if brace_depth > 0:
            # Multi-line sx block starts here
            in_sx_block = True
            continue
        else:
            # Single-line sx, remove it
            line = re.sub(r'\s+sx={{[^}]+}}', '', line)
            line = re.sub(r'\s+sx_old={{[^}]+}}', '', line)
    
    new_lines.append(line)

with open('src/app/components/ade/studio/PropertyFormFields.tsx', 'w') as f:
    f.writelines(new_lines)

print("Removed all sx and sx_old props")
PYEOF
```

Then run `yarn build` again to check for additional errors.

## Other Known Issues to Fix

After removing sx props, you'll likely encounter:

1. **Radio component errors** - `Radio` is not defined (Material UI component)
2. **control prop errors** - FormControlLabel pattern needs conversion
3. **Checkbox sx props** - Need to be removed
4. **CollapsibleContent timeout prop** - Not valid for Radix UI version
5. **Dense prop** - Material UI prop that doesn't exist on div

These will all need systematic removal/conversion to complete the Radix UI migration.

## Files Modified

- ✅ `/src/app/components/ade/studio/PropertyFormFields.tsx`
  - Removed ~20 `size={size}` props
  - Removed all `label`, `helperText`, `error` props from Input
  - Removed `multiline` and `rows` props
  - Fixed JSX structure around Unique Items checkbox
  - Still needs: sx/sx_old removal, Radio conversion, etc.

## Build Status

**Current:** ❌ Failing on sx_old prop at line 979  
**After sx removal:** Unknown - likely more Material UI prop errors  
**Target:** ✅ Successful build with Radix UI components

## Total Errors Fixed So Far

- Size prop errors: ~20
- Label prop errors: ~15
- HelperText errors: ~10
- Multiline errors: ~3
- JSX structure errors: 1

**Total: ~49 individual fixes**

