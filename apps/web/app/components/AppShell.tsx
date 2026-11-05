"use client";

import { Navbar } from "./Navbar";

export function AppShell({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex min-h-screen">
      <Navbar userName="Demo User" />
      <main className="ml-60 flex-1 p-8 max-w-6xl">{children}</main>
    </div>
  );
}
