// Calling codes for phone inputs. Keep in sync with backend/countries.py.
export const COUNTRIES = [
  ["IN", "India", "+91"], ["AE", "United Arab Emirates", "+971"], ["US", "United States", "+1"],
  ["GB", "United Kingdom", "+44"], ["CA", "Canada", "+1"], ["AU", "Australia", "+61"],
  ["SG", "Singapore", "+65"], ["SA", "Saudi Arabia", "+966"], ["QA", "Qatar", "+974"],
  ["KW", "Kuwait", "+965"], ["OM", "Oman", "+968"], ["BH", "Bahrain", "+973"],
  ["NP", "Nepal", "+977"], ["BD", "Bangladesh", "+880"], ["LK", "Sri Lanka", "+94"],
  ["PK", "Pakistan", "+92"], ["MY", "Malaysia", "+60"], ["ID", "Indonesia", "+62"],
  ["TH", "Thailand", "+66"], ["PH", "Philippines", "+63"], ["VN", "Vietnam", "+84"],
  ["HK", "Hong Kong", "+852"], ["JP", "Japan", "+81"], ["KR", "South Korea", "+82"],
  ["CN", "China", "+86"], ["NZ", "New Zealand", "+64"], ["ZA", "South Africa", "+27"],
  ["NG", "Nigeria", "+234"], ["KE", "Kenya", "+254"], ["EG", "Egypt", "+20"],
  ["DE", "Germany", "+49"], ["FR", "France", "+33"], ["IT", "Italy", "+39"],
  ["ES", "Spain", "+34"], ["NL", "Netherlands", "+31"], ["BE", "Belgium", "+32"],
  ["CH", "Switzerland", "+41"], ["SE", "Sweden", "+46"], ["NO", "Norway", "+47"],
  ["DK", "Denmark", "+45"], ["IE", "Ireland", "+353"], ["PT", "Portugal", "+351"],
  ["PL", "Poland", "+48"], ["TR", "Turkey", "+90"], ["IL", "Israel", "+972"],
  ["RU", "Russia", "+7"], ["BR", "Brazil", "+55"], ["MX", "Mexico", "+52"],
  ["AR", "Argentina", "+54"], ["CL", "Chile", "+56"], ["CO", "Colombia", "+57"],
].map(([iso, name, dial]) => ({ iso, name, dial, flag: flagOf(iso) }));

export function flagOf(iso) {
  return String(iso || "").toUpperCase().replace(/./g, (c) => String.fromCodePoint(127397 + c.charCodeAt(0)));
}

export const countryByIso = (iso) => COUNTRIES.find((c) => c.iso === iso) || COUNTRIES[0];
