import { useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import type { CtcApi } from '@/api/CtcApi';
import type { PublicUserHit } from '@/domain/types';
import { Avatar } from '@/components/Avatar';

export function HeaderSearch({ api }: { api: Pick<CtcApi, 'searchUsers'> }) {
  const [q, setQ] = useState('');
  const [hits, setHits] = useState<PublicUserHit[]>([]);
  const [open, setOpen] = useState(false);
  const navigate = useNavigate();
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  // Monotonic query id: a slow earlier response must not overwrite a newer one.
  const seq = useRef(0);

  useEffect(() => {
    if (timer.current) clearTimeout(timer.current);
    const t = q.trim();
    if (!t) { setHits([]); setOpen(false); return; }
    const mine = ++seq.current;
    timer.current = setTimeout(async () => {
      try {
        const res = await api.searchUsers(t);
        if (mine === seq.current) { setHits(res); setOpen(true); }
      } catch {
        if (mine === seq.current) setHits([]);
      }
    }, 250);
    return () => { if (timer.current) clearTimeout(timer.current); };
  }, [q, api]);

  const go = (id: string) => { setQ(''); setHits([]); setOpen(false); navigate(`/app/users/${id}`); };

  return (
    <div style={{ position: 'relative', width: 280 }}>
      <input
        value={q}
        onChange={(e) => setQ(e.target.value)}
        onFocus={() => hits.length && setOpen(true)}
        onBlur={() => setTimeout(() => setOpen(false), 150)}
        placeholder="Search people…"
        style={{ width: '100%', background: 'var(--surface-2)', border: '1px solid var(--border)', borderRadius: 8, padding: '8px 12px', fontSize: 13, color: 'var(--text)' }}
      />
      {open && hits.length > 0 && (
        <div style={{ position: 'absolute', top: '110%', left: 0, right: 0, background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 10, padding: 6, zIndex: 50, boxShadow: '0 8px 24px rgba(0,0,0,0.18)' }}>
          {hits.map(h => (
            // A real <button> so results are keyboard-reachable (Tab + Enter),
            // not just mouse-clickable. onMouseDown fires before the input's blur
            // closes the dropdown; onClick covers keyboard activation.
            <button key={h.id} type="button" onMouseDown={() => go(h.id)} onClick={() => go(h.id)}
              style={{ display: 'flex', width: '100%', textAlign: 'left', background: 'transparent', border: 'none', alignItems: 'center', gap: 10, padding: '8px 10px', borderRadius: 8, cursor: 'pointer', color: 'var(--text)', fontFamily: 'inherit' }}>
              <Avatar initials={h.initials} size={28} />
              <div style={{ flex: 1 }}>
                <div style={{ fontSize: 13, fontWeight: 600 }}>{h.name}</div>
                <div style={{ fontSize: 11, color: 'var(--text-dim)' }}>@{h.login} · {h.role}</div>
              </div>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
