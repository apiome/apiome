"use client";

import { useState } from 'react';
import { Mail, Lock, User, Info } from 'lucide-react';
import { signIn } from "next-auth/react";
import { createSignupRequest } from '../../../lib/db/helper';
import { useDarkMode } from '../hooks/useDarkMode';
import { SiGithub, SiGitlab } from "react-icons/si";
import BetaBackground from './BetaBackground';

interface SSOButtonProps {
  provider: string;
  icon: React.ReactNode;
  onClick: () => void;
  color?: string;
}

const SSOButton: React.FC<SSOButtonProps> = ({ provider, icon, onClick, color }) => {
  return (
    <button
      type="button"
      onClick={onClick}
      className="w-full flex items-center justify-center gap-3 px-4 py-3.5 bg-white border border-gray-200 rounded-xl hover:border-gray-300 hover:bg-gray-50 hover:shadow-md transition-all duration-200 cursor-pointer group dark:bg-slate-800/80 dark:border-slate-600 dark:hover:border-slate-500 dark:hover:bg-slate-800"
    >
      <span className="flex-shrink-0 transition-transform duration-200 group-hover:scale-110">{icon}</span>
      <span className="text-gray-700 font-semibold dark:text-slate-200">Continue with {provider}</span>
    </button>
  );
};

interface LoginClientProps {
  error?: string;
}

