import type { ButtonHTMLAttributes, ReactNode } from 'react';

interface Props extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: 'primary' | 'danger' | 'outline' | 'ghost' | 'default';
  size?: 'sm' | 'md' | 'lg';
  icon?: ReactNode;
  busy?: boolean;
  block?: boolean;
  iconOnly?: boolean;
}

export function Button({ variant = 'default', size = 'md', icon, busy, block, iconOnly, children, className, disabled,
  type = 'button', ...rest }: Props) {
  const classes = ['btn', variant !== 'default' && `btn-${variant}`, size !== 'md' && `btn-${size}`, block && 'btn-block',
    iconOnly && 'btn-icon', className].filter(Boolean).join(' ');
  return (
    <button type={type} className={classes} disabled={disabled || busy} aria-busy={busy || undefined} {...rest}>
      {busy ? <span className="spinner" aria-hidden /> : icon}
      {iconOnly ? <span className="sr-only">{children}</span> : children}
    </button>
  );
}
