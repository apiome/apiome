import type { Project } from './projectTypes';
import type { ProjectQualitySnapshot } from '../../../utils/project-quality-score-history';

/**
 * KPI projection used by the Projects list dashboard. Real values only —
 * absent signal collapses to 0 / null rather than being faked.
 */
export interface ProjectListKpis {
  total: number;
  enabled: number;
  disabled: number;
  deleted: number;
  /** Projects with a quality history snapshot whose latest overall < 70. */
  attention: number;
  /** Average of the latest overall scores across projects with history. */
  avgQuality: number | null;
  /** Best latest score + the project that holds it. */
  best: { project: Project; score: number } | null;
  /** Worst latest score + the project that holds it. */
  worst: { project: Project; score: number } | null;
  /** Projects updated in the last 24 hours. */
  recentlyUpdated: number;
  /** New project arrivals over the last 8 weeks (oldest → newest). */
  arrivalsSeries: number[];
  /** Average quality trend across the last 8 weeks (oldest → newest). */
  qualitySeries: number[];
  /** Latest snapshot per project keyed by project id. */
  latestQuality: Record<string, number>;
}

const DAY_MS = 24 * 60 * 60 * 1000;
const WEEK_MS = 7 * DAY_MS;
const ARRIVAL_WEEKS = 8;
const QUALITY_WEEKS = 8;
const ATTENTION_THRESHOLD = 70;

function latestQualityFor(history: ProjectQualitySnapshot[] | undefined): number | null {
  if (!history || history.length === 0) return null;
  return history[history.length - 1].overall;
}

/**
 * Average quality at a given point in time, computed from each project's most
 * recent snapshot recorded at or before `cutoff`. Returns null when no
 * project has any snapshot before the cutoff.
 */
function avgQualityAt(
  qualityHistoryMap: Record<string, ProjectQualitySnapshot[]>,
  cutoff: number
): number | null {
  const samples: number[] = [];
  for (const history of Object.values(qualityHistoryMap)) {
    let pick: ProjectQualitySnapshot | null = null;
    for (const snap of history) {
      const ts = Date.parse(snap.recordedAt);
      if (!Number.isFinite(ts) || ts > cutoff) continue;
      if (!pick || Date.parse(pick.recordedAt) < ts) pick = snap;
    }
    if (pick) samples.push(pick.overall);
  }
  if (samples.length === 0) return null;
  return Math.round(samples.reduce((sum, v) => sum + v, 0) / samples.length);
}

export function deriveProjectKpis(
  projects: Project[],
  qualityHistoryMap: Record<string, ProjectQualitySnapshot[]> = {},
  now: number = Date.now()
): ProjectListKpis {
  const total = projects.length;
  const enabled = projects.filter((p) => p.enabled && !p.deleted_at).length;
  const disabled = projects.filter((p) => !p.enabled && !p.deleted_at).length;
  const deleted = projects.filter((p) => Boolean(p.deleted_at)).length;

  const latestQuality: Record<string, number> = {};
  let attention = 0;
  let qualityTotal = 0;
  let qualityCount = 0;
  let best: { project: Project; score: number } | null = null;
  let worst: { project: Project; score: number } | null = null;

  for (const project of projects) {
    const score = latestQualityFor(qualityHistoryMap[project.id]);
    if (score == null) continue;
    latestQuality[project.id] = score;
    qualityTotal += score;
    qualityCount += 1;
    if (score < ATTENTION_THRESHOLD) attention += 1;
    if (!best || score > best.score) best = { project, score };
    if (!worst || score < worst.score) worst = { project, score };
  }

  const avgQuality = qualityCount === 0 ? null : Math.round(qualityTotal / qualityCount);

  const dayCutoff = now - DAY_MS;
  const recentlyUpdated = projects.filter(
    (p) => Date.parse(p.updated_at) >= dayCutoff
  ).length;

  const arrivalsSeries = Array.from({ length: ARRIVAL_WEEKS }, (_, idx) => {
    const bucketEnd = now - (ARRIVAL_WEEKS - 1 - idx) * WEEK_MS;
    const bucketStart = bucketEnd - WEEK_MS;
    return projects.filter((p) => {
      const ts = Date.parse(p.created_at);
      return ts >= bucketStart && ts < bucketEnd;
    }).length;
  });

  const qualitySeries = Array.from({ length: QUALITY_WEEKS }, (_, idx) => {
    const bucketEnd = now - (QUALITY_WEEKS - 1 - idx) * WEEK_MS;
    return avgQualityAt(qualityHistoryMap, bucketEnd) ?? 0;
  });

  return {
    total,
    enabled,
    disabled,
    deleted,
    attention,
    avgQuality,
    best,
    worst,
    recentlyUpdated,
    arrivalsSeries,
    qualitySeries,
    latestQuality,
  };
}
