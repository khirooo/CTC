import { useParams, Navigate } from 'react-router-dom';
import { useApp } from '@/store/AppContext';
import { useAsync } from '@/store/useAsync';
import { aiu, euros } from '@/domain/credit';
import { tierMeta } from '@/domain/tiers';
import { TierBadge } from '@/components/TierBadge';
import { Avatar } from '@/components/Avatar';
import { CreditBar, CreditLegend } from '@/components/CreditBar';
import { monoLabel as monoLabelBase } from '@/theme/styles';

// Short, aristocracy-flavoured blurb keyed to the giver's standing tier.
function tierBlurb(tier: string | null): string {
  switch (tier) {
    case 'aristocrat': return 'Tops the standings — the most generous of hosts.';
    case 'baron': return 'A major benefactor of the pool.';
    case 'bourgeois': return 'Comfortably in the black — gives more than they take.';
    case 'commoner': return 'Holding their own in the marketplace.';
    case 'peasant': return 'Drawing more than they give this cycle.';
    case 'beggar': return 'Deep in the red — leaning on the pool this cycle.';
    case 'newcomer': return 'Fresh to the marketplace — no moves yet.';
    default: return 'Not yet ranked this cycle.';
  }
}

// PublicProfile uses a slightly smaller (10px) mono caption than the shared 11px.
const monoLabel: React.CSSProperties = { ...monoLabelBase, fontSize: 10 };

