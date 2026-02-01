'use client';

import React, { useState } from 'react';
import Box from '@mui/material/Box';
import TextField from '@mui/material/TextField';
import Typography from '@mui/material/Typography';
import IconButton from '@mui/material/IconButton';
import List from '@mui/material/List';
import ListItem from '@mui/material/ListItem';
import ListItemText from '@mui/material/ListItemText';
import AddIcon from '@mui/icons-material/Add';
import DeleteIcon from '@mui/icons-material/Delete';
import Alert from '@mui/material/Alert';

export interface ExtensionsEditorProps {
  /**
   * Current extensions as a record of key-value pairs
   */
  value: Record<string, any>;

  /**
   * Called when extensions change
   */
  onChange: (extensions: Record<string, any>) => void;

  /**
   * Whether the editor is disabled
   */
  disabled?: boolean;

  /**
   * Size variant
   */
  size?: 'small' | 'medium';
}

/**
 * ExtensionsEditor - A component for managing x- prefixed extension properties
 * per OpenAPI 3.1 specification
 */
export const ExtensionsEditor: React.FC<ExtensionsEditorProps> = ({
  value = {},
  onChange,
  disabled = false,
  size = 'medium',
}) => {
  const [keyInput, setKeyInput] = useState('');
  const [valueInput, setValueInput] = useState('');
  const [error, setError] = useState('');

  const handleAdd = () => {
    // Validate key
    if (!keyInput.trim()) {
      setError('Key cannot be empty');
      return;
    }

    const trimmedKey = keyInput.trim();

    // Validate x- prefix
    if (!trimmedKey.startsWith('x-')) {
      setError('Extension keys must start with "x-"');
      return;
    }

    // Validate key format (alphanumeric, hyphens, underscores)
    if (!/^x-[a-zA-Z0-9_-]+$/.test(trimmedKey)) {
      setError('Extension keys can only contain letters, numbers, hyphens, and underscores after "x-"');
      return;
    }

    // Check for duplicate
    if (trimmedKey in value) {
      setError('This extension key already exists');
      return;
    }

    // Validate and parse value as JSON
    let parsedValue: any;
    const trimmedValue = valueInput.trim();

    if (!trimmedValue) {
      setError('Value cannot be empty');
      return;
    }

    try {
      // Try to parse as JSON
      parsedValue = JSON.parse(trimmedValue);
    } catch (e) {
      // If not valid JSON, treat as string
      parsedValue = trimmedValue;
    }

    // Add the extension
    const newExtensions = { ...value, [trimmedKey]: parsedValue };
    onChange(newExtensions);

    // Clear inputs
    setKeyInput('');
    setValueInput('');
    setError('');
  };

  const handleRemove = (key: string) => {
    const newExtensions = { ...value };
    delete newExtensions[key];
    onChange(newExtensions);
  };

  const handleKeyPress = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleAdd();
    }
  };

  const extensionEntries = Object.entries(value).sort(([a], [b]) => a.localeCompare(b));

  return (
    <Box>
      <Typography variant="body2" sx={{ mb: 1, fontWeight: 500 }}>
        Extensions
      </Typography>
      <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mb: 2 }}>
        Add custom x- prefixed properties per OpenAPI 3.1 specification. Values can be any valid JSON.
      </Typography>

      {error && (
        <Alert severity="error" sx={{ mb: 2 }} onClose={() => setError('')}>
          {error}
        </Alert>
      )}

      <Box sx={{ mb: 2 }}>
        <Box sx={{ display: 'grid', gridTemplateColumns: '1fr 2fr auto', gap: 1, mb: 1 }}>
          <TextField
            label="Key"
            size={size}
            fullWidth
            value={keyInput}
            onChange={(e) => {
              setKeyInput(e.target.value);
              setError('');
            }}
            onKeyDown={handleKeyPress}
            placeholder="x-custom-property"
            disabled={disabled}
            helperText="Must start with x-"
          />
          <TextField
            label="Value (JSON)"
            size={size}
            fullWidth
            value={valueInput}
            onChange={(e) => {
              setValueInput(e.target.value);
              setError('');
            }}
            onKeyDown={handleKeyPress}
            placeholder='true, 42, "text", or {"key": "value"}'
            disabled={disabled}
            helperText="Enter valid JSON or plain text"
          />
          <IconButton
            onClick={handleAdd}
            disabled={!keyInput.trim() || !valueInput.trim() || disabled}
            sx={{
              height: size === 'small' ? 40 : 56,
              width: size === 'small' ? 40 : 56,
              bgcolor: 'primary.main',
              color: 'primary.contrastText',
              '&:hover': { bgcolor: 'primary.dark' },
              '&.Mui-disabled': { bgcolor: 'action.disabledBackground', color: 'action.disabled' },
            }}
          >
            <AddIcon />
          </IconButton>
        </Box>
      </Box>

      {extensionEntries.length > 0 && (
        <List
          dense
          sx={{
            bgcolor: 'action.hover',
            borderRadius: 1,
            maxHeight: 300,
            overflow: 'auto',
            border: 1,
            borderColor: 'divider',
          }}
        >
          {extensionEntries.map(([key, val]) => (
            <ListItem
              key={key}
              sx={{
                borderBottom: 1,
                borderColor: 'divider',
                display: 'flex',
                alignItems: 'flex-start',
                gap: 1,
                '&:last-child': {
                  borderBottom: 0,
                },
              }}
            >
              <ListItemText
                primary={
                  <Box>
                    <Typography
                      component="span"
                      sx={{
                        fontFamily: 'monospace',
                        fontSize: '0.875rem',
                        fontWeight: 600,
                        color: 'primary.main',
                      }}
                    >
                      {key}
                    </Typography>
                  </Box>
                }
                secondary={
                  <Typography
                    component="span"
                    sx={{
                      fontFamily: 'monospace',
                      fontSize: '0.813rem',
                      color: 'text.secondary',
                      display: 'block',
                      mt: 0.5,
                      wordBreak: 'break-word',
                    }}
                  >
                    {JSON.stringify(val)}
                  </Typography>
                }
                sx={{ flex: 1, my: 0.5 }}
              />
              <IconButton
                edge="end"
                onClick={() => handleRemove(key)}
                size="small"
                disabled={disabled}
                sx={{
                  flex: 0,
                  mt: 0.5,
                }}
              >
                <DeleteIcon fontSize="small" />
              </IconButton>
            </ListItem>
          ))}
        </List>
      )}

      {extensionEntries.length === 0 && (
        <Box
          sx={{
            p: 3,
            bgcolor: 'action.hover',
            borderRadius: 1,
            border: 1,
            borderColor: 'divider',
            textAlign: 'center',
          }}
        >
          <Typography variant="body2" color="text.secondary">
            No extensions defined. Extensions allow you to add custom metadata that can be used by tools and documentation generators.
          </Typography>
        </Box>
      )}
    </Box>
  );
};

