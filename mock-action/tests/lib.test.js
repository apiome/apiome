'use strict';
/** Unit tests for the Apiome mock CI action helpers (#4748, PMR-3.1). */

const assert = require('node:assert/strict');
const path = require('node:path');
const { test } = require('node:test');

const {
  BROKER_BOOTSTRAP_ENV,
  BROKER_PASSWORD_ENV,
  CONTAINER_BUNDLE_PATH,
  CONTAINER_GRPC_PORT,
  CONTAINER_PORT,
  GRPC_PORT_ENV,
  PROTOCOLS,
  SECRET_ENV,
  checkBrokerInputs,
  conformanceArgs,
  containerName,
  dockerRunArgs,
  outputLine,
  parseBool,
  parseProtocols,
  parseReady,
  protocolEndpoints,
  resolveBrokerBootstrap,
  resolveBundlePath,
  resolveEnvName,
  resolveHost,
  resolveNetwork,
  resolvePort,
  resolveWait,
  serviceUrl,
  summaryMarkdown,
} = require('../lib');

const WORKSPACE = path.resolve('/workspace');

test('parseBool accepts the documented true spellings only', () => {
  for (const value of ['true', 'TRUE', ' 1 ', 'yes', 'on']) {
    assert.equal(parseBool(value), true, value);
  }
  for (const value of ['false', '0', 'no', '', undefined, 'maybe', 'truthy']) {
    assert.equal(parseBool(value), false, String(value));
  }
});

test('resolveBundlePath resolves workspace-relative and absolute paths inside the workspace', () => {
  assert.equal(resolveBundlePath('mock-bundle.json', WORKSPACE), path.join(WORKSPACE, 'mock-bundle.json'));
  assert.equal(resolveBundlePath('./dist/b.json', WORKSPACE), path.join(WORKSPACE, 'dist', 'b.json'));
  assert.equal(resolveBundlePath(path.join(WORKSPACE, 'b.json'), WORKSPACE), path.join(WORKSPACE, 'b.json'));
});

test('resolveBundlePath refuses paths that escape the workspace', () => {
  for (const value of ['../secrets.json', '../../etc/passwd', '/etc/passwd']) {
    assert.throws(() => resolveBundlePath(value, WORKSPACE), /outside the workspace/, value);
  }
});

test('resolveBundlePath requires a value', () => {
  assert.throws(() => resolveBundlePath('', WORKSPACE), /is required/);
  assert.throws(() => resolveBundlePath('   ', WORKSPACE), /is required/);
});

test('resolveBundlePath does not treat a sibling prefix as inside the workspace', () => {
  assert.throws(() => resolveBundlePath('/workspace-evil/b.json', WORKSPACE), /outside the workspace/);
});

test('resolveHost defaults to loopback and rejects malformed hosts', () => {
  assert.equal(resolveHost(''), '127.0.0.1');
  assert.equal(resolveHost(undefined), '127.0.0.1');
  assert.equal(resolveHost(' 0.0.0.0 '), '0.0.0.0');
  assert.throws(() => resolveHost('127.0.0.1 --privileged'), /not a valid host/);
});

test('resolvePort accepts 0 for auto-selection and rejects out-of-range values', () => {
  assert.equal(resolvePort(''), 0);
  assert.equal(resolvePort('8080'), 8080);
  assert.throws(() => resolvePort('-1'), /non-negative integer/);
  assert.throws(() => resolvePort('80 80'), /non-negative integer/);
  assert.throws(() => resolvePort('70000'), /between 0 and 65535/);
});

test('resolveWait requires a positive number of seconds', () => {
  assert.equal(resolveWait(''), 60);
  assert.equal(resolveWait('12.5'), 12.5);
  assert.throws(() => resolveWait('0'), /positive number/);
  assert.throws(() => resolveWait('soon'), /positive number/);
});

test('containerName is scoped to the run and sanitized', () => {
  assert.equal(containerName({ GITHUB_RUN_ID: '42' }, 'abcd'), 'apiome-mock-42-abcd');
  assert.equal(containerName({}, 'abcd'), 'apiome-mock-local-abcd');
  assert.equal(containerName({ GITHUB_RUN_ID: 'a/b;rm -rf' }, 'abcd'), 'apiome-mock-abrm-rf-abcd');
});

