'use client';

import React, { useState, useEffect } from 'react';
import Dialog from '@mui/material/Dialog';
import DialogTitle from '@mui/material/DialogTitle';
import DialogContent from '@mui/material/DialogContent';
import DialogActions from '@mui/material/DialogActions';
import Button from '@mui/material/Button';
import TextField from '@mui/material/TextField';
import Alert from '@mui/material/Alert';
import FormControlLabel from '@mui/material/FormControlLabel';
import Checkbox from '@mui/material/Checkbox';
import Typography from '@mui/material/Typography';
import Box from '@mui/material/Box';
import FormControl from '@mui/material/FormControl';
import InputLabel from '@mui/material/InputLabel';
import Select from '@mui/material/Select';
import MenuItem from '@mui/material/MenuItem';
import FormHelperText from '@mui/material/FormHelperText';
import Radio from '@mui/material/Radio';
import RadioGroup from '@mui/material/RadioGroup';
import Chip from '@mui/material/Chip';

export interface ClassItem {
  id: string;
  name: string;
  description?: string;
}

type CompositionType = 'none' | 'allOf' | 'anyOf' | 'oneOf';

interface ReferenceDialogProps {
  open: boolean;
  onClose: () => void;
  classes: ClassItem[];
  onSubmit: (referenceData: {
    name: string;
    description: string | null;
    isArray: boolean;
    targetClassId: string | null;
    targetClassIds?: string[];
    compositionType?: CompositionType;
    minItems?: number;
    maxItems?: number;
    uniqueItems?: boolean;
  }) => Promise<void>;
}

