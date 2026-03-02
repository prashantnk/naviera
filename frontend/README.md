# Naviera Frontend 🚢

This directory contains the Next.js 15 application. It is an **Edge-Dynamic Monolith**, meaning it serves all tenants (Naviera, Logismart, etc.) from a single codebase using Next.js Middleware to rewrite URLs based on subdomains or paths.

## 💻 Local Setup

1.  **Install Dependencies:**
    ```bash
    npm install
    ```

2.  **Set up Environment Variables:**
    Copy the example environment file and fill in your Supabase variables.
    ```bash
    cp .env.example .env.local
    ```

3.  **Run the Development Server:**
    ```bash
    npm run dev
    ```
    The application will be available at `http://localhost:3000`.

## 🔄 Syncing the UI with the Backend (OpenAPI)

We use an auto-generated TypeScript client to ensure strict typing between our Python backend and React frontend.

**Rule:** Whenever you add a new FastAPI endpoint, change a Pydantic schema, or update a database model, you must regenerate the frontend API client.

### The Sync Command

Ensure your FastAPI server is running locally on port 8000, then run the following command from the `frontend/` directory:

```bash
unset LD_LIBRARY_PATH && curl -s http://127.0.0.1:8000/openapi.json > openapi.json && npx openapi-typescript-codegen --input ./openapi.json --output ./src/api_client --client fetch && rm openapi.json
```

**Why `unset LD_LIBRARY_PATH`?**
If you are developing inside a Linux container, Project IDX, or NixOS, system-level library paths can sometimes interfere with Node.js network requests or `curl` calls to `localhost`. Unsetting this variable temporarily for the command ensures the JSON schema is fetched securely without runtime conflicts.

## 🎨 Theming System (Chameleon Architecture)

Tenant themes are not hardcoded. They are injected dynamically at runtime based on the database configuration.

-   **Global Injection:** CSS variables are injected via `src/components/theme-provider.tsx` inside the root layout.
-   **Tailwind Integration:** We mapped these CSS variables to Tailwind classes in `globals.css` (e.g., `--primary`).
-   **Design Rule:** Never use hardcoded colors (like `bg-red-500` or `text-blue-600`) for primary branding elements. Always use Tailwind's semantic classes: `bg-primary`, `text-primary`, `bg-secondary`, or `text-primary-foreground`. This ensures the UI instantly adapts when a new tenant logs in.

## 🔐 Authentication

This project uses Supabase for authentication. User sessions are managed through Next.js Middleware and a Higher-Order Component (HOC).

-   `src/middleware.ts`: Intercepts requests to protect routes and handle session refresh logic based on the tenant.
-   `src/components/auth/auth-guard.tsx`: A client-side component that wraps protected pages, redirecting unauthenticated users to the login page.

## 📂 Folder Structure

A brief overview of the key directories in the `frontend` application.

-   `src/app`: Contains the application's routes, following the Next.js App Router convention. The `[tenant_slug]` dynamic segment is key to the multi-tenant architecture.
-   `src/api_client`: Houses the auto-generated TypeScript client for interacting with the backend API. **Do not edit this directory manually.**
-   `src/components`: Contains reusable React components, organized into `ui` (generic, unstyled components from shadcn/ui) and `blocks` (larger, more complex components making up sections of a page).
-   `src/lib`: A place for utility functions, API configuration (`api.ts`), and Supabase client initialization (`supabase.ts`).
-   `public`: Stores static assets like images, SVGs, and fonts.
