// verified: /vercel/next.js/v15.1.11 — App Router root layout pattern
export const metadata = {
  title: "Codebase Q&A Agent",
  description: "Agentic Q&A over a public GitHub codebase",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body
        style={{
          margin: 0,
          fontFamily:
            "-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif",
          background: "#fafafa",
          color: "#111",
        }}
      >
        {children}
      </body>
    </html>
  );
}
