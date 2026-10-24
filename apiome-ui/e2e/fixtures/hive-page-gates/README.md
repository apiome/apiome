# Frozen page-gate fixtures (HIVE-13.2, #5615)

Unlike the other `hive-*` folders, nothing re-dumps these files. They are copies of the Versions
timeline fixture (`hive-versions/timeline.html`) from before the two quiet-pass tickets the page
gates were written against, kept so `tests/page-header-gate.test.tsx` can prove it still fails
them:

| File | Taken from | The gate fails it on |
| --- | --- | --- |
| `versions-pre-11-2.html` | the parent of `52436bd68` — before HIVE-11.2 (#5598) | three stacked banners, plus the crowded header below |
| `versions-pre-11-3.html` | the parent of `6e1886e94` — before HIVE-11.3 (#5599) | a project select and three secondaries in the header |

Do not edit or re-dump them. If a rule change makes the gate pass either one, the gate has stopped
measuring what it was built for: fix the rule, not the copy.
