'use client';

import React, { useState } from 'react';
import Box from '@mui/material/Box';
import Typography from '@mui/material/Typography';
import TextField from '@mui/material/TextField';
import Button from '@mui/material/Button';
import IconButton from '@mui/material/IconButton';
import Autocomplete from '@mui/material/Autocomplete';
import Chip from '@mui/material/Chip';
import Collapse from '@mui/material/Collapse';
import Tooltip from '@mui/material/Tooltip';
import { useColorScheme } from '@mui/material/styles';
import AddIcon from '@mui/icons-material/Add';
import DeleteIcon from '@mui/icons-material/Delete';
import ExpandMoreIcon from '@mui/icons-material/ExpandMore';
import ExpandLessIcon from '@mui/icons-material/ExpandLess';
import HelpOutlineIcon from '@mui/icons-material/HelpOutline';
import { GitBranch, ArrowRight, Check, X } from 'lucide-react';

export interface ConditionalRule {
  id: string;
  // IF condition
  ifCondition: {
    property: string;
    operator: 'equals' | 'const' | 'enum' | 'type' | 'required' | 'pattern' | 'minimum' | 'maximum';
    value: string;
  };
  // THEN schema (what should be required/validated when IF is true)
  thenSchema: {
    requiredProperties: string[];
    propertyConstraints: Array<{
      property: string;
      constraint: 'minLength' | 'maxLength' | 'minimum' | 'maximum' | 'pattern' | 'const' | 'enum' | 'type';
      value: string;
    }>;
  };
  // ELSE schema (optional - what should be required/validated when IF is false)
  elseSchema?: {
    requiredProperties: string[];
    propertyConstraints: Array<{
      property: string;
      constraint: 'minLength' | 'maxLength' | 'minimum' | 'maximum' | 'pattern' | 'const' | 'enum' | 'type';
      value: string;
    }>;
  };
}

interface ConditionalSchemaBuilderProps {
  rules: ConditionalRule[];
  onChange: (rules: ConditionalRule[]) => void;
  availableProperties: string[];
  disabled?: boolean;
}

const generateId = () => Math.random().toString(36).substring(2, 9);

const OPERATORS = [
  { value: 'equals', label: 'equals (const)', description: 'Property must equal exact value' },
  { value: 'enum', label: 'is one of (enum)', description: 'Property value is in a set of values' },
  { value: 'type', label: 'has type', description: 'Property has specific type' },
  { value: 'required', label: 'is present', description: 'Property exists (is not undefined)' },
  { value: 'pattern', label: 'matches pattern', description: 'Property matches regex pattern' },
  { value: 'minimum', label: 'is at least', description: 'Number is >= value' },
  { value: 'maximum', label: 'is at most', description: 'Number is <= value' },
];

const CONSTRAINTS = [
  { value: 'minLength', label: 'Min Length', forTypes: ['string'] },
  { value: 'maxLength', label: 'Max Length', forTypes: ['string'] },
  { value: 'minimum', label: 'Minimum', forTypes: ['number', 'integer'] },
  { value: 'maximum', label: 'Maximum', forTypes: ['number', 'integer'] },
  { value: 'pattern', label: 'Pattern', forTypes: ['string'] },
  { value: 'const', label: 'Const', forTypes: ['string', 'number', 'integer', 'boolean'] },
  { value: 'enum', label: 'Enum', forTypes: ['string', 'number', 'integer'] },
  { value: 'type', label: 'Type', forTypes: ['any'] },
];

