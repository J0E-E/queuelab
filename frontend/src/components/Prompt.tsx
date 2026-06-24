export interface PromptProps {
  /** Unique, descriptive id (project CLAUDE.md). */
  id: string;
  /** The guest handle shown before the host, in its guest color (e.g. `guest-amber`). */
  user?: string;
  /** Host segment — defaults to the project name. */
  host?: string;
  /** Path segment — defaults to the home `~`. */
  path?: string;
  /** Prompt symbol — `$`, `>`, or `~` (Guide §4.1). */
  symbol?: string;
  /** Append the signature blinking block cursor (Guide §7.3). */
  hasCursor?: boolean;
}

/**
 * A shell prompt lead-in — `guest-amber@queuelab:~$ ` (Guide §7.3). Forms and command lines render
 * this before their input so the UI reads like typing into a terminal rather than a web form.
 */
export function Prompt({
  id,
  user,
  host = 'queuelab',
  path = '~',
  symbol = '$',
  hasCursor = false,
}: PromptProps) {
  return (
    <span id={id} className="text-fg-dim">
      {user ? <span className="text-fg">{user}</span> : null}
      {user ? '@' : null}
      {host}:{path}
      {symbol} {hasCursor ? <span className="animate-blink text-accent">█</span> : null}
    </span>
  );
}
