'use strict';
/**
 * Pure helpers for the Apiome mock CI action (#4748, PMR-3.1).
 *
 * Everything here is free of I/O and process state so it can be unit-tested directly: argument
 * construction, workspace-relative path safety, readiness parsing, and the strings the action
 * writes to GitHub outputs and the job summary. `main.js` and `post.js` hold the side effects.
 */

const path = require('path');

/** Port the runtime listens on inside the container image. */
const CONTAINER_PORT = 8775;

/** Path the image expects a mounted bundle at (its documented default). */
const CONTAINER_BUNDLE_PATH = '/bundle/mock-bundle.json';

/** Environment variable carrying the bundle signing secret into the container. */
const SECRET_ENV = 'APIOME_MOCK_BUNDLE_SECRET';

/** Port the runtime's opt-in native gRPC listener binds inside the container (XPC-5.2). */
const CONTAINER_GRPC_PORT = 8776;

/** Environment variable that turns the runtime's native gRPC listener on, at a container port. */
const GRPC_PORT_ENV = 'APIOME_MOCK_GRPC_PORT';

/** Environment variable naming the broker the runtime publishes event channels through. */
const BROKER_BOOTSTRAP_ENV = 'APIOME_MOCK_BROKER_BOOTSTRAP';

/** Environment variable carrying the broker password into the container — env only, never a flag. */
const BROKER_PASSWORD_ENV = 'APIOME_MOCK_BROKER_PASSWORD';

/**
 * Protocol ids the `protocols` input accepts, in the order the runtime reports them on `/ready`
 * (`apiome_mock.protocol_support.PROTOCOL_IDS`). `events` covers WebSocket/SSE and broker channels.
 */
const PROTOCOLS = ['http', 'graphql', 'connect', 'grpc', 'events'];

/**
 * Interpret a GitHub Action boolean input.
 *
 * Action inputs are always strings, and an unset input arrives as "". Anything other than a
 * recognized true value is false, so a typo never silently enables a behavior.
 *
 * @param {string|undefined} value Raw input value.
 * @returns {boolean} Whether the input reads as true.
 */
function parseBool(value) {
  return ['true', '1', 'yes', 'on'].includes(String(value ?? '').trim().toLowerCase());
}

/**
 * Resolve the bundle path and refuse anything outside the workspace.
 *
 * A workflow controls this input, but it is still an untrusted string on a shared runner: without
 * this check a bundle input of `../../.ssh/id_rsa` would be bind-mounted into a container.
 *
 * @param {string} input Raw `bundle` input (workspace-relative or absolute).
 * @param {string} workspace Absolute path of the checked-out workspace.
 * @returns {string} The absolute bundle path.
 * @throws {Error} When the input is empty or resolves outside the workspace.
 */
function resolveBundlePath(input, workspace) {
  const raw = String(input ?? '').trim();
  if (!raw) {
    throw new Error('Input "bundle" is required: give the path of the mock bundle to serve.');
  }
  const root = path.resolve(workspace);
  const resolved = path.resolve(root, raw);
  if (resolved !== root && !resolved.startsWith(root + path.sep)) {
    throw new Error(`Input "bundle" (${raw}) resolves outside the workspace and was refused.`);
  }
  return resolved;
}

/**
 * Validate a published host interface.
 *
 * @param {string} value Raw `host` input.
 * @returns {string} The host to publish on (defaults to loopback).
 * @throws {Error} When the value contains characters that are not host-shaped.
 */
function resolveHost(value) {
  const host = String(value ?? '').trim() || '127.0.0.1';
  if (!/^[A-Za-z0-9.:_-]+$/.test(host)) {
    throw new Error(`Input "host" (${host}) is not a valid host address.`);
  }
  return host;
}

/**
 * Validate a requested host port.
 *
 * @param {string|number} value Raw port input; 0 means "pick a free port".
 * @param {string} [name] Input name used in error messages (`port` or `grpc-port`).
 * @returns {number} The requested port.
 * @throws {Error} When the value is not an integer in range.
 */
function resolvePort(value, name = 'port') {
  const raw = String(value ?? '').trim() || '0';
  if (!/^\d+$/.test(raw)) {
    throw new Error(`Input "${name}" (${raw}) must be a non-negative integer.`);
  }
  const port = Number(raw);
  if (port > 65535) {
    throw new Error(`Input "${name}" (${raw}) must be between 0 and 65535.`);
  }
  return port;
}

/**
 * Parse the `protocols` input into a de-duplicated list of protocol ids.
 *
 * `http` is always served (it is the listener everything else rides on), so it is always in the
 * result whether or not it was named.
 *
 * @param {string|undefined} value Raw `protocols` input: comma- or whitespace-separated ids.
 * @returns {string[]} Requested protocol ids, in {@link PROTOCOLS} order.
 * @throws {Error} When an id is not one of {@link PROTOCOLS}.
 */
