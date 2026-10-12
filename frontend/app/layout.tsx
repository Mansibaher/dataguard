import "./globals.css";
import type { Metadata } from "next";
export const metadata: Metadata = {
  title: "DataGuard — Pipeline health",
  description: "Data quality, durable processing, and evidence you can trust.",
};
export default function Layout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
