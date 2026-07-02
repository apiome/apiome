# Regex Tester Feature

## Overview
A reusable regex testing component has been added to both the Class Property Edit Dialog and the Property Dialog forms. This allows users to validate and test regular expression patterns before saving them.

## Features

### RegexTester Component
- **Location**: `/src/app/components/ade/studio/RegexTester.tsx`
- **Collapsible Interface**: The tester starts collapsed to save space and can be expanded with a "Test Regex" button
- **Real-time Testing**: Users can enter test strings and validate them against the regex pattern
- **Visual Feedback**: 
  - Success/info alerts show match results
  - Error alerts display invalid regex syntax errors
  - Color-coded chips show match status (green for match, gray for no match)
- **Pattern Display**: Shows the current regex pattern being tested
- **Keyboard Support**: Press Enter to test the pattern
- **Dark Mode Support**: Automatically adapts colors for both light and dark themes

### Integration Points

#### 1. ClassPropertyEditDialog
- **File**: `/src/app/components/ade/studio/ClassPropertyEditDialog.tsx`
- **Location**: Appears below the "Pattern (Regex)" text field in the String Constraints section
- **Context**: Used when editing properties of a class

#### 2. PropertyDialog
- **File**: `/src/app/components/ade/studio/PropertyDialog.tsx`
- **Location**: Appears below the "Pattern (Regex)" text field
- **Context**: Used when creating new properties

## Usage

1. Enter a regular expression pattern in the "Pattern (Regex)" field
2. The "Test Regex" button automatically appears when a pattern is entered
3. Click "Test Regex" to expand the testing interface
4. Enter a test string in the "Test String" field
5. Click "Test" or press Enter to validate the string against the pattern
6. View the results:
   - Green "Match" chip and success alert if the pattern matches
   - Gray "No Match" chip and info alert if the pattern doesn't match
   - Red error alert if the regex pattern is invalid

## Example Patterns

- Email: `^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$`
- Phone: `^\+?[1-9]\d{1,14}$`
- UUID: `^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$`
- US Zip Code: `^\d{5}(-\d{4})?$`

## Implementation Details

### Component Props
```typescript
interface RegexTesterProps {
  pattern: string;  // The regex pattern to test
}
```

### State Management
- `testString`: The user's input string to test
- `testResult`: Object containing match status and any errors
- `expanded`: Controls the visibility of the testing interface

### Error Handling
- Catches and displays JavaScript regex syntax errors
- Validates that a pattern exists before testing
- User-friendly error messages

## Benefits

1. **Reduced Errors**: Users can validate regex patterns before saving
2. **Better UX**: Immediate feedback on pattern correctness
3. **Learning Tool**: Helps users understand how their patterns work
4. **Time Saving**: No need to save and test in a separate tool
5. **Consistency**: Same testing interface in both forms

