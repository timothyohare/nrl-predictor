"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const isNfl = (path: string | null) => path === "/nfl" || (path ?? "").startsWith("/nfl/");

/** NRL | NFL toggle in the site header. The NRL brand, nav and routes are unchanged. */
export default function SportSwitcher() {
  const nfl = isNfl(usePathname());
  const sports = [
    { label: "NRL", href: "/predictions/current", active: !nfl },
    { label: "NFL", href: "/nfl", active: nfl },
  ];

  return (
    <nav aria-label="Sport" className="flex rounded-md border-2 border-nrl-gold overflow-hidden text-xs font-display tracking-wider">
      {sports.map(({ label, href, active }) => (
        <Link
          key={label}
          href={href}
          aria-current={active ? "page" : undefined}
          className={`px-3 py-1 transition-colors focus-visible:outline focus-visible:outline-2 focus-visible:outline-white ${
            active ? "bg-nrl-gold text-nrl-blue" : "text-white hover:text-nrl-gold"
          }`}
        >
          {label}
        </Link>
      ))}
    </nav>
  );
}
