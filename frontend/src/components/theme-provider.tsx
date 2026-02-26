// src/components/theme-provider.tsx

export function ThemeProvider({ primaryColor }: { primaryColor?: string }) {
  if (!primaryColor) return null;

  // We inject a global style tag that overrides the Tailwind CSS variable.
  // This instantly changes the theme across the entire application at runtime.
  return (
    <style
      dangerouslySetInnerHTML={{
        __html: `
          :root {
            --primary: ${primaryColor};
          }
        `,
      }}
    />
  );
}