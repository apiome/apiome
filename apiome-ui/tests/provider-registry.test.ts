/**
 * Provider registry & deploy config tests (OLO-2.3, #4195).
 *
 * The registry is the single surface deciding which sign-in providers a deployment enables,
 * purely from env. These tests pin:
 *
 *   1. The registry vocabulary — ids, labels, statuses, and each provider's env contract.
 *   2. Enablement semantics — all required env vars set + non-blank; blanks count as unset;
 *      `coming-soon` and unknown ids are never enabled.
 *   3. The acceptance criteria — enabling/disabling a provider via env alone adds/removes it
 *      from the enabled set (no code changes).
 *   4. Delegation — `isEntraIdConfigured` (OLO-2.1) resolves through the registry, so the
 *      azure env contract cannot drift between the two modules.
 *   5. Route contracts (source level) — the signup-intent and link routes gate on the
 *      registry, and the NextAuth route registers providers from it.
 */
import * as fs from 'fs';
import * as path from 'path';
import {
  PROVIDER_REGISTRY,
  enabledProviderIds,
  enabledProviders,
  getProviderDescriptor,
  isProviderEnabled,
  providerSummaries,
  readEnvString,
} from '../lib/auth/provider-registry';
import { isEntraIdConfigured } from '../lib/auth/entra-provider';

/** Env enabling every available provider. */
const ALL_ENABLED_ENV = {
  GITHUB_ID: 'gh-id',
  GITHUB_SECRET: 'gh-secret',
  GITLAB_CLIENT_ID: 'gl-id',
  GITLAB_CLIENT_SECRET: 'gl-secret',
  AZURE_AD_CLIENT_ID: 'az-id',
  AZURE_AD_CLIENT_SECRET: 'az-secret',
  GOOGLE_CLIENT_ID: 'gg-id',
  GOOGLE_CLIENT_SECRET: 'gg-secret',
  OKTA_CLIENT_ID: 'ok-id',
  OKTA_CLIENT_SECRET: 'ok-secret',
  OKTA_ISSUER: 'https://example.okta.com/oauth2/default',
  COGNITO_CLIENT_ID: 'cg-id',
  COGNITO_CLIENT_SECRET: 'cg-secret',
  COGNITO_ISSUER: 'https://cognito-idp.us-east-1.amazonaws.com/us-east-1_AbCdEf',
  KEYCLOAK_CLIENT_ID: 'kc-id',
  KEYCLOAK_CLIENT_SECRET: 'kc-secret',
  KEYCLOAK_ISSUER: 'https://kc.example.com/realms/apiome',
  OIDC_CLIENT_ID: 'oidc-id',
  OIDC_CLIENT_SECRET: 'oidc-secret',
  OIDC_ISSUER: 'https://auth.example.com',
  AUTH0_CLIENT_ID: 'a0-id',
  AUTH0_CLIENT_SECRET: 'a0-secret',
  AUTH0_ISSUER: 'https://acme.auth0.com',
  LINE_CLIENT_ID: 'line-id',
  LINE_CLIENT_SECRET: 'line-secret',
  VK_CLIENT_ID: 'vk-id',
  VK_CLIENT_SECRET: 'vk-secret',
  WECHAT_CLIENT_ID: 'wx-id',
  WECHAT_CLIENT_SECRET: 'wx-secret',
  ATLASSIAN_CLIENT_ID: 'atl-id',
  ATLASSIAN_CLIENT_SECRET: 'atl-secret',
  BITBUCKET_CLIENT_ID: 'bb-key',
  BITBUCKET_CLIENT_SECRET: 'bb-secret',
  SLACK_CLIENT_ID: 'slack-id',
  SLACK_CLIENT_SECRET: 'slack-secret',
  LINKEDIN_CLIENT_ID: 'li-id',
  LINKEDIN_CLIENT_SECRET: 'li-secret',
  DISCORD_CLIENT_ID: 'dc-id',
  DISCORD_CLIENT_SECRET: 'dc-secret',
  SALESFORCE_CLIENT_ID: 'sf-id',
  SALESFORCE_CLIENT_SECRET: 'sf-secret',
  NOTION_CLIENT_ID: 'nt-id',
  NOTION_CLIENT_SECRET: 'nt-secret',
  FIGMA_CLIENT_ID: 'fg-id',
  FIGMA_CLIENT_SECRET: 'fg-secret',
  LINEAR_CLIENT_ID: 'ln-id',
  LINEAR_CLIENT_SECRET: 'ln-secret',
  DROPBOX_CLIENT_ID: 'db-id',
  DROPBOX_CLIENT_SECRET: 'db-secret',
  ZOOM_CLIENT_ID: 'zm-id',
  ZOOM_CLIENT_SECRET: 'zm-secret',
  HUGGINGFACE_CLIENT_ID: 'hf-id',
  HUGGINGFACE_CLIENT_SECRET: 'hf-secret',
  VERCEL_CLIENT_ID: 'vc-id',
  VERCEL_CLIENT_SECRET: 'vc-secret',
  RAILWAY_CLIENT_ID: 'rw-id',
  RAILWAY_CLIENT_SECRET: 'rw-secret',
  HUBSPOT_CLIENT_ID: 'hs-id',
  HUBSPOT_CLIENT_SECRET: 'hs-secret',
  APPLE_CLIENT_ID: 'com.example.web',
  APPLE_PRIVATE_KEY: 'ap-key',
  APPLE_TEAM_ID: 'A1B2C3D4E5',
  APPLE_KEY_ID: 'ABC123DEFG',
  FACEBOOK_CLIENT_ID: 'fb-id',
  FACEBOOK_CLIENT_SECRET: 'fb-secret',
  TWITTER_CLIENT_ID: 'x-id',
  TWITTER_CLIENT_SECRET: 'x-secret',
  REDDIT_CLIENT_ID: 'rd-id',
  REDDIT_CLIENT_SECRET: 'rd-secret',
  SPOTIFY_CLIENT_ID: 'sp-id',
  SPOTIFY_CLIENT_SECRET: 'sp-secret',
  TWITCH_CLIENT_ID: 'tw-id',
  TWITCH_CLIENT_SECRET: 'tw-secret',
  TIKTOK_CLIENT_KEY: 'tt-key',
  TIKTOK_CLIENT_SECRET: 'tt-secret',
  ROBLOX_CLIENT_ID: 'rb-id',
  ROBLOX_CLIENT_SECRET: 'rb-secret',
};

