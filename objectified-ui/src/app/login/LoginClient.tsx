"use client";

import { useState } from 'react';
import { Mail, Lock, User, Info, Github } from 'lucide-react';
import { signIn } from "next-auth/react";
import { createSignupRequest } from '../../../lib/db/helper';
import { SiGithub } from "react-icons/si";

interface SSOButtonProps {
  provider: string;
  icon: React.ReactNode;
  onClick: () => void;
}

const SSOButton: React.FC<SSOButtonProps> = ({ provider, icon, onClick }) => {
  return (
    <button
      type="button"
      onClick={onClick}
      className="w-full flex items-center justify-center gap-3 px-4 py-3 border border-gray-300 rounded-lg hover:bg-gray-50 transition-colors cursor-pointer"
    >
      <span className="flex-shrink-0">{icon}</span>
      <span className="text-gray-700 font-medium">Continue with {provider}</span>
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

  // Handle OAuth error from URL
  const getErrorMessage = (errorCode?: string): { type: 'error' | 'info'; text: string } | null => {
    if (!errorCode) return null;

    if (errorCode === 'AccessDenied') {
      return {
        type: 'error',
        text: 'An issue occurred with the OAuth provider. Your account may not have been set up properly. Please contact support or try a different sign-in method.'
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
        callbackUrl: '/ade/dashboard',
        redirect: true,
      }).finally(() => setSignInEnabled(true));
    }
  };

  const handleSSOLogin = async (provider: string) => {
    await signIn(provider, { callbackUrl: '/ade/dashboard' })
      .then((x) => {
        console.log('SSO sign-in initiated:', x);
      });
  }

  const handleChange = (e: any) => {
    setPayload({
      ...payload,
      [e.target.name]: e.target.value,
    });
  }

  return (
    <div className="min-h-screen bg-gray-100 flex items-center justify-center p-4">
      <div className="w-full max-w-md">
        <div className="bg-white rounded-lg shadow-lg p-8">
          {/* Logo */}
          <div className="flex justify-center mb-6">
            <img
              src="/Objectified-02.png"
              alt="Objectified Logo"
              style={{ height: "60px", width: "auto", objectFit: "contain" }}
            />
          </div>

          {/* Header */}
          <div className="text-center mb-8">
            <h1 className="text-3xl font-semibold text-gray-900 mb-2">
              {isSignUp ? 'Create Account' : 'Please Sign In'}
            </h1>
            <p className="text-sm text-gray-600">
              {isSignUp ? 'Sign up for early access' : 'Sign in to continue to your account'}
            </p>
          </div>

          {/* Message Display */}
          {(signupMessage || getErrorMessage(error)) && (
            <div className={`mb-6 p-4 rounded-lg ${
              (signupMessage || getErrorMessage(error))!.type === 'success' ? 'bg-green-50 border border-green-200' :
              (signupMessage || getErrorMessage(error))!.type === 'info' ? 'bg-blue-50 border border-blue-200' :
              'bg-red-50 border border-red-200'
            }`}>
              <p className={`text-sm ${
                (signupMessage || getErrorMessage(error))!.type === 'success' ? 'text-green-800' :
                (signupMessage || getErrorMessage(error))!.type === 'info' ? 'text-blue-800' :
                'text-red-800'
              }`}>
                {(signupMessage || getErrorMessage(error))!.text}
              </p>
            </div>
          )}

          {/* Form */}
          <form onSubmit={handleSubmit} className="space-y-4">
            {isSignUp && (
              <div>
                <label htmlFor="name" className="block text-sm font-medium text-gray-700 mb-1">
                  Full Name
                </label>
                <div className="relative">
                  <div className="absolute inset-y-0 left-0 pl-3 flex items-center pointer-events-none">
                    <User size={20} className="text-gray-400" />
                  </div>
                  <input
                    type="text"
                    name={'name'}
                    value={payload['name']}
                    onChange={handleChange}
                    required
                    className="block w-full pl-10 pr-3 py-2.5 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent outline-none text-gray-800"
                    placeholder="John Doe"
                  />
                </div>
              </div>
            )}

            <div>
              <label htmlFor="email" className="block text-sm font-medium text-gray-700 mb-1">
                Email Address
              </label>
              <div className="relative">
                <div className="absolute inset-y-0 left-0 pl-3 flex items-center pointer-events-none">
                  <Mail size={20} className="text-gray-400" />
                </div>
                <input
                  type="email"
                  name={'email'}
                  value={payload['email']}
                  onChange={handleChange}
                  required
                  className="block w-full pl-10 pr-3 py-2.5 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent outline-none text-gray-800"
                  placeholder="you@example.com"
                />
              </div>
            </div>

            <div>
              <label htmlFor="password" className="block text-sm font-medium text-gray-700 mb-1">
                Password
              </label>
              <div className="relative">
                <div className="absolute inset-y-0 left-0 pl-3 flex items-center pointer-events-none">
                  <Lock size={20} className="text-gray-400" />
                </div>
                <input
                  type="password"
                  name={'password'}
                  value={payload['password']}
                  onChange={handleChange}
                  required
                  className="block w-full pl-10 pr-3 py-2.5 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent outline-none text-gray-800"
                  placeholder="••••••••"
                />
              </div>
            </div>

            {isSignUp && (
              <div>
                <label htmlFor="signupSource" className="block text-sm font-medium text-gray-700 mb-1">
                  Where did you hear about Objectified?
                </label>
                <div className="relative">
                  <div className="absolute inset-y-0 left-0 pl-3 flex items-center pointer-events-none">
                    <Info size={20} className="text-gray-400" />
                  </div>
                  <input
                    type="text"
                    name={'signupSource'}
                    value={payload['signupSource'] || ''}
                    onChange={handleChange}
                    className="block w-full pl-10 pr-3 py-2.5 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent outline-none text-gray-800"
                    placeholder="e.g., Google, a friend, social media"
                  />
                </div>
              </div>
            )}

            {!isSignUp && (
              <div className="text-right">
                <a href="#" className="text-sm text-blue-600 hover:text-blue-500">
                  Forgot password?
                </a>
              </div>
            )}

            <button
              type="submit"
              className="w-full bg-blue-600 text-white py-3 rounded-lg font-semibold hover:bg-blue-700 transition-colors cursor-pointer"
            >
              {isSignUp ? 'Sign Up' : 'Sign In'}
            </button>
          </form>

          <div className="relative my-6">
            <div className="absolute inset-0 flex items-center">
              <div className="w-full border-t border-gray-300"></div>
            </div>
            <div className="relative flex justify-center text-sm">
              <span className="px-2 bg-white text-gray-500">OR</span>
            </div>
          </div>

          {/* SSO Buttons */}
          {/*<div className="space-y-3">*/}
          {/*  <SSOButton*/}
          {/*    provider="Google"*/}
          {/*    icon={*/}
          {/*      <svg width="18" height="18" viewBox="0 0 18 18">*/}
          {/*        <path*/}
          {/*          fill="#4285F4"*/}
          {/*          d="M17.64 9.2c0-.637-.057-1.251-.164-1.84H9v3.481h4.844c-.209 1.125-.843 2.078-1.796 2.717v2.258h2.908c1.702-1.567 2.684-3.874 2.684-6.615z"*/}
          {/*        />*/}
          {/*        <path*/}
          {/*          fill="#34A853"*/}
          {/*          d="M9 18c2.43 0 4.467-.806 5.956-2.184l-2.908-2.258c-.806.54-1.837.86-3.048.86-2.344 0-4.328-1.584-5.036-3.711H.957v2.332C2.438 15.983 5.482 18 9 18z"*/}
          {/*        />*/}
          {/*        <path*/}
          {/*          fill="#FBBC05"*/}
          {/*          d="M3.964 10.707c-.18-.54-.282-1.117-.282-1.707s.102-1.167.282-1.707V4.961H.957C.347 6.175 0 7.55 0 9s.348 2.825.957 4.039l3.007-2.332z"*/}
          {/*        />*/}
          {/*        <path*/}
          {/*          fill="#EA4335"*/}
          {/*          d="M9 3.58c1.321 0 2.508.454 3.44 1.345l2.582-2.58C13.463.891 11.426 0 9 0 5.482 0 2.438 2.017.957 4.961L3.964 7.29C4.672 5.163 6.656 3.58 9 3.58z"*/}
          {/*        />*/}
          {/*      </svg>*/}
          {/*    }*/}
          {/*    onClick={() => handleSSOLogin('Google')}*/}
          {/*  />*/}

            <SSOButton
              provider="GitHub"
              icon={<SiGithub size={18} className="text-gray-700" />}
              onClick={() => handleSSOLogin('github')}
            />

          {/*  <SSOButton*/}
          {/*    provider="GitLab"*/}
          {/*    icon={*/}
          {/*      <svg width="18" height="18" viewBox="0 0 18 18" fill="#FC6D26">*/}
          {/*        <path d="M9 16.5l3.5-10.8h-7L9 16.5z" />*/}
          {/*        <path d="M9 16.5l-3.5-10.8H1.8L9 16.5z" />*/}
          {/*        <path d="M1.8 5.7L.3 10.2c-.2.5 0 1.1.4 1.4L9 16.5 1.8 5.7z" />*/}
          {/*        <path d="M1.8 5.7h3.7L3.6 0c-.1-.4-.7-.4-.8 0L1.8 5.7z" />*/}
          {/*        <path d="M9 16.5l3.5-10.8h3.7L9 16.5z" />*/}
          {/*        <path d="M16.2 5.7l1.5 4.5c.2.5 0 1.1-.4 1.4L9 16.5l7.2-10.8z" />*/}
          {/*        <path d="M16.2 5.7h-3.7L14.4 0c.1-.4.7-.4.8 0l1 5.7z" />*/}
          {/*      </svg>*/}
          {/*    }*/}
          {/*    onClick={() => handleSSOLogin('GitLab')}*/}
          {/*  />*/}

          {/*  <SSOButton*/}
          {/*    provider="Microsoft"*/}
          {/*    icon={*/}
          {/*      <svg width="18" height="18" viewBox="0 0 18 18">*/}
          {/*        <rect width="8" height="8" fill="#F25022" />*/}
          {/*        <rect x="10" width="8" height="8" fill="#7FBA00" />*/}
          {/*        <rect y="10" width="8" height="8" fill="#00A4EF" />*/}
          {/*        <rect x="10" y="10" width="8" height="8" fill="#FFB900" />*/}
          {/*      </svg>*/}
          {/*    }*/}
          {/*    onClick={() => handleSSOLogin('Microsoft')}*/}
          {/*  />*/}
          {/*</div>*/}

          {/* Toggle Sign Up/Sign In */}
          <div className="mt-6 text-center">
            <p className="text-sm text-gray-600">
              {isSignUp ? 'Already have an account?' : 'Don\'t have an account?'}{' '}
              <button
                type="button"
                disabled={!signInEnabled}
                onClick={() => {
                  setIsSignUp(!isSignUp);
                  setSignupMessage(null);
                }}
                className="text-blue-600 font-semibold hover:text-blue-500 cursor-pointer"
              >
                {isSignUp ? 'Sign In' : 'Sign Up'}
              </button>
            </p>
          </div>
        </div>
      </div>
    </div>
  );
};

export default LoginClient;