test('dockerRunArgs publishes the requested interface and mounts the bundle read-only', () => {
  const args = dockerRunArgs({
    name: 'mock-1',
    image: 'ghcr.io/apiome/apiome-mock:0.5.0',
    bundlePath: '/workspace/b.json',
    host: '127.0.0.1',
    port: 34567,
  });
  assert.deepEqual(args, [
    'run',
    '--detach',
    '--name',
    'mock-1',
    '--publish',
    `127.0.0.1:34567:${CONTAINER_PORT}`,
    '--volume',
    `/workspace/b.json:${CONTAINER_BUNDLE_PATH}:ro`,
    'ghcr.io/apiome/apiome-mock:0.5.0',
    'run',
  ]);
});

test('dockerRunArgs forwards the signing secret by name, never by value', () => {
  const args = dockerRunArgs({
    name: 'mock-1',
    image: 'img',
    bundlePath: '/workspace/b.json',
    host: '127.0.0.1',
    port: 1,
    hasSecret: true,
    requireSignature: true,
  });
  const envIndex = args.indexOf(SECRET_ENV);
  assert.ok(envIndex > 0, 'secret env var is passed');
  assert.equal(args[envIndex - 1], '--env');
  assert.ok(args.includes('APIOME_MOCK_REQUIRE_SIGNATURE=true'));
  // The value itself must never appear anywhere in the argument list.
  assert.ok(!args.some((arg) => arg.includes('=') && arg.startsWith(`${SECRET_ENV}=`)));
});

test('conformanceArgs runs the packaged corpus on the container loopback', () => {
  assert.deepEqual(conformanceArgs('mock-1'), [
    'exec',
    'mock-1',
    'apiome-mock',
    'conformance',
    '--base-url',
    `http://127.0.0.1:${CONTAINER_PORT}`,
  ]);
});

test('parseReady extracts the identity a job should record', () => {
  const identity = parseReady({
    status: 'ready',
    runtime: { name: 'apiome-mock', version: '0.5.0', mount: '/acme/petstore/1.0.0' },
    bundle: { digest: 'sha256:abc', tenant: 'acme', project: 'petstore', version: '1.0.0', signed: true },
  });
  assert.deepEqual(identity, {
    digest: 'sha256:abc',
    runtimeVersion: '0.5.0',
    mount: '/acme/petstore/1.0.0',
    tenant: 'acme',
    project: 'petstore',
    version: '1.0.0',
    signed: true,
  });
});

test('parseReady tolerates a root mount and missing fields', () => {
  assert.equal(parseReady({ runtime: { mount: '/' } }).mount, '');
  assert.equal(parseReady({}).digest, '');
  assert.equal(parseReady(null).runtimeVersion, '');
  assert.equal(parseReady({ runtime: { mount: '/acme/p/1.0.0/' } }).mount, '/acme/p/1.0.0');
});

test('serviceUrl joins the runtime root and its version mount', () => {
  assert.equal(serviceUrl('http://127.0.0.1:8775', '/acme/p/1.0.0'), 'http://127.0.0.1:8775/acme/p/1.0.0');
  assert.equal(serviceUrl('http://127.0.0.1:8775/', '/acme/p/1.0.0'), 'http://127.0.0.1:8775/acme/p/1.0.0');
  assert.equal(serviceUrl('http://127.0.0.1:8775', ''), 'http://127.0.0.1:8775');
});