describe('registry vocabulary', () => {
  it('lists every known provider in display order', () => {
    expect(PROVIDER_REGISTRY.map((p) => p.id)).toEqual([
      'github',
      'gitlab',
      'azure',
      'google',
      'okta',
      'aws',
      'keycloak',
      'oidc',
      'auth0',
      'line',
      'vk',
      'wechat',
      'atlassian',
      'bitbucket',
      'slack',
      'linkedin',
      'discord',
      'salesforce',
      'notion',
      'figma',
      'linear',
      'dropbox',
      'zoom',
      'huggingface',
      'vercel',
      'railway',
      'hubspot',
      'apple',
      'facebook',
      'twitter',
      'reddit',
      'spotify',
      'twitch',
      'tiktok',
      'roblox',
    ]);
  });

  it('carries the display labels the login/link surfaces render', () => {
    expect(getProviderDescriptor('github')?.label).toBe('GitHub');
    expect(getProviderDescriptor('gitlab')?.label).toBe('GitLab');
    expect(getProviderDescriptor('azure')?.label).toBe('Microsoft');
    expect(getProviderDescriptor('google')?.label).toBe('Google');
    expect(getProviderDescriptor('okta')?.label).toBe('Okta');
    expect(getProviderDescriptor('aws')?.label).toBe('AWS');
    expect(getProviderDescriptor('keycloak')?.label).toBe('Keycloak');
    expect(getProviderDescriptor('oidc')?.label).toBe('OIDC');
    expect(getProviderDescriptor('auth0')?.label).toBe('Auth0');
    expect(getProviderDescriptor('line')?.label).toBe('LINE');
    expect(getProviderDescriptor('vk')?.label).toBe('VK');
    expect(getProviderDescriptor('wechat')?.label).toBe('WeChat');
    expect(getProviderDescriptor('atlassian')?.label).toBe('Atlassian');
    expect(getProviderDescriptor('bitbucket')?.label).toBe('Bitbucket');
    expect(getProviderDescriptor('slack')?.label).toBe('Slack');
    expect(getProviderDescriptor('linkedin')?.label).toBe('LinkedIn');
    expect(getProviderDescriptor('discord')?.label).toBe('Discord');
    expect(getProviderDescriptor('salesforce')?.label).toBe('Salesforce');
    expect(getProviderDescriptor('notion')?.label).toBe('Notion');
    expect(getProviderDescriptor('figma')?.label).toBe('Figma');
    expect(getProviderDescriptor('linear')?.label).toBe('Linear');
    expect(getProviderDescriptor('dropbox')?.label).toBe('Dropbox');
    expect(getProviderDescriptor('zoom')?.label).toBe('Zoom');
    expect(getProviderDescriptor('huggingface')?.label).toBe('Hugging Face');
    expect(getProviderDescriptor('vercel')?.label).toBe('Vercel');
    expect(getProviderDescriptor('railway')?.label).toBe('Railway');
    expect(getProviderDescriptor('hubspot')?.label).toBe('HubSpot');
    expect(getProviderDescriptor('apple')?.label).toBe('Apple');
    expect(getProviderDescriptor('facebook')?.label).toBe('Facebook');
    expect(getProviderDescriptor('twitter')?.label).toBe('X (Twitter)');
    expect(getProviderDescriptor('reddit')?.label).toBe('Reddit');
    expect(getProviderDescriptor('spotify')?.label).toBe('Spotify');
    expect(getProviderDescriptor('twitch')?.label).toBe('Twitch');
    expect(getProviderDescriptor('tiktok')?.label).toBe('TikTok');
    expect(getProviderDescriptor('roblox')?.label).toBe('Roblox');
  });

  it('pins each available provider env contract', () => {
    expect(getProviderDescriptor('github')?.requiredEnvKeys).toEqual(['GITHUB_ID', 'GITHUB_SECRET']);
    expect(getProviderDescriptor('gitlab')?.requiredEnvKeys).toEqual([
      'GITLAB_CLIENT_ID',
      'GITLAB_CLIENT_SECRET',
    ]);
    expect(getProviderDescriptor('azure')?.requiredEnvKeys).toEqual([
      'AZURE_AD_CLIENT_ID',
      'AZURE_AD_CLIENT_SECRET',
    ]);
    expect(getProviderDescriptor('google')?.requiredEnvKeys).toEqual([
      'GOOGLE_CLIENT_ID',
      'GOOGLE_CLIENT_SECRET',
    ]);
    expect(getProviderDescriptor('okta')?.requiredEnvKeys).toEqual([
      'OKTA_CLIENT_ID',
      'OKTA_CLIENT_SECRET',
      'OKTA_ISSUER',
    ]);
    expect(getProviderDescriptor('aws')?.requiredEnvKeys).toEqual([
      'COGNITO_CLIENT_ID',
      'COGNITO_CLIENT_SECRET',
      'COGNITO_ISSUER',
    ]);
    expect(getProviderDescriptor('keycloak')?.requiredEnvKeys).toEqual([
      'KEYCLOAK_CLIENT_ID',
      'KEYCLOAK_CLIENT_SECRET',
      'KEYCLOAK_ISSUER',
    ]);
    expect(getProviderDescriptor('oidc')?.requiredEnvKeys).toEqual([
      'OIDC_CLIENT_ID',
      'OIDC_CLIENT_SECRET',
      'OIDC_ISSUER',
    ]);
    expect(getProviderDescriptor('auth0')?.requiredEnvKeys).toEqual([
      'AUTH0_CLIENT_ID',
      'AUTH0_CLIENT_SECRET',
      'AUTH0_ISSUER',
    ]);
    expect(getProviderDescriptor('line')?.requiredEnvKeys).toEqual([
      'LINE_CLIENT_ID',
      'LINE_CLIENT_SECRET',
    ]);
    expect(getProviderDescriptor('vk')?.requiredEnvKeys).toEqual([
      'VK_CLIENT_ID',
      'VK_CLIENT_SECRET',
    ]);
    expect(getProviderDescriptor('wechat')?.requiredEnvKeys).toEqual([
      'WECHAT_CLIENT_ID',
      'WECHAT_CLIENT_SECRET',
    ]);
    expect(getProviderDescriptor('atlassian')?.requiredEnvKeys).toEqual([
      'ATLASSIAN_CLIENT_ID',
      'ATLASSIAN_CLIENT_SECRET',
    ]);
    expect(getProviderDescriptor('bitbucket')?.requiredEnvKeys).toEqual([
      'BITBUCKET_CLIENT_ID',
      'BITBUCKET_CLIENT_SECRET',
    ]);
    expect(getProviderDescriptor('slack')?.requiredEnvKeys).toEqual([
      'SLACK_CLIENT_ID',
      'SLACK_CLIENT_SECRET',
    ]);
    expect(getProviderDescriptor('linkedin')?.requiredEnvKeys).toEqual([
      'LINKEDIN_CLIENT_ID',
      'LINKEDIN_CLIENT_SECRET',
    ]);
    expect(getProviderDescriptor('discord')?.requiredEnvKeys).toEqual([
      'DISCORD_CLIENT_ID',
      'DISCORD_CLIENT_SECRET',
    ]);
    // The Salesforce issuer is an optional extra, so it is not a required env key.
    expect(getProviderDescriptor('salesforce')?.requiredEnvKeys).toEqual([
      'SALESFORCE_CLIENT_ID',
      'SALESFORCE_CLIENT_SECRET',
    ]);
    expect(getProviderDescriptor('notion')?.requiredEnvKeys).toEqual([
      'NOTION_CLIENT_ID',
      'NOTION_CLIENT_SECRET',
    ]);
    expect(getProviderDescriptor('figma')?.requiredEnvKeys).toEqual([
      'FIGMA_CLIENT_ID',
      'FIGMA_CLIENT_SECRET',
    ]);
    expect(getProviderDescriptor('linear')?.requiredEnvKeys).toEqual([
      'LINEAR_CLIENT_ID',
      'LINEAR_CLIENT_SECRET',
    ]);
    expect(getProviderDescriptor('dropbox')?.requiredEnvKeys).toEqual([
      'DROPBOX_CLIENT_ID',
      'DROPBOX_CLIENT_SECRET',
    ]);
    expect(getProviderDescriptor('zoom')?.requiredEnvKeys).toEqual([
      'ZOOM_CLIENT_ID',
      'ZOOM_CLIENT_SECRET',
    ]);
    expect(getProviderDescriptor('huggingface')?.requiredEnvKeys).toEqual([
      'HUGGINGFACE_CLIENT_ID',
      'HUGGINGFACE_CLIENT_SECRET',
    ]);
    expect(getProviderDescriptor('vercel')?.requiredEnvKeys).toEqual([
      'VERCEL_CLIENT_ID',
      'VERCEL_CLIENT_SECRET',
    ]);
    expect(getProviderDescriptor('railway')?.requiredEnvKeys).toEqual([
      'RAILWAY_CLIENT_ID',
      'RAILWAY_CLIENT_SECRET',
    ]);
    expect(getProviderDescriptor('hubspot')?.requiredEnvKeys).toEqual([
      'HUBSPOT_CLIENT_ID',
      'HUBSPOT_CLIENT_SECRET',
    ]);
    // Apple (OLO-9.30): the sealed secret is the .p8 key; Team ID and Key ID are config extras.
    expect(getProviderDescriptor('apple')?.requiredEnvKeys).toEqual([
      'APPLE_CLIENT_ID',
      'APPLE_PRIVATE_KEY',
      'APPLE_TEAM_ID',
      'APPLE_KEY_ID',
    ]);
    expect(getProviderDescriptor('apple')?.requiredFields).toEqual([
      { field: 'client_id', kind: 'client_id', envKey: 'APPLE_CLIENT_ID' },
      { field: 'private_key', kind: 'client_secret', envKey: 'APPLE_PRIVATE_KEY' },
      { field: 'team_id', kind: 'config', envKey: 'APPLE_TEAM_ID' },
      { field: 'key_id', kind: 'config', envKey: 'APPLE_KEY_ID' },
    ]);
    expect(getProviderDescriptor('facebook')?.requiredEnvKeys).toEqual([
      'FACEBOOK_CLIENT_ID',
      'FACEBOOK_CLIENT_SECRET',
    ]);
    expect(getProviderDescriptor('twitter')?.requiredEnvKeys).toEqual([
      'TWITTER_CLIENT_ID',
      'TWITTER_CLIENT_SECRET',
    ]);
    expect(getProviderDescriptor('reddit')?.requiredEnvKeys).toEqual([
      'REDDIT_CLIENT_ID',
      'REDDIT_CLIENT_SECRET',
    ]);
    expect(getProviderDescriptor('spotify')?.requiredEnvKeys).toEqual([
      'SPOTIFY_CLIENT_ID',
      'SPOTIFY_CLIENT_SECRET',
    ]);
    expect(getProviderDescriptor('twitch')?.requiredEnvKeys).toEqual([
      'TWITCH_CLIENT_ID',
      'TWITCH_CLIENT_SECRET',
    ]);
    expect(getProviderDescriptor('tiktok')?.requiredEnvKeys).toEqual([
      'TIKTOK_CLIENT_KEY',
      'TIKTOK_CLIENT_SECRET',
    ]);
    expect(getProviderDescriptor('roblox')?.requiredEnvKeys).toEqual([
      'ROBLOX_CLIENT_ID',
      'ROBLOX_CLIENT_SECRET',
    ]);
  });

  it('marks google/okta/aws/keycloak/oidc/auth0/atlassian/bitbucket/slack/linkedin/discord/salesforce/notion/figma/linear/dropbox/zoom/huggingface/vercel/railway/hubspot/apple/facebook/twitter/reddit/spotify/tiktok/roblox/line/vk/wechat available (OLO-9.2–9.9, 9.17–9.34, 9.36, 9.37, 9.41–9.43); no coming-soon placeholders remain', () => {
    expect(getProviderDescriptor('google')?.status).toBe('available');
    expect(getProviderDescriptor('okta')?.status).toBe('available');
    expect(getProviderDescriptor('aws')?.status).toBe('available');
    expect(getProviderDescriptor('keycloak')?.status).toBe('available');
    expect(getProviderDescriptor('oidc')?.status).toBe('available');
    expect(getProviderDescriptor('auth0')?.status).toBe('available');
    expect(getProviderDescriptor('line')?.status).toBe('available');
    expect(getProviderDescriptor('vk')?.status).toBe('available');
    expect(getProviderDescriptor('wechat')?.status).toBe('available');
    expect(getProviderDescriptor('atlassian')?.status).toBe('available');
    expect(getProviderDescriptor('bitbucket')?.status).toBe('available');
    expect(getProviderDescriptor('slack')?.status).toBe('available');
    expect(getProviderDescriptor('linkedin')?.status).toBe('available');
    expect(getProviderDescriptor('discord')?.status).toBe('available');
    expect(getProviderDescriptor('salesforce')?.status).toBe('available');
    expect(getProviderDescriptor('notion')?.status).toBe('available');
    expect(getProviderDescriptor('figma')?.status).toBe('available');
    expect(getProviderDescriptor('linear')?.status).toBe('available');
    expect(getProviderDescriptor('dropbox')?.status).toBe('available');
    expect(getProviderDescriptor('zoom')?.status).toBe('available');
    expect(getProviderDescriptor('huggingface')?.status).toBe('available');
    expect(getProviderDescriptor('vercel')?.status).toBe('available');
    expect(getProviderDescriptor('railway')?.status).toBe('available');
    expect(getProviderDescriptor('hubspot')?.status).toBe('available');
    expect(getProviderDescriptor('apple')?.status).toBe('available');
    expect(getProviderDescriptor('facebook')?.status).toBe('available');
    expect(getProviderDescriptor('twitter')?.status).toBe('available');
    expect(getProviderDescriptor('reddit')?.status).toBe('available');
    expect(getProviderDescriptor('spotify')?.status).toBe('available');
    expect(getProviderDescriptor('tiktok')?.status).toBe('available');
    expect(getProviderDescriptor('roblox')?.status).toBe('available');
    expect(PROVIDER_REGISTRY.every((p) => p.status === 'available')).toBe(true);
  });

  it('returns undefined for unknown ids', () => {
    expect(getProviderDescriptor('not-a-provider')).toBeUndefined();
  });
});

