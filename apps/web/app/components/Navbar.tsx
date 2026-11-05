"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { Inbox, CheckSquare, BarChart3, Zap, ExternalLink } from "lucide-react";

const links = [
  { href: "/dashboard/",           label: "Inbox",     icon: Inbox },
  { href: "/dashboard/approvals/", label: "Approvals", icon: CheckSquare },
  { href: "/dashboard/metrics/",   label: "Metrics",   icon: BarChart3 },
];

export function Navbar({ userName }: { userName: string }) {
  const path = usePathname();
  return (
    <nav className="fixed left-0 top-0 h-full w-60 bg-gray-950 text-white flex flex-col z-20">
      <div className="px-5 py-5 border-b border-gray-800">
        <Link href="/" className="flex items-center gap-2.5">
          <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-blue-500 to-violet-600 flex items-center justify-center">
            <Zap size={16} className="text-white" />
          </div>
          <div>
            <span className="text-base font-bold tracking-tight">Resolute</span>
            <p className="text-[10px] text-gray-500 leading-none mt-0.5">AI Support Platform</p>
          </div>
        </Link>
      </div>

      <div className="flex-1 py-4 space-y-0.5 px-3">
        <p className="text-[10px] uppercase tracking-wider text-gray-600 font-semibold px-3 mb-2">
          Workspace
        </p>
        {links.map(({ href, label, icon: Icon }) => {
          const active = path === href || path === href.slice(0, -1);
          return (
            <Link
              key={href}
              href={href}
              className={`flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm transition-all ${
                active
                  ? "bg-gray-800 text-white font-medium"
                  : "text-gray-400 hover:bg-gray-900 hover:text-gray-200"
              }`}
            >
              <Icon size={16} className={active ? "text-blue-400" : ""} />
              {label}
            </Link>
          );
        })}
      </div>

      <div className="px-3 pb-4 space-y-2">
        <Link
          href="https://github.com/DhrumilPanchal10/resolute"
          target="_blank"
          className="flex items-center gap-2 px-3 py-2 text-xs text-gray-500 hover:text-gray-300 transition-colors"
        >
          <ExternalLink size={12} /> GitHub
        </Link>
        <div className="px-3 py-2 border-t border-gray-800">
          <p className="text-xs text-gray-500 truncate">{userName}</p>
          <p className="text-[10px] text-gray-600">tenant-demo</p>
        </div>
      </div>
    </nav>
  );
}
