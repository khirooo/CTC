import React from 'react';
import { useNavigate } from 'react-router-dom';

interface UserLinkProps {
  userId: string | null | undefined;
  name?: string;
  children?: React.ReactNode;
}

export function UserLink({ userId, name, children }: UserLinkProps) {
  const navigate = useNavigate();
  // No id → render plain text, not a link. Guards against click-through to
  // /app/users/null (e.g. a leaderboard/dashboard row with no resolvable user).
  if (!userId) return <span>{children ?? name}</span>;
  return (
    <span
      role="link"
      tabIndex={0}
      onClick={() => navigate(`/app/users/${userId}`)}
      onKeyDown={(e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault();
          navigate(`/app/users/${userId}`);
        }
      }}
      style={{ cursor: 'pointer', color: 'inherit', textDecoration: 'none' }}
      onMouseEnter={(e) => (e.currentTarget.style.textDecoration = 'underline')}
      onMouseLeave={(e) => (e.currentTarget.style.textDecoration = 'none')}
    >
      {children ?? name}
    </span>
  );
}
