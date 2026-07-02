/**
 * Application-wide theme configuration
 * Supports multiple pre-built themes with custom color schemes
 */

export interface ThemeColors {
  // Base colors
  background: string;
  foreground: string;

  // UI elements
  primary: string;
  primaryForeground: string;
  secondary: string;
  secondaryForeground: string;
  muted: string;
  mutedForeground: string;

  // Borders and accents
  border: string;
  accent: string;
  accentForeground: string;

  // Interactive elements
  card: string;
  cardForeground: string;
  popover: string;
  popoverForeground: string;

  // Status colors
  destructive: string;
  destructiveForeground: string;
}

export interface Theme {
  id: string;
  name: string;
  description: string;
  colors: ThemeColors;
  cssClass: string; // Class to add to <html> element
}

export const themes: Theme[] = [
  {
    id: 'system',
    name: 'Follow System',
    description: 'Automatically matches your system light/dark preference',
    cssClass: 'theme-system',
    colors: {
      // These are placeholder colors - actual colors come from light or dark theme
      background: '#ffffff',
      foreground: '#171717',
      primary: '#6366f1',
      primaryForeground: '#ffffff',
      secondary: '#f1f5f9',
      secondaryForeground: '#0f172a',
      muted: '#f8fafc',
      mutedForeground: '#64748b',
      border: '#e2e8f0',
      accent: '#f1f5f9',
      accentForeground: '#0f172a',
      card: '#ffffff',
      cardForeground: '#171717',
      popover: '#ffffff',
      popoverForeground: '#171717',
      destructive: '#ef4444',
      destructiveForeground: '#ffffff',
    },
  },
  {
    id: 'light',
    name: 'Light',
    description: 'Clean and bright default theme',
    cssClass: 'theme-light',
    colors: {
      background: '#ffffff',
      foreground: '#171717',
      primary: '#6366f1',
      primaryForeground: '#ffffff',
      secondary: '#f1f5f9',
      secondaryForeground: '#0f172a',
      muted: '#f8fafc',
      mutedForeground: '#64748b',
      border: '#e2e8f0',
      accent: '#f1f5f9',
      accentForeground: '#0f172a',
      card: '#ffffff',
      cardForeground: '#171717',
      popover: '#ffffff',
      popoverForeground: '#171717',
      destructive: '#ef4444',
      destructiveForeground: '#ffffff',
    },
  },
  {
    id: 'dark',
    name: 'Dark',
    description: 'Easy on the eyes for low-light environments',
    cssClass: 'theme-dark',
    colors: {
      background: '#0a0a0a',
      foreground: '#ededed',
      primary: '#6366f1',
      primaryForeground: '#ffffff',
      secondary: '#1e293b',
      secondaryForeground: '#f8fafc',
      muted: '#1e293b',
      mutedForeground: '#94a3b8',
      border: '#334155',
      accent: '#1e293b',
      accentForeground: '#f8fafc',
      card: '#0f172a',
      cardForeground: '#ededed',
      popover: '#0f172a',
      popoverForeground: '#ededed',
      destructive: '#dc2626',
      destructiveForeground: '#ffffff',
    },
  },
  {
    id: 'high-contrast',
    name: 'High Contrast',
    description: 'Maximum readability with stark contrasts',
    cssClass: 'theme-high-contrast',
    colors: {
      background: '#000000',
      foreground: '#ffffff',
      primary: '#ffffff',
      primaryForeground: '#000000',
      secondary: '#1a1a1a',
      secondaryForeground: '#ffffff',
      muted: '#1a1a1a',
      mutedForeground: '#cccccc',
      border: '#ffffff',
      accent: '#ffff00',
      accentForeground: '#000000',
      card: '#000000',
      cardForeground: '#ffffff',
      popover: '#000000',
      popoverForeground: '#ffffff',
      destructive: '#ff0000',
      destructiveForeground: '#ffffff',
    },
  },
  {
    id: 'blueprint',
    name: 'Blueprint',
    description: 'Professional blueprint style with blue grid',
    cssClass: 'theme-blueprint',
    colors: {
      background: '#0c1e3a',
      foreground: '#e3f2fd',
      primary: '#2196f3',
      primaryForeground: '#ffffff',
      secondary: '#1a3a5c',
      secondaryForeground: '#e3f2fd',
      muted: '#163250',
      mutedForeground: '#90caf9',
      border: '#1e88e5',
      accent: '#42a5f5',
      accentForeground: '#ffffff',
      card: '#0d2847',
      cardForeground: '#e3f2fd',
      popover: '#0d2847',
      popoverForeground: '#e3f2fd',
      destructive: '#ef5350',
      destructiveForeground: '#ffffff',
    },
  },
  {
    id: 'whiteboard',
    name: 'Whiteboard',
    description: 'Minimal and clean like a physical whiteboard',
    cssClass: 'theme-whiteboard',
    colors: {
      background: '#fafafa',
      foreground: '#212121',
      primary: '#424242',
      primaryForeground: '#ffffff',
      secondary: '#f5f5f5',
      secondaryForeground: '#212121',
      muted: '#eeeeee',
      mutedForeground: '#757575',
      border: '#e0e0e0',
      accent: '#eeeeee',
      accentForeground: '#212121',
      card: '#ffffff',
      cardForeground: '#212121',
      popover: '#ffffff',
      popoverForeground: '#212121',
      destructive: '#d32f2f',
      destructiveForeground: '#ffffff',
    },
  },
  {
    id: 'solarized',
    name: 'Solarized',
    description: 'Popular theme with carefully chosen colors',
    cssClass: 'theme-solarized',
    colors: {
      background: '#002b36',
      foreground: '#839496',
      primary: '#268bd2',
      primaryForeground: '#fdf6e3',
      secondary: '#073642',
      secondaryForeground: '#839496',
      muted: '#073642',
      mutedForeground: '#586e75',
      border: '#094653',
      accent: '#2aa198',
      accentForeground: '#fdf6e3',
      card: '#00212b',
      cardForeground: '#839496',
      popover: '#00212b',
      popoverForeground: '#839496',
      destructive: '#dc322f',
      destructiveForeground: '#fdf6e3',
    },
  },
  {
    id: 'nord',
    name: 'Nord',
    description: 'Arctic, north-bluish color palette',
    cssClass: 'theme-nord',
    colors: {
      background: '#2e3440',
      foreground: '#eceff4',
      primary: '#88c0d0',
      primaryForeground: '#2e3440',
      secondary: '#3b4252',
      secondaryForeground: '#eceff4',
      muted: '#3b4252',
      mutedForeground: '#d8dee9',
      border: '#4c566a',
      accent: '#5e81ac',
      accentForeground: '#eceff4',
      card: '#2e3440',
      cardForeground: '#eceff4',
      popover: '#2e3440',
      popoverForeground: '#eceff4',
      destructive: '#bf616a',
      destructiveForeground: '#eceff4',
    },
  },
  {
    id: 'darcula',
    name: 'Darcula',
    description: 'IntelliJ-inspired dark theme',
    cssClass: 'theme-darcula',
    colors: {
      background: '#2b2b2b',
      foreground: '#a9b7c6',
      primary: '#589df6',
      primaryForeground: '#ffffff',
      secondary: '#313335',
      secondaryForeground: '#a9b7c6',
      muted: '#313335',
      mutedForeground: '#808080',
      border: '#3c3f41',
      accent: '#4b6eaf',
      accentForeground: '#ffffff',
      card: '#2b2b2b',
      cardForeground: '#a9b7c6',
      popover: '#2b2b2b',
      popoverForeground: '#a9b7c6',
      destructive: '#e74848',
      destructiveForeground: '#ffffff',
    },
  },
];

export const getThemeById = (id: string): Theme | undefined => {
  return themes.find(theme => theme.id === id);
};

export const getDefaultTheme = (): Theme => {
  return themes[0]; // Light theme
};

