import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import ReportsPage from "@/app/(app)/reports/page";

vi.mock("@/lib/api-client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api-client")>();
  return {
    ...actual,
    listBatches: vi.fn(),
    listInspections: vi.fn(),
    listReports: vi.fn(),
    requestReport: vi.fn(),
    downloadReport: vi.fn(),
  };
});

const { downloadReport, listBatches, listInspections, listReports, requestReport } = await import(
  "@/lib/api-client"
);

const BATCH = {
  batch_id: "batch-1",
  batch_number: "BATCH-42",
  board_count: 3,
  completed_count: 3,
  boards_with_defects: 2,
  defect_count: 5,
  defect_rate: 0.66,
  defect_types: [],
  severity: "high" as const,
  status: "COMPLETED" as const,
  created_at: "2026-01-01T00:00:00Z",
  last_activity_at: "2026-01-01T01:00:00Z",
};

function board(id: string, boardNumber: string) {
  return {
    id,
    status: "COMPLETED" as const,
    batch_number: "BATCH-42",
    board_number: boardNumber,
    defect_types: [],
    severity_max: "high" as const,
    review_status: "PENDING" as const,
    disposition_recommendation: null,
    disposition: null,
    failure_reason: null,
    created_at: "2026-01-01T00:00:00Z",
    processed_at: "2026-01-01T00:01:00Z",
  };
}

const BOARDS = [board("insp-1", "BOARD-01"), board("insp-2", "BOARD-02")];

const EMPTY_REPORT_LIST = { count: 0, next: null, previous: null, results: [] };

function renderPage() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <ReportsPage />
    </QueryClientProvider>
  );
}

afterEach(() => {
  vi.clearAllMocks();
});

describe("Reports screen", () => {
  it("requests a batch report from the guided batch and board pickers", async () => {
    const user = userEvent.setup();
    vi.mocked(listReports).mockResolvedValue(EMPTY_REPORT_LIST);
    vi.mocked(listBatches).mockResolvedValue({ count: 1, results: [BATCH] });
    vi.mocked(listInspections).mockResolvedValue({
      count: 2,
      next: null,
      previous: null,
      results: BOARDS,
    });
    vi.mocked(requestReport).mockResolvedValue({
      id: "report-1",
      type: "consolidated",
      format: "pdf",
      filters: {},
      status: "PENDING",
      file_path: null,
      row_count: null,
      error_message: null,
      requested_by: "user-1",
      created_at: "2026-01-01T00:00:00Z",
    });

    renderPage();

    // Waits for the batch list itself to arrive, not just for the control to render.
    await screen.findByRole("option", { name: /BATCH-42/ });
    await user.selectOptions(screen.getByLabelText("Batch"), "BATCH-42");
    await user.click(await screen.findByRole("checkbox", { name: "BOARD-02" }));
    await user.selectOptions(screen.getByLabelText("Language"), "pt");
    await user.click(screen.getByRole("button", { name: "Generate report" }));

    await waitFor(() =>
      expect(requestReport).toHaveBeenCalledWith(
        expect.objectContaining({
          type: "consolidated",
          format: "pdf",
          language: "pt",
          filters: expect.objectContaining({
            batch_number: "BATCH-42",
            board_numbers: ["BOARD-02"],
          }),
        })
      )
    );
  });

  it("keeps the individual board report, addressed by the board picked from the batch", async () => {
    const user = userEvent.setup();
    vi.mocked(listReports).mockResolvedValue(EMPTY_REPORT_LIST);
    vi.mocked(listBatches).mockResolvedValue({ count: 1, results: [BATCH] });
    vi.mocked(listInspections).mockResolvedValue({
      count: 2,
      next: null,
      previous: null,
      results: BOARDS,
    });

    renderPage();

    await user.selectOptions(await screen.findByLabelText("Report type"), "individual");
    // Waits for the batch list itself to arrive, not just for the control to render.
    await screen.findByRole("option", { name: /BATCH-42/ });
    await user.selectOptions(screen.getByLabelText("Batch"), "BATCH-42");
    await user.selectOptions(await screen.findByLabelText("Board"), "insp-1");
    await user.selectOptions(screen.getByLabelText("Format"), "csv");
    await user.click(screen.getByRole("button", { name: "Generate report" }));

    await waitFor(() =>
      expect(requestReport).toHaveBeenCalledWith({
        type: "individual",
        format: "csv",
        inspection_id: "insp-1",
        language: "en",
      })
    );
  });

  it("refuses an individual report with no board picked instead of posting an empty request", async () => {
    const user = userEvent.setup();
    vi.mocked(listReports).mockResolvedValue(EMPTY_REPORT_LIST);
    vi.mocked(listBatches).mockResolvedValue({ count: 1, results: [BATCH] });

    renderPage();

    await user.selectOptions(await screen.findByLabelText("Report type"), "individual");
    await user.click(screen.getByRole("button", { name: "Generate report" }));

    expect(await screen.findByText("Pick the batch and the board to report on.")).toBeVisible();
    expect(requestReport).not.toHaveBeenCalled();
  });

  it("reports download progress and confirms the file was saved", async () => {
    const user = userEvent.setup();
    vi.mocked(listBatches).mockResolvedValue({ count: 0, results: [] });
    vi.mocked(listReports).mockResolvedValue({
      count: 1,
      next: null,
      previous: null,
      results: [
        {
          id: "report-1",
          type: "consolidated",
          format: "pdf",
          filters: { batch_number: "BATCH-42", language: "pt" },
          status: "COMPLETED",
          file_path: "/data/reports/consolidated-report-1.pdf",
          row_count: 3,
          error_message: null,
          requested_by: "user-1",
          created_at: "2026-01-01T00:00:00Z",
        },
      ],
    });

    let release: (() => void) | undefined;
    vi.mocked(downloadReport).mockReturnValue(
      new Promise<void>((resolve) => {
        release = resolve;
      })
    );

    renderPage();

    // The language the report was generated in is shown alongside it.
    expect(await screen.findByText("Português")).toBeVisible();

    await user.click(await screen.findByRole("button", { name: "Download" }));

    const busyButton = await screen.findByRole("button", { name: "Preparing…" });
    expect(busyButton).toBeDisabled();
    expect(screen.getByText("Preparing the file…")).toBeVisible();

    release?.();

    expect(await screen.findByText("Saved to your downloads.")).toBeVisible();
    expect(await screen.findByRole("button", { name: "Download again" })).toBeEnabled();
  });
});
