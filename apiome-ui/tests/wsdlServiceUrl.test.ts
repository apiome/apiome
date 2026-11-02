/**
 * Unit tests for the SOAP-service helpers of the catalog URL intake (MFI-13.6, #3793).
 *
 * `wsdlCandidateUrls` must follow the CLI's `wsdl_candidate_urls` for the URLs it rewrites —
 * `?singleWsdl` first, then `?wsdl` — and leave every URL that is not plainly SOAP alone;
 * `fetchWsdlDescription` must skip a candidate that fails or does not answer with WSDL.
 */

import { fetchWsdlDescription, isWsdlText, wsdlCandidateUrls } from '../src/app/utils/wsdl-service-url';

const SERVICE = 'https://soap.example.com/Calculator.svc';
const WSDL_11 = '<?xml version="1.0"?><wsdl:definitions xmlns:wsdl="http://schemas.xmlsoap.org/wsdl/"/>';
const WSDL_20 = '<description xmlns="http://www.w3.org/ns/wsdl"/>';

describe('wsdlCandidateUrls', () => {
  it.each([
    [`${SERVICE}?wsdl`, [`${SERVICE}?singleWsdl`, `${SERVICE}?wsdl`]],
    [`${SERVICE}?WSDL`, [`${SERVICE}?singleWsdl`, `${SERVICE}?wsdl`]],
    [SERVICE, [`${SERVICE}?singleWsdl`, `${SERVICE}?wsdl`]],
    ['https://h/legacy/Service.asmx', ['https://h/legacy/Service.asmx?singleWsdl', 'https://h/legacy/Service.asmx?wsdl']],
    [`${SERVICE}?wsdl&tenant=a#top`, [`${SERVICE}?tenant=a&singleWsdl`, `${SERVICE}?tenant=a&wsdl`]],
  ])('%s → %p', (url, expected) => {
    expect(wsdlCandidateUrls(url)).toEqual(expected);
  });

  it.each([
    `${SERVICE}?singleWsdl`,
    'https://h/files/calculator.wsdl',
    'https://h/api/openapi.json',
    'https://h/odata/trippin/',
    `${SERVICE}?tenant=a`,
    'ftp://h/Calculator.svc?wsdl',
    'not a url',
    '',
  ])('leaves %p as entered', (url) => {
    expect(wsdlCandidateUrls(url)).toBeNull();
  });
});

describe('isWsdlText', () => {
  it.each([WSDL_11, WSDL_20, '<definitions xmlns="http://schemas.xmlsoap.org/wsdl/"/>'])('recognizes %p', (text) => {
    expect(isWsdlText(text)).toBe(true);
  });

  it.each(['<html><body>You have created a service.</body></html>', '{"openapi":"3.1.0"}', ''])(
    'rejects %p',
    (text) => {
      expect(isWsdlText(text)).toBe(false);
    },
  );
});

describe('fetchWsdlDescription', () => {
  /** A fetcher answering from `routes`, throwing like `fetchUrlText` for anything else. */
  function fetcher(routes: Record<string, string>) {
    const calls: string[] = [];
    const fetchText = async (url: string): Promise<string> => {
      calls.push(url);
      if (url in routes) return routes[url];
      throw new Error('Fetch failed with HTTP 404.');
    };
    return { calls, fetchText };
  }

  it('prefers ?singleWsdl', async () => {
    const { calls, fetchText } = fetcher({ [`${SERVICE}?singleWsdl`]: WSDL_11, [`${SERVICE}?wsdl`]: WSDL_11 });
    await expect(fetchWsdlDescription(`${SERVICE}?wsdl`, fetchText)).resolves.toEqual({
      url: `${SERVICE}?singleWsdl`,
      text: WSDL_11,
    });
    expect(calls).toEqual([`${SERVICE}?singleWsdl`]);
  });

  it('falls back to ?wsdl when ?singleWsdl fails or is not WSDL', async () => {
    const failing = fetcher({ [`${SERVICE}?wsdl`]: WSDL_20 });
    await expect(fetchWsdlDescription(SERVICE, failing.fetchText)).resolves.toEqual({
      url: `${SERVICE}?wsdl`,
      text: WSDL_20,
    });
    const helpPage = fetcher({ [`${SERVICE}?singleWsdl`]: '<html>help</html>', [`${SERVICE}?wsdl`]: WSDL_11 });
    await expect(fetchWsdlDescription(SERVICE, helpPage.fetchText)).resolves.toEqual({
      url: `${SERVICE}?wsdl`,
      text: WSDL_11,
    });
  });

  it('returns null when no candidate answers with WSDL', async () => {
    const { fetchText } = fetcher({ [`${SERVICE}?wsdl`]: '<html>no</html>' });
    await expect(fetchWsdlDescription(SERVICE, fetchText)).resolves.toBeNull();
  });

  it('fetches nothing for a URL that is not a SOAP description URL', async () => {
    const { calls, fetchText } = fetcher({});
    await expect(fetchWsdlDescription('https://h/files/calculator.wsdl', fetchText)).resolves.toBeNull();
    expect(calls).toEqual([]);
  });
});