describe('readEnvString', () => {
  it('returns the trimmed value when set', () => {
    expect(readEnvString({ KEY: '  value  ' }, 'KEY')).toBe('value');
  });

  it('treats unset, empty, and whitespace-only values as null', () => {
    expect(readEnvString({}, 'KEY')).toBeNull();
    expect(readEnvString({ KEY: '' }, 'KEY')).toBeNull();
    expect(readEnvString({ KEY: '   ' }, 'KEY')).toBeNull();
  });
});

describe('isProviderEnabled', () => {
  it('enables a provider when all of its env vars are set and non-blank', () => {
    expect(isProviderEnabled('github', ALL_ENABLED_ENV)).toBe(true);
    expect(isProviderEnabled('gitlab', ALL_ENABLED_ENV)).toBe(true);
    expect(isProviderEnabled('azure', ALL_ENABLED_ENV)).toBe(true);
    expect(isProviderEnabled('google', ALL_ENABLED_ENV)).toBe(true);
    expect(isProviderEnabled('okta', ALL_ENABLED_ENV)).toBe(true);
    expect(isProviderEnabled('aws', ALL_ENABLED_ENV)).toBe(true);
    expect(isProviderEnabled('keycloak', ALL_ENABLED_ENV)).toBe(true);
    expect(isProviderEnabled('oidc', ALL_ENABLED_ENV)).toBe(true);
    expect(isProviderEnabled('auth0', ALL_ENABLED_ENV)).toBe(true);
    expect(isProviderEnabled('line', ALL_ENABLED_ENV)).toBe(true);
    expect(isProviderEnabled('vk', ALL_ENABLED_ENV)).toBe(true);
    expect(isProviderEnabled('wechat', ALL_ENABLED_ENV)).toBe(true);
    expect(isProviderEnabled('atlassian', ALL_ENABLED_ENV)).toBe(true);
    expect(isProviderEnabled('bitbucket', ALL_ENABLED_ENV)).toBe(true);
    expect(isProviderEnabled('slack', ALL_ENABLED_ENV)).toBe(true);
    expect(isProviderEnabled('linkedin', ALL_ENABLED_ENV)).toBe(true);
    expect(isProviderEnabled('discord', ALL_ENABLED_ENV)).toBe(true);
    expect(isProviderEnabled('salesforce', ALL_ENABLED_ENV)).toBe(true);
    expect(isProviderEnabled('notion', ALL_ENABLED_ENV)).toBe(true);
    expect(isProviderEnabled('figma', ALL_ENABLED_ENV)).toBe(true);
    expect(isProviderEnabled('linear', ALL_ENABLED_ENV)).toBe(true);
    expect(isProviderEnabled('dropbox', ALL_ENABLED_ENV)).toBe(true);
    expect(isProviderEnabled('zoom', ALL_ENABLED_ENV)).toBe(true);
    expect(isProviderEnabled('huggingface', ALL_ENABLED_ENV)).toBe(true);
    expect(isProviderEnabled('vercel', ALL_ENABLED_ENV)).toBe(true);
    expect(isProviderEnabled('railway', ALL_ENABLED_ENV)).toBe(true);
    expect(isProviderEnabled('hubspot', ALL_ENABLED_ENV)).toBe(true);
    expect(isProviderEnabled('apple', ALL_ENABLED_ENV)).toBe(true);
    expect(isProviderEnabled('facebook', ALL_ENABLED_ENV)).toBe(true);
    expect(isProviderEnabled('twitter', ALL_ENABLED_ENV)).toBe(true);
    expect(isProviderEnabled('reddit', ALL_ENABLED_ENV)).toBe(true);
    expect(isProviderEnabled('spotify', ALL_ENABLED_ENV)).toBe(true);
    expect(isProviderEnabled('tiktok', ALL_ENABLED_ENV)).toBe(true);
    expect(isProviderEnabled('roblox', ALL_ENABLED_ENV)).toBe(true);
  });

  it('requires every env var — a missing secret disables the provider', () => {
    expect(isProviderEnabled('github', { GITHUB_ID: 'gh-id' })).toBe(false);
    expect(isProviderEnabled('gitlab', { GITLAB_CLIENT_SECRET: 'gl-secret' })).toBe(false);
  });

  it('treats blank values as unset', () => {
    expect(isProviderEnabled('github', { GITHUB_ID: 'gh-id', GITHUB_SECRET: '   ' })).toBe(false);
  });

  it('enables google once its client id + secret are set (OLO-9.2)', () => {
    expect(
      isProviderEnabled('google', { GOOGLE_CLIENT_ID: 'x', GOOGLE_CLIENT_SECRET: 'y' })
    ).toBe(true);
    expect(isProviderEnabled('google', { GOOGLE_CLIENT_ID: 'x' })).toBe(false);
  });

  it('requires the Okta issuer trio (OLO-9.3) — id+secret alone is not enough', () => {
    expect(
      isProviderEnabled('okta', {
        OKTA_CLIENT_ID: 'x',
        OKTA_CLIENT_SECRET: 'y',
        OKTA_ISSUER: 'https://acme.okta.com/oauth2/default',
      })
    ).toBe(true);
    expect(
      isProviderEnabled('okta', { OKTA_CLIENT_ID: 'x', OKTA_CLIENT_SECRET: 'y' })
    ).toBe(false);
  });

  it('requires the Cognito issuer trio (OLO-9.4) — id+secret alone is not enough', () => {
    expect(
      isProviderEnabled('aws', {
        COGNITO_CLIENT_ID: 'x',
        COGNITO_CLIENT_SECRET: 'y',
        COGNITO_ISSUER: 'https://cognito-idp.us-east-1.amazonaws.com/us-east-1_AbCdEf',
      })
    ).toBe(true);
    expect(
      isProviderEnabled('aws', { COGNITO_CLIENT_ID: 'x', COGNITO_CLIENT_SECRET: 'y' })
    ).toBe(false);
  });

  it('requires the Keycloak issuer trio (OLO-9.5) — id+secret alone is not enough', () => {
    expect(
      isProviderEnabled('keycloak', {
        KEYCLOAK_CLIENT_ID: 'x',
        KEYCLOAK_CLIENT_SECRET: 'y',
        KEYCLOAK_ISSUER: 'https://kc.example.com/realms/apiome',
      })
    ).toBe(true);
    expect(
      isProviderEnabled('keycloak', { KEYCLOAK_CLIENT_ID: 'x', KEYCLOAK_CLIENT_SECRET: 'y' })
    ).toBe(false);
  });

  it('requires the OIDC issuer trio (OLO-9.6) — id+secret alone is not enough', () => {
    expect(
      isProviderEnabled('oidc', {
        OIDC_CLIENT_ID: 'x',
        OIDC_CLIENT_SECRET: 'y',
        OIDC_ISSUER: 'https://auth.example.com',
      })
    ).toBe(true);
    expect(
      isProviderEnabled('oidc', { OIDC_CLIENT_ID: 'x', OIDC_CLIENT_SECRET: 'y' })
    ).toBe(false);
  });

  it('requires the Auth0 issuer trio (OLO-9.7) — id+secret alone is not enough', () => {
    expect(
      isProviderEnabled('auth0', {
        AUTH0_CLIENT_ID: 'x',
        AUTH0_CLIENT_SECRET: 'y',
        AUTH0_ISSUER: 'https://acme.auth0.com',
      })
    ).toBe(true);
    expect(
      isProviderEnabled('auth0', { AUTH0_CLIENT_ID: 'x', AUTH0_CLIENT_SECRET: 'y' })
    ).toBe(false);
    expect(
      isProviderEnabled('line', {
        LINE_CLIENT_ID: 'x',
        LINE_CLIENT_SECRET: 'y',
      })
    ).toBe(true);
    expect(isProviderEnabled('line', { LINE_CLIENT_ID: 'x' })).toBe(false);
    expect(
      isProviderEnabled('vk', {
        VK_CLIENT_ID: 'x',
        VK_CLIENT_SECRET: 'y',
      })
    ).toBe(true);
    expect(isProviderEnabled('vk', { VK_CLIENT_ID: 'x' })).toBe(false);
    expect(
      isProviderEnabled('wechat', {
        WECHAT_CLIENT_ID: 'x',
        WECHAT_CLIENT_SECRET: 'y',
      })
    ).toBe(true);
    expect(isProviderEnabled('wechat', { WECHAT_CLIENT_ID: 'x' })).toBe(false);
    expect(
      isProviderEnabled('atlassian', {
        ATLASSIAN_CLIENT_ID: 'x',
        ATLASSIAN_CLIENT_SECRET: 'y',
      })
    ).toBe(true);
    expect(isProviderEnabled('atlassian', { ATLASSIAN_CLIENT_ID: 'x' })).toBe(false);
    expect(
      isProviderEnabled('bitbucket', {
        BITBUCKET_CLIENT_ID: 'x',
        BITBUCKET_CLIENT_SECRET: 'y',
      })
    ).toBe(true);
    expect(isProviderEnabled('bitbucket', { BITBUCKET_CLIENT_ID: 'x' })).toBe(false);
    expect(isProviderEnabled('slack', { SLACK_CLIENT_ID: 'x', SLACK_CLIENT_SECRET: 'y' })).toBe(true);
    expect(isProviderEnabled('slack', { SLACK_CLIENT_SECRET: 'y' })).toBe(false);
    expect(
      isProviderEnabled('linkedin', { LINKEDIN_CLIENT_ID: 'x', LINKEDIN_CLIENT_SECRET: 'y' })
    ).toBe(true);
    expect(isProviderEnabled('linkedin', { LINKEDIN_CLIENT_ID: 'x' })).toBe(false);
    expect(
      isProviderEnabled('discord', { DISCORD_CLIENT_ID: 'x', DISCORD_CLIENT_SECRET: 'y' })
    ).toBe(true);
    expect(isProviderEnabled('discord', { DISCORD_CLIENT_SECRET: 'y' })).toBe(false);
    // Salesforce is enabled without an issuer (it defaults to login.salesforce.com).
    expect(
      isProviderEnabled('salesforce', { SALESFORCE_CLIENT_ID: 'x', SALESFORCE_CLIENT_SECRET: 'y' })
    ).toBe(true);
    expect(
      isProviderEnabled('salesforce', {
        SALESFORCE_CLIENT_ID: 'x',
        SALESFORCE_ISSUER: 'https://acme.my.salesforce.com',
      })
    ).toBe(false);
    expect(isProviderEnabled('notion', { NOTION_CLIENT_ID: 'x', NOTION_CLIENT_SECRET: 'y' })).toBe(
      true
    );
    expect(isProviderEnabled('notion', { NOTION_CLIENT_ID: 'x' })).toBe(false);
    expect(isProviderEnabled('figma', { FIGMA_CLIENT_ID: 'x', FIGMA_CLIENT_SECRET: 'y' })).toBe(
      true
    );
    expect(isProviderEnabled('figma', { FIGMA_CLIENT_ID: 'x' })).toBe(false);
    expect(isProviderEnabled('linear', { LINEAR_CLIENT_ID: 'x', LINEAR_CLIENT_SECRET: 'y' })).toBe(
      true
    );
    expect(isProviderEnabled('linear', { LINEAR_CLIENT_ID: 'x' })).toBe(false);
    expect(
      isProviderEnabled('dropbox', { DROPBOX_CLIENT_ID: 'x', DROPBOX_CLIENT_SECRET: 'y' })
    ).toBe(true);
    expect(isProviderEnabled('dropbox', { DROPBOX_CLIENT_ID: 'x' })).toBe(false);
    expect(isProviderEnabled('zoom', { ZOOM_CLIENT_ID: 'x', ZOOM_CLIENT_SECRET: 'y' })).toBe(true);
    expect(isProviderEnabled('zoom', { ZOOM_CLIENT_ID: 'x' })).toBe(false);
    expect(
      isProviderEnabled('huggingface', {
        HUGGINGFACE_CLIENT_ID: 'x',
        HUGGINGFACE_CLIENT_SECRET: 'y',
      })
    ).toBe(true);
    expect(isProviderEnabled('huggingface', { HUGGINGFACE_CLIENT_ID: 'x' })).toBe(false);
    expect(
      isProviderEnabled('vercel', { VERCEL_CLIENT_ID: 'x', VERCEL_CLIENT_SECRET: 'y' })
    ).toBe(true);
    expect(isProviderEnabled('vercel', { VERCEL_CLIENT_ID: 'x' })).toBe(false);
    expect(
      isProviderEnabled('railway', { RAILWAY_CLIENT_ID: 'x', RAILWAY_CLIENT_SECRET: 'y' })
    ).toBe(true);
    expect(isProviderEnabled('railway', { RAILWAY_CLIENT_ID: 'x' })).toBe(false);
    expect(
      isProviderEnabled('hubspot', { HUBSPOT_CLIENT_ID: 'x', HUBSPOT_CLIENT_SECRET: 'y' })
    ).toBe(true);
    expect(isProviderEnabled('hubspot', { HUBSPOT_CLIENT_ID: 'x' })).toBe(false);
    const apple = {
      APPLE_CLIENT_ID: 'x',
      APPLE_PRIVATE_KEY: 'k',
      APPLE_TEAM_ID: 't',
      APPLE_KEY_ID: 'i',
    };
    expect(isProviderEnabled('apple', apple)).toBe(true);
    // Every one of the four is required: the JWT cannot be signed without any of them.
    for (const key of Object.keys(apple)) {
      expect(isProviderEnabled('apple', { ...apple, [key]: '' })).toBe(false);
    }
    expect(
      isProviderEnabled('facebook', { FACEBOOK_CLIENT_ID: 'x', FACEBOOK_CLIENT_SECRET: 'y' })
    ).toBe(true);
    expect(isProviderEnabled('facebook', { FACEBOOK_CLIENT_ID: 'x' })).toBe(false);
    expect(
      isProviderEnabled('twitter', { TWITTER_CLIENT_ID: 'x', TWITTER_CLIENT_SECRET: 'y' })
    ).toBe(true);
    expect(isProviderEnabled('twitter', { TWITTER_CLIENT_ID: 'x' })).toBe(false);
    expect(
      isProviderEnabled('reddit', { REDDIT_CLIENT_ID: 'x', REDDIT_CLIENT_SECRET: 'y' })
    ).toBe(true);
    expect(isProviderEnabled('reddit', { REDDIT_CLIENT_ID: 'x' })).toBe(false);
    expect(
      isProviderEnabled('spotify', { SPOTIFY_CLIENT_ID: 'x', SPOTIFY_CLIENT_SECRET: 'y' })
    ).toBe(true);
    expect(isProviderEnabled('spotify', { SPOTIFY_CLIENT_ID: 'x' })).toBe(false);
    expect(
      isProviderEnabled('tiktok', { TIKTOK_CLIENT_KEY: 'x', TIKTOK_CLIENT_SECRET: 'y' })
    ).toBe(true);
    expect(isProviderEnabled('tiktok', { TIKTOK_CLIENT_KEY: 'x' })).toBe(false);
    expect(
      isProviderEnabled('roblox', { ROBLOX_CLIENT_ID: 'x', ROBLOX_CLIENT_SECRET: 'y' })
    ).toBe(true);
    expect(isProviderEnabled('roblox', { ROBLOX_CLIENT_ID: 'x' })).toBe(false);
  });

  it('never enables unknown ids', () => {
    expect(isProviderEnabled('not-a-provider', ALL_ENABLED_ENV)).toBe(false);
  });
});