export const ConditionalSchemaBuilder: React.FC<ConditionalSchemaBuilderProps> = ({
  rules,
  onChange,
  availableProperties,
  disabled = false,
}) => {
  const { mode: colorMode, systemMode } = useColorScheme();
  const isDark = colorMode === 'dark' || (colorMode === 'system' && systemMode === 'dark');

  const [expandedRules, setExpandedRules] = useState<Set<string>>(new Set());

  const toggleExpanded = (ruleId: string) => {
    const next = new Set(expandedRules);
    if (next.has(ruleId)) {
      next.delete(ruleId);
    } else {
      next.add(ruleId);
    }
    setExpandedRules(next);
  };

  const addRule = () => {
    const newRule: ConditionalRule = {
      id: generateId(),
      ifCondition: {
        property: '',
        operator: 'equals',
        value: '',
      },
      thenSchema: {
        requiredProperties: [],
        propertyConstraints: [],
      },
    };
    const newRules = [...rules, newRule];
    onChange(newRules);
    setExpandedRules(new Set([...expandedRules, newRule.id]));
  };

  const updateRule = (ruleId: string, updates: Partial<ConditionalRule>) => {
    onChange(rules.map(r => r.id === ruleId ? { ...r, ...updates } : r));
  };

  const deleteRule = (ruleId: string) => {
    onChange(rules.filter(r => r.id !== ruleId));
    const next = new Set(expandedRules);
    next.delete(ruleId);
    setExpandedRules(next);
  };

  const addElseSchema = (ruleId: string) => {
    updateRule(ruleId, {
      elseSchema: {
        requiredProperties: [],
        propertyConstraints: [],
      }
    });
  };

  const removeElseSchema = (ruleId: string) => {
    const rule = rules.find(r => r.id === ruleId);
    if (rule) {
      const { elseSchema, ...rest } = rule;
      onChange(rules.map(r => r.id === ruleId ? rest as ConditionalRule : r));
    }
  };

  const addThenConstraint = (ruleId: string) => {
    const rule = rules.find(r => r.id === ruleId);
    if (rule) {
      updateRule(ruleId, {
        thenSchema: {
          ...rule.thenSchema,
          propertyConstraints: [
            ...rule.thenSchema.propertyConstraints,
            { property: '', constraint: 'minLength', value: '' }
          ]
        }
      });
    }
  };

  const addElseConstraint = (ruleId: string) => {
    const rule = rules.find(r => r.id === ruleId);
    if (rule && rule.elseSchema) {
      updateRule(ruleId, {
        elseSchema: {
          ...rule.elseSchema,
          propertyConstraints: [
            ...rule.elseSchema.propertyConstraints,
            { property: '', constraint: 'minLength', value: '' }
          ]
        }
      });
    }
  };

  const removeThenConstraint = (ruleId: string, index: number) => {
    const rule = rules.find(r => r.id === ruleId);
    if (rule) {
      updateRule(ruleId, {
        thenSchema: {
          ...rule.thenSchema,
          propertyConstraints: rule.thenSchema.propertyConstraints.filter((_, i) => i !== index)
        }
      });
    }
  };

  const removeElseConstraint = (ruleId: string, index: number) => {
    const rule = rules.find(r => r.id === ruleId);
    if (rule && rule.elseSchema) {
      updateRule(ruleId, {
        elseSchema: {
          ...rule.elseSchema,
          propertyConstraints: rule.elseSchema.propertyConstraints.filter((_, i) => i !== index)
        }
      });
    }
  };

  const renderConditionBuilder = (rule: ConditionalRule) => (
    <Box sx={{
      p: 2,
      bgcolor: isDark ? '#312e81' : '#eef2ff',
      borderRadius: 2,
      border: `1px solid ${isDark ? '#4338ca' : '#c7d2fe'}`,
      mb: 2
    }}>
      <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 2 }}>
        <Box sx={{
          px: 1.5,
          py: 0.5,
          bgcolor: isDark ? '#4338ca' : '#6366f1',
          color: 'white',
          borderRadius: 1,
          fontSize: '0.75rem',
          fontWeight: 600
        }}>
          IF
        </Box>
        <Typography variant="caption" sx={{ color: isDark ? '#c7d2fe' : '#4338ca' }}>
          Condition to check
        </Typography>
      </Box>

      <Box sx={{ display: 'grid', gridTemplateColumns: '1fr auto 1fr', gap: 2, alignItems: 'start' }}>
        {/* Property selector */}
        <Autocomplete
          size="small"
          options={availableProperties}
          value={rule.ifCondition.property || null}
          onChange={(_, newValue) => {
            updateRule(rule.id, {
              ifCondition: { ...rule.ifCondition, property: newValue || '' }
            });
          }}
          disabled={disabled}
          freeSolo
          renderInput={(params) => (
            <TextField
              {...params}
              label="Property"
              placeholder="Select or type property name"
              size="small"
            />
          )}
        />

        {/* Operator selector */}
        <TextField
          select
          size="small"
          label="Operator"
          value={rule.ifCondition.operator}
          onChange={(e) => {
            updateRule(rule.id, {
              ifCondition: { ...rule.ifCondition, operator: e.target.value as any }
            });
          }}
          disabled={disabled}
          SelectProps={{ native: true }}
          sx={{ minWidth: 140 }}
        >
          {OPERATORS.map(op => (
            <option key={op.value} value={op.value}>{op.label}</option>
          ))}
        </TextField>

        {/* Value input (hidden for 'required' operator) */}
        {rule.ifCondition.operator !== 'required' && (
          <TextField
            size="small"
            label={rule.ifCondition.operator === 'enum' ? 'Values (comma-separated)' : 'Value'}
            value={rule.ifCondition.value}
            onChange={(e) => {
              updateRule(rule.id, {
                ifCondition: { ...rule.ifCondition, value: e.target.value }
              });
            }}
            disabled={disabled}
            placeholder={
              rule.ifCondition.operator === 'enum' ? 'value1, value2, value3' :
              rule.ifCondition.operator === 'type' ? 'string, number, boolean...' :
              rule.ifCondition.operator === 'pattern' ? '^[A-Z]+$' :
              'value'
            }
            helperText={OPERATORS.find(o => o.value === rule.ifCondition.operator)?.description}
          />
        )}
        {rule.ifCondition.operator === 'required' && (
          <Box sx={{ display: 'flex', alignItems: 'center', color: isDark ? '#94a3b8' : '#64748b' }}>
            <Typography variant="caption">(property exists)</Typography>
          </Box>
        )}
      </Box>
    </Box>
  );

  const renderSchemaBuilder = (
    rule: ConditionalRule,
    schemaType: 'then' | 'else',
    schema: ConditionalRule['thenSchema']
  ) => (
    <Box sx={{
      p: 2,
      bgcolor: schemaType === 'then'
        ? (isDark ? '#14532d' : '#f0fdf4')
        : (isDark ? '#7f1d1d' : '#fef2f2'),
      borderRadius: 2,
      border: `1px solid ${schemaType === 'then' 
        ? (isDark ? '#16a34a' : '#bbf7d0')
        : (isDark ? '#dc2626' : '#fecaca')}`,
      mb: schemaType === 'then' ? 2 : 0
    }}>
      <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', mb: 2 }}>
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
          <Box sx={{
            px: 1.5,
            py: 0.5,
            bgcolor: schemaType === 'then'
              ? (isDark ? '#16a34a' : '#22c55e')
              : (isDark ? '#dc2626' : '#ef4444'),
            color: 'white',
            borderRadius: 1,
            fontSize: '0.75rem',
            fontWeight: 600
          }}>
            {schemaType.toUpperCase()}
          </Box>
          <Typography variant="caption" sx={{
            color: schemaType === 'then'
              ? (isDark ? '#86efac' : '#16a34a')
              : (isDark ? '#fca5a5' : '#dc2626')
          }}>
            {schemaType === 'then' ? 'Apply when condition is TRUE' : 'Apply when condition is FALSE'}
          </Typography>
        </Box>
        {schemaType === 'else' && (
          <IconButton
            size="small"
            onClick={() => removeElseSchema(rule.id)}
            disabled={disabled}
            sx={{ color: isDark ? '#fca5a5' : '#dc2626' }}
          >
            <DeleteIcon fontSize="small" />
          </IconButton>
        )}
      </Box>

      {/* Required properties */}
      <Box sx={{ mb: 2 }}>
        <Typography variant="caption" sx={{
          fontWeight: 600,
          color: isDark ? '#e2e8f0' : '#334155',
          display: 'block',
          mb: 1
        }}>
          Require these properties:
        </Typography>
        <Autocomplete
          multiple
          size="small"
          options={availableProperties}
          value={schema.requiredProperties}
          onChange={(_, newValue) => {
            if (schemaType === 'then') {
              updateRule(rule.id, {
                thenSchema: { ...schema, requiredProperties: newValue }
              });
            } else {
              updateRule(rule.id, {
                elseSchema: { ...schema, requiredProperties: newValue }
              });
            }
          }}
          disabled={disabled}
          freeSolo
          renderTags={(value, getTagProps) =>
            value.map((option, index) => (
              <Chip
                label={option}
                size="small"
                color={schemaType === 'then' ? 'success' : 'error'}
                {...getTagProps({ index })}
              />
            ))
          }
          renderInput={(params) => (
            <TextField
              {...params}
              placeholder="Select properties to require..."
              size="small"
            />
          )}
        />
      </Box>

      {/* Property constraints */}
      <Box>
        <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', mb: 1 }}>
          <Typography variant="caption" sx={{
            fontWeight: 600,
            color: isDark ? '#e2e8f0' : '#334155'
          }}>
            Additional constraints:
          </Typography>
          <Button
            size="small"
            startIcon={<AddIcon />}
            onClick={() => schemaType === 'then' ? addThenConstraint(rule.id) : addElseConstraint(rule.id)}
            disabled={disabled}
            sx={{ fontSize: '0.7rem' }}
          >
            Add Constraint
          </Button>
        </Box>

        {schema.propertyConstraints.length === 0 ? (
          <Typography variant="caption" sx={{
            color: isDark ? '#94a3b8' : '#64748b',
            fontStyle: 'italic',
            display: 'block',
            textAlign: 'center',
            py: 1
          }}>
            No additional constraints
          </Typography>
        ) : (
          <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1 }}>
            {schema.propertyConstraints.map((constraint, idx) => (
              <Box
                key={idx}
                sx={{
                  display: 'grid',
                  gridTemplateColumns: '1fr auto 1fr auto',
                  gap: 1,
                  alignItems: 'center',
                  p: 1,
                  bgcolor: isDark ? 'rgba(0,0,0,0.2)' : 'rgba(255,255,255,0.5)',
                  borderRadius: 1
                }}
              >
                <Autocomplete
                  size="small"
                  options={availableProperties}
                  value={constraint.property || null}
                  onChange={(_, newValue) => {
                    const newConstraints = [...schema.propertyConstraints];
                    newConstraints[idx] = { ...constraint, property: newValue || '' };
                    if (schemaType === 'then') {
                      updateRule(rule.id, {
                        thenSchema: { ...schema, propertyConstraints: newConstraints }
                      });
                    } else {
                      updateRule(rule.id, {
                        elseSchema: { ...schema, propertyConstraints: newConstraints }
                      });
                    }
                  }}
                  disabled={disabled}
                  freeSolo
                  renderInput={(params) => (
                    <TextField {...params} placeholder="Property" size="small" />
                  )}
                />
                <TextField
                  select
                  size="small"
                  value={constraint.constraint}
                  onChange={(e) => {
                    const newConstraints = [...schema.propertyConstraints];
                    newConstraints[idx] = { ...constraint, constraint: e.target.value as any };
                    if (schemaType === 'then') {
                      updateRule(rule.id, {
                        thenSchema: { ...schema, propertyConstraints: newConstraints }
                      });
                    } else {
                      updateRule(rule.id, {
                        elseSchema: { ...schema, propertyConstraints: newConstraints }
                      });
                    }
                  }}
                  disabled={disabled}
                  SelectProps={{ native: true }}
                  sx={{ minWidth: 100 }}
                >
                  {CONSTRAINTS.map(c => (
                    <option key={c.value} value={c.value}>{c.label}</option>
                  ))}
                </TextField>
                <TextField
                  size="small"
                  value={constraint.value}
                  onChange={(e) => {
                    const newConstraints = [...schema.propertyConstraints];
                    newConstraints[idx] = { ...constraint, value: e.target.value };
                    if (schemaType === 'then') {
                      updateRule(rule.id, {
                        thenSchema: { ...schema, propertyConstraints: newConstraints }
                      });
                    } else {
                      updateRule(rule.id, {
                        elseSchema: { ...schema, propertyConstraints: newConstraints }
                      });
                    }
                  }}
                  disabled={disabled}
                  placeholder="Value"
                />
                <IconButton
                  size="small"
                  onClick={() => schemaType === 'then'
                    ? removeThenConstraint(rule.id, idx)
                    : removeElseConstraint(rule.id, idx)
                  }
                  disabled={disabled}
                >
                  <DeleteIcon fontSize="small" />
                </IconButton>
              </Box>
            ))}
          </Box>
        )}
      </Box>
    </Box>
  );

  const renderVisualFlow = (rule: ConditionalRule) => {
    const hasCondition = rule.ifCondition.property && (rule.ifCondition.operator === 'required' || rule.ifCondition.value);
    const hasThen = rule.thenSchema.requiredProperties.length > 0 || rule.thenSchema.propertyConstraints.length > 0;
    const hasElse = rule.elseSchema && (rule.elseSchema.requiredProperties.length > 0 || rule.elseSchema.propertyConstraints.length > 0);

    return (
      <Box sx={{
        display: 'flex',
        alignItems: 'center',
        gap: 1,
        py: 1,
        px: 2,
        bgcolor: isDark ? '#0f172a' : '#f8fafc',
        borderRadius: 1,
        mb: 2,
        flexWrap: 'wrap'
      }}>
        <Chip
          size="small"
          label={hasCondition ? `${rule.ifCondition.property} ${rule.ifCondition.operator} ${rule.ifCondition.value || ''}` : 'No condition'}
          color={hasCondition ? 'primary' : 'default'}
          icon={<GitBranch size={14} />}
        />
        <ArrowRight size={16} style={{ color: isDark ? '#94a3b8' : '#64748b' }} />
        <Chip
          size="small"
          label={hasThen ? `Then: ${rule.thenSchema.requiredProperties.length} required` : 'No then'}
          color={hasThen ? 'success' : 'default'}
          icon={<Check size={14} />}
        />
        {rule.elseSchema && (
          <>
            <Typography sx={{ color: isDark ? '#94a3b8' : '#64748b', fontSize: '0.75rem' }}>/</Typography>
            <Chip
              size="small"
              label={hasElse ? `Else: ${rule.elseSchema.requiredProperties.length} required` : 'No else'}
              color={hasElse ? 'error' : 'default'}
              icon={<X size={14} />}
            />
          </>
        )}
      </Box>
    );
  };

  return (
    <Box>
      {/* Header */}
      <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', mb: 2 }}>
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
          <GitBranch size={18} style={{ color: '#6366f1' }} />
          <Typography variant="subtitle2" sx={{ fontWeight: 600, color: isDark ? '#e2e8f0' : 'inherit' }}>
            Conditional Schema Rules
          </Typography>
          <Tooltip title="Define if/then/else conditions for complex validation. When the 'if' condition matches, the 'then' schema is applied. Optionally, an 'else' schema applies when the condition doesn't match.">
            <HelpOutlineIcon sx={{ fontSize: 16, color: isDark ? '#94a3b8' : '#64748b', cursor: 'help' }} />
          </Tooltip>
        </Box>
        <Button
          size="small"
          variant="outlined"
          startIcon={<AddIcon />}
          onClick={addRule}
          disabled={disabled}
        >
          Add Rule
        </Button>
      </Box>

      {/* Rules list */}
      {rules.length === 0 ? (
        <Box sx={{
          p: 3,
          textAlign: 'center',
          bgcolor: isDark ? '#1e293b' : '#f8fafc',
          borderRadius: 2,
          border: `2px dashed ${isDark ? '#334155' : '#e2e8f0'}`
        }}>
          <GitBranch size={24} style={{ color: isDark ? '#64748b' : '#94a3b8', marginBottom: 8 }} />
          <Typography variant="body2" sx={{ color: isDark ? '#94a3b8' : '#64748b' }}>
            No conditional rules defined
          </Typography>
          <Typography variant="caption" sx={{ color: isDark ? '#64748b' : '#94a3b8', display: 'block', mt: 0.5 }}>
            Add rules to create dynamic validation based on property values
          </Typography>
        </Box>
      ) : (
        <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
          {rules.map((rule, index) => (
            <Box
              key={rule.id}
              sx={{
                border: `1px solid ${isDark ? '#334155' : '#e2e8f0'}`,
                borderRadius: 2,
                overflow: 'hidden',
                bgcolor: isDark ? '#1e293b' : 'white'
              }}
            >
              {/* Rule header */}
              <Box
                sx={{
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'space-between',
                  p: 1.5,
                  bgcolor: isDark ? '#0f172a' : '#f8fafc',
                  borderBottom: expandedRules.has(rule.id) ? `1px solid ${isDark ? '#334155' : '#e2e8f0'}` : 'none',
                  cursor: 'pointer'
                }}
                onClick={() => toggleExpanded(rule.id)}
              >
                <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                  <Typography variant="caption" sx={{
                    fontWeight: 600,
                    color: isDark ? '#94a3b8' : '#64748b',
                    minWidth: 60
                  }}>
                    Rule {index + 1}
                  </Typography>
                  {!expandedRules.has(rule.id) && renderVisualFlow(rule)}
                </Box>
                <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5 }}>
                  <IconButton
                    size="small"
                    onClick={(e) => {
                      e.stopPropagation();
                      deleteRule(rule.id);
                    }}
                    disabled={disabled}
                    sx={{ color: isDark ? '#f87171' : '#ef4444' }}
                  >
                    <DeleteIcon fontSize="small" />
                  </IconButton>
                  {expandedRules.has(rule.id) ? <ExpandLessIcon /> : <ExpandMoreIcon />}
                </Box>
              </Box>

              {/* Rule content */}
              <Collapse in={expandedRules.has(rule.id)}>
                <Box sx={{ p: 2 }}>
                  {/* Visual flow summary */}
                  {renderVisualFlow(rule)}

                  {/* IF condition */}
                  {renderConditionBuilder(rule)}

                  {/* THEN schema */}
                  {renderSchemaBuilder(rule, 'then', rule.thenSchema)}

                  {/* ELSE schema (optional) */}
                  {rule.elseSchema ? (
                    renderSchemaBuilder(rule, 'else', rule.elseSchema)
                  ) : (
                    <Button
                      size="small"
                      variant="text"
                      onClick={() => addElseSchema(rule.id)}
                      disabled={disabled}
                      sx={{
                        color: isDark ? '#f87171' : '#dc2626',
                        '&:hover': { bgcolor: isDark ? 'rgba(248, 113, 113, 0.1)' : 'rgba(220, 38, 38, 0.1)' }
                      }}
                    >
                      + Add ELSE condition
                    </Button>
                  )}
                </Box>
              </Collapse>
            </Box>
          ))}
        </Box>
      )}
    </Box>
  );
};

