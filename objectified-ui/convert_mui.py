#!/usr/bin/env python3
"""
Convert Material UI components to Radix UI + Tailwind in PropertyFormFields.tsx
"""

import re
import sys

def convert_sx_to_tailwind(sx_content):
    """Convert MUI sx prop to Tailwind classes"""
    classes = []

    # Layout
    if "display: 'flex'" in sx_content:
        classes.append('flex')
    if "flexDirection: 'column'" in sx_content:
        classes.append('flex-col')
    if "alignItems: 'center'" in sx_content:
        classes.append('items-center')
    if "justifyContent: 'space-between'" in sx_content:
        classes.append('justify-between')

    # Gap
    gap_match = re.search(r"gap:\s*(\d+(?:\.\d+)?)", sx_content)
    if gap_match:
        gap = float(gap_match.group(1))
        classes.append(f'gap-{int(gap * 2)}')

    # Padding
    p_match = re.search(r"(?:p|padding):\s*(\d+(?:\.\d+)?)", sx_content)
    if p_match:
        p = float(p_match.group(1))
        classes.append(f'p-{int(p * 2)}')

    # Background
    if "bgcolor:" in sx_content or "backgroundColor:" in sx_content:
        if "'white'" in sx_content or "'#fff'" in sx_content:
            classes.append('bg-white dark:bg-gray-800')
        elif "'#0f172a'" in sx_content or "'#1e293b'" in sx_content:
            classes.append('bg-gray-900')

    # Border
    if "borderRadius:" in sx_content:
        classes.append('rounded-lg')
    if "border:" in sx_content:
        classes.append('border')

    return ', '.join(f'"{c}"' for c in classes) if classes else '""'

def convert_box(content):
    """Convert Box components to div"""

    def replace_box(match):
        sx_content = match.group(1) if match.group(1) else ""
        tailwind_classes = convert_sx_to_tailwind(sx_content)
        if tailwind_classes and tailwind_classes != '""':
            return f'<div className={{cn({tailwind_classes})}}>'
        return '<div>'

    # Box with sx prop
    content = re.sub(r'<Box\s+sx={{([^}]+)}}>', replace_box, content)
    # Box without props
    content = re.sub(r'<Box\s*>', '<div>', content)
    # Closing tags
    content = re.sub(r'</Box>', '</div>', content)

    return content

def convert_textfield(content):
    """Convert TextField to Input/Textarea with FormField"""

    def replace_textfield(match):
        full_match = match.group(0)
        props = match.group(1)

        # Check if multiline
        is_multiline = 'multiline' in props
        component = 'Textarea' if is_multiline else 'Input'

        # Extract props
        label_match = re.search(r'label="([^"]+)"', props)
        helper_match = re.search(r'helperText="([^"]+)"', props)
        value_match = re.search(r'value={([^}]+)}', props)
        onchange_match = re.search(r'onChange={([^}]+)}', props)
        error_match = re.search(r'error={([^}]+)}', props)
        rows_match = re.search(r'rows={(\d+)}', props)

        label = label_match.group(1) if label_match else None
        helper = helper_match.group(1) if helper_match else None
        value = value_match.group(1) if value_match else "''  "
        onchange = onchange_match.group(1) if onchange_match else None
        error = error_match.group(1) if error_match else None
        rows = rows_match.group(1) if rows_match else '3'

        result = []

        # FormField wrapper if needed
        if label or helper or error:
            result.append('<FormField')
            if label:
                result.append(f'  label="{label}"')
            if helper:
                result.append(f'  helperText="{helper}"')
            if error:
                result.append(f'  error={{{error}}}')
            result.append('>')
            result.append(f'  <{component}')
        else:
            result.append(f'<{component}')

        # Add props
        if value:
            result.append(f'    value={{{value}}}')
        if onchange:
            result.append(f'    onChange={{{onchange}}}')
        if is_multiline:
            result.append(f'    rows={rows}')
        result.append('    className="rounded-lg"')
        result.append('  />')

        # Close FormField if needed
        if label or helper or error:
            result.append('</FormField>')

        return '\n'.join(result)

    # Match TextField components
    content = re.sub(
        r'<TextField\s+([^>]+)/>',
        replace_textfield,
        content,
        flags=re.DOTALL
    )

    return content

def convert_typography(content):
    """Convert Typography to HTML elements"""

    def replace_typography(match):
        variant = match.group(1)
        props = match.group(2)
        text = match.group(3)

        tag_map = {
            'h1': 'h1', 'h2': 'h2', 'h3': 'h3', 'h4': 'h4', 'h5': 'h5', 'h6': 'h6',
            'subtitle1': 'h3', 'subtitle2': 'h4',
            'body1': 'p', 'body2': 'p',
            'caption': 'span'
        }

        tag = tag_map.get(variant, 'span')

        # Extract sx styles and convert to classes
        sx_match = re.search(r'sx={{([^}]+)}}', props)
        if sx_match:
            sx_content = sx_match.group(1)
            classes = convert_sx_to_tailwind(sx_content)
            if variant == 'caption':
                classes += ', "text-xs"'
            if classes and classes != '""':
                return f'<{tag} className={{cn({classes})}}>{text}</{tag}>'

        return f'<{tag}>{text}</{tag}>'

    content = re.sub(
        r'<Typography\s+variant="([^"]+)"([^>]*)>([^<]*)</Typography>',
        replace_typography,
        content
    )

    return content

def main():
    if len(sys.argv) < 2:
        print("Usage: python3 convert_mui.py <file>")
        sys.exit(1)

    filepath = sys.argv[1]

    with open(filepath, 'r') as f:
        content = f.read()

    # Apply conversions
    print("Converting Box components...")
    content = convert_box(content)

    print("Converting TextField components...")
    content = convert_textfield(content)

    print("Converting Typography components...")
    content = convert_typography(content)

    # Write back
    output_file = filepath.replace('.tsx', '.converted.tsx')
    with open(output_file, 'w') as f:
        f.write(content)

    print(f"Conversion complete! Output written to {output_file}")
    print("Please review the changes before replacing the original file.")

if __name__ == '__main__':
    main()

