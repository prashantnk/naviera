// frontend/src/components/pricing-admin/pricing-admin-components.test.tsx
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  downloadPrimeLanesTemplateCsv,
  fetchPricingPolicy,
  fetchPrimeLanes,
  importPrimeLanes,
  MarkupMode,
  patchPrimeLane,
  ServiceOption,
  updatePricingPolicy,
  type PricingPolicyRead,
  type PrimeLaneRead,
} from "./pricing-admin-api";
import { PricingPolicyPanel } from "./pricing-policy-panel";
import { PrimeLanesEditor } from "./prime-lanes-editor";

vi.mock("./pricing-admin-api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("./pricing-admin-api")>();
  return {
    ...actual,
    fetchPricingPolicy: vi.fn(),
    updatePricingPolicy: vi.fn(),
    fetchPrimeLanes: vi.fn(),
    patchPrimeLane: vi.fn(),
    importPrimeLanes: vi.fn(),
    downloadPrimeLanesCsv: vi.fn(),
    downloadPrimeLanesTemplateCsv: vi.fn(),
  };
});

vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn(), info: vi.fn() } }));

const SLUG = "logismart-test";

const POLICY: PricingPolicyRead = {
  delhivery_markup_percent: 0,
  prime_default_markup_percent: 20,
  cod_fee_percent: null,
  cod_fee_min: null,
  enabled_options: [ServiceOption.DELHIVERY_SURFACE, ServiceOption.DELHIVERY_EXPRESS, ServiceOption.PRIME_SURFACE],
  cod_enabled: false,
  delhivery_configured: false,
};

const LANE: PrimeLaneRead = {
  id: "lane-1",
  origin_zone: "Delhi NCR",
  dest_zone: "Mumbai",
  mode: "SURFACE",
  transporter_name: "Vision Express",
  tat_hours: 72,
  rate_per_kg: 8,
  min_lr_charge: 500,
  docket_charge: 100,
  min_chargeable_kg: 50,
  volumetric_divisor: 4500,
  max_dimension_cm: 240,
  delivery_type: "GODOWN",
  oda_per_kg: 2,
  oda_min: 800,
  odd_weight_per_kg: 2,
  odd_weight_min: 800,
  pickup_per_kg: 1,
  pickup_min: 600,
  door_delivery_per_kg: 1,
  door_delivery_min: 600,
  markup_percent: 20,
  is_active: true,
  updated_at: "2026-10-30T12:00:00",
};

beforeEach(() => {
  vi.clearAllMocks();
});

