'use client';

import Link from 'next/link';
import { useState } from 'react';
import { FolderKanban, Globe, LogOut, Settings2, ShieldCheck } from 'lucide-react';

import { BrandMark } from '../brand';
import { Avatar } from '@/app/components/ui/Avatar';
import { Button } from '@/app/components/ui/Button';
import { Card } from '@/app/components/ui/Card';
import { ComingNext } from '@/app/components/ui/ComingNext';
import { ICON_SIZE, ICON_STROKE_WIDTH } from '@/app/components/ui/iconSizes';
import CommandPaletteHost from '@/app/components/shell/CommandPaletteHost';
import ShortcutsHost from '@/app/components/shell/ShortcutsHost';
import { LAUNCHER_ROUTE } from '@/app/components/shell/appShellRoutes';
import { useControlPanelVisit } from '../shell/controlPanelVisit';
import { markWhatsNewSeen } from '../shell/whatsNewSeen';
import PreferencesDrawerHost from './preferences/PreferencesDrawerHost';
import { openPreferences } from './preferences/preferencesDrawerBus';
import WhatsNewDialog from './WhatsNewDialog';

import { useAuthSession } from '@lib/auth/session-client';
import { signOutEverywhere } from '@lib/auth/sign-out-client';
// The one place the build string is derived (HIVE-3.4, #5290) — the launcher, the top bar
// and the rail's user menu must never print three different builds.
import { APP_VERSION_BADGE } from '@lib/app-version';
import type { ExternalHomeCard } from '@lib/external-links';
import { formatWorkspaceMeta } from '@lib/auth/tenant-membership-context-mapping';
import type { LauncherSummary } from '@lib/db/launcher-summary';
import { findPlatformNavItem } from '@lib/platform-nav';

import AppLaunchCard from './launcher/AppLaunchCard';
import HoneycombOrnament from './launcher/HoneycombOrnament';
import ResourceRow from './launcher/ResourceRow';
import {
  accountMenuLabel,
  ANONYMOUS_ACCOUNT_NAME,
  countLabel,
  firstNameOf,
  greetingFor,
  lastOpenedFooter,
  launcherApps,
  launcherComingNext,
  LAUNCHER_RESOURCES,
} from './launcher/launcherModel';

/**
 * The `/ade` launcher (HIVE-4.5, #5299).
 *
 * Authority: `docs/mockups/home/launcher.html`; design language `docs/mockups/DESIGN.md`.
 *
 * This is the one signed-in route with no rail — it is the page an application is chosen
 * *from*, so there is nothing to navigate yet — and therefore the one route that draws its
 * own chrome. What that chrome is now is the brand: the hex canvas and honey wash the auth
 * pages use, a honeycomb ornament with the bee at its centre, and a card per application
 * carrying one identity hue. It replaced a zinc page with four `rgba()` glows and a Tailwind
 * gradient pair per card, none of which could follow a theme.
 *
 * Every line in the mockup's **Keeps (1:1)** list is still here: the build badge opening
 * What's new, preferences, the account chip, sign out, the greeting and headline, the ordered
 * application grid, the resource rows, and the footer's version and copyright.
 *
 * ### Only what opens (HIVE-12.5, #5612)
 *
 * Authority for this pass: `docs/mockups/proposals/launcher-focused.html`, callouts 2 and 3.
 * The grid and the Resources panel draw only destinations that can be opened. What is not
 * shipped — a host's disabled card, Community, Marketplace — is named once on the
 * `ComingNext` line under the grid, whose only control is a link to What's new. The dashed
 * "On the roadmap" panel is gone (its one row was a disabled button); HIVE-12.6 puts
 * "Recently shipped" in its place. The hero lost its eyebrow pill and filler paragraph and
 * gained an "n need attention" chip.
 *
 * ### The commercial slot
 *
 * No route into a separate product is written down anywhere in this file. The middle of the
 * grid is `commercialHomeCards` — `getCommercialAccessForSession().homeCards`, already
 * filtered by the reader's licence — and when they are entitled to nothing it is simply
 * empty. An open-source install therefore shows two cards, which is the honest picture.
 *
 * ### Why the three overlay hosts are here
 *
 * `PreferencesDrawerHost`, `CommandPaletteHost` and `ShortcutsHost` are mounted in three
 * mutually exclusive places (HIVE-1.4 / 3.6 / 3.7). `AppShell` hosts them for every other
 * `/ade` route; this route has no `AppShell`, so `⌘,`, `⌘K` and `?` would otherwise do
 * nothing on the first page a reader lands on.
 */

