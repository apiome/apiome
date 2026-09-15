/**
 * The Project Discussion rule set (COL-1.3, #4515) — `lib/comment-discussion.ts`.
 *
 * Pins the four decisions the panel and its BFF routes share: the filter vocabulary (and the
 * whitelist the BFF forwards), the unresolved count rule (a copy of the Studio's COL-1.2 badge
 * rule), the element labels (V260's `anchor_label` spelling), and the COL-1.2 deep link.
 */

import {
  ANCHOR_TYPE_LABELS,
  COMMENT_ANCHOR_PARAM,
  COMMENT_ANCHOR_TYPES,
  COMMENT_THREAD_PARAM,
  COMMENT_THREAD_STATUSES,
  DEFAULT_DISCUSSION_FILTERS,
  DISCUSSION_ELEMENT_FILTERS,
  DISCUSSION_PAGE_SIZE,
  DISCUSSION_STATUS_FILTERS,
  REST_THREAD_PAGE_LIMIT,
  WORKSPACE_LENS_PARAM,
  WORKSPACE_PROJECT_PARAM,
  WORKSPACE_SELECTION_PARAM,
  WORKSPACE_VERSION_PARAM,
  anchorSelectionAddress,
  buildPointer,
  classAnchorLabel,
  commentAnchorKey,
  commentDeepLinkLens,
  commentExcerpt,
  discussionListParams,
  discussionSummaryParams,
  discussionThreadHref,
  discussionThreadSearch,
  isCommentAnchorType,
  isCommentThreadStatus,
  isUuid,
  operationAnchorLabel,
  propertyAnchorLabel,
  replyCountText,
  sanitizeThreadListParams,
  serializeSelectionAddress,
  statusFilterCount,
  threadElementLabel,
  unresolvedCommentCounts,
  unresolvedOnElementText,
  type DiscussionThread,
} from '../lib/comment-discussion';

/** A thread with sensible defaults, overridable per test. */
function thread(overrides: Partial<DiscussionThread> = {}): DiscussionThread {
  return {
    id: 't-1',
    project_id: 'p-1',
    version_id: 'v-1',
    anchor_type: 'class',
    anchor_id: 'c-1',
    status: 'open',
    anchor_label: null,
    orphaned_at: null,
    created_by: 'u-1',
    created_by_name: 'Ada',
    resolved_by: null,
    resolved_at: null,
    created_at: '2026-09-10T10:00:00Z',
    last_activity_at: '2026-09-12T10:00:00Z',
    comment_count: 1,
    root_comment: null,
    anchor_context: null,
    ...overrides,
  };
}

describe('wire vocabulary', () => {
  it('names the anchor kinds and statuses apiome-rest accepts', () => {
    expect(COMMENT_ANCHOR_TYPES).toEqual(['class', 'property', 'path', 'operation', 'version']);
    expect(COMMENT_THREAD_STATUSES).toEqual(['open', 'resolved', 'orphaned']);
  });

  it('guards anchor kinds, statuses and UUIDs', () => {
    expect(isCommentAnchorType('operation')).toBe(true);
    expect(isCommentAnchorType('schema')).toBe(false);
    expect(isCommentAnchorType(undefined)).toBe(false);
    expect(isCommentThreadStatus('orphaned')).toBe(true);
    expect(isCommentThreadStatus('closed')).toBe(false);
    expect(isUuid('0c6f3a52-5d0e-4a4b-9a52-6c1f8e0a0020')).toBe(true);
    expect(isUuid('0C6F3A52-5D0E-4A4B-9A52-6C1F8E0A0020')).toBe(true);
    expect(isUuid('c-1')).toBe(false);
    expect(isUuid("0c6f3a52-5d0e-4a4b-9a52-6c1f8e0a0020' OR 1=1")).toBe(false);
  });
});