export const ReferenceDialog: React.FC<ReferenceDialogProps> = ({
  open,
  onClose,
  classes,
  onSubmit,
}) => {
  const [referenceName, setReferenceName] = useState('');
  const [referenceDescription, setReferenceDescription] = useState('');
  const [isArray, setIsArray] = useState(false);
  const [compositionType, setCompositionType] = useState<CompositionType>('none');
  const [targetClassId, setTargetClassId] = useState<string>('');
  const [targetClassIds, setTargetClassIds] = useState<string[]>([]);
  const [minItems, setMinItems] = useState('');
  const [maxItems, setMaxItems] = useState('');
  const [uniqueItems, setUniqueItems] = useState(false);
  const [error, setError] = useState('');
  const [isSubmitting, setIsSubmitting] = useState(false);

  // Reset form when dialog opens
  useEffect(() => {
    if (open) {
      setReferenceName('');
      setReferenceDescription('');
      setIsArray(false);
      setCompositionType('none');
      setTargetClassId('');
      setTargetClassIds([]);
      setMinItems('');
      setMaxItems('');
      setUniqueItems(false);
      setError('');
    }
  }, [open]);

  const handleSubmit = async () => {
    if (!referenceName.trim()) {
      setError('Reference name is required');
      return;
    }

    // Validate reference name contains only A-Za-z0-9_
    if (!/^[A-Za-z0-9_]+$/.test(referenceName)) {
      setError('Reference name can only contain letters, numbers, and underscores');
      return;
    }

    // Validate composition type references
    if (compositionType !== 'none' && targetClassIds.length === 0) {
      setError(`Please select at least one class for ${compositionType}`);
      return;
    }

    if (compositionType === 'none' && targetClassId === '' && targetClassIds.length === 0) {
      // Allow empty reference - will be connected later
    }

    setIsSubmitting(true);
    setError('');

    try {
      await onSubmit({
        name: referenceName,
        description: referenceDescription || null,
        isArray,
        targetClassId: compositionType === 'none' ? (targetClassId || null) : null,
        targetClassIds: compositionType !== 'none' ? targetClassIds : undefined,
        compositionType: compositionType !== 'none' ? compositionType : undefined,
        minItems: minItems ? parseInt(minItems) : undefined,
        maxItems: maxItems ? parseInt(maxItems) : undefined,
        uniqueItems: isArray ? uniqueItems : undefined,
      });

      onClose();
    } catch (err) {
      console.error('Error creating reference:', err);
      setError(err instanceof Error ? err.message : 'An error occurred while creating the reference');
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <Dialog
      open={open}
      onClose={onClose}
      maxWidth="sm"
      fullWidth
    >
      <DialogTitle>Create Reference</DialogTitle>
      <DialogContent>
        {error && (
          <Alert severity="error" sx={{ mb: 2 }}>
            {error}
          </Alert>
        )}

        <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
          Create a reference property that links to another class. You can set the target class now or connect it later using the canvas.
        </Typography>

        <TextField
          autoFocus
          margin="dense"
          label="Reference Name"
          type="text"
          fullWidth
          required
          value={referenceName}
          onChange={(e) => {
            // Only allow A-Za-z0-9_ characters
            const filteredValue = e.target.value.replace(/[^A-Za-z0-9_]/g, '');
            setReferenceName(filteredValue);
          }}
          helperText="Only letters, numbers, and underscores are allowed. Suggest camelCase names."
          sx={{ mb: 2 }}
        />

        <TextField
          margin="dense"
          label="Description"
          type="text"
          fullWidth
          multiline
          rows={2}
          value={referenceDescription}
          onChange={(e) => setReferenceDescription(e.target.value)}
          helperText="Optional description of this reference"
          sx={{ mb: 2 }}
        />

        <FormControlLabel
          control={
            <Checkbox
              checked={isArray}
              onChange={(e) => setIsArray(e.target.checked)}
            />
          }
          label="Array of references"
          sx={{ mb: 2 }}
        />

        {isArray && (
          <Box sx={{ pl: 4, mb: 2 }}>
            <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mb: 1 }}>
              Array constraints:
            </Typography>
            <Box sx={{ display: 'flex', gap: 2, mb: 1 }}>
              <TextField
                margin="dense"
                label="Min Items"
                type="number"
                size="small"
                value={minItems}
                onChange={(e) => setMinItems(e.target.value)}
                helperText="Minimum number of items"
              />
              <TextField
                margin="dense"
                label="Max Items"
                type="number"
                size="small"
                value={maxItems}
                onChange={(e) => setMaxItems(e.target.value)}
                helperText="Maximum number of items"
              />
            </Box>
            <FormControlLabel
              control={
                <Checkbox
                  checked={uniqueItems}
                  onChange={(e) => setUniqueItems(e.target.checked)}
                />
              }
              label="Unique items (all array elements must be distinct)"
            />
          </Box>
        )}

        <Box sx={{ mb: 3, p: 2, bgcolor: 'grey.50', borderRadius: 1 }}>
          <Typography variant="subtitle2" sx={{ mb: 1, fontWeight: 600 }}>
            Reference Type
          </Typography>
          <FormControl component="fieldset">
            <RadioGroup
              value={compositionType}
              onChange={(e) => {
                setCompositionType(e.target.value as CompositionType);
                // Clear selections when switching modes
                if (e.target.value !== 'none') {
                  setTargetClassId('');
                } else {
                  setTargetClassIds([]);
                }
              }}
            >
              <FormControlLabel
                value="none"
                control={<Radio />}
                label={
                  <Box>
                    <Typography variant="body2" fontWeight={500}>Single Reference</Typography>
                    <Typography variant="caption" color="text.secondary">
                      Reference a single class (can be set now or connected later)
                    </Typography>
                  </Box>
                }
              />
              <FormControlLabel
                value="allOf"
                control={<Radio />}
                label={
                  <Box>
                    <Typography variant="body2" fontWeight={500}>allOf (Composition/Inheritance)</Typography>
                    <Typography variant="caption" color="text.secondary">
                      Must satisfy all referenced schemas (solid line, blue)
                    </Typography>
                  </Box>
                }
              />
              <FormControlLabel
                value="anyOf"
                control={<Radio />}
                label={
                  <Box>
                    <Typography variant="body2" fontWeight={500}>anyOf (Union)</Typography>
                    <Typography variant="caption" color="text.secondary">
                      Can satisfy any of the referenced schemas (dashed line, orange)
                    </Typography>
                  </Box>
                }
              />
              <FormControlLabel
                value="oneOf"
                control={<Radio />}
                label={
                  <Box>
                    <Typography variant="body2" fontWeight={500}>oneOf (Exclusive)</Typography>
                    <Typography variant="caption" color="text.secondary">
                      Must satisfy exactly one referenced schema (dotted line, purple)
                    </Typography>
                  </Box>
                }
              />
            </RadioGroup>
          </FormControl>
        </Box>

        {compositionType === 'none' ? (
          <FormControl fullWidth margin="dense" sx={{ mb: 2 }}>
            <InputLabel id="target-class-label">Target Class (Optional)</InputLabel>
            <Select
              labelId="target-class-label"
              label="Target Class (Optional)"
              value={targetClassId}
              onChange={(e) => setTargetClassId(e.target.value)}
            >
              <MenuItem value="">
                <em>No target (set later)</em>
              </MenuItem>
              {classes.map((cls) => (
                <MenuItem key={cls.id} value={cls.id}>
                  {cls.name}
                </MenuItem>
              ))}
            </Select>
            <FormHelperText>Select a class to reference, or leave empty to set later via canvas connections</FormHelperText>
          </FormControl>
        ) : (
          <Box sx={{ mb: 2 }}>
            <Typography variant="subtitle2" sx={{ mb: 1, fontWeight: 600 }}>
              Select Classes for {compositionType}
            </Typography>
            <FormControl fullWidth margin="dense" sx={{ mb: 1 }}>
              <InputLabel id="add-class-label">Add Class</InputLabel>
              <Select
                labelId="add-class-label"
                label="Add Class"
                value=""
                onChange={(e) => {
                  const classId = e.target.value;
                  if (classId && !targetClassIds.includes(classId)) {
                    setTargetClassIds([...targetClassIds, classId]);
                  }
                }}
              >
                <MenuItem value="">
                  <em>Select a class to add...</em>
                </MenuItem>
                {classes
                  .filter(cls => !targetClassIds.includes(cls.id))
                  .map((cls) => (
                    <MenuItem key={cls.id} value={cls.id}>
                      {cls.name}
                    </MenuItem>
                  ))}
              </Select>
              <FormHelperText>
                {compositionType === 'allOf' && 'Add all classes that this property must satisfy'}
                {compositionType === 'anyOf' && 'Add classes that this property can satisfy (one or more)'}
                {compositionType === 'oneOf' && 'Add classes that this property must satisfy (exactly one)'}
              </FormHelperText>
            </FormControl>

            {targetClassIds.length > 0 && (
              <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 1, mt: 1 }}>
                {targetClassIds.map((classId) => {
                  const cls = classes.find(c => c.id === classId);
                  return cls ? (
                    <Chip
                      key={classId}
                      label={cls.name}
                      onDelete={() => {
                        setTargetClassIds(targetClassIds.filter(id => id !== classId));
                      }}
                      color="primary"
                      variant="outlined"
                    />
                  ) : null;
                })}
              </Box>
            )}

            {targetClassIds.length === 0 && (
              <Alert severity="info" sx={{ mt: 1 }}>
                No classes selected. Add at least one class to create a {compositionType} reference.
              </Alert>
            )}
          </Box>
        )}
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose} disabled={isSubmitting}>Cancel</Button>
        <Button onClick={handleSubmit} variant="contained" disabled={isSubmitting}>
          Create Reference
        </Button>
      </DialogActions>
    </Dialog>
  );
};

export default ReferenceDialog;

