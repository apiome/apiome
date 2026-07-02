#!/usr/bin/env node

const fs = require('fs');
const path = require('path');

const filePath = process.argv[2] || './src/app/components/ade/studio/PropertyFormFields.tsx';
let content = fs.readFileSync(filePath, 'utf8');

// Component replacements
const replacements = [
  // Box -> div with className
  [/<Box\s+sx={{([^}]+)}}>/, (match, styles) => {
    const classes = convertSxToClassName(styles);
    return `<div className={cn(${classes})}>`;
  }],
  [/<\/Box>/g, '</div>'],

  // TextField -> Input/Textarea with FormField wrapper
  [/<TextField\s+([^>]+)\/>/g, (match, props) => convertTextField(props, true)],
  [/<TextField\s+([^>]+)>([^<]*)<\/TextField>/g, (match, props, children) => convertTextField(props, false, children)],

  // Typography -> appropriate HTML element
  [/<Typography\s+variant="([^"]+)"([^>]*)>([^<]*)<\/Typography>/g, (match, variant, props, text) => {
    const tag = {
      'h1': 'h1', 'h2': 'h2', 'h3': 'h3', 'h4': 'h4', 'h5': 'h5', 'h6': 'h6',
      'subtitle1': 'h3', 'subtitle2': 'h4',
      'body1': 'p', 'body2': 'p',
      'caption': 'span'
    }[variant] || 'span';
    const className = extractClassName(props);
    return `<${tag} className={cn(${className})}>${text}</${tag}>`;
  }],

  // IconButton -> button
  [/<IconButton([^>]*)>([^<]*)<\/IconButton>/g, (match, props, children) => {
    const className = extractClassName(props);
    const otherProps = extractOtherProps(props);
    return `<button className={cn(${className})} ${otherProps}>${children}</button>`;
  }],

  // Tooltip -> TooltipProvider + Tooltip + TooltipTrigger + TooltipContent
  [/<Tooltip\s+title="([^"]+)"([^>]*)>([^<]*)<\/Tooltip>/g, (match, title, props, children) => {
    return `<TooltipProvider><Tooltip><TooltipTrigger asChild>${children}</TooltipTrigger><TooltipContent><p>${title}</p></TooltipContent></Tooltip></TooltipProvider>`;
  }],

  // Collapse -> Collapsible
  [/<Collapse\s+in={([^}]+)}([^>]*)>/g, (match, condition, props) => {
    return `<Collapsible open={${condition}}>`;
  }],
  [/<\/Collapse>/g, '</CollapsibleContent></Collapsible>'],

  // FormControlLabel with Checkbox
  [/<FormControlLabel\s+control={<Checkbox([^>]*)>}([^>]*)\/>/g, (match, checkProps, labelProps) => {
    return convertFormControlLabel(checkProps, labelProps, 'checkbox');
  }],

  // FormControlLabel with Radio
  [/<FormControlLabel\s+control={<Radio([^>]*)>}([^>]*)\/>/g, (match, radioProps, labelProps) => {
    return convertFormControlLabel(radioProps, labelProps, 'radio');
  }],

  // List -> div
  [/<List([^>]*)>/g, '<div className="space-y-1">'],
  [/<\/List>/g, '</div>'],

  // ListItem -> div
  [/<ListItem([^>]*)>/g, '<div className="flex items-center gap-2 py-2">'],
  [/<\/ListItem>/g, '</div>'],
];

function convertSxToClassName(sx) {
  // Simple conversion - this would need to be more sophisticated for production
  const classes = [];
  if (sx.includes('display: \'flex\'')) classes.push('"flex"');
  if (sx.includes('flexDirection: \'column\'')) classes.push('"flex-col"');
  if (sx.includes('gap:')) {
    const gap = sx.match(/gap:\s*(\d+)/)?.[1];
    if (gap) classes.push(`"gap-${gap}"`);
  }
  return classes.join(', ');
}

function convertTextField(props, selfClosing, children = '') {
  const isMultiline = props.includes('multiline');
  const Component = isMultiline ? 'Textarea' : 'Input';

  // Extract props
  const label = props.match(/label="([^"]+)"/)?.[1];
  const helperText = props.match(/helperText="([^"]+)"/)?.[1];
  const error = props.match(/error={([^}]+)}/)?.[1];

  let result = '';
  if (label || helperText || error) {
    result += '<FormField';
    if (label) result += ` label="${label}"`;
    if (helperText) result += ` helperText="${helperText}"`;
    if (error) result += ` error={${error}}`;
    result += `>\n  <${Component} `;
  } else {
    result += `<${Component} `;
  }

  // Add other props
  const otherProps = props
    .replace(/label="[^"]+"/g, '')
    .replace(/helperText="[^"]+"/g, '')
    .replace(/error={[^}]+}/g, '')
    .replace(/sx={{[^}]+}}/g, '')
    .trim();

  result += otherProps;
  result += selfClosing ? ' />' : `>${children}</${Component}>`;

  if (label || helperText || error) {
    result += '\n</FormField>';
  }

  return result;
}

function extractClassName(props) {
  const sx = props.match(/sx={{([^}]+)}}/)?.[1];
  if (!sx) return '""';
  return convertSxToClassName(sx);
}

function extractOtherProps(props) {
  return props
    .replace(/sx={{[^}]+}}/g, '')
    .replace(/size="[^"]+"/g, '')
    .trim();
}

function convertFormControlLabel(controlProps, labelProps, type) {
  const label = labelProps.match(/label={([^}]+)}/)?.[1] || labelProps.match(/label="([^"]+)"/)?.[1];
  const checked = controlProps.match(/checked={([^}]+)}/)?.[1];
  const onChange = controlProps.match(/onChange={([^}]+)}/)?.[1];

  if (type === 'checkbox') {
    return `<div className="flex items-center gap-2">
      <Checkbox checked={${checked}} onCheckedChange={${onChange}} />
      <Label>${label}</Label>
    </div>`;
  } else {
    return `<RadioGroupItem value="${label}" label={${label}} checked={${checked}} />`;
  }
}

// Apply replacements
replacements.forEach(([pattern, replacement]) => {
  content = content.replace(pattern, replacement);
});

// Write back
fs.writeFileSync(filePath, content, 'utf8');
console.log('Conversion complete!');