/** Props for {@link AdeHome}. */
export type AdeHomeProps = {
  /** Entitlement-filtered commercial cards, injected by the host. */
  commercialHomeCards?: ExternalHomeCard[];
  /**
   * Licence flags the reader holds. Not read here — the cards above are already filtered by
   * them — and kept because the page is the natural place to gate a future hero affordance.
   */
  entitledFeatureFlags?: string[];
  /** Workspace and counts for the hero's summary chips; absent while unresolved. */
  summary?: LauncherSummary;
};

/** The copyright line, which is the same on every surface that prints one. */
const COPYRIGHT = '© 2021 – 2026 NobuData LLC';

/**
 * The href of a nav destination, by id.
 *
 * The summary chips link into the app, and the routes they link to are the HIVE-3.2 nav
 * model's — read from it rather than restated, so a moved route moves here too.
 *
 * @param id A `PlatformNavItem.id`.
 * @returns The destination's href, falling back to the model's own Home and finally to the
 *          launcher — so a renamed id degrades to a working link rather than to `undefined`.
 */
function navHref(id: string): string {
  return findPlatformNavItem(id)?.href ?? findPlatformNavItem('home')?.href ?? LAUNCHER_ROUTE;
}

/**
 * The launcher.
 *
 * @param props Commercial cards, entitlements and the hero summary — see {@link AdeHomeProps}.
 * @returns The whole `/ade` page, including its three overlay hosts.
 */
