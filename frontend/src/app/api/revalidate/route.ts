// frontend/src/app/api/revalidate/route.ts

import { revalidatePath, revalidateTag } from "next/cache";
import { NextRequest, NextResponse } from "next/server";

const SHARED_SECRET = process.env.REVALIDATION_SECRET || "naviera-super-secret-key";

/**
 * GET /api/revalidate?secret=...&key=...
 * Evicts cache selectively:
 * - If `key` (tenant slug) is provided: purges cached profile for that tenant specifically via revalidateTag.
 * - If `key` is omitted: purges all layout and page caches across the entire portal.
 */
export async function GET(request: NextRequest) {
  const { searchParams } = new URL(request.url);
  const secret = searchParams.get("secret");
  const key = searchParams.get("key");

  if (secret !== SHARED_SECRET) {
    return NextResponse.json({ message: "Invalid secret token" }, { status: 401 });
  }

  try {
    if (key) {
      // Purge using custom revalidateTag signature with string profile
      revalidateTag(`tenant-${key}`, "default");
      return NextResponse.json({
        revalidated: true,
        scope: `tenant-${key}`,
        message: `Successfully evicted cache for tag: tenant-${key}`,
      });
    } else {
      // Purge all routes
      revalidatePath("/", "layout");
      return NextResponse.json({
        revalidated: true,
        scope: "all",
        message: "Successfully evicted all layout and page caches.",
      });
    }
  } catch (err) {
    return NextResponse.json(
      {
        message: "Failed to revalidate",
        error: err instanceof Error ? err.message : String(err),
      },
      { status: 500 }
    );
  }
}

/**
 * POST /api/revalidate
 * For programmatic webhooks from backend services.
 * Body parameters: { "secret": "...", "key": "..." }
 */
export async function POST(request: NextRequest) {
  try {
    const body = await request.json();
    const secret = body.secret;
    const key = body.key;

    if (secret !== SHARED_SECRET) {
      return NextResponse.json({ message: "Invalid secret token" }, { status: 401 });
    }

    if (key) {
      revalidateTag(`tenant-${key}`, "default");
      return NextResponse.json({
        revalidated: true,
        scope: `tenant-${key}`,
        message: `Successfully evicted cache for tag: tenant-${key}`,
      });
    } else {
      revalidatePath("/", "layout");
      return NextResponse.json({
        revalidated: true,
        scope: "all",
        message: "Successfully evicted all layout and page caches.",
      });
    }
  } catch (err) {
    return NextResponse.json(
      {
        message: "Failed to revalidate",
        error: err instanceof Error ? err.message : String(err),
      },
      { status: 500 }
    );
  }
}
