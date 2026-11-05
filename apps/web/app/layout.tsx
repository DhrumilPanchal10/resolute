import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Resolute — AI Support Resolution",
  description:
    "Multi-agent customer support resolution platform with triage, investigation, and human-in-the-loop approval",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body className="antialiased bg-gray-50 text-gray-900">
        {children}
      </body>
    </html>
  );
}
