import React from 'react';
import { useNavigate } from 'react-router-dom';

interface UserLinkProps {
  userId: string;
  name?: string;
  children?: React.ReactNode;
}

export function UserLink({ userId, name, children }: UserLinkProps) {
  const navigate = useNavigate();
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
