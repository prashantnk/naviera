// frontend/src/components/ui/icon-select.test.tsx
import { createElement, type ComponentProps } from "react";
import { describe, expect, it, vi } from "vitest";
import { useForm } from "react-hook-form";
import { fireEvent, render, screen } from "@testing-library/react";
import { AddressCategory } from "@/api_client";
import { Form, FormControl, FormField, FormItem, FormLabel } from "@/components/ui/form";
import { ADDRESS_CATEGORY_OPTIONS, toOptions } from "@/lib/form-options";
import { IconSelect } from "./icon-select";

const CATEGORY_OPTIONS = toOptions(ADDRESS_CATEGORY_OPTIONS);

/** Radix Select relies on pointer-capture and scrollIntoView, which jsdom lacks. */
function stubPointerApis(): void {
  const proto = window.HTMLElement.prototype as unknown as Record<string, unknown>;
  proto.hasPointerCapture = vi.fn(() => false);
  proto.releasePointerCapture = vi.fn();
  proto.scrollIntoView = vi.fn();
}

/** Opens a Radix select trigger the way a keyboard user would. */
function openWithKeyboard(trigger: HTMLElement): void {
  trigger.focus();
  fireEvent.keyDown(trigger, { key: "Enter" });
}

describe("IconSelect", () => {
  it("renders the friendly label (not the raw enum) for the selected value", () => {
    render(
      <IconSelect
        aria-label="Address category"
        options={CATEGORY_OPTIONS}
        value={AddressCategory.WAREHOUSE}
        onValueChange={() => undefined}
      />,
    );
    const trigger = screen.getByRole("combobox", { name: "Address category" });
    expect(trigger).toHaveTextContent("Warehouse");
    expect(trigger).not.toHaveTextContent("WAREHOUSE");
  });

  it("shows the placeholder when the value is empty", () => {
    render(
      <IconSelect
        aria-label="Address category"
        options={CATEGORY_OPTIONS}
        value=""
        placeholder="Pick a category"
        onValueChange={() => undefined}
      />,
    );
    expect(screen.getByRole("combobox")).toHaveTextContent("Pick a category");
  });

  it("lists every option with label and helper text and reports the chosen enum value", () => {
    stubPointerApis();
    const onValueChange = vi.fn();
    render(
      <IconSelect
        aria-label="Address category"
        options={CATEGORY_OPTIONS}
        value={AddressCategory.HOME}
        onValueChange={onValueChange}
      />,
    );

    openWithKeyboard(screen.getByRole("combobox"));

    const options = screen.getAllByRole("option");
    expect(options).toHaveLength(CATEGORY_OPTIONS.length);
    expect(screen.getByRole("option", { name: /Storefront/ })).toHaveTextContent(
      "Retail shop, outlet or showroom",
    );

    fireEvent.click(screen.getByRole("option", { name: /Storefront/ }));
    expect(onValueChange).toHaveBeenCalledWith(AddressCategory.STOREFRONT);
  });

  it("renders an empty state when there are no options", () => {
    stubPointerApis();
    render(
      <IconSelect
        aria-label="Saved address"
        options={[]}
        value=""
        emptyMessage="No saved addresses yet"
        onValueChange={() => undefined}
      />,
    );
    openWithKeyboard(screen.getByRole("combobox"));
    expect(screen.getByText("No saved addresses yet")).toBeInTheDocument();
  });

  it("integrates with react-hook-form FormControl (label association + aria-invalid)", () => {
    function Harness() {
      const form = useForm<{ category: AddressCategory }>({
        defaultValues: { category: AddressCategory.OFFICE },
      });
      const content = (
        <FormField
          control={form.control}
          name="category"
          render={({ field }) => (
            <FormItem>
              <FormLabel>Category</FormLabel>
              <FormControl>
                <IconSelect
                  options={CATEGORY_OPTIONS}
                  value={field.value}
                  onValueChange={field.onChange}
                />
              </FormControl>
            </FormItem>
          )}
        />
      );
      const providerProps = Object.assign({ children: content }, form) as unknown as ComponentProps<
        typeof Form
      >;
      return createElement(Form, providerProps);
    }

    render(<Harness />);
    const trigger = screen.getByRole("combobox", { name: /Category/ });
    expect(trigger).toHaveTextContent("Office");
    expect(trigger).toHaveAttribute("aria-invalid", "false");
  });
});