describe("PricingPolicyPanel", () => {
  it("shows the COD-off and Delhivery-not-connected banners for a fresh policy", async () => {
    vi.mocked(fetchPricingPolicy).mockResolvedValue(POLICY);
    render(<PricingPolicyPanel tenantSlug={SLUG} canEdit />);

    expect(await screen.findByTestId("pricing-policy.cod-off")).toHaveTextContent(
      "COD is OFF for all customers until you set both values",
    );
    expect(screen.getByTestId("pricing-policy.delhivery-not-configured")).toHaveTextContent(
      "Delhivery price API not connected yet",
    );
    expect(screen.queryByTestId("pricing-policy.read-only")).not.toBeInTheDocument();
    expect(screen.getByTestId("pricing-policy.save")).toBeDisabled();
  });

  it("flips the banner to COD ON once both values are typed, then saves after confirmation", async () => {
    vi.mocked(fetchPricingPolicy).mockResolvedValue(POLICY);
    const saved: PricingPolicyRead = Object.assign({}, POLICY, {
      cod_fee_min: 30,
      cod_fee_percent: 1.5,
      cod_enabled: true,
    });
    vi.mocked(updatePricingPolicy).mockResolvedValue(saved);
    render(<PricingPolicyPanel tenantSlug={SLUG} canEdit />);

    fireEvent.change(await screen.findByTestId("pricing-policy.cod-min"), { target: { value: "30" } });
    expect(screen.getByTestId("pricing-policy.cod-off")).toBeInTheDocument();
    fireEvent.change(screen.getByTestId("pricing-policy.cod-percent"), { target: { value: "1.5" } });
    expect(await screen.findByTestId("pricing-policy.cod-on")).toHaveTextContent("₹30 or 1.5%");

    await waitFor(() => expect(screen.getByTestId("pricing-policy.save")).not.toBeDisabled());
    fireEvent.click(screen.getByTestId("pricing-policy.save"));
    const dialog = await screen.findByTestId("pricing-policy.confirm-dialog", {}, { timeout: 5000 });
    expect(within(dialog).getByText("COD fee minimum")).toBeInTheDocument();
    expect(within(dialog).getByText("₹30")).toBeInTheDocument();

    fireEvent.click(within(dialog).getByTestId("pricing-policy.confirm-save"));
    await waitFor(() =>
      expect(updatePricingPolicy).toHaveBeenCalledWith(
        {
          delhivery_markup_percent: 0,
          prime_default_markup_percent: 20,
          cod_fee_min: 30,
          cod_fee_percent: 1.5,
          enabled_options: POLICY.enabled_options,
          option_markups: {},
        },
        SLUG,
      ),
    );
  }, 15000);

  it("saves a flat ₹ markup for one option after showing it in the confirm dialog", async () => {
    vi.mocked(fetchPricingPolicy).mockResolvedValue(POLICY);
    vi.mocked(updatePricingPolicy).mockResolvedValue(POLICY);
    render(<PricingPolicyPanel tenantSlug={SLUG} canEdit />);

    const mode = await screen.findByTestId(`pricing-policy.markup.${ServiceOption.DELHIVERY_EXPRESS}.mode`);
    fireEvent.change(mode, { target: { value: MarkupMode.FLAT } });
    fireEvent.change(screen.getByTestId(`pricing-policy.markup.${ServiceOption.DELHIVERY_EXPRESS}.value`), {
      target: { value: "25" },
    });
    expect(screen.getByTestId(`pricing-policy.markup.${ServiceOption.PRIME_SURFACE}`)).toHaveTextContent(
      "Set per lane on the Prime lanes page.",
    );
    await waitFor(() => expect(screen.getByTestId("pricing-policy.save")).not.toBeDisabled());
    fireEvent.click(screen.getByTestId("pricing-policy.save"));
    const dialog = await screen.findByTestId("pricing-policy.confirm-dialog", {}, { timeout: 5000 });
    expect(within(dialog).getByText("₹25 per shipment")).toBeInTheDocument();

    fireEvent.click(within(dialog).getByTestId("pricing-policy.confirm-save"));
    await waitFor(() =>
      expect(updatePricingPolicy).toHaveBeenCalledWith(
        expect.objectContaining({
          option_markups: { [ServiceOption.DELHIVERY_EXPRESS]: { mode: MarkupMode.FLAT, value: 25 } },
        }),
        SLUG,
      ),
    );
  });

  it("is read-only for non-admin staff", async () => {
    vi.mocked(fetchPricingPolicy).mockResolvedValue(
      Object.assign({}, POLICY, { delhivery_configured: true, delhivery_b2b_configured: true }),
    );
    render(<PricingPolicyPanel tenantSlug={SLUG} canEdit={false} />);

    expect(await screen.findByTestId("pricing-policy.read-only")).toBeInTheDocument();
    expect(screen.getByTestId(`pricing-policy.markup.${ServiceOption.DELHIVERY_SURFACE}.value`)).toBeDisabled();
    expect(screen.getByTestId(`pricing-policy.markup.${ServiceOption.PRIME_SURFACE}.mode`)).toBeDisabled();
    expect(screen.getByTestId(`pricing-policy.option.${ServiceOption.PRIME_SURFACE}`)).toBeDisabled();
    expect(screen.queryByTestId("pricing-policy.save")).not.toBeInTheDocument();
    expect(screen.queryByTestId("pricing-policy.delhivery-not-configured")).not.toBeInTheDocument();
    expect(screen.queryByTestId("pricing-policy.delhivery-b2b-not-configured")).not.toBeInTheDocument();
  });

  it("explains a load failure and retries", async () => {
    vi.mocked(fetchPricingPolicy).mockRejectedValueOnce(new Error("boom")).mockResolvedValueOnce(POLICY);
    render(<PricingPolicyPanel tenantSlug={SLUG} canEdit />);

    expect(await screen.findByTestId("pricing-policy.load-error")).toHaveTextContent(
      "We couldn't load your pricing settings.",
    );
    fireEvent.click(screen.getByText("Try again"));
    expect(await screen.findByTestId("pricing-policy.panel")).toBeInTheDocument();
  });
});