export function PublicProfileScreen() {
  const { id } = useParams<{ id: string }>();
  const { api, session } = useApp();

  // Hooks must run unconditionally and in a stable order — keep useAsync above
  // any early return. (session restores asynchronously, so an early return that
  // gated this hook would change the hook count between renders and crash.)
  const { data: p, loading, error } = useAsync(() => api.getUserProfile(id!), [id]);

  // Redirect own profile to the editable profile screen.
  if (id && session && id === session.userId) {
    return <Navigate to="/app/profile" replace />;
  }

  if (loading) {
    return (
      <div style={{ padding: 40, color: 'var(--text-faint)', fontFamily: "'JetBrains Mono', monospace", fontSize: 13, textAlign: 'center' }}>
        Loading…
      </div>
    );
  }
  if (error || !p) {
    return (
      <div style={{ padding: 40, color: 'var(--text-dim)' }}>
        We couldn't find that user.
      </div>
    );
  }

  const isGiver = p.role === 'giver';
  const tone = isGiver ? 'var(--give)' : 'var(--consume)';
  const toneSoft = isGiver ? 'var(--give-soft)' : 'var(--consume-soft)';
  const meta = tierMeta(p.tier);
  const rate = session?.creditToEuroRate;

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 18, maxWidth: 680, width: '100%' }}>
      {/* Hero banner — role-tinted, with a faint flow motif and a large avatar. */}
      <div
        style={{
          position: 'relative',
          overflow: 'hidden',
          background: 'var(--surface)',
          border: '1px solid var(--border)',
          borderRadius: 18,
          padding: '28px 28px 24px',
          boxShadow: 'var(--shadow)',
        }}
      >
        {/* decorative glow */}
        <div
          aria-hidden
          style={{
            position: 'absolute', top: -80, right: -60, width: 260, height: 260, borderRadius: '50%',
            background: `radial-gradient(circle, ${toneSoft} 0%, transparent 70%)`, pointerEvents: 'none',
          }}
        />
        <div style={{ position: 'relative', display: 'flex', alignItems: 'center', gap: 18 }}>
          <div style={{ position: 'relative', flex: 'none' }}>
            <Avatar initials={p.initials} tone={isGiver ? 'give' : 'consume'} size={72} />
            {isGiver && p.tier && (
              <span
                aria-hidden
                title={meta.label}
                style={{
                  position: 'absolute', bottom: -4, right: -4, fontSize: 22, lineHeight: 1,
                  filter: 'drop-shadow(0 1px 2px rgba(0,0,0,.4))',
                }}
              >
                {meta.emoji}
              </span>
            )}
          </div>
          <div style={{ flex: 1, minWidth: 0 }}>
            <div style={{ fontSize: 24, fontWeight: 700, letterSpacing: '-0.01em', overflow: 'hidden', textOverflow: 'ellipsis' }}>
              {p.name}
            </div>
            <div style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 13, color: 'var(--text-dim)', marginTop: 3 }}>
              @{p.login}
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginTop: 10, flexWrap: 'wrap' }}>
              <span
                style={{
                  fontFamily: "'JetBrains Mono', monospace", fontSize: 12, fontWeight: 600,
                  padding: '4px 12px', borderRadius: 20, color: tone, background: toneSoft,
                }}
              >
                {isGiver ? 'Host' : 'Guest'}
              </span>
              {isGiver && <TierBadge tier={p.tier} />}
            </div>
          </div>
        </div>
        {isGiver && (
          <div style={{ position: 'relative', marginTop: 16, fontSize: 13, color: 'var(--text-dim)', lineHeight: 1.5 }}>
            {tierBlurb(p.tier)}
          </div>
        )}
      </div>

      {isGiver ? (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 14 }}>
          <StatCard
            label="Net this cycle"
            icon="⚖"
            iconTone={(p.net ?? 0) >= 0 ? 'var(--give)' : 'var(--consume)'}
            value={
              <span style={{ color: (p.net ?? 0) >= 0 ? 'var(--give)' : 'var(--consume)' }}>
                {p.net != null ? `${p.net >= 0 ? '+' : '−'}${aiu(Math.abs(p.net))}` : '—'}
              </span>
            }
            sub="chipped in minus used"
          />
          <StatCard
            label="Chipped in"
            icon="♥"
            iconTone="var(--give)"
            value={<span style={{ color: 'var(--give)' }}>{p.donated != null ? aiu(p.donated) : '—'}</span>}
            sub={p.donated != null ? `≈ ${euros(p.donated, rate)} to teammates` : 'nothing yet'}
          />
          <StatCard
            label="Donations made"
            icon="⇄"
            iconTone="var(--give)"
            value={p.donationsMade != null ? String(p.donationsMade) : '—'}
            sub={`separate chip-in${p.donationsMade === 1 ? '' : 's'}`}
          />
        </div>
      ) : (
        <div
          style={{
            display: 'flex', alignItems: 'center', gap: 14,
            background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 16, padding: '20px 22px',
          }}
        >
          <span
            style={{
              width: 40, height: 40, borderRadius: 10, flex: 'none',
              background: 'var(--consume-soft)', color: 'var(--consume)',
              display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 18,
            }}
          >
            🌱
          </span>
          <div>
            <div style={{ fontWeight: 600, fontSize: 14 }}>Guest of the marketplace</div>
            <div style={{ fontSize: 13, color: 'var(--text-dim)', marginTop: 3, lineHeight: 1.5 }}>
              Runs Copilot on credits chipped in by Hosts or routed from the shared pool.
              Personal balances stay private.
            </div>
          </div>
        </div>
      )}

      {/* Public credit cycle — same bar the Host sees on their own profile,
          read-only. Hidden for unlimited entitlements (no meaningful split). */}
      {isGiver && p.entitlement != null && !p.unlimited && (
        <div
          data-public-credit-bar
          style={{ background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 16, padding: '22px 24px' }}
        >
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: 14 }}>
            <span style={monoLabel}>Monthly credits</span>
            <span style={{ fontFamily: "'JetBrains Mono', monospace", fontWeight: 600, fontSize: 15, color: 'var(--text)' }}>
              {aiu(p.entitlement)}
            </span>
          </div>
          <CreditBar
            max={p.entitlement}
            segments={[
              { key: 'used', label: 'used', value: p.used ?? 0, color: 'var(--own)', pattern: 'striped' as const },
              { key: 'donatedC', label: 'chipped in', value: p.donatedConsumed ?? 0, color: 'var(--give)', pattern: 'striped' as const },
              { key: 'pledgedC', label: 'shared', value: p.pledgedConsumed ?? 0, color: 'var(--pool)', pattern: 'striped' as const },
              { key: 'donatedR', label: 'chipped in', value: p.donatedRemaining ?? 0, color: 'var(--give)' },
              { key: 'pledgedR', label: 'shared', value: p.pledgedRemaining ?? 0, color: 'var(--pool)' },
              { key: 'left', label: 'kept', value: p.left ?? 0, color: 'var(--own)' },
            ].filter((s) => s.value > 0)}
          />
          <CreditLegend items={[
            { label: 'used', value: aiu(p.used ?? 0), color: 'var(--own)', pattern: 'striped' as const },
            ...((p.donatedConsumed ?? 0) > 0 ? [{ label: 'chipped in · used', value: aiu(p.donatedConsumed ?? 0), color: 'var(--give)', pattern: 'striped' as const }] : []),
            ...((p.pledgedConsumed ?? 0) > 0 ? [{ label: 'shared · used', value: aiu(p.pledgedConsumed ?? 0), color: 'var(--pool)', pattern: 'striped' as const }] : []),
            ...((p.donatedRemaining ?? 0) > 0 ? [{ label: 'chipped in · left', value: aiu(p.donatedRemaining ?? 0), color: 'var(--give)' }] : []),
            ...((p.pledgedRemaining ?? 0) > 0 ? [{ label: 'shared · left', value: aiu(p.pledgedRemaining ?? 0), color: 'var(--pool)' }] : []),
            { label: 'kept', value: aiu(p.left ?? 0), color: 'var(--own)' },
          ]} />
        </div>
      )}
    </div>
  );
}

function StatCard({
  label, value, sub, icon, iconTone,
}: {
  label: string;
  value: React.ReactNode;
  sub: string;
  icon: string;
  iconTone: string;
}) {
  return (
    <div style={{ background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 14, padding: '16px 18px' }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 12 }}>
        <span style={monoLabel}>{label}</span>
        <span aria-hidden style={{ color: iconTone, fontSize: 14 }}>{icon}</span>
      </div>
      <div style={{ fontFamily: "'JetBrains Mono', monospace", fontWeight: 600, fontSize: 22, lineHeight: 1 }}>
        {value}
      </div>
      <div style={{ fontSize: 11.5, color: 'var(--text-faint)', marginTop: 6 }}>{sub}</div>
    </div>
  );
}
