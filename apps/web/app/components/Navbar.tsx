"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { InboxIcon, CheckSquare, BarChart3, LogOut } from "lucide-react";

const links = [
  { href: "/",           label: "Inbox",    icon: InboxIcon },
  { href: "/approvals",  label: "Approvals",icon: CheckSquare },
  { href: "/admin",      label: "Metrics",  icon: BarChart3 },
];

export function Navbar({ userName }: { userName: string }) {
  const path = usePathname();
  return (
    <nav className="fixed left-0 top-0 h-full w-56 bg-gray-900 text-white flex flex-col z-10">
      <div className="px-4 py-5 border-b border-gray-700">
        <span className="text-lg font-semibold tracking-tight">Resolute</span>
        <p className="text-xs text-gray-400 mt-0.5 truncate">{userName}</p>
      </div>
      <div className="flex-1 py-4 space-y-1 px-2">
        {links.map(({ href, label, icon: Icon }) => (
          <Link
            key={href}
            href={href}
            className={`flex items-center gap-3 px-3 py-2 rounded-md text-sm transition-colors ${
              path === href
                ? "bg-gray-700 text-white"
                : "text-gray-300 hover:bg-gray-800 hover:text-white"
            }`}
          >
            <Icon size={16} />
            {label}
          </Link>
        ))}
      </div>
      <form action="/api/logout" method="POST" className="px-2 pb-4">
        <button
          type="submit"
          className="flex items-center gap-3 w-full px-3 py-2 rounded-md text-sm text-gray-400 hover:bg-gray-800 hover:text-white transition-colors"
        >
          <LogOut size={16} />
          Sign out
        </button>
      </form>
    </nav>
  );
}
