import { aiu, euros, NANO_PER_AIU } from '@/domain/credit';
import type { CycleReport } from '@/domain/types';
import { monoLabel } from '@/theme/styles';
import { InfoTip } from '@/components/InfoTip';

/** One KPI card in the cycle-summary stat row (mono value; optional bar/sub below). */
function StatCard({ label, value, children, infoTip }: {
  label: string;
  value: React.ReactNode;
  children?: React.ReactNode;
  infoTip?: React.ReactNode;
}) {
  return (
    <div style={{ background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 14, padding: '18px 20px' }}>
      <div style={{ ...monoLabel, display: 'inline-flex', alignItems: 'center', gap: 5 }}>
        {label}
        {infoTip}
      </div>
      <div style={{ fontFamily: "'JetBrains Mono', monospace", fontWeight: 600, fontSize: 26, marginTop: 8 }}>
        {value}
      </div>
      {children}
    </div>
  );
}

export function CycleDetail({ report, rate }: { report: CycleReport; rate?: number }) {
  const fillRate = Math.round((report.reqFilled / Math.max(1, report.reqTotal)) * 100);
  const patPct = Math.round((report.reqPat / Math.max(1, report.reqFilled)) * 100);
  const nonPatPct = Math.round((report.reqNonPat / Math.max(1, report.reqFilled)) * 100);

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 18 }}>
      {/* KPI flow summary */}
      <div
        style={{
          background: 'var(--surface)',
          border: '1px solid var(--border)',
          borderRadius: 18,
          padding: '26px 28px',
          boxShadow: 'var(--shadow)',
        }}
      >
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
              {report.label} · cycle summary <InfoTip term="cycle" />
            </div>
            <div style={{ fontSize: 15, color: 'var(--text-dim)', marginTop: 3 }}>
              Where credits came from and where they went
            </div>
          </div>
          <span
            style={{
              fontFamily: "'JetBrains Mono', monospace",
              fontSize: 12,
              color: 'var(--text-faint)',
              padding: '4px 10px',
              border: '1px solid var(--border)',
              borderRadius: 7,
            }}
          >
            closed
          </span>
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: 0 }}>
          {/* Pledged */}
          <div style={{ flex: '0 1 auto', display: 'flex', flexDirection: 'column', gap: 10, padding: '4px 0' }}>
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
              Shared with the pool
              <InfoTip term="pledge" />
            </span>
            <span
              style={{
                fontFamily: "'JetBrains Mono', monospace",
                fontWeight: 600,
                fontSize: 36,
                color: 'var(--text)',
                lineHeight: 1,
              }}
            >
              {aiu(report.pledged)}
            </span>
            <span style={{ fontSize: 13, color: 'var(--text-dim)' }}>
              total set aside by Hosts · <span style={{ color: 'var(--give)' }}>≈ {euros(report.pledged, rate)}</span>
            </span>
          </div>

          {/* Arrow */}
          <div style={{ flex: 1, minWidth: 56, padding: '0 16px', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
            <div
              style={{
                width: '100%',
                height: 3,
                backgroundImage: 'linear-gradient(90deg,var(--give) 60%,transparent 0)',
                backgroundSize: '14px 3px',
                backgroundRepeat: 'repeat-x',
                opacity: 0.6,
              }}
            />
          </div>

          {/* Actually donated */}
          <div
            style={{
              flex: 'none',
              display: 'flex',
              flexDirection: 'column',
              alignItems: 'center',
              gap: 8,
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
                display: 'flex',
                alignItems: 'center',
                gap: 4,
              }}
            >
              Actually chipped in
              <InfoTip term="chipIn" />
            </span>
            <div
              style={{
                minWidth: 148,
                height: 96,
                borderRadius: 14,
                border: '1px solid var(--border-strong)',
                background: 'var(--give-soft)',
                display: 'flex',
                flexDirection: 'column',
                alignItems: 'center',
                justifyContent: 'center',
                gap: 3,
                padding: '0 16px',
              }}
            >
              <span
                style={{
                  fontFamily: "'JetBrains Mono', monospace",
                  fontWeight: 600,
                  fontSize: 34,
                  color: 'var(--give)',
                  lineHeight: 1,
                  whiteSpace: 'nowrap',
                }}
              >
                {/* number only — the pill's label, green highlight and euros line
                    already carry the unit; keeps the hero on one line. */}
                {(report.donated / NANO_PER_AIU).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                <span style={{ fontSize: 16, marginLeft: 5 }}>AIU</span>
              </span>
              <span
                style={{
                  fontSize: 11,
                  color: 'var(--give)',
                  fontFamily: "'JetBrains Mono', monospace",
                }}
              >
                ≈ {euros(report.donated, rate)} saved
              </span>
            </div>
            {/* Invisible twin of the label above, so the box is the column's
                true vertical center — keeps it level with the connectors and
                the left/right values (which center on the row's midline). */}
            <span
              aria-hidden="true"
              style={{
                fontFamily: "'JetBrains Mono', monospace",
                fontSize: 11,
                letterSpacing: '0.12em',
                textTransform: 'uppercase',
                visibility: 'hidden',
              }}
            >
              Actually chipped in
            </span>
          </div>

          {/* Arrow */}
          <div style={{ flex: 1, minWidth: 56, padding: '0 16px', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
            <div
              style={{
                width: '100%',
                height: 3,
                backgroundImage:
                  'linear-gradient(90deg,var(--reroute) 0 30%,transparent 30% 50%,var(--accent) 50% 80%,transparent 80%)',
                backgroundSize: '28px 3px',
                backgroundRepeat: 'repeat-x',
                opacity: 0.6,
              }}
            />
          </div>

          {/* PAT / non-PAT split — right-aligned to mirror the left value, with
              the connectors stretching to fill the gap (matches the dashboard hero). */}
          <div
            style={{
              flex: '0 1 auto',
              display: 'flex',
              flexDirection: 'column',
              alignItems: 'flex-end',
              justifyContent: 'center',
              gap: 14,
            }}
          >
            <div style={{ textAlign: 'right' }}>
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'flex-end', gap: 10 }}>
                <span style={{ width: 9, height: 9, borderRadius: '50%', background: 'var(--reroute)', flex: 'none' }} />
                <span
                  style={{
                    fontFamily: "'JetBrains Mono', monospace",
                    fontWeight: 600,
                    fontSize: 22,
                    color: 'var(--text)',
                  }}
                >
                  {aiu(report.toPat)}
                </span>
              </div>
              <div style={{ fontSize: 12, color: 'var(--text-dim)', marginTop: 3 }}>
                routed to Hosts <InfoTip term="routed" /> · <span style={{ color: 'var(--give)' }}>≈ {euros(report.toPat, rate)}</span>
              </div>
            </div>
            <div style={{ textAlign: 'right' }}>
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'flex-end', gap: 10 }}>
                <span style={{ width: 9, height: 9, borderRadius: '50%', background: 'var(--consume)', flex: 'none' }} />
                <span
                  style={{
                    fontFamily: "'JetBrains Mono', monospace",
                    fontWeight: 600,
                    fontSize: 22,
                    color: 'var(--text)',
                  }}
                >
                  {aiu(report.toNonPat)}
                </span>
              </div>
              <div style={{ fontSize: 12, color: 'var(--text-dim)', marginTop: 3 }}>
                transferred to Guests · <span style={{ color: 'var(--give)' }}>≈ {euros(report.toNonPat, rate)}</span>
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* Stat row */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 16 }}>
        <StatCard label="Requests covered" value={report.reqFilled}>
          <div style={{ fontSize: 12, color: 'var(--text-dim)', marginTop: 4 }}>covered this cycle</div>
        </StatCard>
        <StatCard
          label="Fulfillment rate"
          value={`${fillRate}%`}
          infoTip={
            <InfoTip
              title="Fulfillment rate"
              body="Share of requests that got fully covered before expiring."
            />
          }
        >
          <div
            style={{
              height: 5,
              borderRadius: 3,
              background: 'var(--surface-3)',
              overflow: 'hidden',
              marginTop: 9,
            }}
          >
            <div style={{ height: '100%', width: `${fillRate}%`, background: 'var(--give)' }} />
          </div>
        </StatCard>
        <StatCard
          label="Unused budget"
          value={aiu(report.budgetTotal - report.usedTotal)}
          infoTip={
            <InfoTip
              title="Unused budget"
              body="Credits the whole team had this cycle but never used — quota that expired on the reset."
            />
          }
        >
          <div style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 12, color: 'var(--give)', marginTop: 3 }}>
            ≈ {euros(report.budgetTotal - report.usedTotal, rate)}
          </div>
          <div style={{ fontSize: 12, color: 'var(--text-dim)', marginTop: 4 }}>
            {aiu(report.usedTotal)} of {aiu(report.budgetTotal)} used
          </div>
        </StatCard>
      </div>

      {/* Fills + Winners — same 1.55fr 1fr split as the dashboard's bottom row
          so the right-hand leaderboard rail lines up across pages. */}
      <div style={{ display: 'grid', gridTemplateColumns: '1.55fr 1fr', gap: 16 }}>
        {/* Requests filled by type */}
        <div
          style={{
            background: 'var(--surface)',
            border: '1px solid var(--border)',
            borderRadius: 16,
            padding: '22px 24px',
            display: 'flex',
            flexDirection: 'column',
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 20 }}>
            <span
              style={{
                width: 30,
                height: 30,
                borderRadius: 8,
                background: 'var(--give-soft)',
                color: 'var(--give)',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                fontSize: 15,
              }}
            >
              ✓
            </span>
            <div>
              <div style={{ fontWeight: 600, fontSize: 15 }}>Requests covered</div>
              <div style={{ fontSize: 12, color: 'var(--text-dim)' }}>split by requester type</div>
            </div>
          </div>
          <div style={{ display: 'flex', alignItems: 'flex-end', gap: 8, marginBottom: 18 }}>
            <span
              style={{
                fontFamily: "'JetBrains Mono', monospace",
                fontWeight: 600,
                fontSize: 42,
                color: 'var(--text)',
                lineHeight: 1,
              }}
            >
              {report.reqFilled}
            </span>
            <span
              style={{
                fontFamily: "'JetBrains Mono', monospace",
                fontSize: 14,
                color: 'var(--text-faint)',
                marginBottom: 4,
              }}
            >
              requests covered
            </span>
          </div>
          <div
            style={{
              display: 'flex',
              height: 10,
              borderRadius: 5,
              overflow: 'hidden',
              background: 'var(--surface-3)',
              marginBottom: 18,
            }}
          >
            <div style={{ width: `${patPct}%`, background: 'var(--reroute)' }} />
            <div style={{ width: `${nonPatPct}%`, background: 'var(--consume)' }} />
          </div>
          <div style={{ display: 'flex', gap: 16 }}>
            <div style={{ flex: 1, display: 'flex', alignItems: 'center', gap: 10 }}>
              <span
                style={{
                  width: 9,
                  height: 9,
                  borderRadius: '50%',
                  background: 'var(--reroute)',
                  flex: 'none',
                }}
              />
              <div style={{ flex: 1 }}>
                <div
                  style={{
                    fontFamily: "'JetBrains Mono', monospace",
                    fontWeight: 600,
                    fontSize: 24,
                    color: 'var(--text)',
                  }}
                >
                  {report.reqPat}
                </div>
                <div style={{ fontSize: 12, color: 'var(--text-dim)' }}>Host requests</div>
              </div>
            </div>
            <div style={{ flex: 1, display: 'flex', alignItems: 'center', gap: 10 }}>
              <span
                style={{
                  width: 9,
                  height: 9,
                  borderRadius: '50%',
                  background: 'var(--consume)',
                  flex: 'none',
                }}
              />
              <div style={{ flex: 1 }}>
                <div
                  style={{
                    fontFamily: "'JetBrains Mono', monospace",
                    fontWeight: 600,
                    fontSize: 24,
                    color: 'var(--text)',
                  }}
                >
                  {report.reqNonPat}
                </div>
                <div style={{ fontSize: 12, color: 'var(--text-dim)' }}>Guest requests</div>
              </div>
            </div>
          </div>

          {/* Top fillers */}
          {report.fills.length > 0 && (
            <div style={{ marginTop: 20, borderTop: '1px solid var(--border)', paddingTop: 16 }}>
              <div
                style={{
                  fontFamily: "'JetBrains Mono', monospace",
                  fontSize: 10,
                  letterSpacing: '0.12em',
                  textTransform: 'uppercase',
                  color: 'var(--text-faint)',
                  marginBottom: 10,
                }}
              >
                Top supporters
              </div>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                {report.fills.map((fill) => (
                  <div key={fill.who} style={{ display: 'flex', alignItems: 'center', gap: 10, fontSize: 13 }}>
                    <span style={{ flex: 1 }}>{fill.who}</span>
                    <span
                      style={{
                        fontFamily: "'JetBrains Mono', monospace",
                        color: 'var(--give)',
                        fontWeight: 600,
                      }}
                    >
                      {aiu(fill.amount)}
                    </span>
                    <span style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 11, color: 'var(--text-faint)' }}>
                      ×{fill.count}
                    </span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>

        {/* Cycle winners */}
        <div
          style={{
            background: 'var(--surface)',
            border: '1px solid var(--border)',
            borderRadius: 16,
            padding: '22px 24px',
          }}
        >
          <div style={{ fontWeight: 600, fontSize: 15, marginBottom: 4 }}>Cycle winners</div>
          <div style={{ fontSize: 12, color: 'var(--text-dim)', marginBottom: 18 }}>
            leaderboard champions for {report.label}
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
            {/* Most generous */}
            <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
              <span
                style={{
                  width: 30,
                  height: 30,
                  borderRadius: 8,
                  background: 'var(--give-soft)',
                  color: 'var(--give)',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  fontSize: 14,
                  flex: 'none',
                }}
              >
                ♥
              </span>
              <div style={{ flex: 1, minWidth: 0 }}>
                <div
                  style={{
                    fontFamily: "'JetBrains Mono', monospace",
                    fontSize: 10,
                    letterSpacing: '0.1em',
                    textTransform: 'uppercase',
                    color: 'var(--text-faint)',
                  }}
                >
                  Most generous
                </div>
                <div
                  style={{
                    fontSize: 13.5,
                    fontWeight: 600,
                    whiteSpace: 'nowrap',
                    overflow: 'hidden',
                    textOverflow: 'ellipsis',
                  }}
                >
                  {report.winners.generous.name}
                </div>
              </div>
              <span
                style={{
                  fontFamily: "'JetBrains Mono', monospace",
                  fontWeight: 600,
                  color: 'var(--give)',
                }}
              >
                {aiu(report.winners.generous.value)}
              </span>
            </div>

            {/* Top pro */}
            <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
              <span
                style={{
                  width: 30,
                  height: 30,
                  borderRadius: 8,
                  background: 'var(--reroute-soft)',
                  color: 'var(--reroute)',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  fontSize: 14,
                  flex: 'none',
                }}
              >
                ◆
              </span>
              <div style={{ flex: 1, minWidth: 0 }}>
                <div
                  style={{
                    fontFamily: "'JetBrains Mono', monospace",
                    fontSize: 10,
                    letterSpacing: '0.1em',
                    textTransform: 'uppercase',
                    color: 'var(--text-faint)',
                  }}
                >
                  Top Host (by usage)
                </div>
                <div
                  style={{
                    fontSize: 13.5,
                    fontWeight: 600,
                    whiteSpace: 'nowrap',
                    overflow: 'hidden',
                    textOverflow: 'ellipsis',
                  }}
                >
                  {report.winners.pro.name}
                </div>
              </div>
              <span
                style={{
                  fontFamily: "'JetBrains Mono', monospace",
                  fontWeight: 600,
                  color: 'var(--reroute)',
                }}
              >
                {aiu(report.winners.pro.value)}
              </span>
            </div>

            {/* Top noob */}
            <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
              <span
                style={{
                  width: 30,
                  height: 30,
                  borderRadius: 8,
                  background: 'var(--consume-soft)',
                  color: 'var(--consume)',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  fontSize: 14,
                  flex: 'none',
                }}
              >
                ▲
              </span>
              <div style={{ flex: 1, minWidth: 0 }}>
                <div
                  style={{
                    fontFamily: "'JetBrains Mono', monospace",
                    fontSize: 10,
                    letterSpacing: '0.1em',
                    textTransform: 'uppercase',
                    color: 'var(--text-faint)',
                  }}
                >
                  Top Guest
                </div>
                <div
                  style={{
                    fontSize: 13.5,
                    fontWeight: 600,
                    whiteSpace: 'nowrap',
                    overflow: 'hidden',
                    textOverflow: 'ellipsis',
                  }}
                >
                  {report.winners.noob.name}
                </div>
              </div>
              <span
                style={{
                  fontFamily: "'JetBrains Mono', monospace",
                  fontWeight: 600,
                  color: 'var(--consume)',
                }}
              >
                {aiu(report.winners.noob.value)}
              </span>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
