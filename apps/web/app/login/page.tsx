"use client";

import { useRouter } from "next/navigation";
import { AUTH_COOKIE, DEV_USER } from "@/app/lib/auth";

export default function LoginPage() {
  const router = useRouter();

  function signIn() {
    document.cookie = `${AUTH_COOKIE}=${encodeURIComponent(
      JSON.stringify(DEV_USER)
    )}; path=/; max-age=86400`;
    router.push("/");
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-gray-50">
      <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-10 w-full max-w-sm text-center">
        <h1 className="text-2xl font-bold text-gray-900 mb-1">Resolute</h1>
        <p className="text-sm text-gray-500 mb-8">Multi-agent support platform</p>
        <button
          onClick={signIn}
          className="w-full bg-gray-900 text-white rounded-lg py-2.5 text-sm font-medium hover:bg-gray-700 transition-colors"
        >
          Sign in as Dev User
        </button>
        <p className="text-xs text-gray-400 mt-4">
          Mock auth — swap for Clerk in production
        </p>
      </div>
    </div>
  );
}
