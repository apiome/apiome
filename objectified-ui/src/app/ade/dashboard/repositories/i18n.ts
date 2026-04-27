export type RepositoriesLocale = 'en';

export interface RepositoriesI18nBundle {
  pageTitle: string;
  pageSubtitle: string;
  addRepositoryButton: string;
  searchPlaceholder: string;
  providerAll: string;
  statusAll: string;
  tableLastScan: string;
  tableActions: string;
  emptyTitle: string;
  emptyDescription: string;
  emptyAction: string;
  tableRepo: string;
  tableProvider: string;
  tableBranches: string;
  tableStatus: string;
  scanNowButton: string;
  pauseButton: string;
  resumeButton: string;
  openDetailButton: string;
  scanQueuedMessage: string;
  pausedMessage: string;
  resumedMessage: string;
  wizardTitle: string;
  wizardDescription: string;
  wizardBack: string;
  wizardNext: string;
  refreshingButton: string;
  wizardCancel: string;
  wizardSubmit: string;
  wizardStepBadgeFormat: string;
  wizardStepperAccount: string;
  wizardStepperRepo: string;
  wizardStepperBranches: string;
  wizardStepperManifest: string;
  wizardFooterEyebrow: string;
  wizardSearchEmpty: string;
  wizardManifestHint: string;
  wizardManifestSchemaLink: string;
  wizardManifestValid: string;
  wizardManifestInvalidPrefix: string;
  wizardManifestEmpty: string;
  wizardBranchPatternHint: string;
  wizardProviderUnsupported: string;
  wizardAccountListHint: string;
  wizardAccountReposCountFormat: string;
  wizardManifestFilenameLabel: string;
  stepAccountTitle: string;
  stepRepoTitle: string;
  stepBranchesTitle: string;
  stepManifestTitle: string;
  defaultBranchLabel: string;
  addBranchPatternLabel: string;
  addPatternButton: string;
  branchPatternPlaceholder: string;
  pollIntervalPlaceholder: string;
  removeButton: string;
  availableBranchesLabel: string;
  saveBranchesButton: string;
  savingButton: string;
  accountRequired: string;
  repoRequired: string;
  repoSelectionHint: string;
  branchesRequired: string;
  successMessage: string;
  branchesUpdatedMessage: string;
  scanTimelineMessage: string;
  loadingRepositories: string;
  loadingRepository: string;
  refreshingRepositoriesMessage: string;
  refreshingRepositoryDataMessage: string;
  viewButton: string;
  backButton: string;
  providerLabel: string;
  statusLabel: string;
  branchesLabel: string;
  timelineLabel: string;
  branchSubpathPlaceholder: string;
  manifestPlaceholder: string;
  noLinkedAccountsQuestion: string;
  yesButton: string;
  noButton: string;
  ownerPlaceholder: string;
  namePlaceholder: string;
  ownerNameRequired: string;
  settingsUpdatedMessage: string;
  repositoryDisabledMessage: string;
  repositoryEnabledMessage: string;
  saveSettingsButton: string;
  enableButton: string;
  disableButton: string;
  deleteButton: string;
  deleteDialogTitle: string;
  deleteDialogDescriptionPrefix: string;
  deleteDialogDescriptionSuffix: string;
  cancelButton: string;
  deleteRepositoryButton: string;
  ownerNameFallbackPlaceholder: string;
  statusHealthy: string;
  statusWarnings: string;
  statusError: string;
  statusScanning: string;
  statusDisabled: string;
  kpiTrackedLabel: string;
  kpiTrackedSubtitle: string;
  kpiHealthyLabel: string;
  kpiHealthySubtitleFormat: string;
  kpiAttentionLabel: string;
  kpiAttentionSubtitleFormat: string;
  kpiScannedLabel: string;
  kpiScannedSubtitleFormat: string;
  kpiAvgScanLabel: string;
  kpiAvgScanSubtitle: string;
  kpiAvgScanNoData: string;
  kpiSlowestLabel: string;
  kpiSlowestNoData: string;
  scanDurationFallback: string;
  recentScansEyebrow: string;
  providerMixEyebrow: string;
  recentActivityEyebrow: string;
  favoritesOnlyButton: string;
  favoriteAriaLabel: string;
  unfavoriteAriaLabel: string;
  sortLabel: string;
  sortLastScanDesc: string;
  sortLastScanAsc: string;
  sortNameAsc: string;
  sortNameDesc: string;
  sortStatus: string;
  sortFavoritesFirst: string;
  paginationFooterFormat: string;
  viewAllLink: string;
  scanReportsLink: string;
}

