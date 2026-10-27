import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Walkdown",
  description: "Inspection video to a verified defect register and a solver-optimal maintenance plan.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