describe('acceptance: env alone adds/removes providers everywhere', () => {
  it('renders exactly the enabled providers', () => {
    expect(enabledProviderIds(ALL_ENABLED_ENV)).toEqual([
      'github',
      'gitlab',
      'azure',
      'google',
      'okta',
      'aws',
      'keycloak',
      'oidc',
      'auth0',
      'line',
      'vk',
      'wechat',
      'atlassian',
      'bitbucket',
      'slack',
      'linkedin',
      'discord',
      'salesforce',
      'notion',
      'figma',
      'linear',
      'dropbox',
      'zoom',
      'huggingface',
      'vercel',
      'railway',
      'hubspot',
      'apple',
      'facebook',
      'twitter',
      'reddit',
      'spotify',
      'twitch',
      'tiktok',
      'roblox',
    ]);
    expect(enabledProviderIds({ GITHUB_ID: 'gh-id', GITHUB_SECRET: 'gh-secret' })).toEqual(['github']);
    expect(enabledProviderIds({})).toEqual([]);
  });

  it('disabling a provider via env removes it without code changes', () => {
    const withoutGitlab = { ...ALL_ENABLED_ENV, GITLAB_CLIENT_ID: '' };
    expect(enabledProviderIds(withoutGitlab)).toEqual([
      'github',
      'azure',
      'google',
      'okta',
      'aws',
      'keycloak',
      'oidc',
      'auth0',
      'line',
      'vk',
      'wechat',
      'atlassian',
      'bitbucket',
      'slack',
      'linkedin',
      'discord',
      'salesforce',
      'notion',
      'figma',
      'linear',
      'dropbox',
      'zoom',
      'huggingface',
      'vercel',
      'railway',
      'hubspot',
      'apple',
      'facebook',
      'twitter',
      'reddit',
      'spotify',
      'twitch',
      'tiktok',
      'roblox',
    ]);
  });

  it('enabledProviders preserves registry display order', () => {
    expect(enabledProviders(ALL_ENABLED_ENV).map((p) => p.id)).toEqual([
      'github',
      'gitlab',
      'azure',
      'google',
      'okta',
      'aws',
      'keycloak',
      'oidc',
      'auth0',
      'line',
      'vk',
      'wechat',
      'atlassian',
      'bitbucket',
      'slack',
      'linkedin',
      'discord',
      'salesforce',
      'notion',
      'figma',
      'linear',
      'dropbox',
      'zoom',
      'huggingface',
      'vercel',
      'railway',
      'hubspot',
      'apple',
      'facebook',
      'twitter',
      'reddit',
      'spotify',
      'twitch',
      'tiktok',
      'roblox',
    ]);
  });
});

