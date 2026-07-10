import { describe, expect, it } from 'vitest';
import {
  applySecretPlaceholders,
  inferSecretPlaceholders,
  placeholderForHeader,
  placeholderForQueryParam,
} from '../secrets';
import {
  buildSnippetRequest,
  formatPythonLiteral,
  generateSnippet,
  jsSingleQuote,
  pythonDoubleQuote,
  shellQuote,
} from '../snippet';

describe('shellQuote', () => {
  it('wraps simple strings in single quotes', () => {
    expect(shellQuote('hello')).toBe("'hello'");
  });

  it('escapes embedded single quotes for POSIX shells', () => {
    expect(shellQuote("it's")).toBe("'it'\\''s'");
    expect(shellQuote(`a'b"c`)).toBe(`'a'\\''b"c'`);
  });

  it('quotes an empty string', () => {
    expect(shellQuote('')).toBe("''");
  });
});

describe('jsSingleQuote', () => {
  it('escapes backslashes, quotes, and newlines', () => {
    expect(jsSingleQuote('line\n"quote"\\')).toBe("'line\\n\"quote\"\\\\'");
  });
});

describe('pythonDoubleQuote', () => {
  it('escapes backslashes, double quotes, and newlines', () => {
    expect(pythonDoubleQuote('line\n"quote"\\')).toBe('"line\\n\\"quote\\"\\\\"');
  });
});

describe('placeholder helpers', () => {
  it('maps common header names to stable tokens', () => {
    expect(placeholderForHeader('Authorization')).toBe('$AUTHORIZATION');
    expect(placeholderForHeader('X-API-Key')).toBe('$API_KEY');
    expect(placeholderForHeader('X-Custom-Secret')).toBe('$SECRET');
  });

  it('maps common query names to stable tokens', () => {
    expect(placeholderForQueryParam('api_key')).toBe('$API_KEY');
    expect(placeholderForQueryParam('access_token')).toBe('$ACCESS_TOKEN');
  });
});

describe('inferSecretPlaceholders', () => {
  it('detects Authorization and api-key headers', () => {
    expect(
      inferSecretPlaceholders('https://api.example.com/pets', {
        Authorization: 'Bearer sk_live_abc',
        'X-API-Key': 'secret-key',
        'X-Trace': 'abc',
      })
    ).toEqual({
      authorization: '$AUTHORIZATION',
      'x-api-key': '$API_KEY',
    });
  });

  it('detects secret query parameters in the URL', () => {
    expect(
      inferSecretPlaceholders('https://api.example.com/pets?api_key=secret&limit=10', {})
    ).toEqual({
      'query:api_key': '$API_KEY',
    });
  });
});

describe('applySecretPlaceholders', () => {
  it('replaces header and query values with placeholders', () => {
    const result = applySecretPlaceholders(
      {
        url: 'https://api.example.com/pets?api_key=real-secret&limit=5',
        headers: { Authorization: 'Bearer real-token', Accept: 'application/json' },
      },
      inferSecretPlaceholders(
        'https://api.example.com/pets?api_key=real-secret&limit=5',
        { Authorization: 'Bearer real-token', Accept: 'application/json' }
      )
    );
    expect(result.headers).toEqual({
      Authorization: '$AUTHORIZATION',
      Accept: 'application/json',
    });
    expect(result.url).toBe('https://api.example.com/pets?api_key=%24API_KEY&limit=5');
  });

  it('honours explicit SIM-3.6 placeholders over inferred ones', () => {
    const result = applySecretPlaceholders(
      {
        url: 'https://api.example.com/pets',
        headers: { Authorization: 'Bearer real-token' },
      },
      { authorization: '$MY_CUSTOM_TOKEN' }
    );
    expect(result.headers.Authorization).toBe('$MY_CUSTOM_TOKEN');
  });
});

describe('buildSnippetRequest', () => {
  it('composes URL and headers like the send pipeline', () => {
    const request = buildSnippetRequest({
      method: 'GET',
      serverUrl: 'https://api.example.com/v1',
      path: '/pets/{petId}',
      params: [
        { name: 'petId', location: 'path', required: true, schema: { type: 'integer' } },
        { name: 'verbose', location: 'query', required: false, schema: { type: 'boolean' } },
        { name: 'X-Trace', location: 'header', required: false, schema: { type: 'string' } },
      ],
      values: {
        'path:petId': '42',
        'query:verbose': 'true',
        'header:X-Trace': 'trace-1',
      },
      extraHeaders: [{ name: 'X-Extra', value: 'yes' }],
      body: null,
      contentType: null,
    });
    expect(request).toEqual({
      method: 'GET',
      url: 'https://api.example.com/v1/pets/42?verbose=true',
      headers: { 'X-Trace': 'trace-1', 'X-Extra': 'yes' },
      body: null,
    });
  });
});

