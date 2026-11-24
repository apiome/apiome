// pact-js provider verification (the Rust core): fetches the pacts to verify from Apiome with
// consumer-version selectors and publishes the result. Part of the Pact Broker conformance suite
// (PFX-1.8, #6921). The provider itself is the stub ../conformance.py serves.
import { Verifier } from '@pact-foundation/pact';

const providerBaseUrl = process.env.PROVIDER_BASE_URL;

await new Verifier({
  provider: 'ConformanceJsAPI',
  providerBaseUrl,
  // The stub always has order 1, so the state needs no set-up.
  stateHandlers: { 'order 1 exists': async () => {} },
  pactBrokerUrl: process.env.PACT_BROKER_BASE_URL,
  pactBrokerToken: process.env.PACT_BROKER_TOKEN,
  consumerVersionSelectors: [{ mainBranch: true }, { deployedOrReleased: true }],
  enablePending: true,
  publishVerificationResult: true,
  providerVersion: '1.0.0',
  providerVersionBranch: 'main',
  logLevel: 'warn',
}).verifyProvider();
console.log('pact-js provider: verified and published');
