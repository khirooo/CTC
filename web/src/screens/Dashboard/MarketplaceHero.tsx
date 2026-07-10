import { useNavigate } from 'react-router-dom';
import type { DashboardData } from '@/domain/types';
import { aiu, euros } from '@/domain/credit';
import { useApp } from '@/store/AppContext';
import { InfoTip } from '@/components/InfoTip';

interface Props {
  data: DashboardData;
}

const connector = (color: string) => ({
  width: '100%',
  height: 3,
  backgroundImage: `linear-gradient(90deg, ${color} 60%, transparent 0)`,
  backgroundSize: '14px 3px',
  backgroundRepeat: 'repeat-x' as const,
  animation: 'flow 1.4s linear infinite',
  opacity: 0.7,
});

// Two-color dashed flow: alternating dashes of `a` then `b` (used for the
// outgoing line, which splits to Rotated-to-PAT (blue) + Donated-to-non-PAT (orange)).
const connectorMix = (a: string, b: string) => ({
  width: '100%',
  height: 3,
  backgroundImage: `linear-gradient(90deg, ${a} 0 30%, transparent 30% 50%, ${b} 50% 80%, transparent 80%)`,
  backgroundSize: '28px 3px',
  backgroundRepeat: 'repeat-x' as const,
  animation: 'flow 1.4s linear infinite',
  opacity: 0.7,
});

