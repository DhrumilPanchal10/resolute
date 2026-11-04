/**
 * Mock auth — a single hardcoded dev user stored in a cookie.
 * Swap this file's exports for Clerk (or any real auth) later:
 *   import { currentUser } from "@clerk/nextjs/server"
 */

export interface User {
  id: string;
  name: string;
  email: string;
  role: "admin" | "lead" | "support_engineer";
  tenant_id: string;
}

export const DEV_USER: User = {
  id: "user-dev-001",
  name: "Dev User",
  email: "dev@resolute.local",
  role: "lead",
  tenant_id: "tenant-demo",
};

export const AUTH_COOKIE = "resolute-auth";

/** Returns the signed-in user from the cookie, or null. (Server-side) */
export async function getUser(cookieHeader: string | null): Promise<User | null> {
  if (!cookieHeader) return null;
  const match = cookieHeader.match(new RegExp(`${AUTH_COOKIE}=([^;]+)`));
  if (!match) return null;
  try {
    return JSON.parse(decodeURIComponent(match[1])) as User;
  } catch {
    return null;
  }
}
