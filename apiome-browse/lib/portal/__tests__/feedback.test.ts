import { describe, expect, it } from 'vitest';

import {
  createBody,
  feedbackBffUrl,
  feedbackErrorCopy,
  feedbackRestUrl,
  isFeedbackAction,
  isFeedbackSegment,
  isThreadId,
  specOperations,
  targetValue,
  threadSubject,
  WHOLE_API,
} from '../feedback';

const THREAD = '0c6f3a52-5d0e-4a4b-9a52-6c1f8e0a0010';

describe('URLs', () => {
  it('addresses apiome-rest under /portal/{tenant}/feedback', () => {
    expect(feedbackRestUrl('https://api.example/v1/', 'acme', 'pets', '1.0.0')).toBe(
      'https://api.example/v1/portal/acme/feedback/pets/1.0.0/threads',
    );
    expect(feedbackRestUrl('https://api.example/v1', 'acme', 'pets', '1.0.0', THREAD, 'resolve')).toBe(
      `https://api.example/v1/portal/acme/feedback/pets/1.0.0/threads/${THREAD}/resolve`,
    );
  });

  it('addresses Browse’s own route under the base path', () => {
    expect(feedbackBffUrl('/browse/', 'acme', 'pets', '1.0.0')).toBe('/browse/api/portal/feedback/acme/pets/1.0.0/threads');
    expect(feedbackBffUrl('', 'acme', 'pets', '1.0.0', THREAD, 'comments')).toBe(
      `/api/portal/feedback/acme/pets/1.0.0/threads/${THREAD}/comments`,
    );
  });
});

describe('guards', () => {
  it.each(['pets', '1.0.0', 'v2-beta', '2.0.0+build.1'])('accepts the segment %s', (value) => {
    expect(isFeedbackSegment(value)).toBe(true);
  });
  it.each(['', '..', '../x', 'a/b', '.hidden', 'a b', '%2e%2e', null])('refuses the segment %s', (value) => {
    expect(isFeedbackSegment(value)).toBe(false);
  });
  it('accepts only UUID thread ids and the three actions', () => {
    expect(isThreadId(THREAD)).toBe(true);
    expect(isThreadId('../../tenants')).toBe(false);
    expect(['comments', 'resolve', 'reopen'].every(isFeedbackAction)).toBe(true);
    expect(isFeedbackAction('delete')).toBe(false);
  });
});

describe('specOperations', () => {
  it('lists each method of each path in document order', () => {
    const spec = {
      paths: {
        '/pets': { get: {}, post: {}, parameters: [] },
        '/pets/{petId}': { delete: {}, summary: 'x' },
      },
    };
    expect(specOperations(spec)).toEqual([
      { method: 'GET', path: '/pets' },
      { method: 'POST', path: '/pets' },
      { method: 'DELETE', path: '/pets/{petId}' },
    ]);
  });

  it.each([null, undefined, {}, { paths: 'x' }, { workflows: [] }])('yields nothing for %s', (spec) => {
    expect(specOperations(spec)).toEqual([]);
  });
});

describe('the target picker', () => {
  it('round-trips the whole API and an operation into the request body', () => {
    expect(targetValue(null)).toBe(WHOLE_API);
    expect(createBody(WHOLE_API, 'hi')).toEqual({ target: 'version', body: 'hi' });
    const value = targetValue({ method: 'GET', path: '/pets/{petId}' });
    expect(createBody(value, 'hi')).toEqual({ target: 'operation', method: 'GET', path: '/pets/{petId}', body: 'hi' });
  });

  it('keeps a path that contains spaces whole', () => {
    expect(createBody('GET /a b', 'x')).toMatchObject({ method: 'GET', path: '/a b' });
  });

  it('names a thread’s subject', () => {
    expect(threadSubject({ target: 'version', operation: null })).toBe('Whole API');
    expect(threadSubject({ target: 'operation', operation: { method: 'GET', path: '/pets' } })).toBe('GET /pets');
    expect(threadSubject({ target: 'operation', operation: null })).toBe('An operation that was removed');
  });
});

describe('feedbackErrorCopy', () => {
  it.each([
    [401, null, /Sign in again/],
    [429, 'comment-rate-limited', /Wait a minute/],
    [404, 'feedback-operation-not-found', /not part of this version/],
    [404, 'feedback-version-not-found', /no longer takes feedback/],
    [404, 'feedback-thread-not-found', /no longer available/],
    [400, 'comment-empty-body', /Write a message/],
    [502, null, /could not be sent/],
  ])('%i %s', (status, code, pattern) => {
    expect(feedbackErrorCopy(status, code)).toMatch(pattern);
  });
});
