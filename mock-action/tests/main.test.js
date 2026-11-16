'use strict';
/**
 * Smoke tests for the action entrypoints (#4748, PMR-3.1).
 *
 * `node --check` only parses a file: it cannot catch a helper that is used but never imported.
 * These tests actually execute `main.js` and `post.js` in a child process, so the module graph and
 * the paths that run before Docker is ever contacted are exercised for real.
 */

const assert = require('node:assert/strict');
const path = require('node:path');
const { execFileSync } = require('node:child_process');
const { test } = require('node:test');

const ACTION_DIR = path.resolve(__dirname, '..');

/**
 * Run one of the action scripts and capture its outcome.
 *
 * @param {string} script File name inside the action directory.
 * @param {Record<string, string>} env Environment overrides.
 * @returns {{status: number, output: string}} Exit status and combined output.
 */
function runScript(script, env) {
  try {
    const output = execFileSync(process.execPath, [path.join(ACTION_DIR, script)], {
      env: { PATH: process.env.PATH, ...env },
      encoding: 'utf8',
      stdio: ['ignore', 'pipe', 'pipe'],
    });
    return { status: 0, output };
  } catch (error) {
    return {
      status: error.status ?? 1,
      output: `${error.stdout ?? ''}${error.stderr ?? ''}`,
    };
  }
}

test('main.js fails cleanly when no bundle is given', () => {
  const result = runScript('main.js', { GITHUB_WORKSPACE: ACTION_DIR });

  assert.equal(result.status, 1);
  assert.match(result.output, /Input "bundle" is required/);
});

test('main.js refuses a bundle outside the workspace before touching Docker', () => {
  const result = runScript('main.js', {
    GITHUB_WORKSPACE: ACTION_DIR,
    INPUT_BUNDLE: '../../etc/passwd',
  });

  assert.equal(result.status, 1);
  assert.match(result.output, /outside the workspace/);
});

test('main.js reports a bundle path that does not exist', () => {
  const result = runScript('main.js', {
    GITHUB_WORKSPACE: ACTION_DIR,
    INPUT_BUNDLE: 'no-such-bundle.json',
  });

  assert.equal(result.status, 1);
  assert.match(result.output, /Bundle not found at /);
});

test('main.js validates its numeric inputs', () => {
  const result = runScript('main.js', {
    GITHUB_WORKSPACE: ACTION_DIR,
    INPUT_BUNDLE: 'package.json',
    INPUT_PORT: 'eighty',
  });

  assert.equal(result.status, 1);
  assert.match(result.output, /Input "port" \(eighty\) must be a non-negative integer/);
});

test('post.js is a no-op when no container was started', () => {
  const result = runScript('post.js', {});

  assert.equal(result.status, 0);
  assert.equal(result.output.trim(), '');
});

// ---------------------------------------------------------------------------------------------
// Protocols, end to end through main.js (#5755, XPC-5.4)
//
// A stub `docker` on PATH records its argv and reports the container as running; a local HTTP
// server stands in for the runtime's /ready on the fixed port the step is told to publish. That
// exercises input checks, argv construction, the readiness poll and the outputs for real, with
// no Docker daemon.
// ---------------------------------------------------------------------------------------------

const fs = require('node:fs');
const http = require('node:http');
const os = require('node:os');
const { spawn } = require('node:child_process');

/**
 * Create a temporary directory holding a stub `docker` executable that logs every call.
 *
 * @returns {{dir: string, log: string}} The stub directory (prepend to PATH) and its call log.
 */
function stubDocker() {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'mock-action-docker-'));
  const log = path.join(dir, 'calls.log');
  fs.writeFileSync(
    path.join(dir, 'docker'),
    `#!/bin/sh\necho "$@" >> "${log}"\nif [ "$1" = inspect ]; then echo true; fi\nexit 0\n`,
    { mode: 0o755 },
  );
  return { dir, log };
}

/**
 * Serve a fixed /ready document on an ephemeral loopback port.
 *
 * @param {any} ready The document to answer /ready with.
 * @returns {Promise<{port: number, close: () => Promise<void>}>} The listening port and a closer.
 */
function serveReady(ready) {
  const server = http.createServer((request, response) => {
    response.writeHead(request.url === '/ready' ? 200 : 404, { 'content-type': 'application/json' });
    response.end(JSON.stringify(ready));
  });
  return new Promise((resolve) => {
    server.listen(0, '127.0.0.1', () =>
      resolve({ port: server.address().port, close: () => new Promise((done) => server.close(done)) }),
    );
  });
}

/**
 * Run main.js asynchronously (the /ready server lives in this process) and collect its outputs.
 *
 * @param {Record<string, string>} env Inputs and environment.
 * @param {string} dockerDir Directory holding the stub `docker`.
 * @returns {Promise<{status: number, output: string, outputs: Record<string, string>}>} The outcome.
 */
