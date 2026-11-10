'use client';

import { useState } from 'react';
import { useRouter } from 'next/navigation';
import { Lock, AlertCircle } from 'lucide-react';
import { BrandMark } from '@/app/components/brand';
import { Button } from '@/app/components/ui/Button';
import { Input } from '@/app/components/ui/Input';

export default function AdminLoginClient() {
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const router = useRouter();

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');
    setIsLoading(true);

    try {
      const response = await fetch('/api/admin/auth', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ password }),
      });

      if (response.ok) {
        router.push('/admin/dashboard');
        router.refresh();
      } else {
        const data = await response.json();
        setError(data.error || 'Authentication failed');
        setPassword('');
      }
    } catch (err) {
      setError('An unexpected error occurred. Please try again.');
      console.error('Admin login error:', err);
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div className="min-h-screen bg-subtle flex items-center justify-center p-4">
      <div className="w-full max-w-md">
        <div className="bg-surface rounded-lg shadow-lg p-8 border border-border">
          {/* Header */}
          <div className="text-center mb-8">
            <div className="inline-flex items-center justify-center mb-4">
              <BrandMark variant="glyph" size={44} />
            </div>
            <h1 className="text-3xl font-bold text-fg mb-2">
              Super Admin
            </h1>
            <p className="text-fg-muted text-sm">
              Apiome Administration Portal
            </p>
          </div>

          {/* Error Message */}
          {error && (
            <div className="mb-6 p-4 bg-danger/50 border border-danger rounded-lg flex items-start gap-3">
              <AlertCircle className="w-5 h-5 text-danger-fg flex-shrink-0 mt-0.5" />
              <div>
                <h3 className="text-danger-fg font-semibold text-sm mb-1">
                  Authentication Failed
                </h3>
                <p className="text-danger-fg text-sm">{error}</p>
              </div>
            </div>
          )}

          {/* Login Form */}
          <form onSubmit={handleSubmit}>
            <div className="mb-6">
              <label
                htmlFor="password"
                className="block text-sm font-medium text-fg mb-[var(--space-field)]"
              >
                Admin Password
              </label>
              <div className="relative">
                <Lock className="absolute left-3 top-1/2 transform -translate-y-1/2 w-5 h-5 text-fg-muted" />
                <Input
                  id="password"
                  type="password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  className="pl-10 pr-4"
                  placeholder="Enter admin password"
                  required
                  disabled={isLoading}
                  autoFocus
                />
              </div>
            </div>

            <Button
              type="submit"
              disabled={isLoading || !password}
              variant="danger" className="w-full"
            >
              {isLoading ? (
                <>
                  <div className="w-5 h-5 border-2 border-white border-t-transparent rounded-full animate-spin" />
                  Authenticating...
                </>
              ) : (
                <>
                  <Lock className="w-5 h-5" />
                  Access Admin Portal
                </>
              )}
            </Button>
          </form>

          {/* Warning */}
          {/* The warn chip pair rather than raw yellows: yellow-400 text measured under 2:1 on
              the light page (HIVE-10.2); the pair clears AA in every theme. */}
          <div className="mt-6 p-4 bg-warn-soft border border-warn/40 rounded-lg">
            <p className="text-warn-fg text-xs text-center">
              ⚠️ This is a restricted area. Unauthorized access is prohibited.
            </p>
          </div>
        </div>

        {/* Footer */}
        <div className="mt-6 text-center">
          <a
            href="/"
            className="text-fg-muted hover:text-fg text-sm transition-colors"
          >
            ← Back to Apiome
          </a>
        </div>
      </div>
    </div>
  );
}

