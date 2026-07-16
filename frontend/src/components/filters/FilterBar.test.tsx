import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { FilterBar } from "@/components/filters/FilterBar";
import { EMPTY_INSPECTION_FILTERS, type InspectionFilterValues } from "@/lib/inspection-filters";

function renderFilterBar(value: InspectionFilterValues, onChange: (next: InspectionFilterValues) => void) {
  return render(<FilterBar value={value} onChange={onChange} />);
}

describe("FilterBar", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("toggles a defect-type checkbox immediately", () => {
    const onChange = vi.fn();
    renderFilterBar(EMPTY_INSPECTION_FILTERS, onChange);

    fireEvent.click(screen.getByRole("checkbox", { name: "Short" }));

    expect(onChange).toHaveBeenCalledWith({ ...EMPTY_INSPECTION_FILTERS, defect_type: ["short"] });
  });

  it("unchecks an already-selected defect type", () => {
    const onChange = vi.fn();
    renderFilterBar({ ...EMPTY_INSPECTION_FILTERS, defect_type: ["short", "spur"] }, onChange);

    fireEvent.click(screen.getByRole("checkbox", { name: "Short" }));

    expect(onChange).toHaveBeenCalledWith({
      ...EMPTY_INSPECTION_FILTERS,
      defect_type: ["spur"],
    });
  });

  it("debounces the batch/board text filters instead of firing on every keystroke", () => {
    const onChange = vi.fn();
    renderFilterBar(EMPTY_INSPECTION_FILTERS, onChange);

    fireEvent.change(screen.getByLabelText("Batch"), { target: { value: "B-42" } });
    expect(onChange).not.toHaveBeenCalled();

    vi.advanceTimersByTime(399);
    expect(onChange).not.toHaveBeenCalled();

    vi.advanceTimersByTime(1);
    expect(onChange).toHaveBeenCalledWith({ ...EMPTY_INSPECTION_FILTERS, batch_number: "B-42" });
  });

  it("commits select and date filters immediately, combined with existing filters", () => {
    const onChange = vi.fn();
    const current = { ...EMPTY_INSPECTION_FILTERS, batch_number: "B-42" };
    renderFilterBar(current, onChange);

    fireEvent.change(screen.getByLabelText("Status"), { target: { value: "COMPLETED" } });

    expect(onChange).toHaveBeenCalledWith({ ...current, status: "COMPLETED" });
  });

  it("commits the review-status and disposition filters (FR-10)", () => {
    const onChange = vi.fn();
    renderFilterBar(EMPTY_INSPECTION_FILTERS, onChange);

    fireEvent.change(screen.getByLabelText("Review status"), { target: { value: "VALIDATED" } });
    expect(onChange).toHaveBeenCalledWith({ ...EMPTY_INSPECTION_FILTERS, review_status: "VALIDATED" });

    fireEvent.change(screen.getByLabelText("Disposition"), { target: { value: "rework" } });
    expect(onChange).toHaveBeenCalledWith({ ...EMPTY_INSPECTION_FILTERS, disposition: "rework" });
  });

  it("only shows Clear filters once a filter is active, and resets everything when clicked", () => {
    const onChange = vi.fn();
    const { rerender } = renderFilterBar(EMPTY_INSPECTION_FILTERS, onChange);

    expect(screen.queryByRole("button", { name: "Clear filters" })).not.toBeInTheDocument();

    const active = { ...EMPTY_INSPECTION_FILTERS, severity: "critical" as const };
    rerender(<FilterBar value={active} onChange={onChange} />);

    const clearButton = screen.getByRole("button", { name: "Clear filters" });
    fireEvent.click(clearButton);

    expect(onChange).toHaveBeenCalledWith(EMPTY_INSPECTION_FILTERS);
  });
});
