# Installation Instructions for Version & What's New Feature

## Quick Start

Dependencies are already declared in `apiome-ui/package.json`. From the **repository root** (Yarn workspaces):

```bash
yarn install
```

Or from `apiome-ui/` only:

```bash
cd apiome-ui && npm install
```

If you are adding the markdown stack to another project, align with this app’s versions:

```bash
npm install react-markdown@^10.1.0 remark-gfm@^4.0.1 rehype-raw@^7.0.0 --save
```

(`react-markdown` v10 includes its own TypeScript types; a separate `@types/react-markdown` package is not used.)

### Yarn / pnpm / bun (explicit pins)

```bash
yarn add react-markdown@^10.1.0 remark-gfm@^4.0.1 rehype-raw@^7.0.0
```

```bash
pnpm add react-markdown@^10.1.0 remark-gfm@^4.0.1 rehype-raw@^7.0.0
```

```bash
bun add react-markdown@^10.1.0 remark-gfm@^4.0.1 rehype-raw@^7.0.0
```

## What Was Changed

1. **Version badge**: Clickable label next to the Apiome logo (semver from `package.json`, or optional build label — see below).
2. **What's New dialog**: Opens release notes from `/WHATS_NEW.md`.
3. **Markdown**: GFM via `remark-gfm`, raw HTML via `rehype-raw` where configured.
4. **Dark mode**: Dialog styled for light and dark themes.

## Files to Review

- `src/app/components/ade/TopHeader.tsx` — badge label
- `src/app/components/ade/WhatsNewDialog.tsx` — dialog
- `public/WHATS_NEW.md` — release notes
- `docs/VERSION_WHATS_NEW_FEATURE.md` — full feature notes

## Testing

1. `npm run dev` or `yarn workspace apiome-ui dev`
2. Open any `/ade` route.
3. Confirm the badge shows `v` + `package.json` version (e.g. `v0.11.60`), unless `NEXT_PUBLIC_APP_BUILD_LABEL` is set.
4. Click the badge and confirm the What’s New dialog loads.

## Customizing

### Version / build badge

- **Default**: Badge text is `v{version}` from `apiome-ui/package.json` (`"version"` field).
- **CI / image builds**: Set `NEXT_PUBLIC_APP_BUILD_LABEL` at **build** time to a single string, e.g. `2026.05.05-84a231c` (date + short git SHA). That value is shown as-is (no extra `v` prefix).

### Release notes

Edit `public/WHATS_NEW.md`. Use normal Markdown, images under `public/`, external links, code blocks, tables, etc.

## Troubleshooting

- TypeScript or missing module errors: run `yarn install` from repo root or `npm install` in `apiome-ui/`.
- Empty dialog: ensure `public/WHATS_NEW.md` exists and the dev server was restarted after adding env vars.

## Next Steps

Ideas for later: unread marker, multi-release history, localization. See `docs/VERSION_WHATS_NEW_FEATURE.md`.
