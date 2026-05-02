import { resolveApiKeyFromEnv, resolveRestBaseUrl } from './auth.js';

/**
 * Typed entry point for objectified-rest. All HTTP traffic must originate here.
 */
export class RestClient {
  readonly baseUrl: string;

  private constructor(baseUrl: string) {
    this.baseUrl = baseUrl;
  }

  static fromEnv(): RestClient {
    return new RestClient(resolveRestBaseUrl());
  }

  /** Test / tooling helper (prefer {@link RestClient.fromEnv} in production). */
  static withBaseUrl(baseUrl: string): RestClient {
    return new RestClient(baseUrl.replace(/\/$/, ''));
  }

  /** Bearer token when MCP-1.3 wires env / headers into the client. */
  apiKey(): string | undefined {
    return resolveApiKeyFromEnv();
  }
}
