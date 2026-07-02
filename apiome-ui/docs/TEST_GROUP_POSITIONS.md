# Test Scenario: Group Class Position Persistence

## Overview
This test verifies that classes dragged inside groups save their positions correctly and restore properly when the canvas is reloaded.

## Prerequisites
- Access to Apiome UI application
- A project with at least one version
- At least 2-3 classes available to work with

## Test Steps

### Test 1: Add Class to Group
1. Open the canvas editor for a version
2. Create a new group (click "Create Group" or drag from sidebar)
3. Position the group somewhere on the canvas
4. Drag a class node into the group
5. Verify the class is visually inside the group
6. **Expected**: Class is added to the group immediately

### Test 2: Move Class Within Group
1. With a class already in a group
2. Drag the class to a different position within the same group
3. Note the new position
4. **Expected**: Position change is saved to database

### Test 3: Save and Reload
1. After positioning classes in a group
2. Click the "Save Layout" button in the toolbar
3. Wait for "Saved" confirmation
4. Refresh the browser page (F5 or Cmd+R)
5. Wait for canvas to fully load
6. **Expected**: 
   - Group appears at correct position
   - All classes are inside the group
   - Classes are at the positions they were saved at

### Test 4: Move Between Groups
1. Create two groups on the canvas
2. Drag a class from one group to another
3. Confirm the move in the dialog
4. Save the layout
5. Reload the canvas
6. **Expected**: Class is in the new group at the correct position

### Test 5: Multiple Classes in Group
1. Add 3-4 classes to a single group
2. Arrange them in a specific pattern (e.g., grid layout)
3. Save the layout
4. Reload the canvas
5. **Expected**: All classes maintain their relative positions within the group

### Test 6: Group Movement with Classes
1. Create a group with 2-3 classes inside
2. Move the entire group to a new position
3. Save the layout
4. Reload the canvas
5. **Expected**: 
   - Group is at new position
   - Classes maintain their relative positions within the group

## Database Verification

To verify the fix at the database level:

```sql
-- Check that classes are associated with groups
SELECT g.name as group_name, c.name as class_name, 
       gc.position_x, gc.position_y, gc.sort_order
FROM apiome.groups g
JOIN apiome.group_classes gc ON g.id = gc.group_id
JOIN apiome.classes c ON gc.class_id = c.id
WHERE g.version_id = '<your-version-id>'
ORDER BY g.name, gc.sort_order;
```

**Expected Result**: 
- Rows should exist for each class in a group
- `position_x` and `position_y` should NOT be NULL
- Values should match the visual positions on the canvas

## Known Issues (Before Fix)
- Classes appeared in groups initially but positions were NULL
- After reload, classes would be missing from groups
- `syncGroupsForVersion` only saved sort_order, not positions
- `handleNodeDragStop` didn't update database for within-group moves

## Known Issues (After Fix)
None expected. If issues occur:
1. Check browser console for errors
2. Verify database has position data (see SQL above)
3. Check network tab for failed API calls

## Success Criteria
✅ Classes drag into groups successfully  
✅ Moving classes within groups updates database  
✅ Saved positions persist across page reloads  
✅ Multiple classes in a group maintain layout  
✅ Database shows non-NULL position_x and position_y values  

## Date
January 3, 2026