function runMain(env, dockerDir) {
  const outputFile = path.join(dockerDir, 'outputs.txt');
  fs.writeFileSync(outputFile, '');
  return new Promise((resolve) => {
    const child = spawn(process.execPath, [path.join(ACTION_DIR, 'main.js')], {
      env: {
        PATH: `${dockerDir}${path.delimiter}${process.env.PATH}`,
        GITHUB_WORKSPACE: ACTION_DIR,
        GITHUB_OUTPUT: outputFile,
        INPUT_BUNDLE: 'package.json',
        INPUT_PULL: 'false',
        INPUT_WAIT: '5',
        ...env,
      },
    });
    let output = '';
    child.stdout.on('data', (chunk) => (output += chunk));
    child.stderr.on('data', (chunk) => (output += chunk));
    child.on('close', (status) => {
      const outputs = {};
      for (const match of fs.readFileSync(outputFile, 'utf8').matchAll(/^([\w-]+)<<(\S+)\n([\s\S]*?)\n\2$/gm)) {
        outputs[match[1]] = match[3];
      }
      resolve({ status, output, outputs });
    });
  });
}

const SERVES_ALL = {
  status: 'ready',
  runtime: { version: '9.9.9', mount: '/acme/shop/1.0.0' },
  bundle: { digest: 'sha256:abc' },
  protocols: {
    http: { served: true, path: '' },
    graphql: { served: true, path: '/graphql' },
    connect: { served: true, path: '' },
    grpc: { served: false, reason: 'gRPC listener is off.' },
    events: { served: false, reason: 'broker: absent' },
  },
};

test('protocols: graphql,connect gets both URLs and the served list', async () => {
  const docker = stubDocker();
  const runtime = await serveReady(SERVES_ALL);
  try {
    const result = await runMain({ INPUT_PORT: String(runtime.port), INPUT_PROTOCOLS: 'graphql,connect' }, docker.dir);
    const base = `http://127.0.0.1:${runtime.port}/acme/shop/1.0.0`;

    assert.equal(result.status, 0, result.output);
    assert.equal(result.outputs['service-url'], base);
    assert.equal(result.outputs['graphql-url'], `${base}/graphql`);
    assert.equal(result.outputs['connect-url'], base);
    assert.equal(result.outputs['grpc-url'], '');
    assert.equal(result.outputs['protocols-served'], 'http,graphql,connect');
  } finally {
    await runtime.close();
  }
});

test('a protocol the runtime does not serve fails the step with its reason', async () => {
  const docker = stubDocker();
  const runtime = await serveReady({ ...SERVES_ALL, protocols: { http: { served: true, path: '' } } });
  try {
    const result = await runMain({ INPUT_PORT: String(runtime.port), INPUT_PROTOCOLS: 'graphql' }, docker.dir);

    assert.equal(result.status, 1);
    assert.match(result.output, /cannot serve every requested protocol/);
    assert.match(result.output, /graphql: not served by this runtime/);
    assert.equal(result.outputs['service-url'], undefined, 'no URL is handed out for a refused run');
  } finally {
    await runtime.close();
  }
});

test('events without broker-bootstrap fails before Docker is touched', async () => {
  const docker = stubDocker();
  const result = await runMain({ INPUT_PROTOCOLS: 'events' }, docker.dir);

  assert.equal(result.status, 1);
  assert.match(result.output, /includes events, which needs a broker: set "broker-bootstrap"/);
  assert.equal(fs.existsSync(docker.log), false, 'docker was never called');
});

test('grpc and broker inputs reach the container without the password on argv', async () => {
  const docker = stubDocker();
  const runtime = await serveReady({
    ...SERVES_ALL,
    protocols: { ...SERVES_ALL.protocols, grpc: { served: true, port: 8776 }, events: { served: true } },
  });
  try {
    const result = await runMain(
      {
        INPUT_PORT: String(runtime.port),
        INPUT_PROTOCOLS: 'grpc events',
        INPUT_GRPC_PORT: '50123',
        INPUT_BROKER_BOOTSTRAP: 'redpanda:9092',
        INPUT_BROKER_PASSWORD_ENV: 'MY_BROKER_PASSWORD',
        INPUT_NETWORK: 'apiome-ci',
        MY_BROKER_PASSWORD: 'super-secret-value',
      },
      docker.dir,
    );
    const calls = fs.readFileSync(docker.log, 'utf8');

    assert.equal(result.status, 0, result.output);
    assert.equal(result.outputs['grpc-url'], '127.0.0.1:50123');
    assert.equal(result.outputs['protocols-served'], 'http,graphql,connect,grpc,events');
    assert.match(calls, /--publish 127\.0\.0\.1:50123:8776/);
    assert.match(calls, /APIOME_MOCK_BROKER_BOOTSTRAP=redpanda:9092/);
    assert.match(calls, /--network apiome-ci/);
    assert.doesNotMatch(calls, /super-secret-value/);
  } finally {
    await runtime.close();
  }
});
