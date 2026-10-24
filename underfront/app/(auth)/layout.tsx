
import type { ReactNode } from "react";

export default function AuthLayout({
  children,
}: {
  children: ReactNode;
}) {
  return (
    <div className="relative min-h-screen">
      <a
        href="https://izolitra.github.io/"
        className="absolute left-4 top-5 z-10 block whitespace-nowrap text-[16px] font-semibold leading-[24.15px] tracking-[-0.23px] text-[rgba(12,12,12,0.9)] antialiased sm:left-8 sm:top-7"
        style={{
          fontFamily:
            'ppNeueMontreal, "ppNeueMontreal Fallback", sans-serif',
        }}
      >
        front - izolitra<span className="text-[rgb(255,192,125)]">.</span>
      </a>

      {children}
    </div>
  );
}
