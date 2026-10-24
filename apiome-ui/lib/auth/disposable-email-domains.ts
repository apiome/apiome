/**
 * Disposable-email-domain blocklist for email sign-up (SGN-1.5, #5654).
 *
 * Throwaway inboxes let a script create accounts in bulk, so email sign-up refuses an address at
 * a disposable provider with `email-signup-disposable-domain`. Two lists are checked:
 *
 *   - {@link BUNDLED_DISPOSABLE_EMAIL_DOMAINS} — shipped with Apiome, always on;
 *   - the extra domains a super-admin adds on the System settings **Sign-up** card
 *     (`apiome.signup_policy.blocked_email_domains`, V317), read with the sign-up policy.
 *
 * A listed domain also blocks its subdomains (`mailinator.com` blocks `x.mailinator.com`), because
 * many disposable services hand out a subdomain per inbox.
 *
 * Email sign-up only: an OAuth provider has already verified the address it hands over, so
 * provider sign-up never consults this list.
 *
 * Pure (no I/O, no imports) so the admin card can show the bundled count.
 */

/**
 * Well-known disposable email providers. Lower-case bare domains, sorted. Kept deliberately to
 * services whose only purpose is a throwaway inbox — never a general mail provider.
 */
export const BUNDLED_DISPOSABLE_EMAIL_DOMAINS: readonly string[] = [
  '0-mail.com',
  '10minutemail.com',
  '10minutemail.net',
  '20minutemail.com',
  '33mail.com',
  'anonbox.net',
  'anonymbox.com',
  'binkmail.com',
  'bobmail.info',
  'burnermail.io',
  'byom.de',
  'chammy.info',
  'deadaddress.com',
  'despam.it',
  'devnullmail.com',
  'discard.email',
  'discardmail.com',
  'discardmail.de',
  'dispostable.com',
  'dodgit.com',
  'dropmail.me',
  'e4ward.com',
  'emailondeck.com',
  'emailtemporanea.net',
  'fakeinbox.com',
  'fakemail.net',
  'fakemailgenerator.com',
  'filzmail.com',
  'getairmail.com',
  'getnada.com',
  'guerrillamail.biz',
  'guerrillamail.com',
  'guerrillamail.de',
  'guerrillamail.info',
  'guerrillamail.net',
  'guerrillamail.org',
  'guerrillamailblock.com',
  'harakirimail.com',
  'inboxbear.com',
  'inboxkitten.com',
  'incognitomail.org',
  'jetable.org',
  'kasmail.com',
  'killmail.net',
  'klzlk.com',
  'linshiyouxiang.net',
  'mail-temp.com',
  'mailcatch.com',
  'maildrop.cc',
  'mailexpire.com',
  'mailinator.com',
  'mailinator.net',
  'mailinator2.com',
  'mailnesia.com',
  'mailnull.com',
  'mailpoof.com',
  'mailsac.com',
  'mailtemp.info',
  'meltmail.com',
  'mintemail.com',
  'moakt.com',
  'mohmal.com',
  'mt2015.com',
  'mytemp.email',
  'mytrashmail.com',
  'nada.email',
  'no-spam.ws',
  'noclickemail.com',
  'nowmymail.com',
  'one-time.email',
  'owlymail.com',
  'pookmail.com',
  'putthisinyourspamdatabase.com',
  'rcpt.at',
  'sharklasers.com',
  'shieldemail.com',
  'sneakemail.com',
  'sogetthis.com',
  'spam4.me',
  'spambog.com',
  'spambox.us',
  'spamex.com',
  'spamfree24.org',
  'spamgourmet.com',
  'spamhole.com',
  'spaml.com',
  'spammotel.com',
  'spamspot.com',
  'superrito.com',
  'suremail.info',
  'temp-mail.io',
  'temp-mail.org',
  'tempail.com',
  'tempemail.net',
  'tempinbox.com',
  'tempmail.com',
  'tempmail.dev',
  'tempmail.net',
  'tempmail.plus',
  'tempmailaddress.com',
  'tempmailo.com',
  'tempr.email',
  'thankyou2010.com',
  'throwam.com',
  'throwawaymail.com',
  'tmail.ws',
  'tmpmail.net',
  'tmpmail.org',
  'trash-mail.com',
  'trashmail.com',
  'trashmail.de',
  'trashmail.me',
  'trashmail.net',
  'trashmailer.com',
  'wegwerfmail.de',
  'wegwerfmail.net',
  'yopmail.com',
  'yopmail.fr',
  'yopmail.net',
  'zetmail.com',
];

/** The bundled list as a set, for constant-time lookups. */
const BUNDLED = new Set(BUNDLED_DISPOSABLE_EMAIL_DOMAINS);

/**
 * The domain itself and each parent domain with at least two labels, most specific first.
 *
 * @param domain A lower-case bare domain (`a.b.example.com`).
 * @returns e.g. `['a.b.example.com', 'b.example.com', 'example.com']`.
 */
function domainAndParents(domain: string): string[] {
  const labels = domain.split('.');
  const candidates: string[] = [];
  for (let start = 0; start <= labels.length - 2; start += 1) {
    candidates.push(labels.slice(start).join('.'));
  }
  return candidates;
}

/**
 * Whether an email address is at a blocked disposable domain.
 *
 * @param email The canonical (trimmed, lower-cased) address.
 * @param extraDomains The admin's extra blocked domains (already normalized).
 * @returns True when the address's domain, or a parent of it, is on the bundled list or on
 *   `extraDomains`. An address without a domain is never "disposable" (validation refuses it
 *   separately).
 */
export function isDisposableEmail(
  email: string,
  extraDomains: readonly string[] = [],
): boolean {
  const at = email.lastIndexOf('@');
  if (at <= 0 || at === email.length - 1) return false;
  const domain = email.slice(at + 1).toLowerCase();
  const extra = new Set(extraDomains);
  return domainAndParents(domain).some((candidate) => BUNDLED.has(candidate) || extra.has(candidate));
}