describe("PrimeLanesEditor", () => {
  it("loads active lanes and PATCHes only the changed field", async () => {
    vi.mocked(fetchPrimeLanes).mockResolvedValue([LANE]);
    vi.mocked(patchPrimeLane).mockResolvedValue(Object.assign({}, LANE, { rate_per_kg: 9 }));
    render(<PrimeLanesEditor tenantSlug={SLUG} canEdit />);

    expect(await screen.findByTestId("prime-lanes.row.lane-1")).toHaveTextContent("Vision Express");
    expect(fetchPrimeLanes).toHaveBeenCalledWith(true, SLUG);

    fireEvent.click(screen.getByTestId("prime-lanes.row.lane-1.edit"));
    fireEvent.change(screen.getByTestId("prime-lanes.row.lane-1.rate_per_kg"), { target: { value: "9" } });
    fireEvent.click(screen.getByTestId("prime-lanes.row.lane-1.save"));

    await waitFor(() => expect(patchPrimeLane).toHaveBeenCalledWith("lane-1", { rate_per_kg: 9 }, SLUG));
    expect(await screen.findByTestId("prime-lanes.row.lane-1.edit")).toBeInTheDocument();
  });

  it("shows a validation message instead of saving a bad value", async () => {
    vi.mocked(fetchPrimeLanes).mockResolvedValue([LANE]);
    render(<PrimeLanesEditor tenantSlug={SLUG} canEdit />);

    fireEvent.click(await screen.findByTestId("prime-lanes.row.lane-1.edit"));
    fireEvent.change(screen.getByTestId("prime-lanes.row.lane-1.tat_hours"), { target: { value: "0" } });
    fireEvent.click(screen.getByTestId("prime-lanes.row.lane-1.save"));

    expect(await screen.findByText("TAT must be more than 0")).toBeInTheDocument();
    expect(patchPrimeLane).not.toHaveBeenCalled();
  });

  it("reloads with all lanes when 'Active lanes only' is unticked, and shows a plain empty state", async () => {
    vi.mocked(fetchPrimeLanes).mockResolvedValue([]);
    render(<PrimeLanesEditor tenantSlug={SLUG} canEdit={false} />);

    expect(await screen.findByTestId("prime-lanes.empty")).toHaveTextContent("No active Prime lanes yet");
    expect(screen.getByTestId("prime-lanes.read-only")).toBeInTheDocument();
    expect(screen.queryByTestId("prime-lanes.import-open")).not.toBeInTheDocument();

    fireEvent.click(screen.getByTestId("prime-lanes.active-only"));
    await waitFor(() => expect(fetchPrimeLanes).toHaveBeenLastCalledWith(false, SLUG));
    expect(await screen.findByText("No Prime lanes yet")).toBeInTheDocument();
  });

  it("previews a CSV import and blocks it when rows have errors", async () => {
    vi.mocked(fetchPrimeLanes).mockResolvedValue([LANE]);
    vi.mocked(importPrimeLanes).mockResolvedValue({
      created: 2,
      updated: 0,
      deactivated: 0,
      errors: [{ row: 7, message: "RATE/KG is NA" }],
      warnings: [],
    });
    render(<PrimeLanesEditor tenantSlug={SLUG} canEdit />);

    fireEvent.click(await screen.findByTestId("prime-lanes.import-open"));
    const file = new File(["a,b\n1,2"], "lanes.csv", { type: "text/csv" });
    fireEvent.change(screen.getByTestId("prime-lanes.import.file"), { target: { files: [file] } });
    fireEvent.click(screen.getByTestId("prime-lanes.import.check"));

    await waitFor(() => expect(importPrimeLanes).toHaveBeenCalledWith(file, true, SLUG));
    expect(await screen.findByTestId("prime-lanes.import.summary")).toHaveTextContent("1 row has a problem");
    expect(screen.getByTestId("prime-lanes.import.errors")).toHaveTextContent("Row 7: RATE/KG is NA");
    expect(screen.queryByTestId("prime-lanes.import.confirm")).not.toBeInTheDocument();
  });

  it("imports after a clean dry run and reloads the table", async () => {
    vi.mocked(fetchPrimeLanes).mockResolvedValue([LANE]);
    const clean = { created: 1, updated: 2, deactivated: 1, errors: [], warnings: [] };
    vi.mocked(importPrimeLanes).mockResolvedValue(clean);
    render(<PrimeLanesEditor tenantSlug={SLUG} canEdit />);

    fireEvent.click(await screen.findByTestId("prime-lanes.import-open"));
    const file = new File(["a,b\n1,2"], "lanes.csv", { type: "text/csv" });
    fireEvent.change(screen.getByTestId("prime-lanes.import.file"), { target: { files: [file] } });
    fireEvent.click(screen.getByTestId("prime-lanes.import.check"));

    expect(await screen.findByTestId("prime-lanes.import.summary")).toHaveTextContent(
      "1 lane will be added, 2 lanes will be updated and 1 lane will be switched off.",
    );
    fireEvent.click(screen.getByTestId("prime-lanes.import.confirm"));
    await waitFor(() => expect(importPrimeLanes).toHaveBeenLastCalledWith(file, false, SLUG));
    await waitFor(() => expect(fetchPrimeLanes).toHaveBeenCalledTimes(2));
  });

  it("rejects a non-CSV file before uploading", async () => {
    vi.mocked(fetchPrimeLanes).mockResolvedValue([LANE]);
    render(<PrimeLanesEditor tenantSlug={SLUG} canEdit />);

    fireEvent.click(await screen.findByTestId("prime-lanes.import-open"));
    const file = new File(["x"], "lanes.xlsx");
    fireEvent.change(screen.getByTestId("prime-lanes.import.file"), { target: { files: [file] } });

    expect(await screen.findByTestId("prime-lanes.import.file-error")).toHaveTextContent("Choose a .csv file");
    expect(screen.getByTestId("prime-lanes.import.check")).toBeDisabled();
  });

  it("downloads the sample CSV template when clicking Download Template CSV", async () => {
    vi.mocked(fetchPrimeLanes).mockResolvedValue([LANE]);
    vi.mocked(downloadPrimeLanesTemplateCsv).mockResolvedValue(undefined);
    render(<PrimeLanesEditor tenantSlug={SLUG} canEdit />);

    const templateBtn = await screen.findByTestId("prime-lanes-template-csv");
    expect(templateBtn).toHaveTextContent(/Download Template CSV/i);
    fireEvent.click(templateBtn);

    await waitFor(() => expect(downloadPrimeLanesTemplateCsv).toHaveBeenCalledTimes(1));
  });
});
