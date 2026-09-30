import { render, screen } from "@testing-library/react";
import { App } from "antd";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { api, type DictsResponse } from "../api/http";
import { DictsPage } from "./DictsPage";

vi.mock("../api/http", () => ({
  ApiError: class ApiError extends Error {},
  api: {
    listDicts: vi.fn(),
  },
}));

const dicts: DictsResponse = {
  province: [{ code: "js", name: "江苏" }],
  operator: [{ code: "cmcc", name: "移动" }],
  product: [],
  version: [],
};

describe("DictsPage", () => {
  beforeEach(() => {
    vi.mocked(api.listDicts).mockResolvedValue(dicts);
  });

  it("shows readable dictionary values without technical codes", async () => {
    render(
      <App>
        <DictsPage />
      </App>,
    );

    expect(await screen.findByText("江苏")).toBeTruthy();
    expect(screen.getByText("移动")).toBeTruthy();
    expect(screen.queryByText("版本")).toBeNull();
    expect(screen.queryByText("R10")).toBeNull();
    expect(screen.queryByText("js")).toBeNull();
    expect(screen.queryByText("cmcc")).toBeNull();
    expect(screen.getByText("暂无数据")).toBeTruthy();
  });
});