test('summaryMarkdown reports the digests a reader needs to trust the run', () => {
  const markdown = summaryMarkdown({
    serviceUrl: 'http://127.0.0.1:8775/acme/petstore/1.0.0',
    image: 'ghcr.io/apiome/apiome-mock:0.5.0',
    runtimeVersion: '0.5.0',
    digest: 'sha256:abc',
    signed: false,
    tenant: 'acme',
    project: 'petstore',
    version: '1.0.0',
  });
  assert.match(markdown, /### Apiome mock runtime/);
  assert.match(markdown, /`sha256:abc`/);
  assert.match(markdown, /ghcr\.io\/apiome\/apiome-mock:0\.5\.0/);
  assert.match(markdown, /\| Bundle signed \| no \|/);
  assert.match(markdown, /acme \/ petstore \/ 1\.0\.0/);
});

test('summaryMarkdown says so when the runtime reported nothing', () => {
  const markdown = summaryMarkdown({ serviceUrl: 'http://127.0.0.1:1', image: 'img' });
  assert.match(markdown, /\(not reported\)/);
});

test('outputLine uses the heredoc form so a value cannot inject another output', () => {
  assert.equal(outputLine('service-url', 'http://x', 'DELIM'), 'service-url<<DELIM\nhttp://x\nDELIM\n');
  const injected = outputLine('a', 'x\nb=evil', 'DELIM');
  assert.equal(injected, 'a<<DELIM\nx\nb=evil\nDELIM\n');
});

// ---------------------------------------------------------------------------------------------
// Protocols (#5755, XPC-5.4)
// ---------------------------------------------------------------------------------------------

/** A /ready document from a runtime that serves every protocol (the XPC-5.2 shape). */
const ALL_SERVED = {
  status: 'ready',
  runtime: { mount: '/acme/shop/1.0.0' },
  protocols: {
    http: { served: true, path: '' },
    graphql: { served: true, path: '/graphql' },
    connect: { served: true, path: '' },
    grpc: { served: true, port: 8776 },
    events: { served: true },
  },
};

const CONTEXT = { serviceUrl: 'http://127.0.0.1:5000/acme/shop/1.0.0', host: '127.0.0.1', grpcPort: null, image: 'img:1' };

test('parseProtocols defaults to http and always includes it', () => {
  assert.deepEqual(parseProtocols(''), ['http']);
  assert.deepEqual(parseProtocols(undefined), ['http']);
  assert.deepEqual(parseProtocols('graphql,connect'), ['http', 'graphql', 'connect']);
});

test('parseProtocols accepts commas or spaces, any case, and de-duplicates in report order', () => {
  assert.deepEqual(parseProtocols(' Events  GRPC,graphql, graphql '), ['http', 'graphql', 'grpc', 'events']);
  assert.deepEqual(parseProtocols(PROTOCOLS.join(',')), PROTOCOLS);
});

test('parseProtocols names unknown protocols and the accepted values', () => {
  assert.throws(() => parseProtocols('graphql,soap,ws'), /names soap, ws; accepted values are http, graphql, connect, grpc, events/);
});

test('resolvePort names the input it validates', () => {
  assert.throws(() => resolvePort('x', 'grpc-port'), /Input "grpc-port" \(x\)/);
  assert.equal(resolvePort('', 'grpc-port'), 0);
});

test('resolveBrokerBootstrap accepts a host:port list and rejects anything else', () => {
  assert.equal(resolveBrokerBootstrap(''), '');
  assert.equal(resolveBrokerBootstrap(' redpanda:9092 , b-2.kafka:9093 '), 'redpanda:9092,b-2.kafka:9093');
  assert.throws(() => resolveBrokerBootstrap('redpanda'), /must be host:port/);
  assert.throws(() => resolveBrokerBootstrap('redpanda:99999'), /must be host:port/);
  assert.throws(() => resolveBrokerBootstrap('a:1;rm -rf /'), /must be host:port/);
});

test('resolveEnvName refuses what looks like a value instead of a name', () => {
  assert.equal(resolveEnvName(' BROKER_PASSWORD ', 'broker-password-env'), 'BROKER_PASSWORD');
  assert.equal(resolveEnvName('', 'broker-password-env'), '');
  assert.throws(() => resolveEnvName('hunter2!', 'broker-password-env'), /must be the name of an environment variable/);
  assert.throws(() => resolveEnvName('1ABC', 'broker-password-env'), /must be the name/);
});

test('resolveNetwork accepts Docker network names only', () => {
  assert.equal(resolveNetwork(''), '');
  assert.equal(resolveNetwork('apiome-ci'), 'apiome-ci');
  assert.throws(() => resolveNetwork('net --privileged'), /not a valid Docker network name/);
});

test('checkBrokerInputs fails events without a broker, with the fix in the message', () => {
  assert.throws(
    () => checkBrokerInputs(['http', 'events'], '', '', {}),
    /includes events, which needs a broker: set "broker-bootstrap"/,
  );
  assert.doesNotThrow(() => checkBrokerInputs(['http', 'events'], 'redpanda:9092', '', {}));
  assert.doesNotThrow(() => checkBrokerInputs(['http', 'graphql'], '', '', {}));
});

test('checkBrokerInputs requires a named password variable to be set, and a broker to go with it', () => {
  assert.throws(() => checkBrokerInputs(['http'], '', 'PW', { PW: 'x' }), /without "broker-bootstrap"/);
  assert.throws(() => checkBrokerInputs(['http', 'events'], 'redpanda:9092', 'PW', {}), /names PW, which is not set/);
  assert.doesNotThrow(() => checkBrokerInputs(['http', 'events'], 'redpanda:9092', 'PW', { PW: 'x' }));
});

test('dockerRunArgs adds nothing for an HTTP-only run', () => {
  const args = dockerRunArgs({ name: 'n', image: 'img:1', bundlePath: '/w/b.json', host: '127.0.0.1', port: 5000 });

  assert.equal(args.filter((arg) => arg === '--publish').length, 1);
  assert.ok(!args.includes('--network'));
  assert.ok(!args.some((arg) => arg.startsWith('APIOME_MOCK_BROKER') || arg.startsWith(GRPC_PORT_ENV)));
});

test('dockerRunArgs publishes the gRPC listener on the same interface and turns it on', () => {
  const args = dockerRunArgs({ name: 'n', image: 'img:1', bundlePath: '/w/b.json', host: '127.0.0.1', port: 5000, grpcPort: 5001 });

  assert.ok(args.includes(`127.0.0.1:5001:${CONTAINER_GRPC_PORT}`));
  assert.ok(args.includes(`${GRPC_PORT_ENV}=${CONTAINER_GRPC_PORT}`));
  assert.ok(args.indexOf('img:1') > args.indexOf(`${GRPC_PORT_ENV}=${CONTAINER_GRPC_PORT}`), 'options precede the image');
});

test('dockerRunArgs wires the broker and forwards its password by name only', () => {
  const args = dockerRunArgs({
    name: 'n',
    image: 'img:1',
    bundlePath: '/w/b.json',
    host: '127.0.0.1',
    port: 5000,
    brokerBootstrap: 'redpanda:9092',
    hasBrokerPassword: true,
    network: 'apiome-ci',
  });

  assert.ok(args.includes(`${BROKER_BOOTSTRAP_ENV}=redpanda:9092`));
  assert.ok(args.includes(BROKER_PASSWORD_ENV));
  assert.ok(!args.some((arg) => arg.startsWith(`${BROKER_PASSWORD_ENV}=`)), 'the password value never reaches argv');
  assert.equal(args[args.indexOf('--network') + 1], 'apiome-ci');
  assert.ok(args.indexOf('img:1') > args.indexOf('--network'));
});

test('protocolEndpoints hands out GraphQL and Connect URLs under the mount', () => {
  const endpoints = protocolEndpoints(ALL_SERVED, ['http', 'graphql', 'connect'], CONTEXT);

  assert.equal(endpoints.graphqlUrl, 'http://127.0.0.1:5000/acme/shop/1.0.0/graphql');
  assert.equal(endpoints.connectUrl, 'http://127.0.0.1:5000/acme/shop/1.0.0');
  assert.equal(endpoints.grpcUrl, '');
  assert.deepEqual(endpoints.served, PROTOCOLS);
});

test('protocolEndpoints leaves unrequested URLs empty and reports a gRPC host:port target', () => {
  const endpoints = protocolEndpoints(ALL_SERVED, ['http', 'grpc'], { ...CONTEXT, grpcPort: 5001 });

  assert.equal(endpoints.graphqlUrl, '');
  assert.equal(endpoints.connectUrl, '');
  assert.equal(endpoints.grpcUrl, '127.0.0.1:5001');
});

test('protocolEndpoints fails with the runtime reason for every protocol it does not serve', () => {
  const ready = {
    protocols: {
      http: { served: true, path: '' },
      graphql: { served: false, reason: 'graphql is hosted-only.' },
      connect: { served: false, reason: 'connect is hosted-only.' },
    },
  };

  assert.throws(
    () => protocolEndpoints(ready, ['http', 'graphql', 'connect', 'grpc'], CONTEXT),
    (error) =>
      /cannot serve every requested protocol/.test(error.message) &&
      error.message.includes('graphql: graphql is hosted-only.') &&
      error.message.includes('connect: connect is hosted-only.') &&
      error.message.includes('grpc: not served by this runtime.'),
  );
});

test('protocolEndpoints treats an image without a protocol report as HTTP-only', () => {
  const legacy = { status: 'ready', runtime: {} };

  assert.deepEqual(protocolEndpoints(legacy, ['http'], CONTEXT).served, ['http']);
  assert.throws(() => protocolEndpoints(legacy, ['http', 'graphql'], CONTEXT), /img:1 does not report protocol support/);
});

test('protocolEndpoints reports served protocols even when they were not requested', () => {
  assert.deepEqual(protocolEndpoints(ALL_SERVED, ['http'], CONTEXT).served, PROTOCOLS);
});

test('summaryMarkdown lists served protocols and the endpoints the job asked for', () => {
  const markdown = summaryMarkdown({
    serviceUrl: 'http://127.0.0.1:5000',
    image: 'img:1',
    protocolsServed: ['http', 'graphql'],
    graphqlUrl: 'http://127.0.0.1:5000/graphql',
    connectUrl: '',
    grpcUrl: '',
  });

  assert.match(markdown, /\| Protocols served \| http, graphql \|/);
  assert.match(markdown, /\| GraphQL URL \| http:\/\/127\.0\.0\.1:5000\/graphql \|/);
  assert.doesNotMatch(markdown, /Connect URL|gRPC target/);
});