function parseProtocols(value) {
  const requested = String(value ?? '')
    .split(/[\s,]+/)
    .map((entry) => entry.trim().toLowerCase())
    .filter(Boolean);
  const unknown = requested.filter((entry) => !PROTOCOLS.includes(entry));
  if (unknown.length) {
    throw new Error(`Input "protocols" names ${unknown.join(', ')}; accepted values are ${PROTOCOLS.join(', ')}.`);
  }
  return PROTOCOLS.filter((protocol) => protocol === 'http' || requested.includes(protocol));
}

/**
 * Validate the `broker-bootstrap` input: a comma-separated list of `host:port` entries.
 *
 * @param {string|undefined} value Raw input.
 * @returns {string} The normalized bootstrap list, or "" when none was given.
 * @throws {Error} When an entry is not host:port shaped.
 */
function resolveBrokerBootstrap(value) {
  const entries = String(value ?? '')
    .split(',')
    .map((entry) => entry.trim())
    .filter(Boolean);
  for (const entry of entries) {
    if (!/^[A-Za-z0-9._-]+:\d{1,5}$/.test(entry) || Number(entry.split(':').pop()) > 65535) {
      throw new Error(`Input "broker-bootstrap" entry (${entry}) must be host:port.`);
    }
  }
  return entries.join(',');
}

/**
 * Validate an input that names an environment variable (never its value).
 *
 * @param {string|undefined} value Raw input.
 * @param {string} name Input name used in error messages.
 * @returns {string} The variable name, or "" when none was given.
 * @throws {Error} When the value is not a valid environment variable name.
 */
function resolveEnvName(value, name) {
  const raw = String(value ?? '').trim();
  if (raw && !/^[A-Za-z_][A-Za-z0-9_]*$/.test(raw)) {
    throw new Error(`Input "${name}" (${raw}) must be the name of an environment variable, not its value.`);
  }
  return raw;
}

/**
 * Validate a Docker network name for the `network` input.
 *
 * @param {string|undefined} value Raw input.
 * @returns {string} The network name, or "" to use Docker's default bridge.
 * @throws {Error} When the value contains characters Docker does not allow in a network name.
 */
function resolveNetwork(value) {
  const raw = String(value ?? '').trim();
  if (raw && !/^[A-Za-z0-9][A-Za-z0-9_.-]*$/.test(raw)) {
    throw new Error(`Input "network" (${raw}) is not a valid Docker network name.`);
  }
  return raw;
}

/**
 * Check the broker inputs against the requested protocols, before anything is started.
 *
 * Event channels publish through a broker the job provides (the Action stays single-container);
 * asking for `events` without one is a configuration mistake the step reports immediately rather
 * than a runtime that silently serves nothing.
 *
 * @param {string[]} protocols Requested protocol ids (from {@link parseProtocols}).
 * @param {string} bootstrap Normalized `broker-bootstrap` value.
 * @param {string} passwordEnv Name of the variable holding the broker password, or "".
 * @param {Record<string, string|undefined>} env Step environment the password is read from.
 * @throws {Error} When `events` is requested without a broker, or a named password is unset.
 */
function checkBrokerInputs(protocols, bootstrap, passwordEnv, env) {
  if (protocols.includes('events') && !bootstrap) {
    throw new Error(
      'Input "protocols" includes events, which needs a broker: set "broker-bootstrap" to the ' +
        'broker started for this job (see the README broker recipe), or drop events.',
    );
  }
  if (passwordEnv && !bootstrap) {
    throw new Error('Input "broker-password-env" is set without "broker-bootstrap"; set both or neither.');
  }
  if (passwordEnv && !String(env[passwordEnv] ?? '')) {
    throw new Error(`Input "broker-password-env" names ${passwordEnv}, which is not set in this step's env.`);
  }
}

/**
 * Validate the readiness wait.
 *
 * @param {string|number} value Raw `wait` input, in seconds.
 * @returns {number} Seconds to wait for readiness.
 * @throws {Error} When the value is not a positive number.
 */
function resolveWait(value) {
  const seconds = Number(String(value ?? '').trim() || '60');
  if (!Number.isFinite(seconds) || seconds <= 0) {
    throw new Error(`Input "wait" (${value}) must be a positive number of seconds.`);
  }
  return seconds;
}

/**
 * Build a container name that is unique per job and per action step.
 *
 * @param {Record<string, string|undefined>} env Process environment (GitHub run identifiers).
 * @param {string} suffix Random suffix, so two steps in one job never collide.
 * @returns {string} The container name.
 */