describe('filters', () => {
  it('starts on the open threads of every element, whoever they mention', () => {
    expect(DEFAULT_DISCUSSION_FILTERS).toEqual({ status: 'open', mentionsMe: false, elementType: 'all' });
    expect(Object.isFrozen(DEFAULT_DISCUSSION_FILTERS)).toBe(true);
    expect(DISCUSSION_STATUS_FILTERS).toEqual(['open', 'resolved', 'orphaned', 'all']);
    expect(DISCUSSION_ELEMENT_FILTERS).toEqual(['all', 'class', 'property', 'path', 'operation', 'version']);
  });

  it('spells the list query in apiome-rest vocabulary', () => {
    expect(discussionListParams(DEFAULT_DISCUSSION_FILTERS)).toBe(
      `?status=open&limit=${DISCUSSION_PAGE_SIZE}&offset=0`
    );
    expect(
      discussionListParams({ status: 'resolved', mentionsMe: true, elementType: 'operation' }, { limit: 10, offset: 20 })
    ).toBe('?status=resolved&mentions_me=true&anchor_type=operation&limit=10&offset=20');
  });

  it('omits the facets set to all', () => {
    expect(discussionListParams({ status: 'all', mentionsMe: false, elementType: 'all' }, { limit: 1 })).toBe(
      '?limit=1&offset=0'
    );
  });

  it('sends only the count-shaping filters to the summary', () => {
    expect(discussionSummaryParams(DEFAULT_DISCUSSION_FILTERS)).toBe('');
    expect(discussionSummaryParams({ status: 'resolved', mentionsMe: true, elementType: 'path' })).toBe(
      '?mentions_me=true&anchor_type=path'
    );
  });
});

describe('sanitizeThreadListParams', () => {
  it('forwards the panel filters', () => {
    const out = sanitizeThreadListParams(
      new URLSearchParams('status=orphaned&anchor_type=property&mentions_me=true&limit=25&offset=75')
    );
    expect(out.toString()).toBe('status=orphaned&anchor_type=property&mentions_me=true&limit=25&offset=75');
  });

  it('drops everything else, including the scoping parameters', () => {
    const out = sanitizeThreadListParams(
      new URLSearchParams('version=1.0.0&anchor_id=c-1&tenant_slug=other&status=open')
    );
    expect(out.get('version')).toBeNull();
    expect(out.get('anchor_id')).toBeNull();
    expect(out.get('tenant_slug')).toBeNull();
    expect(out.get('status')).toBe('open');
  });

  it('drops unknown statuses and kinds rather than failing', () => {
    const out = sanitizeThreadListParams(new URLSearchParams('status=closed&anchor_type=schema&mentions_me=yes'));
    expect(out.get('status')).toBeNull();
    expect(out.get('anchor_type')).toBeNull();
    expect(out.get('mentions_me')).toBeNull();
  });

  it('clamps the page size and defaults a bad offset', () => {
    expect(sanitizeThreadListParams(new URLSearchParams('limit=0')).get('limit')).toBe('1');
    expect(sanitizeThreadListParams(new URLSearchParams('limit=5000')).get('limit')).toBe(
      String(REST_THREAD_PAGE_LIMIT)
    );
    expect(sanitizeThreadListParams(new URLSearchParams('limit=abc')).get('limit')).toBe(
      String(DISCUSSION_PAGE_SIZE)
    );
    expect(sanitizeThreadListParams(new URLSearchParams('offset=-4')).get('offset')).toBe('0');
    expect(sanitizeThreadListParams(new URLSearchParams('offset=1.5')).get('offset')).toBe('0');
    expect(sanitizeThreadListParams(new URLSearchParams()).toString()).toBe(
      `limit=${DISCUSSION_PAGE_SIZE}&offset=0`
    );
  });
});

