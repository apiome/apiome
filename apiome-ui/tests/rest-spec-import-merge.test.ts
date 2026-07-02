import { mergeOpenApiDocumentIntoCatalogTargets } from "../lib/rest-spec-import-merge";

describe("mergeOpenApiDocumentIntoCatalogTargets", () => {
  const meta = {
    project: { name: "API", slug: "api", description: null },
    version: { versionId: "1.0.0", description: null },
  };

  it("fills project.description from info.description when metadata omits it", () => {
    const doc = {
      openapi: "3.0.0",
      info: {
        title: "1Forge",
        version: "0.0.1",
        description: "Real-time stock quotes.",
        contact: { name: "Support", url: "https://1forge.com", email: "hello@1forge.com" },
      },
    };
    const m = mergeOpenApiDocumentIntoCatalogTargets(meta, doc, "openapi");
    expect(m.project.description).toBe("Real-time stock quotes.");
    expect(m.projectMetadata).toEqual({
      contact: { name: "Support", url: "https://1forge.com", email: "hello@1forge.com" },
    });
  });

  it("keeps explicit metadata.project.description over info.description", () => {
    const doc = {
      openapi: "3.0.0",
      info: { description: "From spec", contact: { email: "a@b.co" } },
    };
    const m = mergeOpenApiDocumentIntoCatalogTargets(
      { ...meta, project: { ...meta.project, description: "From CLI" } },
      doc,
      "openapi",
    );
    expect(m.project.description).toBe("From CLI");
    expect((m.projectMetadata as { contact: unknown }).contact).toEqual({
      email: "a@b.co",
    });
  });

  it("captures license and termsOfService on Swagger 2 info", () => {
    const doc = {
      swagger: "2.0",
      info: {
        description: "Legacy",
        termsOfService: "http://example.com/tos",
        license: { name: "Apache 2.0", url: "https://www.apache.org/licenses/LICENSE-2.0.html" },
      },
    };
    const m = mergeOpenApiDocumentIntoCatalogTargets(meta, doc, "openapi");
    expect(m.project.description).toBe("Legacy");
    expect(m.projectMetadata).toEqual({
      termsOfService: "http://example.com/tos",
      license: { name: "Apache 2.0", url: "https://www.apache.org/licenses/LICENSE-2.0.html" },
    });
  });

  it("stores info.summary in projects.metadata.summary", () => {
    const doc = {
      openapi: "3.0.0",
      info: {
        description: "Body",
        summary: "Short API summary",
      },
    };
    const m = mergeOpenApiDocumentIntoCatalogTargets(meta, doc, "openapi");
    expect(m.project.description).toBe("Body");
    expect(m.projectMetadata).toEqual({ summary: "Short API summary" });
  });

  it("stores vendor info extensions (x-*) and arrays in projectMetadata", () => {
    const doc = {
      openapi: "3.0.0",
      info: {
        title: "1Forge",
        version: "1.0.0",
        description: "Stock and Forex Data",
        contact: { email: "contact@1forge.com", name: "1Forge", url: "http://1forge.com" },
        "x-apisguru-categories": ["financial"],
        "x-logo": { url: "https://1forge.com/f.svg", backgroundColor: "#24292e" },
        "x-providerName": "1forge.com",
      },
      paths: {},
    };
    const m = mergeOpenApiDocumentIntoCatalogTargets(meta, doc, "openapi");
    expect(m.project.description).toBe("Stock and Forex Data");
    expect(m.projectMetadata).toEqual({
      contact: { email: "contact@1forge.com", name: "1Forge", url: "http://1forge.com" },
      "x-apisguru-categories": ["financial"],
      "x-logo": { url: "https://1forge.com/f.svg", backgroundColor: "#24292e" },
      "x-providerName": "1forge.com",
    });
  });

  it("does not merge for arazzo", () => {
    const doc = { openapi: "3.0.0", info: { description: "X" } };
    const m = mergeOpenApiDocumentIntoCatalogTargets(meta, doc, "arazzo");
    expect(m.project.description).toBeUndefined();
    expect(m.projectMetadata).toBeUndefined();
  });
});