export default function AdeHome({
  commercialHomeCards = [],
  entitledFeatureFlags: _entitledFeatureFlags = [],
  summary,
}: AdeHomeProps) {
  const { data: session } = useAuthSession();
  const [showWhatsNew, setShowWhatsNew] = useState(false);

  // When the Control Panel was last open on this device; `null` until after mount.
  const controlPanelOpenedAt = useControlPanelVisit();

  const apps = launcherApps(commercialHomeCards);
  const comingNext = launcherComingNext(commercialHomeCards);

  /** Open What's new — from the build badge or the Coming next line. */
  const openWhatsNew = () => {
    // The launcher's badge and the rail's user menu (HIVE-3.4, #5290) show the same notes
    // for the same build, so reading them here has to clear the rail's unread dot as well.
    markWhatsNewSeen();
    setShowWhatsNew(true);
  };
  const firstName = firstNameOf(session?.user?.name);
  const currentTenantId =
    (session?.user as { current_tenant_id?: string } | undefined)?.current_tenant_id ?? null;
  const workspace = summary?.workspace ?? null;

  return (
    <div className="launch-shell hex-bg glow-honey">
      <header className="launch-row launch-top">
        <Link
          href={LAUNCHER_ROUTE}
          aria-label="Apiome home"
          className="no-underline hover:no-underline"
        >
          <BrandMark variant="lockup" size={28} decorative priority />
        </Link>
        <button
          type="button"
          className="launch-ver"
          onClick={openWhatsNew}
          title="View what’s new"
        >
          <span className="launch-ver__dot" aria-hidden="true" />
          {APP_VERSION_BADGE}
          {/* The same spelling the rail's user menu uses (HIVE-3.4): a build string on its
              own does not say what pressing it does. */}
          <span className="sr-only"> — see what&apos;s new</span>
        </button>

        <div className="launch-top__actions">
          <Button
            variant="ghost"
            size="icon"
            aria-label="Preferences"
            title="Preferences (⌘,)"
            onClick={() => openPreferences()}
          >
            <Settings2 size={ICON_SIZE.button} strokeWidth={ICON_STROKE_WIDTH} aria-hidden />
          </Button>
          <Link
            href={navHref('profile')}
            className="launch-account"
            aria-label={accountMenuLabel(session?.user?.name)}
          >
            <Avatar
              size="sm"
              name={session?.user?.name}
              seed={session?.user?.email}
              src={session?.user?.image}
            />
            <span className="launch-account__name">
              {firstNameOf(session?.user?.name, ANONYMOUS_ACCOUNT_NAME)}
            </span>
          </Link>
          <Button
            variant="ghost"
            size="icon"
            aria-label="Sign out"
            title="Sign out"
            onClick={() => signOutEverywhere('/login')}
          >
            <LogOut size={ICON_SIZE.button} strokeWidth={ICON_STROKE_WIDTH} aria-hidden />
          </Button>
        </div>
      </header>

      <main className="launch-row">
        <section className="launch-hero">
          <HoneycombOrnament />
          {/* The greeting is the reader's *own* time of day, so the server's hour is not
              the right answer and the client's correction is not a mismatch worth warning
              about — the one case React documents `suppressHydrationWarning` for. */}
          <div className="launch-greet" suppressHydrationWarning>
            {greetingFor()}, {firstName}
          </div>
          <h1 className="launch-display">
            Your API
            <br />
            <span className="launch-display__accent">specification workspace</span>
          </h1>

          {summary ? (
            <div className="launch-chips">
              {workspace ? (
                <Link className="launch-chip" href={navHref('tenants')}>
                  <Avatar size="xs" shape="hex" tone="brand" name={workspace.name} />
                  <span className="launch-chip__name">{workspace.name}</span>
                  {workspace.role ? <span>{formatWorkspaceMeta(workspace, false)}</span> : null}
                </Link>
              ) : null}
              <Link className="launch-chip" href={navHref('projects')}>
                <FolderKanban aria-hidden />
                {countLabel(summary.projectCount, 'project')}
              </Link>
              {/* "published" is a state, not a countable noun, so this one is not
                  pluralised the way the projects chip beside it is. */}
              <Link className="launch-chip" href={navHref('published')}>
                <Globe aria-hidden />
                {summary.publishedCount} published
              </Link>
              {/* Only when something does: a "0 need attention" chip is noise. The count is
                  Home's Needs attention definition, and the chip leads to where the
                  findings are worked off. */}
              {summary.attentionCount > 0 ? (
                <Link
                  className="launch-chip"
                  href={navHref('lint-workspace')}
                  data-testid="launch-chip-attention"
                >
                  <ShieldCheck aria-hidden />
                  {summary.attentionCount} need attention
                </Link>
              ) : null}
            </div>
          ) : null}
        </section>

        <section aria-labelledby="launch-applications">
          <div className="launch-eyebrow">
            <h2 id="launch-applications" className="launch-caps">
              Applications
            </h2>
            <span className="launch-eyebrow__sub">Jump into the tool you need right now.</span>
          </div>
          <div className="launch-grid">
            {apps.map((app) => (
              <AppLaunchCard
                key={app.id}
                app={app}
                footerLabel={
                  app.primary ? lastOpenedFooter(app.footerLabel, controlPanelOpenedAt) : undefined
                }
              />
            ))}
          </div>
          {/* Inside the Applications section, right after the tiles: the keyboard order is
              tiles → Follow in What's new → Resources. */}
          <ComingNext items={comingNext} onFollow={openWhatsNew} />
        </section>

        <div className="launch-lower">
          <Card className="launch-panel" role="region" aria-labelledby="launch-resources">
            <div className="launch-eyebrow">
              <h2 id="launch-resources" className="launch-caps">
                Resources
              </h2>
              <span className="launch-eyebrow__sub">Learn, then get back to work.</span>
            </div>
            {LAUNCHER_RESOURCES.map((item) => (
              <ResourceRow key={item.id} item={item} />
            ))}
          </Card>

        </div>
      </main>

      <footer className="launch-row launch-foot">
        <span className="mono">{APP_VERSION_BADGE}</span>
        <span>{COPYRIGHT}</span>
      </footer>

      {/* Preferences pane (HIVE-1.4, #5277), command palette (HIVE-3.6, #5292) and the
          shortcuts sheet (HIVE-3.7, #5293). The launcher is the one `/ade` route with no
          rail, so it is the one route `AppShell` does not host these for. */}
      <PreferencesDrawerHost />
      <CommandPaletteHost currentTenantId={currentTenantId} />
      <ShortcutsHost currentTenantId={currentTenantId} />
      <WhatsNewDialog isOpen={showWhatsNew} onClose={() => setShowWhatsNew(false)} />
    </div>
  );
}
