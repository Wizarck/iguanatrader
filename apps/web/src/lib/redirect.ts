/**
 * Defense-in-depth `redirect_to` allow-list.
 *
 * Per design D9 (slice 4 `auth-jwt-cookie`): the canonical allow-list
 * is enforced at the SvelteKit form-action layer (this function); the
 * FastAPI side ALSO applies the same check as belt-and-suspenders.
 *
 * Acceptable values: a single leading `/` followed by anything that is
 * NOT another `/`, NOT contains `://`, NOT contains a backslash. Any
 * other value falls back to `/`.
 */
export function safeRedirectTo(value: string | null | undefined): string {
  if (!value) return '/';
  if (!value.startsWith('/')) return '/';
  if (value.startsWith('//')) return '/';
  if (value.includes('://')) return '/';
  if (value.includes('\\')) return '/';
  return value;
}
