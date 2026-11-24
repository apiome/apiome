// pact-js consumer test (PactV3): writes ./pacts/ConformanceJsWeb-ConformanceJsAPI.json.
// Part of the Pact Broker conformance suite (PFX-1.8, #6921); ../conformance.py publishes the
// file with the pact-broker CLI, because pact-js has no publisher of its own since v10.
import { fileURLToPath } from 'node:url';
import { MatchersV3, PactV3 } from '@pact-foundation/pact';

const pact = new PactV3({
  consumer: 'ConformanceJsWeb',
  provider: 'ConformanceJsAPI',
  dir: fileURLToPath(new URL('./pacts', import.meta.url)),
  logLevel: 'warn',
});

pact
  .given('order 1 exists')
  .uponReceiving('a request for order 1')
  .withRequest({ method: 'GET', path: '/orders/1' })
  .willRespondWith({
    status: 200,
    headers: { 'Content-Type': 'application/json' },
    body: MatchersV3.like({ id: 1, status: 'open' }),
  });

await pact.executeTest(async (mockServer) => {
  const response = await fetch(`${mockServer.url}/orders/1`);
  const order = await response.json();
  if (response.status !== 200 || order.id !== 1) {
    throw new Error(`unexpected response ${response.status} ${JSON.stringify(order)}`);
  }
});
console.log('pact-js consumer: pact written');