describe('unresolved counts — the COL-1.2 badge rule', () => {
  it('counts open threads per anchor kind and id', () => {
    const counts = unresolvedCommentCounts([
      thread({ id: 'a', anchor_type: 'class', anchor_id: 'x' }),
      thread({ id: 'b', anchor_type: 'class', anchor_id: 'x' }),
      thread({ id: 'c', anchor_type: 'class', anchor_id: 'x', status: 'resolved' }),
      thread({ id: 'd', anchor_type: 'class', anchor_id: 'x', status: 'orphaned' }),
      thread({ id: 'e', anchor_type: 'property', anchor_id: 'x' }),
      thread({ id: 'f', anchor_type: 'operation', anchor_id: 'y', version_id: 'v-2' }),
    ]);
    expect(counts).toEqual({ 'class:x': 2, 'property:x': 1, 'operation:y': 1 });
  });

  it('leaves an element without open threads out', () => {
    expect(unresolvedCommentCounts([thread({ status: 'resolved' })])).toEqual({});
    expect(unresolvedCommentCounts([])).toEqual({});
  });

  it('keys anchors the way the Studio does', () => {
    expect(commentAnchorKey('operation', 'o-9')).toBe('operation:o-9');
  });

  it('totals a status chip, and sums every status for all', () => {
    const totals = { open: 3, resolved: 5, orphaned: 1 };
    expect(statusFilterCount(totals, 'open')).toBe(3);
    expect(statusFilterCount(totals, 'orphaned')).toBe(1);
    expect(statusFilterCount(totals, 'all')).toBe(9);
  });

  it('words a row count, and says nothing for none', () => {
    expect(unresolvedOnElementText(1)).toBe('1 unresolved on this element');
    expect(unresolvedOnElementText(4)).toBe('4 unresolved on this element');
    expect(unresolvedOnElementText(0)).toBe('');
    expect(unresolvedOnElementText(Number.NaN)).toBe('');
  });
});

describe('labels', () => {
  it('spells elements the way V260 stores anchor_label', () => {
    expect(classAnchorLabel('Customer')).toBe('Customer');
    expect(propertyAnchorLabel('Customer', 'email')).toBe('Customer.email');
    expect(propertyAnchorLabel(null, 'email')).toBe('email');
    expect(operationAnchorLabel('get', '/customers/{id}')).toBe('GET /customers/{id}');
  });

  it('names a row: stored label, whole version, resolved label, then kind + short id', () => {
    expect(threadElementLabel(thread({ status: 'orphaned', anchor_label: 'Customer.email' }))).toBe(
      'Customer.email'
    );
    expect(threadElementLabel(thread({ status: 'orphaned' }))).toBe('Deleted element');
    expect(threadElementLabel(thread({ anchor_type: 'version', anchor_id: 'v-1' }))).toBe('Whole version');
    expect(threadElementLabel(thread({ anchor_context: { label: 'Customer', className: 'Customer' } }))).toBe(
      'Customer'
    );
    expect(threadElementLabel(thread({ anchor_type: 'path', anchor_id: '0c6f3a52-5d0e-4a4b' }))).toBe(
      'Path 0c6f3a52'
    );
    expect(ANCHOR_TYPE_LABELS.operation).toBe('Operation');
  });

  it('previews a body on one line', () => {
    expect(commentExcerpt('Should  `nickname`\n\nbe nullable?')).toBe('Should `nickname` be nullable?');
    expect(commentExcerpt(null)).toBe('');
    const long = 'word '.repeat(60);
    const excerpt = commentExcerpt(long, 20);
    expect(excerpt.length).toBeLessThanOrEqual(20);
    expect(excerpt.endsWith('…')).toBe(true);
  });

  it('words the reply count', () => {
    expect(replyCountText(1)).toBe('No replies');
    expect(replyCountText(0)).toBe('No replies');
    expect(replyCountText(2)).toBe('1 reply');
    expect(replyCountText(5)).toBe('4 replies');
  });
});