function containerName(env, suffix) {
  const run = String(env.GITHUB_RUN_ID ?? 'local').replace(/[^A-Za-z0-9_.-]/g, '');
  return `apiome-mock-${run || 'local'}-${suffix}`;
}

/**
 * Build the `docker run` argument list that starts the runtime.
 *
 * The bundle is mounted read-only, the port is published on the requested interface (loopback by
 * default, so the mock is reachable from the job and from nothing else), and the signing secret —
 * when configured — is forwarded **by name**: a value on a command line is readable by every
 * process on the runner through the process table.
 *
 * @param {object} options Start options.
 * @param {string} options.name Container name.
 * @param {string} options.image Runtime image reference.
 * @param {string} options.bundlePath Absolute host path of the bundle.
 * @param {string} options.host Host interface to publish on.
 * @param {number} options.port Host port to publish.
 * @param {boolean} [options.requireSignature] Refuse an unsigned bundle.
 * @param {boolean} [options.hasSecret] Whether a signing secret is configured.
 * @param {number|null} [options.grpcPort] Host port for the native gRPC listener; null leaves it off.
 * @param {string} [options.brokerBootstrap] Broker bootstrap list for event channels, or "".
 * @param {boolean} [options.hasBrokerPassword] Whether a broker password is forwarded (by name).
 * @param {string} [options.network] Docker network to attach to (where the job's broker runs), or "".
 * @returns {string[]} Arguments for `docker`.
 */
function dockerRunArgs({
  name,
  image,
  bundlePath,
  host,
  port,
  requireSignature = false,
  hasSecret = false,
  grpcPort = null,
  brokerBootstrap = '',
  hasBrokerPassword = false,
  network = '',
}) {
  const args = [
    'run',
    '--detach',
    '--name',
    name,
    '--publish',
    `${host}:${port}:${CONTAINER_PORT}`,
    '--volume',
    `${bundlePath}:${CONTAINER_BUNDLE_PATH}:ro`,
  ];
  if (grpcPort !== null) {
    args.push('--publish', `${host}:${grpcPort}:${CONTAINER_GRPC_PORT}`, '--env', `${GRPC_PORT_ENV}=${CONTAINER_GRPC_PORT}`);
  }
  if (network) {
    args.push('--network', network);
  }
  if (hasSecret) {
    args.push('--env', SECRET_ENV);
  }
  if (brokerBootstrap) {
    args.push('--env', `${BROKER_BOOTSTRAP_ENV}=${brokerBootstrap}`);
  }
  if (hasBrokerPassword) {
    // By name, like the signing secret: a value on argv is readable through the process table.
    args.push('--env', BROKER_PASSWORD_ENV);
  }
  if (requireSignature) {
    args.push('--env', 'APIOME_MOCK_REQUIRE_SIGNATURE=true');
  }
  args.push(image, 'run');
  return args;
}

/**
 * Build the `docker exec` argument list that runs the shared corpus inside the started container.
 *
 * The image carries both the runtime and the corpus, so the check needs nothing mounted and no
 * network egress — it addresses the runtime on the container's own loopback interface.
 *
 * @param {string} container Container name.
 * @returns {string[]} Arguments for `docker`.
 */
function conformanceArgs(container) {
  return ['exec', container, 'apiome-mock', 'conformance', '--base-url', `http://127.0.0.1:${CONTAINER_PORT}`];
}

/**
 * Extract the identity a job should record from the runtime's `/ready` document.
 *
 * @param {any} document Parsed `/ready` response.
 * @returns {{digest: string, runtimeVersion: string, mount: string, tenant: string, project: string, version: string, signed: boolean}}
 *   The runtime and bundle identity, with empty strings for anything the runtime did not report.
 */
function parseReady(document) {
  const runtime = (document && document.runtime) || {};
  const bundle = (document && document.bundle) || {};
  const mount = typeof runtime.mount === 'string' && runtime.mount !== '/' ? runtime.mount.replace(/\/$/, '') : '';
  return {
    digest: String(bundle.digest ?? ''),
    runtimeVersion: String(runtime.version ?? ''),
    mount,
    tenant: String(bundle.tenant ?? ''),
    project: String(bundle.project ?? ''),
    version: String(bundle.version ?? ''),
    signed: Boolean(bundle.signed),
  };
}

/**
 * Join the runtime root URL and its version mount into the URL steps should call.
 *
 * @param {string} baseUrl Root URL of the runtime.
 * @param {string} mount Version mount prefix, or "" when the spec is served at the root.
 * @returns {string} The service URL, without a trailing slash.
 */
