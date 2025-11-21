import * as helper from '../db/helper';
const bcrypt = require('bcrypt');

export interface ICredentials {
  email: string;
  password: string;
}

/*
 * Authorization steps:
 * 1. User is retrieved by e-mail address.
 * 2. Comparison is checked against user password and stored password using bcrypt.
 * 3. If the user login succeeds, the record is returned without the password field.
 * 4. Failure returns a null, which the next-auth `authorize()` handler will interpret as an invalid account.
 */
export const credentialsAuthorize = async (credentials: ICredentials) => {
  console.log('[credentialsAuthorize] credentials login for user', credentials);

  const emailAddress = credentials.email;
  const password = credentials.password;
  const results = await helper.getUserByEmail(credentials.email);

  if (results.rowCount > 0) {
    const userResult = results.rows[0];
    const hashPassword = userResult.password;

    if (userResult.password) {
      if (bcrypt.compareSync(password, hashPassword)) {
        delete userResult.password;

        return userResult;
      }

      console.log(`[credentialsAuthorize] credentials login for user ${emailAddress} failed: password mismatch`);
      return null;
    } else {
      console.log(`[credentialsAuthorize] credentials login for user ${emailAddress} failed: no password is set`);
      return null;
    }
  }

  console.log(`[credentialsAuthorize] credentials login for user ${emailAddress} not found`);

  return null;
}

/*
 * Sign-in Steps:
 * 1. User must exist.
 *    If user is null, return 'User account not found'
 * 2. Enabled must be true.
 *    If not enabled, return 'Your account is currently disabled'
 * 3. Verified must be true.
 *    If not verified, return 'You have not yet verified your account e-mail address'
 *
 * TODO: Check licenses here.
 *
 * If all passes, true is returned.
 */
export const credentialsSignIn = (payload: any) => {
  const user = payload.user;

  console.log('[credentialsSignIn] Handling credentials provider');

  if (!user.enabled) {
    return '/login?error=Your account is currently disabled';
  }

  if (!user.verified) {
    return '/login?error=You have not yet verified your account e-mail address';
  }

  console.log('[credentialsSignIn] Login successful', user.email);

  return true;
}

/*
 * Sign-in Steps:
 * 1. User must exist.
 *    If user is null, return 'User account not found'
 * 2. Enabled must be true.
 *    If not enabled, return 'Your account is currently disabled'
 * 3. Verified must be true.
 *    If not verified, return 'You have not yet verified your account e-mail address'
 *
 * TODO: Check licenses here.
 *
 * If all passes, true is returned.
 */
export const credentialsGithub = async (payload: any) => {
  const user = payload.user;

  console.log('[credentialsGithub] Handling github provider', user);
  const results = await helper.getUserByEmail(user.email);

  if (results.rowCount > 0) {
    const userResult = results.rows[0];

    console.log('[credentialsGithub] Retrieved user record from DB:', userResult);

    if (!userResult.enabled) {
      return '/login?error=Your account is currently disabled';
    }

    if (!userResult.verified) {
      return '/login?error=You have not yet verified your account e-mail address';
    }

    console.log('[credentialsGithub] Login successful', user.email);

    return true;
  }

  console.log('[credentialsGithub] User account not found for e-mail address:', user.email);

  return false;
}