describe('deep link — the COL-1.2 format', () => {
  it('uses the Studio parameter names', () => {
    expect([
      WORKSPACE_PROJECT_PARAM,
      WORKSPACE_VERSION_PARAM,
      WORKSPACE_LENS_PARAM,
      WORKSPACE_SELECTION_PARAM,
      COMMENT_ANCHOR_PARAM,
      COMMENT_THREAD_PARAM,
    ]).toEqual(['projectId', 'versionId', 'lens', 'sel', 'comment', 'thread']);
  });

  it('picks the lens that draws each kind', () => {
    expect(commentDeepLinkLens('class')).toBe('schemas');
    expect(commentDeepLinkLens('property')).toBe('schemas');
    expect(commentDeepLinkLens('path')).toBe('paths');
    expect(commentDeepLinkLens('operation')).toBe('paths');
    expect(commentDeepLinkLens('version')).toBeNull();
  });

  it('escapes pointer tokens per RFC 6901 and serializes addresses like the Studio', () => {
    expect(buildPointer([])).toBe('');
    expect(buildPointer(['paths', '/a~b/{id}'])).toBe('/paths/~1a~0b~1{id}');
    expect(serializeSelectionAddress({ versionId: 'v 1', pointer: '/paths/~1x', entityId: 'e|1' })).toBe(
      'v%201|%2Fpaths%2F~1x|e%7C1'
    );
    expect(serializeSelectionAddress({ versionId: 'v', pointer: '' })).toBe('v||');
  });

  it('builds the class link exactly as the Studio builds it', () => {
    const search = discussionThreadSearch(
      thread({ anchor_context: { label: 'Customer', className: 'Customer' } })
    );
    expect(search).toBe(
      '?projectId=p-1&versionId=v-1&lens=schemas&sel=v-1%7C%252Fcomponents%252Fschemas%252FCustomer%7Cc-1' +
        '&comment=class%3Ac-1&thread=t-1'
    );
  });

  it('addresses a property on its class', () => {
    const t = thread({
      anchor_type: 'property',
      anchor_id: 'cp-1',
      anchor_context: { label: 'Customer.email', className: 'Customer', propertyName: 'email' },
    });
    expect(anchorSelectionAddress(t)).toEqual({
      versionId: 'v-1',
      pointer: '/components/schemas/Customer/properties/email',
      entityId: 'cp-1',
    });
    const params = new URLSearchParams(discussionThreadSearch(t));
    expect(params.get('comment')).toBe('property:cp-1');
    expect(params.get('lens')).toBe('schemas');
  });

  it('addresses an operation by pathname and lower-case method', () => {
    const t = thread({
      anchor_type: 'operation',
      anchor_id: 'op-1',
      anchor_context: { label: 'GET /customers/{id}', pathname: '/customers/{id}', method: 'GET' },
    });
    const params = new URLSearchParams(discussionThreadSearch(t));
    expect(params.get('lens')).toBe('paths');
    expect(params.get('sel')).toBe(`v-1|${encodeURIComponent('/paths/~1customers~1{id}/get')}|op-1`);
    expect(params.get('comment')).toBe('operation:op-1');
    expect(params.get('thread')).toBe('t-1');
  });

  it('addresses a path by pathname', () => {
    const t = thread({ anchor_type: 'path', anchor_id: 'pa-1', anchor_context: { label: '/pets', pathname: '/pets' } });
    expect(anchorSelectionAddress(t)?.pointer).toBe('/paths/~1pets');
  });

  it('still opens the popover when the element could not be addressed', () => {
    const library = thread({
      anchor_type: 'property',
      anchor_id: 'lp-1',
      anchor_context: { label: 'email', propertyName: 'email' },
    });
    expect(anchorSelectionAddress(library)).toBeNull();
    const params = new URLSearchParams(discussionThreadSearch(library));
    expect(params.get('sel')).toBeNull();
    expect(params.get('comment')).toBe('property:lp-1');

    expect(anchorSelectionAddress(thread())).toBeNull();
    expect(anchorSelectionAddress(thread({ anchor_type: 'operation', anchor_context: { label: 'x', pathname: '/x' } })))
      .toBeNull();
  });

  it('links a version thread without a lens or selection', () => {
    const params = new URLSearchParams(
      discussionThreadSearch(thread({ anchor_type: 'version', anchor_id: 'v-1' }))
    );
    expect(params.get('lens')).toBeNull();
    expect(params.get('sel')).toBeNull();
    expect(params.get('comment')).toBe('version:v-1');
  });

  it('links an orphaned thread to its version only', () => {
    expect(
      discussionThreadSearch(
        thread({ status: 'orphaned', anchor_label: 'Customer', anchor_context: { label: 'Customer', className: 'Customer' } })
      )
    ).toBe('?projectId=p-1&versionId=v-1');
  });

  it('prefixes the workspace route, and has no link without one', () => {
    expect(discussionThreadHref('https://suite.example.com/workspace', thread({ status: 'orphaned' }))).toBe(
      'https://suite.example.com/workspace?projectId=p-1&versionId=v-1'
    );
    expect(discussionThreadHref(null, thread())).toBeNull();
    expect(discussionThreadHref('', thread())).toBeNull();
  });
});