// Helper function to convert ConditionalRule[] to JSON Schema if/then/else
export const conditionalRulesToJsonSchema = (rules: ConditionalRule[]): any[] => {
  return rules.map(rule => {
    const result: any = {};

    // Build IF schema
    const ifSchema: any = { properties: {} };
    if (rule.ifCondition.property) {
      const propSchema: any = {};

      switch (rule.ifCondition.operator) {
        case 'equals':
        case 'const':
          propSchema.const = rule.ifCondition.value;
          break;
        case 'enum':
          propSchema.enum = rule.ifCondition.value.split(',').map(v => v.trim());
          break;
        case 'type':
          propSchema.type = rule.ifCondition.value;
          break;
        case 'pattern':
          propSchema.pattern = rule.ifCondition.value;
          break;
        case 'minimum':
          propSchema.minimum = parseFloat(rule.ifCondition.value);
          break;
        case 'maximum':
          propSchema.maximum = parseFloat(rule.ifCondition.value);
          break;
        case 'required':
          // For 'required', we just need the property to exist
          break;
      }

      ifSchema.properties[rule.ifCondition.property] = propSchema;

      if (rule.ifCondition.operator === 'required') {
        ifSchema.required = [rule.ifCondition.property];
      }
    }
    result.if = ifSchema;

    // Build THEN schema
    const thenSchema: any = {};
    if (rule.thenSchema.requiredProperties.length > 0) {
      thenSchema.required = rule.thenSchema.requiredProperties;
    }
    if (rule.thenSchema.propertyConstraints.length > 0) {
      thenSchema.properties = {};
      rule.thenSchema.propertyConstraints.forEach(constraint => {
        if (!thenSchema.properties[constraint.property]) {
          thenSchema.properties[constraint.property] = {};
        }
        switch (constraint.constraint) {
          case 'minLength':
            thenSchema.properties[constraint.property].minLength = parseInt(constraint.value);
            break;
          case 'maxLength':
            thenSchema.properties[constraint.property].maxLength = parseInt(constraint.value);
            break;
          case 'minimum':
            thenSchema.properties[constraint.property].minimum = parseFloat(constraint.value);
            break;
          case 'maximum':
            thenSchema.properties[constraint.property].maximum = parseFloat(constraint.value);
            break;
          case 'pattern':
            thenSchema.properties[constraint.property].pattern = constraint.value;
            break;
          case 'const':
            thenSchema.properties[constraint.property].const = constraint.value;
            break;
          case 'enum':
            thenSchema.properties[constraint.property].enum = constraint.value.split(',').map(v => v.trim());
            break;
          case 'type':
            thenSchema.properties[constraint.property].type = constraint.value;
            break;
        }
      });
    }
    result.then = thenSchema;

    // Build ELSE schema (optional)
    if (rule.elseSchema) {
      const elseSchema: any = {};
      if (rule.elseSchema.requiredProperties.length > 0) {
        elseSchema.required = rule.elseSchema.requiredProperties;
      }
      if (rule.elseSchema.propertyConstraints.length > 0) {
        elseSchema.properties = {};
        rule.elseSchema.propertyConstraints.forEach(constraint => {
          if (!elseSchema.properties[constraint.property]) {
            elseSchema.properties[constraint.property] = {};
          }
          switch (constraint.constraint) {
            case 'minLength':
              elseSchema.properties[constraint.property].minLength = parseInt(constraint.value);
              break;
            case 'maxLength':
              elseSchema.properties[constraint.property].maxLength = parseInt(constraint.value);
              break;
            case 'minimum':
              elseSchema.properties[constraint.property].minimum = parseFloat(constraint.value);
              break;
            case 'maximum':
              elseSchema.properties[constraint.property].maximum = parseFloat(constraint.value);
              break;
            case 'pattern':
              elseSchema.properties[constraint.property].pattern = constraint.value;
              break;
            case 'const':
              elseSchema.properties[constraint.property].const = constraint.value;
              break;
            case 'enum':
              elseSchema.properties[constraint.property].enum = constraint.value.split(',').map(v => v.trim());
              break;
            case 'type':
              elseSchema.properties[constraint.property].type = constraint.value;
              break;
          }
        });
      }
      result.else = elseSchema;
    }

    return result;
  }).filter(rule => rule.if && Object.keys(rule.if.properties || {}).length > 0);
};

