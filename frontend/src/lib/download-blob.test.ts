// frontend/src/lib/download-blob.test.ts
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { OBJECT_URL_REVOKE_DELAY_MS, isInAppBrowser, saveBlobAsFile } from "./download-blob";

const DESKTOP_CHROME_UA =
  "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36";
const IOS_SAFARI_UA =
  "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1";
const WHATSAPP_UA =
  "Mozilla/5.0 (Linux; Android 14; SM-A145F Build/UP1A; wv) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/130.0 Mobile Safari/537.36 WhatsApp/2.24";
const GMAIL_IOS_UA =
  "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 GmailApp/6.0";
const OBJECT_URL = "blob:http://localhost/abc";

describe("isInAppBrowser", () => {
  it.each([
    [DESKTOP_CHROME_UA, false],
    [IOS_SAFARI_UA, false],
    [WHATSAPP_UA, true],
    [GMAIL_IOS_UA, true],
  ])("classifies %s", (ua, expected) => {
    expect(isInAppBrowser(ua)).toBe(expected);
  });
});

describe("saveBlobAsFile", () => {
  let createObjectURL: ReturnType<typeof vi.fn>;
  let revokeObjectURL: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    vi.useFakeTimers();
    createObjectURL = vi.fn(() => OBJECT_URL);
    revokeObjectURL = vi.fn();
    Object.assign(window.URL, { createObjectURL, revokeObjectURL });
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it("clicks a download link and revokes the URL only after the delay", () => {
    vi.spyOn(window.navigator, "userAgent", "get").mockReturnValue(IOS_SAFARI_UA);
    const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});

    saveBlobAsFile(new Blob(["%PDF-"]), "Label_X.pdf");

    expect(click).toHaveBeenCalledTimes(1);
    expect(revokeObjectURL).not.toHaveBeenCalled();
    vi.advanceTimersByTime(OBJECT_URL_REVOKE_DELAY_MS);
    expect(revokeObjectURL).toHaveBeenCalledWith(OBJECT_URL);
    expect(document.querySelector("a[download]")).toBeNull();
  });

  it("opens the blob in a new view inside in-app browsers", () => {
    vi.spyOn(window.navigator, "userAgent", "get").mockReturnValue(WHATSAPP_UA);
    const open = vi.spyOn(window, "open").mockReturnValue({} as Window);
    const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});

    saveBlobAsFile(new Blob(["%PDF-"]), "RunSheet.pdf");

    expect(open).toHaveBeenCalledWith(OBJECT_URL, "_blank", "noopener");
    expect(click).not.toHaveBeenCalled();
  });
});
