import type { Metadata } from "next";

export const instant = false;
import { Geist, Geist_Mono } from "next/font/google";
import { cookies } from "next/headers";
import { getUser } from "@/app/lib/auth";
import { Navbar } from "@/app/components/Navbar";
import "./globals.css";

const geistSans = Geist({ variable: "--font-geist-sans", subsets: ["latin"] });
const geistMono = Geist_Mono({ variable: "--font-geist-mono", subsets: ["latin"] });

export const metadata: Metadata = {
  title: "Resolute",
  description: "Multi-agent customer support resolution",
};

export default async function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const cookieStore = await cookies();
  const cookieHeader = cookieStore.toString();
  const user = await getUser(cookieHeader);

  return (
    <html lang="en">
      <body className={`${geistSans.variable} ${geistMono.variable} antialiased bg-gray-50`}>
        {user ? (
          <div className="flex min-h-screen">
            <Navbar userName={user.name} />
            <main className="ml-56 flex-1 p-8">{children}</main>
          </div>
        ) : (
          <main>{children}</main>
        )}
      </body>
    </html>
  );
}
