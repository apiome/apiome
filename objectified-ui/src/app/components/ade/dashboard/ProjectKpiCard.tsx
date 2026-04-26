'use client';

/**
 * Project KPI card. Visually identical to {@link RepositoryKpiCard} —
 * re-exported under a project-specific name so the Projects screens read as
 * `ProjectKpiCard` and can diverge later without touching the repositories
 * surface.
 */
export {
  RepositoryKpiCard as ProjectKpiCard,
  type RepositoryKpiCardProps as ProjectKpiCardProps,
} from './RepositoryKpiCard';
export type {
  RepositoryKpiTone as ProjectKpiTone,
  RepositoryKpiSubtitleTone as ProjectKpiSubtitleTone,
} from './dashboardScreenClasses';
