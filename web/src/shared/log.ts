// Browser-side diagnostics in one place. Development builds print everything; a production build
// prints only errors, since a visitor's console is not a log anyone reads. Server-side failures
// are logged by the API under the request id that ApiError carries.

const DEV = import.meta.env.DEV;

const tag = (scope: string) => `[stf:${scope}]`;

export const log = {
  debug: (scope: string, ...args: unknown[]) => { if (DEV) console.debug(tag(scope), ...args); },
  warn: (scope: string, ...args: unknown[]) => { if (DEV) console.warn(tag(scope), ...args); },
  error: (scope: string, ...args: unknown[]) => { console.error(tag(scope), ...args); },
};

/** A `.catch` handler for best-effort work (a beacon, a courtesy fetch, closing audio): the
    failure changes nothing for the visitor, so it resolves to `fallback`, and dev builds still
    show what failed. */
export function quiet<T = undefined>(scope: string, fallback?: T): (err: unknown) => T {
  return (err) => {
    log.debug(scope, "ignored failure:", err);
    return fallback as T;
  };
}
