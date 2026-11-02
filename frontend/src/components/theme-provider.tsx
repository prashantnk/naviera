// frontend/src/components/theme-provider.tsx
"use client";

import { isLowContrastWithWhite } from "@/components/settings/theme-presets";

export function ThemeProvider({
  primaryColor,
  secondaryColor,
}: {
  primaryColor?: string;
  secondaryColor?: string;
}) {
  if (!primaryColor) return null;

  const resolvedSecondary = secondaryColor || "#0f172a";
  const primaryForeground = isLowContrastWithWhite(primaryColor)
    ? "#0f172a"
    : "#ffffff";
  const secondaryForeground = isLowContrastWithWhite(resolvedSecondary)
    ? "#0f172a"
    : "#ffffff";

  return (
    <style
      dangerouslySetInnerHTML={{
        __html: `
          :root {
            --primary: ${primaryColor};
            --primary-foreground: ${primaryForeground};
            --secondary: ${resolvedSecondary};
            --secondary-foreground: ${secondaryForeground};
          }
        `,
      }}
    />
  );
}