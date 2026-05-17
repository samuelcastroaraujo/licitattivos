import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "LicitAttivos — Dashboard de Decisão",
  description: "Sistema multi-agente de automação de licitações — Attivos Magisttrais Indústria e Comércio Ltda.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="pt-BR">
      <body style={{ background: "var(--bg-base)", minHeight: "100vh" }}>
        {children}
      </body>
    </html>
  );
}
