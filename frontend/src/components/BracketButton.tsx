import type { ReactNode } from 'react';

export interface BracketButtonProps {
  /** Unique, descriptive id (project CLAUDE.md). */
  id: string;
  /** Button label, wrapped in brackets — `[ EXECUTE ]` (Guide §7.1). */
  children: ReactNode;
  onClick?: () => void;
  /** Disabled reads as muted with no fill/invert (Guide §7.1). */
  isDisabled?: boolean;
  /** `primary` inverts to green on hover; `destructive` borders + inverts red (Guide §7.1). */
  variant?: 'primary' | 'destructive';
  type?: 'button' | 'submit';
}

/**
 * A bracketed terminal button (Guide §7.1). Square, bordered, ALL-CAPS; hover fills with inverted
 * video — green for primary actions, red for destructive (chaos) ones, so destruction always reads
 * as deliberate.
 */
export function BracketButton({
  id,
  children,
  onClick,
  isDisabled = false,
  variant = 'primary',
  type = 'button',
}: BracketButtonProps) {
  let variantClasses: string;
  if (isDisabled) {
    variantClasses = 'border-muted text-muted cursor-not-allowed';
  } else if (variant === 'destructive') {
    variantClasses = 'border-error text-error hover:bg-error hover:text-bg';
  } else {
    variantClasses = 'border-fg text-fg hover:bg-fg hover:text-bg';
  }

  return (
    <button
      id={id}
      type={type}
      onClick={onClick}
      disabled={isDisabled}
      className={`border border-solid px-2 py-1 uppercase tracking-[0.02em] ${variantClasses}`}
    >
      [ {children} ]
    </button>
  );
}