describe('providerSummaries', () => {
  it('summarizes every registry entry with its enabled state, serializably', () => {
    const summaries = providerSummaries({ GITHUB_ID: 'gh-id', GITHUB_SECRET: 'gh-secret' });

    expect(summaries).toEqual([
      { id: 'github', label: 'GitHub', status: 'available', enabled: true },
      { id: 'gitlab', label: 'GitLab', status: 'available', enabled: false },
      { id: 'azure', label: 'Microsoft', status: 'available', enabled: false },
      { id: 'google', label: 'Google', status: 'available', enabled: false },
      { id: 'okta', label: 'Okta', status: 'available', enabled: false },
      { id: 'aws', label: 'AWS', status: 'available', enabled: false },
      { id: 'keycloak', label: 'Keycloak', status: 'available', enabled: false },
      { id: 'oidc', label: 'OIDC', status: 'available', enabled: false },
      { id: 'auth0', label: 'Auth0', status: 'available', enabled: false },
      { id: 'line', label: 'LINE', status: 'available', enabled: false },
      { id: 'vk', label: 'VK', status: 'available', enabled: false },
      { id: 'wechat', label: 'WeChat', status: 'available', enabled: false },
      { id: 'atlassian', label: 'Atlassian', status: 'available', enabled: false },
      { id: 'bitbucket', label: 'Bitbucket', status: 'available', enabled: false },
      { id: 'slack', label: 'Slack', status: 'available', enabled: false },
      { id: 'linkedin', label: 'LinkedIn', status: 'available', enabled: false },
      { id: 'discord', label: 'Discord', status: 'available', enabled: false },
      { id: 'salesforce', label: 'Salesforce', status: 'available', enabled: false },
      { id: 'notion', label: 'Notion', status: 'available', enabled: false },
      { id: 'figma', label: 'Figma', status: 'available', enabled: false },
      { id: 'linear', label: 'Linear', status: 'available', enabled: false },
      { id: 'dropbox', label: 'Dropbox', status: 'available', enabled: false },
      { id: 'zoom', label: 'Zoom', status: 'available', enabled: false },
      { id: 'huggingface', label: 'Hugging Face', status: 'available', enabled: false },
      { id: 'vercel', label: 'Vercel', status: 'available', enabled: false },
      { id: 'railway', label: 'Railway', status: 'available', enabled: false },
      { id: 'hubspot', label: 'HubSpot', status: 'available', enabled: false },
      { id: 'apple', label: 'Apple', status: 'available', enabled: false },
      { id: 'facebook', label: 'Facebook', status: 'available', enabled: false },
      { id: 'twitter', label: 'X (Twitter)', status: 'available', enabled: false },
      { id: 'reddit', label: 'Reddit', status: 'available', enabled: false },
      { id: 'spotify', label: 'Spotify', status: 'available', enabled: false },
      { id: 'twitch', label: 'Twitch', status: 'available', enabled: false },
      { id: 'tiktok', label: 'TikTok', status: 'available', enabled: false },
      { id: 'roblox', label: 'Roblox', status: 'available', enabled: false },
    ]);
    // Server → client props must survive serialization untouched.
    expect(JSON.parse(JSON.stringify(summaries))).toEqual(summaries);
  });

  it('overrides the oidc label from OIDC_DISPLAY_NAME when set (OLO-9.6)', () => {
    const summaries = providerSummaries({
      OIDC_DISPLAY_NAME: 'Authentik',
    });
    const oidc = summaries.find((s) => s.id === 'oidc');
    expect(oidc?.label).toBe('Authentik');
  });
});

