// frontend/src/components/theme-provider.tsx
"use client";

export function ThemeProvider({
  primaryColor,
  secondaryColor
}: {
  primaryColor?: string;
  secondaryColor?: string;
}) {
  if (!primaryColor) return null;

  return (
    <style
      dangerouslySetInnerHTML={{
        __html: `
          :root {
            --primary: ${primaryColor};
            --secondary: ${secondaryColor || '#0f172a'};
          }
        `,
      }}
    />
  );
}