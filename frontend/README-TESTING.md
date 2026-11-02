# Testing Infrastructure for Naviera Frontend

This project uses [Vitest](https://vitest.dev/) combined with [React Testing Library (RTL)](https://testing-library.com/docs/react-testing-library/intro/) to test Next.js App Router components.

## How to Run Tests

From the `frontend` directory:

```bash
# Run tests in watch mode (default)
npm run test

# Run tests once (CI mode)
npm run test -- --run
```

### Lightweight Verification Scripts

We provide dedicated verification scripts to ensure compilation, build validity, and page routing stability before pushing updates:

```bash
# 1. Typecheck / Compilation Verification
# Runs the TypeScript compiler in dry-run mode to catch syntax and type errors.
npm run test:compile

# 2. Production Build Verification
# Compiles and builds the production Next.js app to catch build-time configuration or serialization issues.
npm run test:build

# 3. Hermetic Route Smoke Testing
# Spins up a Next.js dev server alongside a native Node.js mock HTTP backend server on port 3003.
# Verifies that key landing, auth, tracking, and dashboard routes load successfully (status 2xx/3xx).
npm run test:smoke
```

## Writing Tests

1. Create a `.test.tsx` file next to your component (e.g. `button.test.tsx` for `button.tsx`).
2. Always import `render` and `screen` from our custom `test-utils.tsx`, **not** directly from `@testing-library/react`.

```tsx
// src/components/ui/button.test.tsx
import { render, screen } from "@/lib/test-utils";
import { Button } from "./button";
import { describe, it, expect } from "vitest";

describe("Button component", () => {
  it("renders correctly", () => {
    render(<Button>Click me</Button>);
    expect(screen.getByRole("button", { name: /click me/i })).toBeInTheDocument();
  });
});
```

### Why use `src/lib/test-utils.tsx`?

Our frontend application is an "Edge-Dynamic Monolith" relying on deep provider chains like `TenantProvider` (for themes/branding) and `QueryClientProvider` (for data fetching). 

By using the custom `render` function from `test-utils.tsx`, your components are automatically wrapped in these necessary providers, preventing runtime errors in tests.

## Mocks & Setup

- **Next.js App Router**: Navigation hooks (`useRouter`, `usePathname`, `useSearchParams`, `useParams`) are mocked globally in `vitest.setup.ts`. 
- **Path Aliases**: We configured path aliases (e.g. `@/*`) in `vitest.config.ts` so imports match the rest of the application.
