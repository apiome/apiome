import { getAuthSession } from '@lib/auth/server-session';
import { getCommercialAccessForSession } from '@lib/db/commercial-access';
import AdeHome from '@/app/components/ade/AdeHome';

export default async function AdePage() {
  const session = await getAuthSession();
  const commercial =
    session?.user != null
      ? await getCommercialAccessForSession()
      : { entitledFlags: [], homeCards: [] };

  return (
    <AdeHome
      commercialHomeCards={commercial.homeCards}
      entitledFeatureFlags={commercial.entitledFlags}
    />
  );
}