// Helper function to parse JSON Schema if/then/else back to ConditionalRule[]
// Handles nested if/then/else by flattening them into separate rules
export const jsonSchemaToConditionalRules = (allOfArray: any[]): ConditionalRule[] => {
  if (!allOfArray || !Array.isArray(allOfArray)) return [];

  const rules: ConditionalRule[] = [];

  const parseIfThenElse = (item: any) => {
    if (!item.if) return;

    const rule: ConditionalRule = {
      id: generateId(),
      ifCondition: {
        property: '',
        operator: 'equals',
        value: '',
      },
      thenSchema: {
        requiredProperties: [],
        propertyConstraints: [],
      },
    };

    // Parse IF condition
    if (item.if?.properties) {
      const propName = Object.keys(item.if.properties)[0];
      if (propName) {
        rule.ifCondition.property = propName;
        const propSchema = item.if.properties[propName];

        if (propSchema.const !== undefined) {
          rule.ifCondition.operator = 'equals';
          rule.ifCondition.value = String(propSchema.const);
        } else if (propSchema.enum) {
          rule.ifCondition.operator = 'enum';
          rule.ifCondition.value = propSchema.enum.join(', ');
        } else if (propSchema.type) {
          rule.ifCondition.operator = 'type';
          rule.ifCondition.value = propSchema.type;
        } else if (propSchema.pattern) {
          rule.ifCondition.operator = 'pattern';
          rule.ifCondition.value = propSchema.pattern;
        } else if (propSchema.minimum !== undefined) {
          rule.ifCondition.operator = 'minimum';
          rule.ifCondition.value = String(propSchema.minimum);
        } else if (propSchema.maximum !== undefined) {
          rule.ifCondition.operator = 'maximum';
          rule.ifCondition.value = String(propSchema.maximum);
        }
      }
    }
    if (item.if?.required && item.if.required.length > 0) {
      rule.ifCondition.property = item.if.required[0];
      rule.ifCondition.operator = 'required';
      rule.ifCondition.value = '';
    }

    // Parse THEN schema
    if (item.then?.required) {
      rule.thenSchema.requiredProperties = item.then.required;
    }
    if (item.then?.properties) {
      Object.entries(item.then.properties).forEach(([prop, schema]: [string, any]) => {
        Object.entries(schema).forEach(([constraint, value]) => {
          rule.thenSchema.propertyConstraints.push({
            property: prop,
            constraint: constraint as any,
            value: Array.isArray(value) ? value.join(', ') : String(value),
          });
        });
      });
    }

    // Parse ELSE schema - check if it contains a nested if/then/else
    if (item.else) {
      if (item.else.if) {
        // Nested if/then/else - recursively parse it as a separate rule
        // Don't add an else to the current rule, just parse the nested one
        parseIfThenElse(item.else);
      } else {
        // Simple else schema - add to current rule
        rule.elseSchema = {
          requiredProperties: item.else.required || [],
          propertyConstraints: [],
        };
        if (item.else.properties) {
          Object.entries(item.else.properties).forEach(([prop, schema]: [string, any]) => {
            Object.entries(schema).forEach(([constraint, value]) => {
              rule.elseSchema!.propertyConstraints.push({
                property: prop,
                constraint: constraint as any,
                value: Array.isArray(value) ? value.join(', ') : String(value),
              });
            });
          });
        }
      }
    }

    rules.push(rule);
  };

  allOfArray
    .filter(item => item.if !== undefined)
    .forEach(item => parseIfThenElse(item));

  return rules;
};

export default ConditionalSchemaBuilder;