export function MarketplaceHero({ data }: Props) {
  const navigate = useNavigate();
  const { session } = useApp();
  const eur = (nano: number) => euros(nano, session?.creditToEuroRate);
  const _closedCount = data.closedCount ?? 0;
  const _poolAvailable = data.poolAvailable ?? 0;

  return (
    <div
      style={{
        background: 'var(--surface)',
        border: '1px solid var(--border)',
        borderRadius: 18,
        padding: '26px 28px',
        boxShadow: 'var(--shadow)',
      }}
    >
      {/* Header row */}
      <div
        style={{
          display: 'flex',
          alignItems: 'baseline',
          justifyContent: 'space-between',
          marginBottom: 24,
        }}
      >
        <div>
          <div
            style={{
              fontFamily: "'JetBrains Mono', monospace",
              fontSize: 11,
              letterSpacing: '0.14em',
              textTransform: 'uppercase',
              color: 'var(--text-faint)',
            }}
          >
            Credit marketplace
          </div>
          <div style={{ fontSize: 15, color: 'var(--text-dim)', marginTop: 3 }}>
            Surplus credit, routed to whoever runs out
          </div>
        </div>
        <span
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: 7,
            fontFamily: "'JetBrains Mono', monospace",
            fontSize: 12,
            color: 'var(--give)',
          }}
        >
          <span
            style={{
              width: 7,
              height: 7,
              borderRadius: '50%',
              background: 'var(--give)',
              animation: 'pulse 1.6s infinite',
              display: 'inline-block',
            }}
          />
          live
        </span>
      </div>

      {/* Flow row */}
      <div style={{ display: 'flex', alignItems: 'stretch', gap: 0 }}>
        {/* Supply column: Pledged + Retained */}
        <div
          style={{
            flex: '0 1 auto',
            display: 'flex',
            flexDirection: 'column',
            justifyContent: 'space-between',
            gap: 20,
            padding: '6px 0',
          }}
        >
          {/* Pledged */}
          <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
            <span
              style={{
                fontFamily: "'JetBrains Mono', monospace",
                fontSize: 11,
                letterSpacing: '0.12em',
                textTransform: 'uppercase',
                color: 'var(--text-faint)',
                display: 'flex',
                alignItems: 'center',
                gap: 7,
              }}
            >
              <span
                style={{
                  width: 8,
                  height: 8,
                  borderRadius: '50%',
                  background: 'var(--consume)',
                  display: 'inline-block',
                }}
              />
              Shared with the pool
              <InfoTip term="pool" />
            </span>
            <span
              style={{
                fontFamily: "'JetBrains Mono', monospace",
                fontWeight: 600,
                fontSize: 32,
                color: 'var(--consume)',
                lineHeight: 1,
              }}
            >
              {aiu(data.pledged)}
            </span>
            <span
              style={{
                fontFamily: "'JetBrains Mono', monospace",
                fontSize: 13,
                color: 'var(--text-faint)',
              }}
            >
              ≈ {eur(data.pledged)}
            </span>
            <span style={{ fontSize: 12.5, color: 'var(--text-dim)' }}>
              what Hosts set aside for everyone
            </span>
          </div>

          {/* Retained */}
          <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
            <span
              style={{
                fontFamily: "'JetBrains Mono', monospace",
                fontSize: 11,
                letterSpacing: '0.12em',
                textTransform: 'uppercase',
                color: 'var(--text-faint)',
                display: 'flex',
                alignItems: 'center',
                gap: 7,
              }}
            >
              Kept for themselves
              <InfoTip term="kept" />
            </span>
            <span
              style={{
                fontFamily: "'JetBrains Mono', monospace",
                fontWeight: 600,
                fontSize: 32,
                color: 'var(--text)',
                lineHeight: 1,
              }}
            >
              {aiu(data.retained)}
            </span>
            <span
              style={{
                fontFamily: "'JetBrains Mono', monospace",
                fontSize: 13,
                color: 'var(--text-faint)',
              }}
            >
              ≈ {eur(data.retained)}
            </span>
            <span style={{ fontSize: 12.5, color: 'var(--text-dim)' }}>
              each Host&apos;s own credits — not in the pool
            </span>
          </div>
        </div>

        {/* Connector → */}
        <div
          style={{
            flex: 1,
            minWidth: 56,
            padding: '0 16px',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
          }}
        >
          <div style={connector('var(--give)')} />
        </div>

        {/* Demand center */}
        <div
          style={{
            flexShrink: 0,
            display: 'flex',
            flexDirection: 'column',
            alignItems: 'center',
            justifyContent: 'center',
            gap: 10,
            padding: '0 6px',
          }}
        >
          <span
            style={{
              fontFamily: "'JetBrains Mono', monospace",
              fontSize: 11,
              letterSpacing: '0.12em',
              textTransform: 'uppercase',
              color: 'var(--text-faint)',
            }}
          >
            Demand
          </span>

          {/* Tile 1: open requests */}
          <div
            style={{
              width: 158,
              borderRadius: 14,
              border: '1px solid var(--border-strong)',
              background: 'var(--surface-2)',
              padding: '12px 14px',
            }}
          >
            <div style={{ display: 'flex', flexDirection: 'column', gap: 3 }}>
              <div style={{ display: 'flex', alignItems: 'baseline', gap: 8 }}>
                <span
                  style={{
                    fontFamily: "'JetBrains Mono', monospace",
                    fontWeight: 600,
                    fontSize: 34,
                    color: 'var(--accent)',
                    lineHeight: 1,
                  }}
                  data-testid="hero-open-count"
                >
                  {data.openCount}
                </span>
                <span
                  style={{
                    fontFamily: "'JetBrains Mono', monospace",
                    fontSize: 11,
                    color: 'var(--text-faint)',
                    whiteSpace: 'nowrap',
                  }}
                >
                  open · {_closedCount} closed
                </span>
              </div>
              <span
                style={{
                  fontFamily: "'JetBrains Mono', monospace",
                  fontSize: 11,
                  color: 'var(--text-dim)',
                  display: 'inline-flex',
                  alignItems: 'center',
                  gap: 5,
                }}
              >
                requests awaiting a supporter
                <InfoTip term="requests" />
              </span>
            </div>
          </div>

          {/* Tile 2: active non-PAT */}
          <div
            style={{
              width: 158,
              borderRadius: 14,
              border: '1px solid var(--border-strong)',
              background: 'var(--surface-2)',
              padding: '12px 14px',
            }}
          >
            <div style={{ display: 'flex', flexDirection: 'column', gap: 3 }}>
              <div style={{ display: 'flex', alignItems: 'baseline', gap: 6 }}>
                <span
                  style={{
                    fontFamily: "'JetBrains Mono', monospace",
                    fontWeight: 600,
                    fontSize: 26,
                    color: 'var(--reroute)',
                    lineHeight: 1.2,
                  }}
                >
                  {aiu(_poolAvailable)}
                </span>
              </div>
              <span
                style={{
                  fontFamily: "'JetBrains Mono', monospace",
                  fontSize: 11,
                  color: 'var(--text-dim)',
                  display: 'inline-flex',
                  alignItems: 'center',
                  gap: 5,
                }}
              >
                Left in the shared pool
                <InfoTip
                  title="Shared pool"
                  body="Credit Hosts pledged that nobody has drawn yet. Post a request and top it up from the pool yourself."
                />
              </span>
            </div>
          </div>

          <span
            onClick={() => navigate('/app/marketplace')}
            style={{
              fontSize: 12,
              color: 'var(--accent)',
              cursor: 'pointer',
              fontWeight: 600,
              fontFamily: "'JetBrains Mono', monospace",
              whiteSpace: 'nowrap',
            }}
          >
            open board →
          </span>
        </div>

        {/* Connector → */}
        <div
          style={{
            flex: 1,
            minWidth: 56,
            padding: '0 16px',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
          }}
        >
          <div style={connectorMix('var(--reroute)', 'var(--accent)')} />
        </div>

        {/* Recipients column: Rotated + Donated to non-PAT (right-aligned to mirror the left column → equal gap to center) */}
        <div
          style={{
            flex: '0 1 auto',
            display: 'flex',
            flexDirection: 'column',
            alignItems: 'flex-end',
            justifyContent: 'space-between',
            gap: 20,
            padding: '6px 0',
          }}
        >
          {/* Rotated */}
          <div style={{ display: 'flex', flexDirection: 'column', gap: 6, textAlign: 'right' }}>
            <span
              style={{
                fontFamily: "'JetBrains Mono', monospace",
                fontSize: 11,
                letterSpacing: '0.12em',
                textTransform: 'uppercase',
                color: 'var(--text-faint)',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'flex-end',
                gap: 7,
                whiteSpace: 'nowrap',
              }}
            >
              <span
                style={{
                  width: 8,
                  height: 8,
                  borderRadius: '50%',
                  background: 'var(--reroute)',
                  display: 'inline-block',
                }}
              />
              Routed to Hosts
              <InfoTip term="routed" />
            </span>
            <span
              style={{
                fontFamily: "'JetBrains Mono', monospace",
                fontWeight: 600,
                fontSize: 32,
                color: 'var(--reroute)',
                lineHeight: 1,
              }}
            >
              {aiu(data.rotated)}
            </span>
            <span
              style={{
                fontFamily: "'JetBrains Mono', monospace",
                fontSize: 13,
                color: 'var(--give)',
              }}
            >
              ≈ {eur(data.rotated)} saved
            </span>
            <span style={{ fontSize: 12.5, color: 'var(--text-dim)' }}>
              surplus passed between Hosts
            </span>
          </div>

          {/* Donated to non-PAT */}
          <div style={{ display: 'flex', flexDirection: 'column', gap: 6, textAlign: 'right' }}>
            <span
              style={{
                fontFamily: "'JetBrains Mono', monospace",
                fontSize: 11,
                letterSpacing: '0.12em',
                textTransform: 'uppercase',
                color: 'var(--text-faint)',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'flex-end',
                gap: 7,
                whiteSpace: 'nowrap',
              }}
            >
              <span
                style={{
                  width: 8,
                  height: 8,
                  borderRadius: '50%',
                  background: 'var(--consume)',
                  display: 'inline-block',
                }}
              />
              Chipped in to Guests
              <InfoTip term="chipIn" />
            </span>
            <span
              style={{
                fontFamily: "'JetBrains Mono', monospace",
                fontWeight: 600,
                fontSize: 32,
                color: 'var(--consume)',
                lineHeight: 1,
              }}
            >
              {aiu(data.donatedToNonPat)}
            </span>
            <span
              style={{
                fontFamily: "'JetBrains Mono', monospace",
                fontSize: 13,
                color: 'var(--give)',
              }}
            >
              ≈ {eur(data.donatedToNonPat)} saved
            </span>
            <span style={{ fontSize: 12.5, color: 'var(--text-dim)' }}>
              given to Guests
            </span>
          </div>
        </div>
      </div>
    </div>
  );
}
