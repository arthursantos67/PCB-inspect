import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import IngestionPage from "@/app/(app)/ingestion/page";

vi.mock("@/lib/api-client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api-client")>();
  return {
    ...actual,
    getIngestionStatus: vi.fn(),
    browseDirectories: vi.fn(),
    updateConfig: vi.fn(),
    scanDirectory: vi.fn(),
  };
});

const { browseDirectories, getIngestionStatus, scanDirectory, updateConfig } = await import(
  "@/lib/api-client"
);

const STATUS = {
  status: "watching" as const,
  watch_mode_enabled: true,
  watch_root_path: "/home/op/PCB",
  files_discovered: 0,
  files_ingested: 0,
  files_failed: 0,
  detail: null,
};

afterEach(() => {
  vi.clearAllMocks();
});

describe("Watched folder", () => {
  it("points watch mode at a folder picked on the host machine", async () => {
    const user = userEvent.setup();
    vi.mocked(getIngestionStatus).mockResolvedValue({ ...STATUS, watch_root_path: null });
    vi.mocked(browseDirectories).mockResolvedValue({
      path: "/home/op/Documents/PCB_Test",
      parent: "/home/op/Documents",
      directories: [],
    });
    vi.mocked(updateConfig).mockResolvedValue({ config: {} });

    render(<IngestionPage />);

    await user.click(
      await screen.findByRole("button", { name: "Choose folder on this computer" })
    );
    await user.click(await screen.findByRole("button", { name: "Use this folder" }));

    await waitFor(() =>
      expect(updateConfig).toHaveBeenCalledWith({
        watch_root_path: "/home/op/Documents/PCB_Test",
      })
    );
  });

  it("surfaces a folder the backend rejects instead of failing silently", async () => {
    const user = userEvent.setup();
    vi.mocked(getIngestionStatus).mockResolvedValue({ ...STATUS, watch_root_path: null });
    vi.mocked(browseDirectories).mockResolvedValue({
      path: "/home/op/Documents",
      parent: "/home/op",
      directories: [],
    });
    const { ApiError } = await import("@/lib/api-client");
    vi.mocked(updateConfig).mockRejectedValue(
      new ApiError("PATH_NOT_READABLE", "Path is not readable: /home/op/Documents", 422)
    );

    render(<IngestionPage />);

    await user.click(
      await screen.findByRole("button", { name: "Choose folder on this computer" })
    );
    await user.click(await screen.findByRole("button", { name: "Use this folder" }));

    expect(
      await screen.findByText("Path is not readable: /home/op/Documents")
    ).toBeInTheDocument();
  });

  it("scans the watched folder on demand instead of waiting for the next poll", async () => {
    const user = userEvent.setup();
    vi.mocked(getIngestionStatus).mockResolvedValue(STATUS);
    vi.mocked(scanDirectory).mockResolvedValue({
      path: "/home/op/PCB",
      discovered: 3,
      ingested: 3,
      duplicate: 0,
      failed: 0,
      skipped: 0,
      files: [],
    });

    render(<IngestionPage />);

    await user.click(await screen.findByRole("button", { name: "Scan now" }));

    await waitFor(() => expect(scanDirectory).toHaveBeenCalledWith("/home/op/PCB"));
    expect(
      await screen.findByText(/Discovered 3 · Ingested 3 · Duplicate 0 · Failed 0 · Skipped 0/)
    ).toBeInTheDocument();
  });
});
