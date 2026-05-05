<script lang="ts">
  import { page } from '$app/state';
  import {
    Bell,
    Briefcase,
    Circle,
    Cpu,
    Gauge,
    PanelLeftClose,
    PanelLeftOpen,
    Search,
    Settings,
    SquareArrowOutUpRight,
    Wallet
  } from 'lucide-svelte';

  import { navStore } from '$lib/stores/nav.svelte';

  /**
   * Sidebar — dynamic enumeration via `import.meta.glob` (anti-collision).
   *
   * Per design D2: every `(app)/<name>/+page.svelte` module is enumerated
   * at compile time. Each module MAY export a top-level `meta` const:
   *
   * ```ts
   * export const meta = {
   *   label: 'Portfolio', icon: 'briefcase', order: 10
   * } as const;
   * ```
   *
   * Routes without `meta` get a fallback (capitalized segment, `circle`
   * icon, order 100). Sorted by `(meta.order, href)` ascending.
   *
   * Subsequent slices add `(app)/<name>/+page.svelte` and the Sidebar
   * picks them up with **zero edits to this file** — that is the
   * anti-collision contract.
   */

  type RouteMeta = {
    label: string;
    icon: string;
    order: number;
    requiresRole?: 'admin' | 'tenant_user' | 'god_admin';
  };

  type RouteModule = { meta?: RouteMeta };

  type Props = {
    user: App.Locals['user'];
  };

  let { user }: Props = $props();

  // `eager: true` resolves modules synchronously at build time so we
  // can read `meta` exports without an awaited async loop. Vite resolves
  // the glob against the project root.
  const routeModules = import.meta.glob<RouteModule>(
    '/src/routes/(app)/*/+page.svelte',
    { eager: true }
  );

  /**
   * Convert `/src/routes/(app)/portfolio/+page.svelte` → `/portfolio`.
   */
  function hrefFromKey(key: string): string {
    return key
      .replace(/^\/src\/routes\/\(app\)/, '')
      .replace(/\/\+page\.svelte$/, '');
  }

  function capitalize(value: string): string {
    if (value.length === 0) return value;
    return value[0].toUpperCase() + value.slice(1);
  }

  function fallbackMetaFor(href: string): RouteMeta {
    const segment = href.replace(/^\//, '').split('/')[0] || 'home';
    return {
      label: capitalize(segment),
      icon: 'circle',
      order: 100
    };
  }

  // Lucide icon name → component map. Adding a new icon means adding
  // an entry here AND consuming it via `meta.icon` in the consumer
  // route module.
  const ICON_MAP: Record<string, typeof Circle> = {
    briefcase: Briefcase,
    'arrow-up-right-from-square': SquareArrowOutUpRight,
    cpu: Cpu,
    search: Search,
    bell: Bell,
    gauge: Gauge,
    wallet: Wallet,
    settings: Settings,
    circle: Circle
  };

  function iconComponent(name: string) {
    return ICON_MAP[name] ?? Circle;
  }

  /**
   * Sorted entries: `[(href, meta)]` ordered by (order, href).
   * `$derived` so HMR-driven additions surface reactively.
   */
  const entries = $derived(
    Object.entries(routeModules)
      .map(([key, mod]) => {
        const href = hrefFromKey(key);
        const meta: RouteMeta = mod.meta ?? fallbackMetaFor(href);
        return { href, meta };
      })
      .sort((a, b) => {
        if (a.meta.order !== b.meta.order) {
          return a.meta.order - b.meta.order;
        }
        return a.href.localeCompare(b.href);
      })
  );

  function isActive(href: string): boolean {
    const path = page.url.pathname;
    if (href === '/') return path === '/';
    return path === href || path.startsWith(href + '/');
  }

  function toggleCollapsed(): void {
    navStore.collapsed = !navStore.collapsed;
  }
</script>

<nav
  class="sidebar"
  class:sidebar--collapsed={navStore.collapsed}
  aria-label="Primary"
>
  <div class="sidebar__brand">
    <span class="sidebar__brand-mark" aria-hidden="true">i</span>
    {#if !navStore.collapsed}
      <span class="sidebar__brand-text">iguanatrader</span>
    {/if}
  </div>

  <ul class="sidebar__items">
    {#each entries as { href, meta } (href)}
      {@const Icon = iconComponent(meta.icon)}
      {@const active = isActive(href)}
      <li>
        <a
          {href}
          class="sidebar__link"
          class:sidebar__link--active={active}
          aria-current={active ? 'page' : undefined}
          title={navStore.collapsed ? meta.label : undefined}
        >
          <span class="sidebar__icon" aria-hidden="true">
            <Icon size={18} strokeWidth={1.75} />
          </span>
          {#if !navStore.collapsed}
            <span class="sidebar__label">{meta.label}</span>
          {/if}
        </a>
      </li>
    {/each}
  </ul>

  <div class="sidebar__footer">
    {#if user && !navStore.collapsed}
      <div class="sidebar__user" aria-label="Signed in user">
        <span class="sidebar__user-email">{user.email}</span>
        <span class="sidebar__user-role">{user.role}</span>
      </div>
    {/if}
    <button
      type="button"
      class="sidebar__toggle"
      onclick={toggleCollapsed}
      aria-label={navStore.collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
      aria-expanded={!navStore.collapsed}
    >
      {#if navStore.collapsed}
        <PanelLeftOpen size={16} strokeWidth={1.75} />
      {:else}
        <PanelLeftClose size={16} strokeWidth={1.75} />
      {/if}
    </button>
  </div>
</nav>

<style>
  .sidebar {
    width: 240px;
    background: var(--surface);
    border-right: 1px solid var(--border);
    display: flex;
    flex-direction: column;
    padding: 16px 12px;
    transition: width 150ms ease;
  }
  .sidebar--collapsed {
    width: 64px;
  }

  .sidebar__brand {
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 4px 8px;
    margin-bottom: 16px;
  }
  .sidebar__brand-mark {
    width: 32px;
    height: 32px;
    background: var(--accent);
    border-radius: var(--r-2);
    display: inline-flex;
    align-items: center;
    justify-content: center;
    color: var(--accent-fg);
    font-weight: 700;
    font-size: 18px;
    flex-shrink: 0;
  }
  .sidebar__brand-text {
    font-size: 16px;
    font-weight: 600;
    color: var(--ink);
  }

  .sidebar__items {
    list-style: none;
    padding: 0;
    margin: 0;
    flex: 1;
    overflow-y: auto;
  }

  .sidebar__link {
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 8px 10px;
    margin-bottom: 2px;
    text-decoration: none;
    color: var(--mute);
    border-radius: var(--r-2);
    font-size: 13px;
    font-weight: 500;
    transition: background 100ms ease, color 100ms ease;
  }
  .sidebar__link:hover {
    background: var(--surface-2);
    color: var(--ink);
  }
  .sidebar__link--active {
    background: var(--surface-2);
    color: var(--accent);
  }
  .sidebar__icon {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 18px;
    height: 18px;
    flex-shrink: 0;
  }

  .sidebar__footer {
    border-top: 1px solid var(--border);
    padding-top: 12px;
    margin-top: 12px;
    display: flex;
    align-items: center;
    gap: 8px;
  }

  .sidebar__user {
    flex: 1;
    min-width: 0;
    display: flex;
    flex-direction: column;
  }
  .sidebar__user-email {
    font-size: 12px;
    color: var(--ink);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .sidebar__user-role {
    font-size: 10px;
    color: var(--mute);
    text-transform: uppercase;
    letter-spacing: 0.05em;
  }

  .sidebar__toggle {
    background: transparent;
    border: 1px solid var(--border);
    color: var(--mute);
    border-radius: var(--r-2);
    width: 32px;
    height: 32px;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    cursor: pointer;
    flex-shrink: 0;
  }
  .sidebar__toggle:hover {
    background: var(--surface-2);
    color: var(--ink);
  }
</style>
