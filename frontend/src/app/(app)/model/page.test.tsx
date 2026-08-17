import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import ModelPage from "@/app/(app)/model/page";

vi.mock("@/lib/api-client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api-client")>();
  return { ...actual, listModelVersions: vi.fn() };
});

const { listModelVersions } = await import("@/lib/api-client");

const ACTIVE = {
  id: "version-1",
  version: "v1.0.0",
  weights_path: "/data/app-data/weights/v1.0.0.pt",
  metrics: { map50: 0.99, map50_95: 0.756, per_class: {} },
  evaluation_status: "COMPLETED" as const,
  evaluation_error: null,
  is_active: true,
  activated_at: "2026-01-02T00:00:00Z",
  created_at: "2026-01-01T00:00:00Z",
};

afterEach(() => {
  vi.clearAllMocks();
});

describe("AI model screen", () => {
  it("names the version actually in use, with the metrics the system measured", async () => {
    vi.mocked(listModelVersions).mockResolvedValue([
      { ...ACTIVE, id: "version-0", version: "v0.9.0", is_active: false },
      ACTIVE,
    ]);

    render(<ModelPage />);

    expect(await screen.findByText("v1.0.0")).toBeVisible();
    expect(screen.queryByText("v0.9.0")).not.toBeInTheDocument();
    expect(screen.getByText(/99\.00% mAP@50/)).toBeVisible();
  });

  it("links to the training notebook, since training happens outside this software", async () => {
    vi.mocked(listModelVersions).mockResolvedValue([]);

    render(<ModelPage />);

    const notebook = screen.getByRole("link", { name: /training notebook/i });
    expect(notebook).toHaveAttribute(
      "href",
      "https://colab.research.google.com/drive/1X3VHl6POiBMQ3npn3OxlvM2PviQIvmfm?usp=sharing"
    );
    // Nothing on this screen offers a dataset export or an in-app retrain any more.
    expect(screen.queryByRole("button", { name: /export/i })).not.toBeInTheDocument();
  });

  it("sends the operator to Settings > Models when no version is active yet", async () => {
    vi.mocked(listModelVersions).mockResolvedValue([]);

    render(<ModelPage />);

    expect(await screen.findByText(/No version is active yet/)).toBeVisible();
    for (const link of screen.getAllByRole("link", { name: "Settings > Models" })) {
      expect(link).toHaveAttribute("href", "/settings/models");
    }
  });
});
