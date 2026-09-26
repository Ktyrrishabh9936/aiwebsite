import api, { formatError } from "../lib/api";
import { toast } from "sonner";

export async function downloadDocument(url) {
  const response = await api.get(url, { responseType: "blob" });
  const blobUrl = URL.createObjectURL(response.data);
  const link = document.createElement("a");
  link.href = blobUrl;
  link.download = response.headers["content-disposition"]?.match(/filename="([^"]+)"/)?.[1] || "receipt.pdf";
  document.body.appendChild(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(blobUrl), 60000);
}

export async function openDocument(url) {
  // Open synchronously so browsers allow the new tab after the request finishes.
  const preview = window.open("about:blank", "_blank");
  if (!preview) throw new Error("Allow pop-ups to open this document.");
  preview.opener = null;
  preview.document.body.textContent = "Loading document…";
  try {
    const response = await api.get(url, { responseType: "text" });
    if (preview.closed) return;
    const sourceUrl = new URL(url, window.location.href);
    const parsed = new DOMParser().parseFromString(response.data, "text/html");
    // Keep invoice receipt links and any relative assets pointing at the API.
    const base = parsed.createElement("base");
    base.href = sourceUrl.href;
    parsed.head.prepend(base);
    preview.document.open();
    preview.document.write(parsed.documentElement.outerHTML);
    preview.document.close();
    preview.document.addEventListener("click", async (event) => {
      const link = event.target.closest("a.receipt-link");
      if (!link) return;
      event.preventDefault();
      const downloadUrl = new URL(link.getAttribute("href"), sourceUrl);
      if (downloadUrl.origin !== sourceUrl.origin) return;
      try {
        await downloadDocument(downloadUrl.href);
      } catch (error) {
        preview.alert(formatError(error.response?.data?.detail || error.message));
      }
    });
  } catch (error) {
    preview.close();
    throw error;
  }
}

export default function AuthenticatedDocumentLink({ href, children, ...props }) {
  async function handleClick(event) {
    event.preventDefault();
    try {
      if (href.endsWith("/pdf")) await downloadDocument(href);
      else await openDocument(href);
    } catch (error) {
      toast.error(formatError(error.response?.data?.detail || error.message));
    }
  }
  return <a {...props} href={href} onClick={handleClick}>{children}</a>;
}