function serviceUrl(baseUrl, mount) {
  return `${String(baseUrl).replace(/\/$/, '')}${mount || ''}`;
}

/**
 * Work out the per-protocol endpoints from the runtime's `/ready` report, or refuse.
 *
 * The runtime is the authority on what it serves: `/ready` carries a `protocols` object (one
 * `{served, path?, port?, reason?}` entry per protocol id). A requested protocol it does not
 * serve fails the step with the runtime's own reason, so a job never gets a URL that 404s. An
 * image whose `/ready` has no `protocols` object predates multi-protocol serving and is treated
 * as HTTP-only.
 *
 * @param {any} document Parsed `/ready` response.
 * @param {string[]} protocols Requested protocol ids (from {@link parseProtocols}).
 * @param {object} context Where the runtime was published.
 * @param {string} context.serviceUrl Service URL (base URL plus mount).
 * @param {string} context.host Host the gRPC listener is reachable on from the job.
 * @param {number|null} context.grpcPort Host port the gRPC listener was published on, or null.
 * @param {string} context.image Image reference, for the error message.
 * @returns {{served: string[], graphqlUrl: string, connectUrl: string, grpcUrl: string}}
 *   Every protocol the runtime reports served, and the endpoint of each requested one ("" when
 *   not requested).
 * @throws {Error} When a requested protocol is not served, naming each one and why.
 */
function protocolEndpoints(document, protocols, { serviceUrl: url, host, grpcPort, image }) {
  const report = document && typeof document.protocols === 'object' && document.protocols ? document.protocols : null;
  const entry = (protocol) => {
    if (report) {
      return report[protocol] && typeof report[protocol] === 'object' ? report[protocol] : { served: false };
    }
    return protocol === 'http'
      ? { served: true, path: '' }
      : { served: false, reason: `${image} does not report protocol support on /ready; it serves HTTP only.` };
  };

  const refused = protocols
    .filter((protocol) => entry(protocol).served !== true)
    .map((protocol) => `${protocol}: ${entry(protocol).reason || 'not served by this runtime.'}`);
  if (refused.length) {
    throw new Error(
      `The pinned runtime cannot serve every requested protocol — pin an image that does, or drop ` +
        `them from "protocols".\n  ${refused.join('\n  ')}`,
    );
  }

  const at = (protocol) => (protocols.includes(protocol) ? `${url}${String(entry(protocol).path ?? '')}` : '');
  return {
    served: PROTOCOLS.filter((protocol) => entry(protocol).served === true),
    graphqlUrl: at('graphql'),
    connectUrl: at('connect'),
    grpcUrl: protocols.includes('grpc') && grpcPort !== null ? `${host}:${grpcPort}` : '',
  };
}

/**
 * Render the job-summary block reporting what the job is testing against.
 *
 * The digests are the point: a green suite means nothing if nobody can tell which artifact
 * answered it.
 *
 * @param {object} identity Values from {@link parseReady} plus the resolved URLs and image.
 * @returns {string} Markdown for `$GITHUB_STEP_SUMMARY`.
 */
function summaryMarkdown(identity) {
  const rows = [
    ['Service URL', identity.serviceUrl],
    ['Image', identity.image],
    ['Runtime version', identity.runtimeVersion || '(not reported)'],
    ['Bundle digest', identity.digest ? `\`${identity.digest}\`` : '(not reported)'],
    ['Bundle signed', identity.signed ? 'yes' : 'no'],
    ['API', [identity.tenant, identity.project, identity.version].filter(Boolean).join(' / ') || '(not reported)'],
  ];
  if (identity.protocolsServed) {
    rows.push(['Protocols served', identity.protocolsServed.join(', ')]);
  }
  for (const [label, value] of [
    ['GraphQL URL', identity.graphqlUrl],
    ['Connect URL', identity.connectUrl],
    ['gRPC target', identity.grpcUrl],
  ]) {
    if (value) {
      rows.push([label, value]);
    }
  }
  const body = rows.map(([label, value]) => `| ${label} | ${value} |`).join('\n');
  return ['### Apiome mock runtime', '', '| | |', '|---|---|', body, ''].join('\n');
}

/**
 * Render one `$GITHUB_OUTPUT` entry using the heredoc form.
 *
 * The delimiter form is used for every value, so a value that ever grows a newline cannot inject
 * additional outputs.
 *
 * @param {string} name Output name.
 * @param {string} value Output value.
 * @param {string} delimiter Unique delimiter token.
 * @returns {string} The text to append to the output file.
 */
function outputLine(name, value, delimiter) {
  return `${name}<<${delimiter}\n${value}\n${delimiter}\n`;
}

module.exports = {
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
};
