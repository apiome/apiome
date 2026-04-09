import AuthenticatedLayout from '@/app/components/auth/AuthenticatedLayout';

export default function PlatformLayout({ children }: { children: React.ReactNode }) {
  return <AuthenticatedLayout>{children}</AuthenticatedLayout>;
}