describe('generateSnippet — GET without body', () => {
  const getRequest = {
    method: 'GET',
    url: 'https://api.example.com/v1/pets/42?q=hello%20world',
    headers: { Accept: 'application/json' },
    body: null,
  };

  it('generates curl without method or body flags', () => {
    expect(generateSnippet('curl', getRequest)).toBe(
      "curl 'https://api.example.com/v1/pets/42?q=hello%20world' -H 'Accept: application/json'"
    );
  });

  it('generates async fetch', () => {
    expect(generateSnippet('fetch', getRequest)).toBe(
      [
        "const response = await fetch('https://api.example.com/v1/pets/42?q=hello%20world', {",
        "  headers: {",
        "    'Accept': 'application/json',",
        '  },',
        '});',
        '',
        'const data = await response.json();',
      ].join('\n')
    );
  });

  it('generates httpx', () => {
    expect(generateSnippet('httpx', getRequest)).toBe(
      [
        'import httpx',
        '',
        'response = httpx.request(',
        '    "GET",',
        '    "https://api.example.com/v1/pets/42?q=hello%20world",',
        '    headers={',
        '        "Accept": "application/json",',
        '    },',
        ')',
        'response.raise_for_status()',
      ].join('\n')
    );
  });
});

describe('generateSnippet — POST with JSON body', () => {
  const postRequest = {
    method: 'POST',
    url: 'https://api.example.com/v1/pets',
    headers: {
      'Content-Type': 'application/json',
      Authorization: 'Bearer sk_live_secret',
    },
    body: '{"name":"Rex","note":"say \\"hi\\""}',
  };

  it('generates curl with method, headers, and shell-quoted body', () => {
    expect(generateSnippet('curl', postRequest)).toBe(
      [
        "curl -X POST 'https://api.example.com/v1/pets'",
        "-H 'Content-Type: application/json'",
        "-H 'Authorization: $AUTHORIZATION'",
        `--data-raw '{"name":"Rex","note":"say \\"hi\\""}'`,
      ].join(' ')
    );
  });

  it('never emits raw Authorization values', () => {
    const snippet = generateSnippet('fetch', postRequest);
    expect(snippet).not.toContain('sk_live_secret');
    expect(snippet).toContain('$AUTHORIZATION');
  });

  it('generates fetch with escaped JSON body string', () => {
    const snippet = generateSnippet('fetch', postRequest);
    expect(snippet).toContain(`  body: ${jsSingleQuote(postRequest.body!)},`);
  });

  it('generates httpx with json= for JSON bodies', () => {
    const snippet = generateSnippet('httpx', postRequest);
    expect(snippet).toContain('json={');
    expect(snippet).toContain('"name": "Rex"');
    expect(snippet).toContain('"note": "say \\"hi\\""');
    expect(snippet).not.toContain('sk_live_secret');
  });
});

describe('generateSnippet — special characters in params', () => {
  it('shell-quotes curl URL and headers with quotes and spaces', () => {
    const request = {
      method: 'GET',
      url: "https://api.example.com/v1/search?q=it's%20fine",
      headers: { 'X-Custom': `value with 'quotes'` },
      body: null,
    };
    const snippet = generateSnippet('curl', request);
    expect(snippet).toContain("curl 'https://api.example.com/v1/search?q=it'\\''s%20fine'");
    expect(snippet).toContain("-H 'X-Custom: value with '\\''quotes'\\'''");
  });

  it('escapes apostrophes in Python httpx URL strings', () => {
    const request = {
      method: 'GET',
      url: "https://api.example.com/v1/search?q=it's%20fine",
      headers: {},
      body: null,
    };
    expect(generateSnippet('httpx', request)).toContain(
      `"https://api.example.com/v1/search?q=it's%20fine"`
    );
  });
});

describe('formatPythonLiteral', () => {
  it('renders nested structures with indentation', () => {
    expect(formatPythonLiteral({ a: [1, 'b'] }, 0)).toBe(
      [
        '{',
        '    "a": [',
        '        1,',
        '        "b",',
        '    ],',
        '}',
      ].join('\n')
    );
  });
});
