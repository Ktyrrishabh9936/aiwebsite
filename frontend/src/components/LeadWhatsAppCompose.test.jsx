import { whatsappLink, whatsappPhone } from "./LeadWhatsAppCompose";

test("opens an Indian lead's local phone with an editable message", () => {
  expect(whatsappPhone("8794856351")).toBe("+918794856351");
  expect(whatsappLink("8794856351", "Hi Vinay, details are ready"))
    .toBe("https://wa.me/918794856351?text=Hi%20Vinay%2C%20details%20are%20ready");
});

test("requires a full international number for other phone formats", () => {
  expect(whatsappLink("12345", "Hello")).toBe("");
  expect(whatsappPhone("+1234567890")).toBe("+1234567890");
  expect(whatsappLink("+1 (415) 555-0123", "Hello"))
    .toBe("https://wa.me/14155550123?text=Hello");
});
