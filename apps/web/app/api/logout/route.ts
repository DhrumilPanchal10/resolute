import { NextResponse } from "next/server";
import { AUTH_COOKIE } from "@/app/lib/auth";

export async function POST() {
  const res = NextResponse.redirect(new URL("/login", "http://localhost:3000"));
  res.cookies.set(AUTH_COOKIE, "", { maxAge: 0, path: "/" });
  return res;
}
