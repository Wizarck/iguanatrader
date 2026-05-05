import type { LayoutServerLoad } from './$types';

/**
 * Expose `event.locals.user` (set by `hooks.server.ts`) as page data
 * for any `(app)` route. Pages access via `page.data.user`.
 */
export const load: LayoutServerLoad = ({ locals }) => {
  return { user: locals.user };
};
