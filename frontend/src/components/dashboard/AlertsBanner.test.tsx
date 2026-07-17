import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { AlertsBanner } from "@/components/dashboard/AlertsBanner";
import { acknowledgeAlert, listAlerts, type QualityAlert } from "@/lib/api-client";

vi.mock("@/lib/api-client", () => ({
  listAlerts: vi.fn(),
  acknowledgeAlert: vi.fn(),
}));

const mockListAlerts = vi.mocked(listAlerts);
const mockAcknowledgeAlert = vi.mocked(acknowledgeAlert);

const BATCH_ALERT: QualityAlert = {
  id: "alert-1",
  type: "defect_rate_batch",
  context: { observed_rate: 0.42, threshold: 0.15, batch_number: "BATCH-42" },
  status: "active",
  acknowledged_by: null,
  acknowledged_at: null,
  created_at: "2026-01-01T00:00:00Z",
};

function renderBanner() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <AlertsBanner />
    </QueryClientProvider>
  );
}

describe("AlertsBanner", () => {
  afterEach(() => {
    vi.clearAllMocks();
  });

  it("renders nothing when there are no active alerts", async () => {
    mockListAlerts.mockResolvedValue({ count: 0, next: null, previous: null, results: [] });

    const { container } = renderBanner();

    await waitFor(() => expect(mockListAlerts).toHaveBeenCalled());
    expect(container).toBeEmptyDOMElement();
  });

  it("shows the batch, rate, and threshold for an active alert", async () => {
    mockListAlerts.mockResolvedValue({
      count: 1,
      next: null,
      previous: null,
      results: [BATCH_ALERT],
    });

    renderBanner();

    expect(await screen.findByText(/Batch BATCH-42/)).toBeInTheDocument();
    expect(screen.getByText(/42\.0%/)).toBeInTheDocument();
    expect(screen.getByText(/15\.0%/)).toBeInTheDocument();
  });

  it("acknowledges an alert and clears it from the banner", async () => {
    mockListAlerts
      .mockResolvedValueOnce({ count: 1, next: null, previous: null, results: [BATCH_ALERT] })
      .mockResolvedValueOnce({ count: 0, next: null, previous: null, results: [] });
    mockAcknowledgeAlert.mockResolvedValue({ ...BATCH_ALERT, status: "acknowledged" });

    renderBanner();

    const button = await screen.findByRole("button", { name: "Acknowledge" });
    fireEvent.click(button);

    await waitFor(() => expect(mockAcknowledgeAlert).toHaveBeenCalledWith("alert-1", expect.anything()));
    await waitFor(() => expect(screen.queryByText(/Batch BATCH-42/)).not.toBeInTheDocument());
  });
});
