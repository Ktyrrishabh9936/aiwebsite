import api from "../lib/api";
import { downloadDocument, openDocument } from "./AuthenticatedDocumentLink";

jest.mock("../lib/api", () => ({ __esModule: true, default: { get: jest.fn() }, formatError: String }));
jest.mock("sonner", () => ({ toast: { error: jest.fn() } }));

beforeEach(() => jest.clearAllMocks());

test("opens authenticated HTML and downloads invoice receipts through the API", async () => {
  const doc = document.implementation.createHTMLDocument();
  const preview = { document: doc, close: jest.fn(), alert: jest.fn() };
  jest.spyOn(window, "open").mockReturnValue(preview);
  api.get.mockResolvedValueOnce({ data: '<html><head><title>Invoice</title></head><body><a class="receipt-link" href="../receipts/r1/pdf">Download Receipt</a></body></html>' });
  await openDocument("http://localhost:8000/api/workspaces/w1/crm/leads/l1/final-invoice/html");
  expect(api.get).toHaveBeenCalledWith(expect.stringContaining("final-invoice/html"), { responseType: "text" });
  expect(doc.title).toBe("Invoice");
  expect(preview.opener).toBeNull();
  api.get.mockRejectedValueOnce(new Error("Download failed"));
  doc.querySelector("a").dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true }));
  await Promise.resolve();
  expect(api.get).toHaveBeenLastCalledWith("http://localhost:8000/api/workspaces/w1/crm/leads/l1/receipts/r1/pdf", { responseType: "blob" });
});

test("closes the loading tab when authentication fails", async () => {
  const preview = { document: document.implementation.createHTMLDocument(), close: jest.fn() };
  jest.spyOn(window, "open").mockReturnValue(preview);
  api.get.mockRejectedValueOnce(new Error("Not authenticated"));
  await expect(openDocument("http://localhost:8000/receipt/html")).rejects.toThrow("Not authenticated");
  expect(preview.close).toHaveBeenCalled();
});

test("downloads the authenticated PDF using its server filename", async () => {
  jest.useFakeTimers();
  URL.createObjectURL = jest.fn(() => "blob:receipt");
  URL.revokeObjectURL = jest.fn();
  const click = jest.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function () {
    expect(this.download).toBe("REC-1.pdf");
    expect(this.href).toBe("blob:receipt");
  });
  api.get.mockResolvedValueOnce({ data: new Blob(["pdf"]), headers: { "content-disposition": 'attachment; filename="REC-1.pdf"' } });
  await downloadDocument("/receipt/pdf");
  expect(click).toHaveBeenCalled();
  jest.runAllTimers();
  expect(URL.revokeObjectURL).toHaveBeenCalledWith("blob:receipt");
  click.mockRestore();
  jest.useRealTimers();
});
