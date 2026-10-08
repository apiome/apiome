# Version Copy Feature

## Overview
Added functionality to copy classes and class properties from an existing version when creating a new version.

## Changes Made

### 1. Database Helper Functions (`lib/db/helper.ts`)

#### New Function: `copyClassesFromVersion`
- **Purpose**: Copies all classes and their associated properties from a source version to a target version
- **Parameters**:
  - `sourceVersionId`: The UUID of the version to copy from
  - `targetVersionId`: The UUID of the version to copy to
- **Returns**: JSON string with success status and count of copied classes
- **Process**:
  1. Copies all non-deleted classes from source to target version
  2. For each copied class, finds the original class by name
  3. Copies all class properties from the original class to the new class

#### Updated Function: `createVersion`
- **New Parameter**: `sourceVersionId?: string | null` (optional)
- **Enhanced Behavior**:
  - If `sourceVersionId` is provided, automatically calls `copyClassesFromVersion` after creating the new version
  - Returns additional information about copied classes in the response:
    - `copiedClasses`: Number of classes successfully copied
    - `copyWarning`: Any warnings encountered during the copy process
  - If copy fails, the version is still created but a warning is returned

### 2. Versions UI (`src/app/ade/dashboard/versions/page.tsx`)

#### New State Variable
- `sourceVersionId`: Tracks the selected source version to copy from

#### Updated Functions

**`handleCreateClick`**
- Resets `sourceVersionId` to empty string when opening the create dialog

**`handleCreateSubmit`**
- Passes `sourceVersionId` (or null) to the `createVersion` function
- Displays success alerts with information about copied classes:
  - Shows count of copied classes if successful
  - Shows warning message if copy encountered issues

#### Updated UI - Create Version Dialog

**New "Copy From Version" Dropdown**
- Positioned at the top of the create dialog
- Displays all existing versions as options
- Default option: "Create blank version" when versions exist
- Disabled state: "No versions available" when no versions exist
- Shows version ID and description for each option
- When a version is selected, displays an info alert explaining that classes and properties will be copied

**Dropdown Features**:
- Disabled when loading or when no versions exist
- Styled consistently with the application theme
- Shows informative placeholder text based on available versions

## User Experience

### Creating a Blank Version
1. Click "New Version" button
2. Leave "Copy From Version" dropdown at "Create blank version"
3. Fill in version details
4. Click "Create Version"
5. New version is created with no classes

### Copying from an Existing Version
1. Click "New Version" button
2. Select a source version from "Copy From Version" dropdown
3. Info alert appears explaining that classes and properties will be copied
4. Fill in version details
5. Click "Create Version"
6. Success alert shows: "Version created successfully! Copied X class(es) from source version."

### Edge Cases Handled
- **No versions available**: Dropdown is disabled with message "No versions available"
- **Copy fails**: Version is still created, user sees warning about the copy issue
- **Empty source version**: If selected version has no classes, new version is created successfully with 0 classes copied

## Database Operations

### Tables Affected
1. `apiome.versions` - New version record is created
2. `apiome.classes` - Classes are copied with new version_id
3. `apiome.class_properties` - Properties are copied with new class_id references

### Transaction Safety
- Version is created first, ensuring it exists before attempting to copy
- If copy fails, version remains valid (no rollback)
- Each class and its properties are copied sequentially
- Soft-deleted classes are excluded from copying (WHERE deleted_at IS NULL)

## Technical Notes

- Uses SQL INSERT...SELECT for efficient bulk copying of classes
- Maintains referential integrity by matching classes by name between source and target
- Preserves all class attributes (description, schema, enabled status)
- Preserves all class property attributes (property_id, name, description, data)
- Returns detailed feedback to the UI for user notification

## Future Enhancements
- Add ability to selectively copy specific classes instead of all classes
- Add preview of what will be copied before creating the version
- Add progress indicator for large copy operations
- Add undo functionality to revert a version copy