const LoginClient: React.FC<LoginClientProps> = ({ error }) => {
  const [isSignUp, setIsSignUp] = useState(false);
  const [payload, setPayload] = useState<any>({
    email: '',
    password: '',
  });
  const [signInEnabled, setSignInEnabled] = useState(true);
  const [signupMessage, setSignupMessage] = useState<{ type: 'success' | 'error' | 'info'; text: string } | null>(null);
  const [isSSOLoading, setIsSSOLoading] = useState(false);
  const isDark = useDarkMode();

  // Handle OAuth error from URL
  const getErrorMessage = (errorCode?: string): { type: 'error' | 'info'; text: string } | null => {
    if (!errorCode) return null;

    if (errorCode === 'AccessDenied') {
      return {
        type: 'error',
        text: 'An issue occurred with the OAuth provider. Your account may not have been set up properly. Please contact support or try a different sign-in method.'
      };
    }

    if (errorCode === 'OAuthAccountExists') {
      return {
        type: 'info',
        text: 'An account with this email already exists. Sign in with your password or use "Continue with GitHub/GitLab" without create-account mode.',
      };
    }

    if (errorCode === 'OAuthEmailRequired') {
      return {
        type: 'error',
        text: 'Your Git provider did not share an email address. Set your email to public or add a verified email on GitHub/GitLab, then try again.',
      };
    }

    if (errorCode === 'OAuthProfileIncomplete') {
      return {
        type: 'error',
        text: 'We could not read your OAuth profile. Please try again or contact support.',
      };
    }

    if (errorCode === 'SignupSessionExpired') {
      return {
        type: 'error',
        text: 'Your signup session expired. Please start again from Create account.',
      };
    }

    if (errorCode === 'CredentialsSignin') {
      return {
        type: 'error',
        text: 'Your account could not be found or the credentials provided were incorrect. Please check your email and password, or sign up for a new account.'
      };
    }

    // Generic error message for other error codes
    return {
      type: 'error',
      text: `Authentication error: ${errorCode}. Please try again or contact support if the issue persists.`
    };
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setSignInEnabled(false);
    setSignupMessage(null);

    if (isSignUp) {
      try {
        const result = await createSignupRequest(
          payload.name || '',
          payload.email || '',
          payload.password || '',
          payload.signupSource || ''
        );

        const response = JSON.parse(result);

        if (response.success) {
          setSignupMessage({type: 'success', text: response.message});
          // Clear the form
          setPayload({
            email: '',
            password: '',
            name: '',
            signupSource: '',
          });
        } else if (response.duplicate) {
          setSignupMessage({type: 'info', text: response.message});
        } else {
          setSignupMessage({type: 'error', text: response.error || 'An error occurred during signup.'});
        }
      } catch (error) {
        console.error('Signup error:', error);
        setSignupMessage({type: 'error', text: 'An unexpected error occurred. Please try again.'});
      } finally {
        setSignInEnabled(true);
      }
    } else {
      signIn('credentials', {
        payload: JSON.stringify(payload),
        callbackUrl: '/ade',
        redirect: true,
      }).finally(() => setSignInEnabled(true));
    }
  };

  const handleSSOLogin = async (provider: string) => {
    setIsSSOLoading(true);
    try {
      if (isSignUp) {
        const res = await fetch(`/api/auth/signup-intent`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ provider }),
        });
        if (!res.ok) {
          setSignupMessage({ type: 'error', text: 'Could not start sign-up. Please try again.' });
          setIsSSOLoading(false);
          return;
        }
      }
      await signIn(provider, { callbackUrl: '/ade' });
    } catch (error) {
      console.error('SSO sign-in error:', error);
      setIsSSOLoading(false);
    }
  }

  const handleChange = (e: any) => {
    setPayload({
      ...payload,
      [e.target.name]: e.target.value,
    });
  }

  const isBetaMode = process.env.NEXT_PUBLIC_BETA_MODE;

  return (
    <div className="min-h-screen bg-gradient-to-br from-slate-50 via-indigo-50/30 to-purple-50/30 dark:from-slate-950 dark:via-slate-900 dark:to-indigo-950/40 flex items-center justify-center p-4 relative overflow-hidden">
      {/* Decorative background elements */}
      <div className="absolute top-0 left-0 w-96 h-96 bg-gradient-to-br from-indigo-200/40 to-purple-200/40 rounded-full blur-3xl -translate-x-1/2 -translate-y-1/2 dark:from-indigo-700/25 dark:to-purple-700/20" />
      <div className="absolute bottom-0 right-0 w-96 h-96 bg-gradient-to-br from-blue-200/40 to-cyan-200/40 rounded-full blur-3xl translate-x-1/2 translate-y-1/2 dark:from-blue-700/25 dark:to-cyan-700/20" />
      <div className="absolute top-1/2 left-1/2 w-64 h-64 bg-gradient-to-br from-purple-200/30 to-pink-200/30 rounded-full blur-3xl -translate-x-1/2 -translate-y-1/2 dark:from-fuchsia-700/15 dark:to-pink-700/20" />

      {/* Beta Background */}
      {isBetaMode && <BetaBackground />}

      <div className="w-full max-w-md relative z-10">
        <div className="bg-white/80 backdrop-blur-xl rounded-2xl shadow-2xl shadow-indigo-500/10 p-8 border border-white/50 dark:bg-slate-900/80 dark:border-slate-700/60 dark:shadow-black/30">
          {/* Logo */}
          <div className="flex justify-center mb-8">
            <div className="relative">
              <div className="absolute inset-0 bg-gradient-to-r from-indigo-500 to-purple-500 blur-xl opacity-20 rounded-full scale-150" />
              <img
                src={isDark ? "/Objectified-05.png" : "/Objectified-02.png"}
                alt="Objectified Logo"
                className="relative"
                style={{ height: "56px", width: "auto", objectFit: "contain" }}
              />
            </div>
          </div>

          {/* Header */}
          <div className="text-center mb-8">
            <h1 className="text-3xl font-bold bg-gradient-to-r from-gray-900 via-indigo-900 to-gray-900 bg-clip-text text-transparent mb-3 dark:from-slate-100 dark:via-indigo-200 dark:to-slate-100">
              {isSignUp ? 'Create Your Account' : 'Welcome Back'}
            </h1>
            <p className="text-gray-500 text-sm dark:text-slate-400">
              {isSignUp ? 'Join thousands of developers building with Objectified' : 'Sign in to continue to your workspace'}
            </p>
            {!isSignUp && (
              <p className="text-sm text-gray-500 mt-3 dark:text-slate-400">
                New to Objectified?{' '}
                <a
                  href="https://youtu.be/GQBgza8eYoQ"
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-indigo-600 hover:text-indigo-500 font-medium hover:underline transition-colors dark:text-indigo-300 dark:hover:text-indigo-200"
                >
                  Watch our intro video →
                </a>
              </p>
            )}
          </div>

          {/* Message Display */}
          {(signupMessage || getErrorMessage(error)) && (
            <div className={`mb-6 p-4 rounded-xl border backdrop-blur-sm ${
              (signupMessage || getErrorMessage(error))!.type === 'success' 
                ? 'bg-emerald-50/80 border-emerald-200 text-emerald-800 dark:bg-emerald-900/30 dark:border-emerald-700/60 dark:text-emerald-200' 
                : (signupMessage || getErrorMessage(error))!.type === 'info' 
                  ? 'bg-blue-50/80 border-blue-200 text-blue-800 dark:bg-blue-900/30 dark:border-blue-700/60 dark:text-blue-200' 
                  : 'bg-red-50/80 border-red-200 text-red-800 dark:bg-red-900/30 dark:border-red-700/60 dark:text-red-200'
            }`}>
              <p className="text-sm font-medium">
                {(signupMessage || getErrorMessage(error))!.text}
              </p>
            </div>
          )}

          {/* Form */}
          <form onSubmit={handleSubmit} className="space-y-5">
            {isSignUp && (
              <div>
                <label htmlFor="name" className="block text-sm font-semibold text-gray-700 mb-1.5 dark:text-slate-300">
                  Full Name
                </label>
                <div className="relative group">
                  <div className="absolute inset-y-0 left-0 pl-3.5 flex items-center pointer-events-none">
                    <User size={18} className="text-gray-400 group-focus-within:text-indigo-500 transition-colors dark:text-slate-500 dark:group-focus-within:text-indigo-300" />
                  </div>
                  <input
                    type="text"
                    name={'name'}
                    value={payload['name']}
                    onChange={handleChange}
                    required
                    className="block w-full pl-11 pr-4 py-3 border border-gray-200 rounded-xl focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-500 outline-none text-gray-800 placeholder-gray-400 transition-all duration-200 bg-gray-50/50 hover:bg-white focus:bg-white dark:border-slate-600 dark:bg-slate-800/70 dark:hover:bg-slate-800 dark:focus:bg-slate-800 dark:text-slate-100 dark:placeholder:text-slate-500 dark:focus:ring-indigo-400/30"
                    placeholder="John Doe"
                  />
                </div>
              </div>
            )}

            <div>
              <label htmlFor="email" className="block text-sm font-semibold text-gray-700 mb-1.5 dark:text-slate-300">
                Email Address
              </label>
              <div className="relative group">
                <div className="absolute inset-y-0 left-0 pl-3.5 flex items-center pointer-events-none">
                  <Mail size={18} className="text-gray-400 group-focus-within:text-indigo-500 transition-colors dark:text-slate-500 dark:group-focus-within:text-indigo-300" />
                </div>
                <input
                  type="email"
                  name={'email'}
                  value={payload['email']}
                  onChange={handleChange}
                  required
                  className="block w-full pl-11 pr-4 py-3 border border-gray-200 rounded-xl focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-500 outline-none text-gray-800 placeholder-gray-400 transition-all duration-200 bg-gray-50/50 hover:bg-white focus:bg-white dark:border-slate-600 dark:bg-slate-800/70 dark:hover:bg-slate-800 dark:focus:bg-slate-800 dark:text-slate-100 dark:placeholder:text-slate-500 dark:focus:ring-indigo-400/30"
                  placeholder="you@example.com"
                />
              </div>
            </div>

            <div>
              <label htmlFor="password" className="block text-sm font-semibold text-gray-700 mb-1.5 dark:text-slate-300">
                Password
              </label>
              <div className="relative group">
                <div className="absolute inset-y-0 left-0 pl-3.5 flex items-center pointer-events-none">
                  <Lock size={18} className="text-gray-400 group-focus-within:text-indigo-500 transition-colors dark:text-slate-500 dark:group-focus-within:text-indigo-300" />
                </div>
                <input
                  type="password"
                  name={'password'}
                  value={payload['password']}
                  onChange={handleChange}
                  required
                  className="block w-full pl-11 pr-4 py-3 border border-gray-200 rounded-xl focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-500 outline-none text-gray-800 placeholder-gray-400 transition-all duration-200 bg-gray-50/50 hover:bg-white focus:bg-white dark:border-slate-600 dark:bg-slate-800/70 dark:hover:bg-slate-800 dark:focus:bg-slate-800 dark:text-slate-100 dark:placeholder:text-slate-500 dark:focus:ring-indigo-400/30"
                  placeholder="••••••••"
                />
              </div>
            </div>

            {isSignUp && (
              <div>
                <label htmlFor="signupSource" className="block text-sm font-semibold text-gray-700 mb-1.5 dark:text-slate-300">
                  How did you hear about us?
                  <span className="text-gray-400 font-normal ml-1 dark:text-slate-500">(optional)</span>
                </label>
                <div className="relative group">
                  <div className="absolute inset-y-0 left-0 pl-3.5 flex items-center pointer-events-none">
                    <Info size={18} className="text-gray-400 group-focus-within:text-indigo-500 transition-colors dark:text-slate-500 dark:group-focus-within:text-indigo-300" />
                  </div>
                  <input
                    type="text"
                    name={'signupSource'}
                    value={payload['signupSource'] || ''}
                    onChange={handleChange}
                    className="block w-full pl-11 pr-4 py-3 border border-gray-200 rounded-xl focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-500 outline-none text-gray-800 placeholder-gray-400 transition-all duration-200 bg-gray-50/50 hover:bg-white focus:bg-white dark:border-slate-600 dark:bg-slate-800/70 dark:hover:bg-slate-800 dark:focus:bg-slate-800 dark:text-slate-100 dark:placeholder:text-slate-500 dark:focus:ring-indigo-400/30"
                    placeholder="e.g., Google, Twitter, a friend"
                  />
                </div>
              </div>
            )}

            {!isSignUp && (
              <div className="flex items-center justify-end">
                <a href="#" className="text-sm text-indigo-600 hover:text-indigo-500 font-medium transition-colors dark:text-indigo-300 dark:hover:text-indigo-200">
                  Forgot your password?
                </a>
              </div>
            )}

            <button
              type="submit"
              disabled={!signInEnabled}
              className="w-full bg-gradient-to-r from-indigo-600 to-purple-600 hover:from-indigo-700 hover:to-purple-700 text-white py-3.5 rounded-xl font-semibold transition-all duration-200 cursor-pointer shadow-lg shadow-indigo-500/25 hover:shadow-indigo-500/40 hover:-translate-y-0.5 disabled:opacity-50 disabled:cursor-not-allowed disabled:hover:translate-y-0"
            >
              {isSignUp ? 'Create Account' : 'Sign In'}
            </button>
          </form>

          {/* Divider */}
          <div className="relative my-8">
            <div className="absolute inset-0 flex items-center">
              <div className="w-full border-t border-gray-200 dark:border-slate-700/60"></div>
            </div>
            <div className="relative flex justify-center text-sm">
              <span className="px-4 bg-white/80 text-gray-400 font-medium dark:bg-slate-900/80 dark:text-slate-500">or continue with</span>
            </div>
          </div>

          {/* SSO Loading Message */}
          {isSSOLoading ? (
            <div className="text-center py-8">
              <div className="inline-flex items-center justify-center w-12 h-12 rounded-xl bg-gradient-to-r from-indigo-500 to-purple-500 mb-4">
                <div className="w-6 h-6 border-2 border-white border-t-transparent rounded-full animate-spin"></div>
              </div>
              <p className="text-lg font-semibold text-gray-900 dark:text-slate-100">Connecting...</p>
              <p className="text-sm text-gray-500 mt-1 dark:text-slate-400">Redirecting to authentication provider</p>
            </div>
          ) : (
            <>
              {/* SSO Buttons */}
              <div className="space-y-3">
                <SSOButton
                  provider="GitHub"
                  icon={<SiGithub size={20} className="text-gray-800 dark:text-slate-100" />}
                  onClick={() => handleSSOLogin('github')}
                />

                <SSOButton
                  provider="GitLab"
                  icon={<SiGitlab size={20} className="text-orange-600" />}
                  onClick={() => handleSSOLogin('gitlab')}
                />
              </div>
            </>
          )}

          {/* Toggle Sign Up/Sign In */}
          <div className="mt-8 pt-6 border-t border-gray-100 text-center dark:border-slate-700/60">
            <p className="text-sm text-gray-600 dark:text-slate-400">
              {isSignUp ? 'Already have an account?' : "Don't have an account?"}{' '}
              <button
                type="button"
                disabled={!signInEnabled}
                onClick={() => {
                  setIsSignUp(!isSignUp);
                  setSignupMessage(null);
                }}
                className="text-indigo-600 font-semibold hover:text-indigo-500 cursor-pointer transition-colors dark:text-indigo-300 dark:hover:text-indigo-200"
              >
                {isSignUp ? 'Sign In' : 'Create one'}
              </button>
            </p>
          </div>

          {/* Trust Badges */}
          {!isSignUp && (
            <div className="mt-6 flex items-center justify-center gap-6 text-xs text-gray-400 dark:text-slate-500">
              <div className="flex items-center gap-1.5">
                <svg className="w-4 h-4 text-emerald-500" fill="currentColor" viewBox="0 0 20 20">
                  <path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm3.707-9.293a1 1 0 00-1.414-1.414L9 10.586 7.707 9.293a1 1 0 00-1.414 1.414l2 2a1 1 0 001.414 0l4-4z" clipRule="evenodd" />
                </svg>
                <span>Secure</span>
              </div>
              <div className="flex items-center gap-1.5">
                <svg className="w-4 h-4 text-emerald-500" fill="currentColor" viewBox="0 0 20 20">
                  <path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm3.707-9.293a1 1 0 00-1.414-1.414L9 10.586 7.707 9.293a1 1 0 00-1.414 1.414l2 2a1 1 0 001.414 0l4-4z" clipRule="evenodd" />
                </svg>
                <span>Free to start</span>
              </div>
              <div className="flex items-center gap-1.5">
                <svg className="w-4 h-4 text-emerald-500" fill="currentColor" viewBox="0 0 20 20">
                  <path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm3.707-9.293a1 1 0 00-1.414-1.414L9 10.586 7.707 9.293a1 1 0 00-1.414 1.414l2 2a1 1 0 001.414 0l4-4z" clipRule="evenodd" />
                </svg>
                <span>No credit card</span>
              </div>
            </div>
          )}
        </div>

        {/* Footer */}
        <p className="text-center text-xs text-gray-400 mt-6 dark:text-slate-500">
          By signing in, you agree to our{' '}
          <a href="#" className="text-indigo-500 hover:text-indigo-600 transition-colors dark:text-indigo-300 dark:hover:text-indigo-200">Terms of Service</a>
          {' '}and{' '}
          <a href="#" className="text-indigo-500 hover:text-indigo-600 transition-colors dark:text-indigo-300 dark:hover:text-indigo-200">Privacy Policy</a>
        </p>
      </div>
    </div>
  );
};

export default LoginClient;
