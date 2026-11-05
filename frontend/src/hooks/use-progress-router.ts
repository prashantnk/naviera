"use client";

import { triggerNavigationProgress } from "@/components/ui/navigation-progress";
import { useRouter } from "next/navigation";
import { useMemo } from "react";

type AppRouter = ReturnType<typeof useRouter>;

/**
 * `useRouter()` whose `push` / `replace` light the global navigation progress
 * bar before navigating, so programmatic navigations (row clicks, "save then
 * open the detail page") are acknowledged as instantly as `<Link>` clicks.
 *
 * @returns A router with the same API as `next/navigation`'s `useRouter`.
 */
export function useProgressRouter(): AppRouter {
  const router = useRouter();
  return useMemo<AppRouter>(
    () => ({
      ...router,
      push: (...args: Parameters<AppRouter["push"]>) => {
        triggerNavigationProgress(args[0]);
        router.push(...args);
      },
      replace: (...args: Parameters<AppRouter["replace"]>) => {
        triggerNavigationProgress(args[0]);
        router.replace(...args);
      },
    }),
    [router],
  );
}
