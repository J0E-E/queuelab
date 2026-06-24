import { NavLink, Outlet } from 'react-router-dom';

import { Scanlines } from './components/Scanlines';

const NAV_ITEMS = [
  { to: '/', label: 'dashboard', end: true },
  { to: '/how-it-works', label: 'how it works', end: false },
  { to: '/how-i-work', label: 'how i work', end: false },
];

/**
 * The app shell shared by every route (Epic 16): the global `Scanlines` overlay mounted once, and
 * a header with the title and primary nav. The active route renders through `<Outlet>`.
 */
export function Layout() {
  return (
    <>
      <Scanlines />
      <div id="app-shell" className="mx-auto max-w-6xl p-6">
        <header
          id="app-header"
          className="mb-6 flex items-center justify-between border border-solid border-muted bg-bg-invert px-3 py-1 text-bg"
        >
          <span id="app-title" className="uppercase tracking-[0.02em]">
            [ QUEUELAB ]
          </span>
          <nav id="app-nav" aria-label="primary" className="flex gap-4 text-sm">
            {NAV_ITEMS.map((item) => (
              <NavLink
                key={item.to}
                id={`nav-link-${item.label.replaceAll(' ', '-')}`}
                to={item.to}
                end={item.end}
                className={({ isActive }) => (isActive ? 'underline' : 'no-underline')}
              >
                {item.label}
              </NavLink>
            ))}
          </nav>
        </header>
        <Outlet />
      </div>
    </>
  );
}
