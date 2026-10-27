/**
 * The catalog item's z/OS Connect binding panel (MFI-21.2, #3992).
 *
 * `A11Y_FIXTURE_DUMP=1` writes the docs-screenshot fixture `catalog-zosconnect-binding`.
 */

import React from "react";
import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import "@testing-library/jest-dom";
import { axe } from "jest-axe";
import "jest-axe/extend-expect";

jest.mock("next/link", () => ({
  __esModule: true,
  default: ({
    children,
    href,
    ...props
  }: {
    children: React.ReactNode;
    href: string;
  }) => (
    <a href={href} {...props}>
      {children}
    </a>
  ),
}));

import { CatalogZosConnectBindingPanel } from "@/app/components/ade/dashboard/catalog/CatalogZosConnectBindingPanel";
import {
  bindingItemHref,
  bindingKindLabel,
  bindingSummaryText,
  type ZosConnectBinding,
} from "@/app/utils/zosconnect-binding";
import { writeA11yFixture } from "./helpers/a11y-fixture-dump";

const GETSTOCK = {
  projectId: "cpy-get",
  name: "GETSTOCK",
  sourceFormat: "cobolcopybook",
  publishable: false,
  linked: true,
};
const OPENAPI = {
  projectId: "api",
  name: "Inventory API",
  sourceFormat: "openapi-3.0",
  publishable: true,
  linked: false,
};

const BINDING: ZosConnectBinding = {
  kind: "requester",
  api: {
    title: "Inventory API",
    specification: "openapi-3.0",
    basePath: "https://api.example.com/inventory",
  },
  operations: [
    {
      operation: "GET /items/{sku}/stock",
      operationId: "getStockLevel",
      method: "GET",
      path: "/items/{sku}/stock",
      program: "INVPGM",
      request: { structure: "GET-STOCK-REQUEST", copybooks: [GETSTOCK] },
      response: { structure: "GET-STOCK-RESPONSE", copybooks: [GETSTOCK] },
      openapi: [OPENAPI],
    },
    {
      operation: "POST /items/{sku}/reservations",
      operationId: "reserveStock",
      method: "POST",
      path: "/items/{sku}/reservations",
      program: "INVPGM",
      request: { structure: "RESERVE-REQUEST", copybooks: [] },
      response: { structure: "RESERVE-RESPONSE", copybooks: [] },
      openapi: [OPENAPI],
    },
  ],
  summary: {
    operations: 2,
    structures: 4,
    structuresWithCopybook: 2,
    structuresLinked: 2,
    operationsWithOpenApi: 2,
  },
};

function mockFetch(response: { ok: boolean; body: unknown }) {
  global.fetch = jest.fn(
    async () =>
      ({ ok: response.ok, json: async () => response.body }) as Response,
  ) as never;
}

beforeEach(() => jest.clearAllMocks());

describe("the binding helpers", () => {
  it("summarizes, labels and links", () => {
    expect(bindingSummaryText(BINDING)).toBe(
      "2 operations · 2 of 4 structures in the catalog (2 linked)",
    );
    expect(bindingKindLabel("requester")).toBe("API requester");
    expect(bindingKindLabel("provider")).toBe("API provider");
    expect(bindingKindLabel(null)).toBe("z/OS Connect");
    expect(bindingItemHref(GETSTOCK)).toBe("/ade/dashboard/catalog/cpy-get");
    expect(bindingItemHref(OPENAPI)).toBe(
      "/ade/dashboard/versions?projectId=api",
    );
  });
});

describe("CatalogZosConnectBindingPanel", () => {
  it("lists each operation with its structures, copybooks and OpenAPI", async () => {
    mockFetch({ ok: true, body: { success: true, binding: BINDING } });
    const { container } = render(
      <CatalogZosConnectBindingPanel projectId="desc" />,
    );
    const rows = await screen.findAllByTestId("zosconnect-binding-row");
    expect(global.fetch).toHaveBeenCalledWith(
      "/api/identity/projects/desc/zosconnect-binding",
    );
    expect(screen.getByTestId("zosconnect-binding-summary")).toHaveTextContent(
      "API requester for Inventory API · 2 operations · 2 of 4 structures in the catalog (2 linked)",
    );

    const first = within(rows[0]);
    expect(first.getByText("GET /items/{sku}/stock")).toBeInTheDocument();
    expect(first.getByText("Program INVPGM")).toBeInTheDocument();
    expect(first.getByText("GET-STOCK-REQUEST")).toBeInTheDocument();
    expect(first.getAllByRole("link", { name: "GETSTOCK" })[0]).toHaveAttribute(
      "href",
      "/ade/dashboard/catalog/cpy-get",
    );
    expect(first.getAllByText("Linked")).toHaveLength(2);
    expect(first.getByText("Not linked")).toBeInTheDocument();

    const second = within(rows[1]);
    expect(second.getAllByText("No copybook in the catalog")).toHaveLength(2);

    expect(await axe(container)).toHaveNoViolations();
    writeA11yFixture(
      "catalog-zosconnect-binding",
      `<div class="page"><div class="page-body">${container.innerHTML}</div></div>`,
    );
  });

  it("says so when the binding cannot be read, and retries", async () => {
    mockFetch({
      ok: false,
      body: { success: false, error: "This item has no z/OS Connect binding." },
    });
    render(<CatalogZosConnectBindingPanel projectId="desc" />);
    expect(
      await screen.findByTestId("zosconnect-binding-error"),
    ).toHaveTextContent("This item has no z/OS Connect binding.");
    mockFetch({ ok: true, body: { success: true, binding: BINDING } });
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    await waitFor(() =>
      expect(screen.getAllByTestId("zosconnect-binding-row")).toHaveLength(2),
    );
  });

  it("notes a descriptor that binds nothing", async () => {
    mockFetch({
      ok: true,
      body: { success: true, binding: { ...BINDING, operations: [] } },
    });
    render(<CatalogZosConnectBindingPanel projectId="desc" />);
    expect(
      await screen.findByText("This descriptor binds no operations."),
    ).toBeInTheDocument();
  });

  it("re-reads when the item’s links change", async () => {
    mockFetch({ ok: true, body: { success: true, binding: BINDING } });
    const { rerender } = render(
      <CatalogZosConnectBindingPanel projectId="desc" refreshKey="a" />,
    );
    await screen.findAllByTestId("zosconnect-binding-row");
    rerender(
      <CatalogZosConnectBindingPanel projectId="desc" refreshKey="a,b" />,
    );
    await waitFor(() => expect(global.fetch).toHaveBeenCalledTimes(2));
  });
});