export const repositoriesI18n: Record<RepositoriesLocale, RepositoriesI18nBundle> = {
  en: {
    pageTitle: 'Repositories',
    pageSubtitle: 'Register and monitor connected source repositories.',
    addRepositoryButton: 'Add Repository',
    searchPlaceholder: 'Search repositories...',
    providerAll: 'All providers',
    statusAll: 'All statuses',
    tableLastScan: 'Last scan',
    tableActions: 'Actions',
    emptyTitle: 'No repositories yet',
    emptyDescription: 'Register a repository to start scan and sync workflows.',
    emptyAction: 'Register your first repository',
    tableRepo: 'Repository',
    tableProvider: 'Provider',
    tableBranches: 'Branches',
    tableStatus: 'Status',
    scanNowButton: 'Scan now',
    pauseButton: 'Pause',
    resumeButton: 'Resume',
    openDetailButton: 'Open detail',
    scanQueuedMessage: 'Scan queued.',
    pausedMessage: 'Repository paused.',
    resumedMessage: 'Repository resumed.',
    wizardTitle: 'Add Repository',
    wizardDescription: 'Connect a repository and kick off an initial scan.',
    wizardBack: 'Back',
    wizardNext: 'Next',
    refreshingButton: 'Refreshing...',
    wizardCancel: 'Cancel',
    wizardSubmit: 'Register repository',
    wizardStepBadgeFormat: 'Step {current} of {total}',
    wizardStepperAccount: 'Linked account',
    wizardStepperRepo: 'Pick repository',
    wizardStepperBranches: 'Branches & subpath',
    wizardStepperManifest: 'Manifest',
    wizardFooterEyebrow: 'Cancellable · no scan starts until you submit',
    wizardSearchEmpty: 'No repositories matched your search.',
    wizardManifestHint:
      "Paste your .objectified/repo.yaml contents. If your repo already has one in the default branch, we'll pick it up automatically — this field is for overriding before the first scan.",
    wizardManifestSchemaLink: 'Manifest schema reference',
    wizardManifestValid: 'Manifest schema is valid.',
    wizardManifestInvalidPrefix: 'Manifest YAML is invalid:',
    wizardManifestEmpty: 'Optional · leave blank to use the manifest from the default branch.',
    wizardBranchPatternHint:
      'Use globs to keep new release branches under the same scan policy automatically.',
    wizardProviderUnsupported: 'Coming soon',
    wizardAccountListHint:
      "Choose which connected provider account to import from. We'll only see the repos you've already authorized for that account.",
    wizardAccountReposCountFormat: '{count} repos discoverable',
    wizardManifestFilenameLabel: '.objectified/repo.yaml',
    stepAccountTitle: 'Pick a linked account',
    stepRepoTitle: 'Search and pick repository',
    stepBranchesTitle: 'Select branches and subpath',
    stepManifestTitle: 'Optional manifest upload',
    defaultBranchLabel: 'Default branch',
    addBranchPatternLabel: 'Track branch pattern',
    addPatternButton: 'Add pattern',
    branchPatternPlaceholder: 'release/*',
    pollIntervalPlaceholder: 'Poll interval seconds (optional)',
    removeButton: 'Remove',
    availableBranchesLabel: 'Available branches',
    saveBranchesButton: 'Save branches',
    savingButton: 'Saving...',
    accountRequired: 'Select a linked account before continuing.',
    repoRequired: 'Select a repository before continuing.',
    repoSelectionHint: 'Select a repository, then click Next to refresh branch data.',
    branchesRequired: 'Select at least one branch.',
    successMessage: 'Repository registered. Initial scan started.',
    branchesUpdatedMessage: 'Repository branches updated.',
    scanTimelineMessage: 'Scan in progress...',
    loadingRepositories: 'Loading repositories...',
    loadingRepository: 'Loading repository...',
    refreshingRepositoriesMessage: 'Refreshing repositories for the selected account...',
    refreshingRepositoryDataMessage: 'Refreshing repository data and loading branches...',
    viewButton: 'View',
    backButton: 'Back',
    providerLabel: 'Provider',
    statusLabel: 'Status',
    branchesLabel: 'Branches',
    timelineLabel: 'Timeline',
    branchSubpathPlaceholder: 'Optional subpath glob (e.g. specs/**)',
    manifestPlaceholder: '.objectified/repo.yaml contents',
    noLinkedAccountsQuestion:
      'No linked accounts have been added yet. Would you like me to direct you to the linked accounts page?',
    yesButton: 'Yes',
    noButton: 'No',
    ownerPlaceholder: 'Repository owner',
    namePlaceholder: 'Repository name',
    ownerNameRequired: 'Owner and repository name are required.',
    settingsUpdatedMessage: 'Repository settings updated.',
    repositoryDisabledMessage: 'Repository disabled.',
    repositoryEnabledMessage: 'Repository enabled.',
    saveSettingsButton: 'Save repository settings',
    enableButton: 'Enable',
    disableButton: 'Disable',
    deleteButton: 'Delete',
    deleteDialogTitle: 'Delete repository',
    deleteDialogDescriptionPrefix: 'Type',
    deleteDialogDescriptionSuffix: 'to confirm permanent deletion.',
    cancelButton: 'Cancel',
    deleteRepositoryButton: 'Delete repository',
    ownerNameFallbackPlaceholder: 'owner/name',
    statusHealthy: 'Healthy',
    statusWarnings: 'Warnings',
    statusError: 'Error',
    statusScanning: 'Scanning',
    statusDisabled: 'Disabled',
    kpiTrackedLabel: 'Total tracked',
    kpiTrackedSubtitle: 'repositories',
    kpiHealthyLabel: 'Healthy',
    kpiHealthySubtitleFormat: '{pct}% of tracked repos',
    kpiAttentionLabel: 'Warnings · scanning',
    kpiAttentionSubtitleFormat: '{warnings} warnings · {scanning} scanning',
    kpiScannedLabel: 'Scanned · 24 h',
    kpiScannedSubtitleFormat: '{stale} stale · > 24 h since last scan',
    kpiAvgScanLabel: 'Avg scan time',
    kpiAvgScanSubtitle: 'across last 7 d scans',
    kpiAvgScanNoData: 'no scan timing data yet',
    kpiSlowestLabel: 'Slowest last scan',
    kpiSlowestNoData: 'no scan timing data yet',
    scanDurationFallback: '—',
    recentScansEyebrow: 'All tracked repositories · sortable',
    providerMixEyebrow: 'Distribution by provider',
    recentActivityEyebrow: 'Latest scans, syncs, and lifecycle events',
    favoritesOnlyButton: 'Favorites only',
    favoriteAriaLabel: 'Star repository',
    unfavoriteAriaLabel: 'Unstar repository',
    sortLabel: 'Sort',
    sortLastScanDesc: 'Last scan ↓ (newest first)',
    sortLastScanAsc: 'Last scan ↑ (oldest first)',
    sortNameAsc: 'Repository A → Z',
    sortNameDesc: 'Repository Z → A',
    sortStatus: 'Status',
    sortFavoritesFirst: 'Favorites first',
    paginationFooterFormat: 'Showing {visible} of {total}',
    viewAllLink: 'View all repositories →',
    scanReportsLink: 'Scan reports',
  },
};

export function getRepositoriesI18nBundle(locale: string | undefined): RepositoriesI18nBundle {
  if (locale && locale.toLowerCase().startsWith('en')) {
    return repositoriesI18n.en;
  }
  return repositoriesI18n.en;
}
