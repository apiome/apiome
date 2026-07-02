import {
  BarChart3,
  Database,
  FileCode,
  Globe,
  GraduationCap,
  Import,
  LayoutGrid,
  Network,
  ScrollText,
  Search,
  ShieldCheck,
  ShieldHalf,
  TrendingUp,
  Users,
  Wand2,
  Zap,
} from "lucide-react";

const ICON_MAP = {
  BarChart3,
  Database,
  FileCode,
  Globe,
  GraduationCap,
  Import,
  LayoutGrid,
  Network,
  ScrollText,
  Search,
  ShieldCheck,
  ShieldHalf,
  TrendingUp,
  Users,
  Wand2,
  Zap,
} as const;

export type SuiteIconName = keyof typeof ICON_MAP;

export function SuiteIcon({
  name,
  className,
}: {
  name: string;
  className?: string;
}) {
  const Icon = ICON_MAP[name as SuiteIconName] ?? LayoutGrid;
  return <Icon className={className} />;
}
