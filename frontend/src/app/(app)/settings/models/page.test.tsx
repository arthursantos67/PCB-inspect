import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import SettingsModelsPage from "@/app/(app)/settings/models/page";

vi.mock("@/lib/api-client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api-client")>();
  return {
    ...actual,
    listModelVersions: vi.fn(),
    uploadModelWeights: vi.fn(),
    activateModelVersion: vi.fn(),
  };
});

const { ApiError, activateModelVersion, listModelVersions, uploadModelWeights } = await import(
  "@/lib/api-client"
);

function modelVersion(overrides: Partial<Awaited<ReturnType<typeof listModelVersions>>[number]>) {
  return {
    id: "version-1",
    version: "v1.0.0",
    weights_path: "/data/app-data/weights/v1.0.0.pt",
    metrics: null,
    evaluation_status: "PENDING" as const,
    evaluation_error: null,
    is_active: false,
    activated_at: null,
    created_at: "2026-01-01T00:00:00Z",
    ...overrides,
  };
}

/** A stand-in for the `best.pt` the training notebook produces. */
function weightsFile(name = "best.pt") {
  return new File([new Uint8Array([0x50, 0x4b, 0x03, 0x04])], name);
}

afterEach(() => {
  vi.clearAllMocks();
});

describe("Settings > Models", () => {
  it("uploads the picked weights file, naming the version after it", async () => {
    const user = userEvent.setup();
    vi.mocked(listModelVersions).mockResolvedValue([]);
    vi.mocked(uploadModelWeights).mockResolvedValue(modelVersion({ version: "pcb-v2" }));

    render(<SettingsModelsPage />);

    const file = weightsFile("pcb-v2.pt");
    await user.upload(screen.getByLabelText("Weights file (.pt)"), file);
    // The filename is the version name the operator would have typed anyway.
    expect(screen.getByLabelText("Name this version")).toHaveValue("pcb-v2");

    await user.click(screen.getByRole("button", { name: "Upload and evaluate" }));

    await waitFor(() =>
      expect(uploadModelWeights).toHaveBeenCalledWith({ version: "pcb-v2", file })
    );
    // Uploading alone must not activate anything: the version comes back pending evaluation.
    expect(activateModelVersion).not.toHaveBeenCalled();
    expect(
      await screen.findByText(/pcb-v2 was uploaded and is being evaluated/)
    ).toBeInTheDocument();
  });

  it("does not name a version after everyone's `best.pt`", async () => {
    const user = userEvent.setup();
    vi.mocked(listModelVersions).mockResolvedValue([]);

    render(<SettingsModelsPage />);

    await user.upload(screen.getByLabelText("Weights file (.pt)"), weightsFile());

    const version = screen.getByLabelText("Name this version") as HTMLInputElement;
    expect(version.value).not.toBe("best");
    expect(version.value).toMatch(/^best-\d{4}-\d{2}-\d{2}$/);
  });

  it("surfaces the backend's rejection of a file that is not a checkpoint", async () => {
    const user = userEvent.setup();
    vi.mocked(listModelVersions).mockResolvedValue([]);
    vi.mocked(uploadModelWeights).mockRejectedValue(
      new ApiError("VALIDATION_FAILED", "That file is not a PyTorch weights file (.pt).", 422)
    );

    render(<SettingsModelsPage />);

    await user.upload(screen.getByLabelText("Weights file (.pt)"), weightsFile("notes.pt"));
    await user.click(screen.getByRole("button", { name: "Upload and evaluate" }));

    expect(
      await screen.findByText("That file is not a PyTorch weights file (.pt).")
    ).toBeVisible();
  });

  it("offers no activation until the golden-set evaluation has completed (FR-12)", async () => {
    vi.mocked(listModelVersions).mockResolvedValue([
      modelVersion({ version: "v9.0.0", evaluation_status: "PENDING" }),
    ]);

    render(<SettingsModelsPage />);

    expect(await screen.findByText("Waiting on evaluation")).toBeVisible();
    expect(screen.queryByRole("button", { name: "Activate" })).not.toBeInTheDocument();
  });
});