describe('isEntraIdConfigured delegates to the registry (no env-contract drift)', () => {
  it('matches the registry verdict for configured and unconfigured envs', () => {
    expect(isEntraIdConfigured(ALL_ENABLED_ENV)).toBe(true);
    expect(isEntraIdConfigured({ AZURE_AD_CLIENT_ID: 'az-id' })).toBe(false);
    expect(isEntraIdConfigured({})).toBe(false);
  });
});

describe('route contracts (source level)', () => {
  const APP_ROOT = path.resolve(__dirname, '..', 'src', 'app');
  const read = (file: string) => fs.readFileSync(file, 'utf8');

  it('the auth route delegates to the Better Auth handler (no per-provider factories)', () => {
    const route = read(path.join(APP_ROOT, 'api', 'auth', '[...all]', 'route.ts'));
    expect(route).toContain('betterAuthHandler');
    expect(route).not.toContain('GithubProvider(');
    expect(route).not.toContain('GitlabProvider(');
  });

  it('the Better Auth provider set is built from the registry', () => {
    const providers = read(
      path.join(__dirname, '..', 'lib', 'auth', 'better-auth-oauth-providers.ts')
    );
    expect(providers).toContain('enabledProviders(');
  });

  // Every surface below reads enablement through the merged DB-over-env overlay (OLO-8.5), not raw
  // `process.env`, so a provider configured from the admin screen is honoured everywhere at once.
  it('the signup-intent route gates on registry enablement against the merged config', () => {
    const route = read(path.join(APP_ROOT, 'api', 'auth', 'signup-intent', 'route.ts'));
    expect(route).toContain('isProviderEnabled(provider, await resolveProviderEnv())');
  });

  it('the link route gates on registry enablement for every provider', () => {
    const route = read(path.join(APP_ROOT, 'api', 'auth', 'link', '[provider]', 'route.ts'));
    expect(route).toContain('isProviderEnabled(provider, await resolveProviderEnv())');
    expect(route).toContain('LINKABLE_PROVIDERS.has(provider)');
  });

  it('the login and linked-accounts pages resolve providers server-side', () => {
    const loginPage = read(path.join(APP_ROOT, 'login', 'page.tsx'));
    const linkedAccountsPage = read(
      path.join(APP_ROOT, 'ade', 'dashboard', 'linked-accounts', 'page.tsx')
    );
    expect(loginPage).toContain('providerSummaries(await resolveProviderEnv())');
    expect(linkedAccountsPage).toContain('providerSummaries(await resolveProviderEnv())');
  });
});
