import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = { title: "Daily Delivery", description: "Daily del equipo de Delivery de Forte" };

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="es">
      <head>
        <meta name="viewport" content="width=device-width, initial-scale=1" />
      </head>
      <body>{children}</body>
    </html>
  );
}
